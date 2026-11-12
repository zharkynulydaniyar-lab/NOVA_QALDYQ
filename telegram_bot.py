"""aiogram transport. Run beside server.py against exactly the same SQLite file."""
import argparse
import asyncio
import io
import json
import logging
import os
import re
import time
from urllib.parse import urlparse

from common import APIError
from server import connect, initialize, ROOT
import telegram_service as service

log = logging.getLogger('qaldyq.telegram')


class DeliveryFailure(Exception):
    def __init__(self, kind, retry_after=None):
        self.kind, self.retry_after = kind, retry_after
        super().__init__(kind)


class AiogramAPI:
    def __init__(self, token):
        from aiogram import Bot
        self.bot = Bot(token)

    async def send(self, method, payload):
        from aiogram.methods import SendMessage, AnswerCallbackQuery
        from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter, TelegramBadRequest, TelegramUnauthorizedError
        model = {'sendMessage':SendMessage, 'answerCallbackQuery':AnswerCallbackQuery}[method]
        try:
            return await self.bot(model(**payload), request_timeout=20)
        except TelegramForbiddenError:
            raise DeliveryFailure('blocked') from None
        except TelegramRetryAfter as error:
            raise DeliveryFailure('retry',error.retry_after) from None
        except (TelegramBadRequest,TelegramUnauthorizedError):
            raise DeliveryFailure('permanent') from None

    async def photo(self, message):
        from aiogram.types import PhotoSize
        photos = message.get('photo', [])
        if not photos:
            return None
        file = PhotoSize.model_validate(photos[-1])
        if not file.file_size or file.file_size > 2_000_000:
            raise APIError('Фото должно быть до 2 МБ. Пришлите меньшее фото или /skip.')
        class LimitedBuffer(io.BytesIO):
            def write(self, data):
                if self.tell()+len(data) > 2_000_000:
                    raise APIError('Фото превышает 2 МБ.')
                return super().write(data)
        buffer = LimitedBuffer()
        await self.bot.download(file, destination=buffer, timeout=20)
        raw = buffer.getvalue()
        if not raw.startswith(b'\xff\xd8\xff'):
            raise APIError('Отправьте JPEG как фото.')
        import base64
        return 'data:image/jpeg;base64,'+base64.b64encode(raw).decode()

    async def close(self):
        await self.bot.session.close()


async def deliver_one(db_path, cfg, api):
    with connect(db_path) as db:
        db.execute('BEGIN IMMEDIATE')
        row = service.claim_delivery(db,cfg)
    if not row:
        return False
    payload = json.loads(row['payload'])
    payload.pop('_org_id',None)
    payload.pop('_notification_id',None)
    payload.pop('_staff_org_id',None)
    if '_path' in payload:
        path = payload.pop('_path')
        payload['reply_markup'] = {'inline_keyboard':[[{'text':'Qaldyq','url':cfg.app_url+path}]]}
    result, retry_after = 'sent', None
    try:
        await api.send(row['method'], payload)
    except Exception as error:
        # Do not persist or log exception strings: Telegram exceptions can contain token-bearing URLs.
        if isinstance(error, DeliveryFailure):
            result, retry_after = error.kind, error.retry_after
        else:
            result = 'retry'
        log.warning('Delivery %s: %s', row['id'], result)
    with connect(db_path) as db:
        db.execute('BEGIN IMMEDIATE')
        service.finish_delivery(db,cfg,row,result,retry_after)
    return True


async def deliver_notification(db_path,cfg,api):
    with connect(db_path) as db:
        db.execute('BEGIN IMMEDIATE')
        row=service.claim_notification(db,cfg)
    if not row:
        return False
    data=json.loads(row['payload'])
    path=data.get('path') or ('/student/#orders' if 'order_id' in data else '/#notifications')
    if not isinstance(path,str) or not path.startswith('/') or path.startswith('//'):
        path='/#notifications'
    payload={'chat_id':row['telegram_id'],'text':(data.get('title','Qaldyq')+'\n'+data.get('body',''))[:4096],
        'reply_markup':{'inline_keyboard':[[{'text':'Qaldyq','url':cfg.app_url+path}]]}}
    result,retry='sent',None
    try:
        await api.send('sendMessage',payload)
    except DeliveryFailure as error:
        result,retry=error.kind,error.retry_after
    except Exception:
        result='retry'
    with connect(db_path) as db:
        db.execute('BEGIN IMMEDIATE')
        service.finish_notification(db,cfg,row,result,retry)
    return True


async def process_one(db_path, cfg, api):
    with connect(db_path) as db:
        row = db.execute("SELECT * FROM telegram_inbox WHERE state='pending' ORDER BY created_at,update_id LIMIT 1").fetchone()
        if not row or row['available_at'] > time.time():
            return False
        row = dict(row)
        update = json.loads(row['payload'])
        # Only fetch a photo for the active employee photo step, in a private conversation.
        message = update.get('message', {})
        tid = message.get('from',{}).get('id')
        wants_photo = bool(message.get('photo') and message.get('chat',{}).get('type')=='private'
            and message.get('chat',{}).get('id')==tid and db.execute("SELECT 1 FROM telegram_conversations c JOIN telegram_links l ON l.telegram_id=c.telegram_id JOIN users u ON u.id=l.user_id WHERE c.telegram_id=? AND c.state='photo' AND c.expires>? AND u.role IN ('operator','admin')",(tid,time.time())).fetchone())
    try:
        photo = None
        photo_error = None
        if wants_photo:
            try:
                photo = await api.photo(message)
            except APIError as error:
                photo_error = error.message
        with connect(db_path) as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT state FROM telegram_inbox WHERE update_id=?',(row['update_id'],)).fetchone()
            if current['state'] != 'pending':
                return True
            if photo_error:
                c = service.Conversation(db,cfg,update)
                c.reply(photo_error)
                db.execute("UPDATE telegram_inbox SET state='done' WHERE update_id=?",(row['update_id'],))
            else:
                service.process(db,cfg,update,photo)
    except Exception:
        # A failed transaction leaves domain changes and replies rolled back together.
        with connect(db_path) as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE telegram_inbox SET attempts=attempts+1,state=CASE WHEN attempts+1>=? THEN 'failed' ELSE 'pending' END,available_at=?,error='processing_failed' WHERE update_id=? AND state='pending'",
                       (cfg.max_attempts,time.time()+min(300,2**(row['attempts']+1)),row['update_id']))
        log.error('Update %s processing failed; inspect failed inbox entries',row['update_id'])
    return True


async def work(db_path, cfg, api):
    next_reminder = 0
    while True:
        if time.monotonic() >= next_reminder:
            with connect(db_path) as db:
                db.execute('BEGIN IMMEDIATE')
                service.collect_reminders(db)
                from server import MODULES
                for module in MODULES:
                    if hasattr(module,'tick'):
                        module.tick(db)
            next_reminder = time.monotonic()+60
        processed = await process_one(db_path,cfg,api)
        delivered = await deliver_one(db_path,cfg,api)
        notified = await deliver_notification(db_path,cfg,api)
        if not processed and not delivered and not notified:
            await asyncio.sleep(.5)


async def poll(db_path, api):
    # Offset persisted separately: Telegram update IDs can restart after a week of inactivity.
    with connect(db_path) as db:
        row = db.execute("SELECT value FROM settings WHERE key='telegram_poll_offset'").fetchone()
        offset = int(row[0]) if row else None
        stamp = db.execute("SELECT value FROM settings WHERE key='telegram_poll_received_at'").fetchone()
        received_at = float(stamp[0]) if stamp else 0
    while True:
        try:
            if time.time()-received_at > 6*86400:
                offset = None
            updates = await api.bot.get_updates(offset=offset,timeout=25,allowed_updates=['message','callback_query','my_chat_member'],request_timeout=35)
            if not updates:
                continue
            with connect(db_path) as db:
                db.execute('BEGIN IMMEDIATE')
                for update in updates:
                    service.ingest(db,update.model_dump(mode='json',exclude_none=True))
                next_offset = updates[-1].update_id+1
                db.execute("INSERT INTO settings VALUES ('telegram_poll_offset',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(next_offset),))
                received_at = time.time()
                db.execute("INSERT INTO settings VALUES ('telegram_poll_received_at',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(received_at),))
            offset = next_offset  # Acknowledge to Telegram only after durable commit.
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning('Polling unavailable; retrying in 5s')
            await asyncio.sleep(5)


async def run(args, cfg):
    if not cfg.token:
        raise SystemExit('TELEGRAM_BOT_TOKEN is absent. Real sending NOT tested. Run: python -m unittest discover -s tests -v')
    if urlparse(cfg.app_url).scheme != 'https':
        raise SystemExit('Telegram Mini App and link buttons require an HTTPS QALDYQ_PUBLIC_URL (use a development tunnel).')
    if args.mode == 'webhook':
        cfg.webhook_url = cfg.webhook_url or cfg.app_url+'/api/telegram/webhook'
        parsed = urlparse(cfg.webhook_url)
        if parsed.scheme != 'https' or parsed.path != '/api/telegram/webhook' or parsed.query or parsed.fragment or parsed.username or parsed.password or not parsed.netloc:
            raise SystemExit('TELEGRAM_WEBHOOK_URL must be https://host/api/telegram/webhook')
        if not re.fullmatch(r'[A-Za-z0-9_-]{32,256}',cfg.webhook_secret):
            raise SystemExit('TELEGRAM_WEBHOOK_SECRET must contain 32–256 URL-safe characters')
    initialize(args.db)
    api = AiogramAPI(cfg.token)
    try:
        me = await api.bot.get_me(request_timeout=20)
        with connect(args.db) as db:
            db.execute("INSERT INTO settings VALUES ('telegram_bot_username',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(me.username,))
        if args.mode == 'polling':
            await api.bot.delete_webhook(drop_pending_updates=False)
        else:
            await api.bot.set_webhook(cfg.webhook_url,secret_token=cfg.webhook_secret,drop_pending_updates=False,
                                      allowed_updates=['message','callback_query','my_chat_member'])
        from aiogram.types import MenuButtonWebApp, WebAppInfo
        await api.bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text='Qaldyq',web_app=WebAppInfo(url=cfg.app_url+'/student/')))
        async with asyncio.TaskGroup() as group:
            group.create_task(work(args.db,cfg,api))
            if args.mode == 'polling':
                group.create_task(poll(args.db,api))
    finally:
        await api.close()


async def check_connection(cfg):
    """Read-only live check. Never output the token or raw API exceptions."""
    api = AiogramAPI(cfg.token)
    try:
        me = await api.bot.get_me(request_timeout=15)
        print(json.dumps({'ok': True, 'username': me.username}), flush=True)
    finally:
        await api.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Qaldyq Telegram transport and durable worker')
    parser.add_argument('--mode',choices=('polling','webhook'),default='polling')
    parser.add_argument('--db',default=os.getenv('QALDYQ_DB',str(ROOT/'data'/'qaldyq-v5.4.sqlite3')))
    parser.add_argument('--check',action='store_true',help='Check getMe without starting polling or changing webhook')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,format='%(levelname)s %(name)s: %(message)s')
    # Avoid third-party HTTP debug logs containing bot credentials.
    logging.getLogger('aiohttp').setLevel(logging.CRITICAL)
    try:
        config = service.Config.from_env()
        if not config.token:
            raise SystemExit('TELEGRAM_BOT_TOKEN is absent. Real sending NOT tested. Run: python tests/run_offline.py')
        asyncio.run(check_connection(config) if args.check else run(args,config))
    except KeyboardInterrupt:
        pass
    except Exception as error:
        raise SystemExit(f'Telegram startup failed ({type(error).__name__}). Check network and configuration; credentials were not logged.') from None
