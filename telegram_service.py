"""Durable Telegram inbox, conversations and outbox on the Qaldyq database.

No network calls here. Caller owns the transaction (BEGIN IMMEDIATE for writes).
"""
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from urllib.parse import parse_qsl, urlparse
from common import APIError
from features import generate_reminders, local_day
from report_domain import ReportDomain
import notify as notices
import telegram_students as campus

KINDS = notices.KINDS


@dataclass
class Config:
    token: str = field(default='', repr=False)
    app_url: str = 'http://127.0.0.1:8765'
    webhook_secret: str = field(default='', repr=False)
    webhook_url: str = ''
    init_max_age: int = 300
    max_attempts: int = 5
    username: str = 'Qalqyq_NOVA_bot'

    @classmethod
    def from_env(cls):
        cfg = cls(os.getenv('TELEGRAM_BOT_TOKEN', ''), (os.getenv('QALDYQ_PUBLIC_URL') or os.getenv('QALDYQ_APP_URL', 'http://127.0.0.1:8765')).rstrip('/'),
                  os.getenv('TELEGRAM_WEBHOOK_SECRET', ''), os.getenv('TELEGRAM_WEBHOOK_URL', ''),
                  int(os.getenv('TELEGRAM_INIT_DATA_MAX_AGE', '300')), int(os.getenv('TELEGRAM_MAX_ATTEMPTS', '5')),
                  os.getenv('TELEGRAM_BOT_USERNAME', 'Qalqyq_NOVA_bot').removeprefix('@'))
        parsed = urlparse(cfg.app_url)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
            raise ValueError('QALDYQ_PUBLIC_URL must be an HTTP(S) origin')
        if not 30 <= cfg.init_max_age <= 3600 or not 1 <= cfg.max_attempts <= 10:
            raise ValueError('Invalid Telegram lifetime/retry limits')
        return cfg


def migrate(db):
    notices.migrate(db)
    from common import add_column
    add_column(db, 'outbox', 'lease_token', 'TEXT')
    add_column(db, 'outbox', 'lease_until', 'REAL NOT NULL DEFAULT 0')
    db.executescript("""
    -- Compatibility view: there is ONE identity binding, in the existing external_links table.
    CREATE VIEW IF NOT EXISTS telegram_links AS SELECT CAST(address AS INTEGER) AS telegram_id,
      user_id,CAST(address AS INTEGER) AS chat_id,1-active AS blocked FROM external_links WHERE channel='telegram';
    CREATE TRIGGER IF NOT EXISTS telegram_link_insert INSTEAD OF INSERT ON telegram_links BEGIN
      INSERT INTO external_links(user_id,channel,address,linked_at,active)
      VALUES(NEW.user_id,'telegram',CAST(NEW.telegram_id AS TEXT),strftime('%Y-%m-%dT%H:%M:%f+00:00','now'),1-COALESCE(NEW.blocked,0)); END;
    CREATE TRIGGER IF NOT EXISTS telegram_link_update INSTEAD OF UPDATE ON telegram_links BEGIN
      UPDATE external_links SET active=1-NEW.blocked WHERE user_id=OLD.user_id AND channel='telegram'; END;
    CREATE TRIGGER IF NOT EXISTS telegram_link_delete INSTEAD OF DELETE ON telegram_links BEGIN
      DELETE FROM external_links WHERE user_id=OLD.user_id AND channel='telegram'; END;
    CREATE TABLE IF NOT EXISTS telegram_preferences(user_id INTEGER PRIMARY KEY REFERENCES users(id),
      org_id INTEGER REFERENCES organizations(id),language TEXT NOT NULL DEFAULT 'ru' CHECK(language IN ('ru','kk')));
    CREATE TABLE IF NOT EXISTS telegram_link_codes(
      digest TEXT PRIMARY KEY, telegram_id INTEGER NOT NULL, chat_id INTEGER NOT NULL,
      expires REAL NOT NULL, consumed INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS telegram_conversations(
      telegram_id INTEGER PRIMARY KEY, state TEXT NOT NULL, data TEXT NOT NULL, expires REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS telegram_inbox(
      update_id INTEGER PRIMARY KEY, payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
      attempts INTEGER NOT NULL DEFAULT 0, available_at REAL NOT NULL DEFAULT 0,
      error TEXT, created_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS telegram_outbox(
      id INTEGER PRIMARY KEY, event_key TEXT UNIQUE NOT NULL, user_id INTEGER REFERENCES users(id),
      telegram_id INTEGER NOT NULL, kind TEXT NOT NULL, method TEXT NOT NULL, payload TEXT NOT NULL,
      state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
      available_at REAL NOT NULL DEFAULT 0, lease_until REAL NOT NULL DEFAULT 0,
      lease_token TEXT, error TEXT, created_at REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS telegram_outbox_due ON telegram_outbox(state,available_at);
    """)


def validate_init_data(raw, cfg, clock=None):
    if not cfg.token:
        raise APIError('Telegram не настроен.', 503)
    if not isinstance(raw, str) or len(raw) > 16384:
        raise APIError('Неверные initData.', 401)
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        raise APIError('Неверные initData.', 401)
    data = dict(pairs)
    if len(pairs) != len(data) or 'hash' not in data:
        raise APIError('Неверные initData.', 401)
    received = data.pop('hash')
    secret = hmac.new(b'WebAppData', cfg.token.encode(), hashlib.sha256).digest()
    check = '\n'.join(f'{key}={value}' for key, value in sorted(data.items()))
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not re.fullmatch('[0-9a-f]{64}', received) or not hmac.compare_digest(expected, received):
        raise APIError('Неверная подпись initData.', 401)
    try:
        stamp = int(data['auth_date'])
        user = json.loads(data['user'])
        tid = user['id']
        if type(tid) is not int or tid <= 0:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise APIError('Неверные initData.', 401)
    age = (time.time() if clock is None else clock) - stamp
    if age < -30 or age > cfg.init_max_age:
        raise APIError('initData устарели. Откройте приложение заново.', 401)
    return tid


def check_webhook(headers, cfg):
    if not cfg.token or not cfg.webhook_secret:
        raise APIError('Webhook не настроен.', 503)
    if not hmac.compare_digest(headers.get('X-Telegram-Bot-Api-Secret-Token', ''), cfg.webhook_secret):
        raise APIError('Неверный секрет webhook.', 403)


def linked_user(db, tid):
    row = db.execute('SELECT u.* FROM users u JOIN telegram_links l ON l.user_id=u.id WHERE l.telegram_id=?', (tid,)).fetchone()
    if not row:
        raise APIError('Сначала /link для существующего аккаунта или /student для нового студента.', 401)
    if not row['active']:
        raise APIError('Аккаунт отключён администратором.', 403)
    return dict(row)


def bind_existing_code(db, tid, code):
    digest = hashlib.sha256(str(code).strip().upper().encode()).hexdigest()
    candidate = db.execute("SELECT user_id FROM link_codes WHERE code_hash=? AND channel='telegram'",(digest,)).fetchone()
    if not candidate or not db.execute('SELECT 1 FROM users WHERE id=? AND active=1',(candidate['user_id'],)).fetchone():
        raise APIError('Код недействителен.')
    if db.execute("SELECT 1 FROM external_links WHERE channel='telegram' AND (user_id=? OR address=?)",(candidate['user_id'],str(tid))).fetchone():
        raise APIError('Сначала отключите существующую привязку.',409)
    uid = notices.consume_link_code(db,code,str(tid))
    if uid is None:
        raise APIError('Код истёк или уже использован.',409)
    subscriptions(db,uid,{k:False for k in KINDS})
    return uid


def issue_link(db, tid, chat_id):
    code = secrets.token_urlsafe(32)
    db.execute('DELETE FROM telegram_link_codes WHERE telegram_id=? OR expires<?', (tid, time.time()))
    db.execute('INSERT INTO telegram_link_codes(digest,telegram_id,chat_id,expires) VALUES (?,?,?,?)',
               (hashlib.sha256(code.encode()).hexdigest(), tid, chat_id, time.time()+600))
    return code


def link_preview(db, code):
    row = db.execute('SELECT * FROM telegram_link_codes WHERE digest=? AND consumed=0 AND expires>?',
                     (hashlib.sha256(str(code).encode()).hexdigest(), time.time())).fetchone()
    if not row:
        raise APIError('Подтверждение истекло или уже использовано.', 409)
    return row


def confirm_link(db, user, code):
    row = link_preview(db, code)
    # Never silently move an identity between accounts, even with a valid code.
    existing = db.execute('SELECT * FROM telegram_links WHERE telegram_id=? OR user_id=?', (row['telegram_id'], user['id'])).fetchall()
    if existing:
        raise APIError('Аккаунт уже привязан. Сначала отключите старую привязку в настройках.', 409)
    db.execute('UPDATE telegram_link_codes SET consumed=1 WHERE digest=?', (row['digest'],))
    db.execute('INSERT INTO telegram_links(telegram_id,user_id,chat_id) VALUES (?,?,?)', (row['telegram_id'], user['id'], row['chat_id']))
    db.execute('DELETE FROM telegram_conversations WHERE telegram_id=?', (row['telegram_id'],))
    for kind in KINDS:
        db.execute("INSERT OR IGNORE INTO subscriptions(user_id,channel,kind,enabled) VALUES (?,'telegram',?,0)", (user['id'], kind))
    return {'ok': True}


def unlink(db, user_id):
    rows = db.execute('SELECT telegram_id FROM telegram_links WHERE user_id=?', (user_id,)).fetchall()
    for row in rows:
        db.execute('DELETE FROM telegram_conversations WHERE telegram_id=?', (row[0],))
        db.execute('DELETE FROM telegram_link_codes WHERE telegram_id=?', (row[0],))
        db.execute("UPDATE telegram_outbox SET state='cancelled' WHERE telegram_id=? AND state IN ('pending','sending')", (row[0],))
    db.execute('DELETE FROM telegram_links WHERE user_id=?', (user_id,))
    db.execute("UPDATE subscriptions SET enabled=0 WHERE user_id=? AND channel='telegram'", (user_id,))
    db.execute("UPDATE outbox SET status='skipped' WHERE user_id=? AND channel='telegram' AND status IN ('pending','sending')", (user_id,))


def subscriptions(db, user_id, changes=None):
    if changes is not None:
        if not isinstance(changes, dict) or any(k not in KINDS or type(v) is not bool for k,v in changes.items()):
            raise APIError('Некорректные подписки.')
        for kind, enabled in changes.items():
            db.execute("INSERT INTO subscriptions(user_id,channel,kind,enabled) VALUES (?,'telegram',?,?) ON CONFLICT(user_id,channel,kind) DO UPDATE SET enabled=excluded.enabled", (user_id,kind,int(enabled)))
            if not enabled:
                db.execute("UPDATE outbox SET status='skipped' WHERE user_id=? AND channel='telegram' AND kind=? AND status='pending'", (user_id,kind))
    return {kind:notices.subscribed(db,user_id,'telegram',kind) for kind in KINDS}


def enqueue(db, event_key, tid, method, payload, kind='system', user_id=None):
    db.execute('INSERT OR IGNORE INTO telegram_outbox(event_key,user_id,telegram_id,kind,method,payload,created_at) VALUES (?,?,?,?,?,?,?)',
               (event_key, user_id, tid, kind, method, json.dumps(payload, ensure_ascii=False), time.time()))


def report_returned(db, org_id, report_id, comment, event_id, period=False):
    path = '/#periods' if period else f'/?report={report_id}#report'
    for user in db.execute("SELECT id FROM users WHERE role='operator' AND active=1 AND org_id=?",(org_id,)).fetchall():
        notices.enqueue(db,user['id'],'report_returned','Есеп қайтарылды / Отчёт возвращён',
            f'№{report_id}: {comment}',f'telegram-return:{"period" if period else "record"}:{event_id}',{'org_id':org_id,'path':path})


def collect_reminders(db):
    generate_reminders(db)
    for row in db.execute('SELECT n.*,u.org_id FROM notifications n JOIN users u ON u.id=n.user_id WHERE n.resolved_at IS NULL AND u.active=1').fetchall():
        notices.enqueue(db,row['user_id'],'report_deadline',row['title'],row['message'],f'deadline:{row["id"]}',
                        {'notification_id':row['id'],'org_id':row['org_id'],'path':'/#notifications'})


def public_config(db, cfg=None):
    cfg = cfg or Config.from_env()
    saved = db.execute("SELECT value FROM settings WHERE key='telegram_bot_username'").fetchone()
    username = saved[0] if saved else cfg.username
    if not re.fullmatch(r'[A-Za-z0-9_]{5,32}',username):
        return {'url':None}
    return {'url':'https://t.me/'+username,'username':username,'mini_app_url':cfg.app_url+'/student/'}


def handle(h, db, user, method, path, query):
    if not path.startswith('/api/telegram/'):
        return False
    if path == '/api/telegram/settings' and method in ('GET','POST'):
        changes = h.body() if method == 'POST' else None
        h.respond({'subscriptions':subscriptions(db,user['id'],changes),
            'linked':bool(db.execute("SELECT 1 FROM external_links WHERE user_id=? AND channel='telegram'",(user['id'],)).fetchone())})
    elif path == '/api/telegram/link/preview' and method == 'POST':
        link = link_preview(db,h.body().get('code'))
        h.respond({'telegram_id':link['telegram_id'],'account':user['email'],'role':user['role']})
    elif path == '/api/telegram/link/confirm' and method == 'POST':
        h.respond(confirm_link(db,user,h.body().get('code')))
    elif path == '/api/telegram/unlink' and method == 'POST':
        unlink(db,user['id'])
        h.respond({'ok':True})
    else:
        raise APIError('Telegram endpoint не найден.',404)
    return True


def ingest(db, update):
    uid = update.get('update_id')
    if type(uid) is not int or uid < 0:
        raise APIError('Некорректный update_id.')
    db.execute('INSERT OR IGNORE INTO telegram_inbox(update_id,payload,created_at) VALUES (?,?,?)', (uid, json.dumps(update, ensure_ascii=False), time.time()))


def buttons(rows):
    return {'inline_keyboard': [[{'text': label, 'callback_data': value} for label,value in row] for row in rows]}


class Conversation:
    def __init__(self, db, cfg, update, photo=None):
        self.db, self.cfg, self.update, self.photo = db, cfg, update, photo
        self.uid = update['update_id']
        self.callback = update.get('callback_query')
        self.message = (self.callback or {}).get('message') or update.get('message') or update.get('my_chat_member') or {}
        sender = (self.callback or {}).get('from') or self.message.get('from') or {}
        self.tid = sender.get('id')
        self.chat = self.message.get('chat', {})
        self.serial = 0

    def reply(self, text, markup=None):
        self.serial += 1
        payload = {'chat_id': self.chat['id'], 'text': text}
        if markup:
            payload['reply_markup'] = markup
        if hasattr(self,'staff_org'):
            payload['_staff_org_id']=self.staff_org
        link=self.db.execute('SELECT user_id FROM telegram_links WHERE telegram_id=?',(self.tid,)).fetchone()
        enqueue(self.db, f'reply:{self.uid}:{self.serial}', self.tid, 'sendMessage', payload,user_id=link['user_id'] if link else None)

    def save(self, state, data):
        self.db.execute('INSERT INTO telegram_conversations VALUES (?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET state=excluded.state,data=excluded.data,expires=excluded.expires',
                        (self.tid, state, json.dumps(data), time.time()+1800))

    def clear(self):
        self.db.execute('DELETE FROM telegram_conversations WHERE telegram_id=?', (self.tid,))

    def run(self):
        if self.chat.get('type') != 'private' or type(self.tid) is not int or self.chat.get('id') != self.tid:
            return  # No account, orders or photos may be exposed in groups.
        if self.callback:
            enqueue(self.db, f'callback:{self.uid}', self.tid, 'answerCallbackQuery', {'callback_query_id': self.callback['id']})
        if 'my_chat_member' in self.update:
            blocked = self.message.get('new_chat_member', {}).get('status') in ('kicked', 'left')
            self.db.execute('UPDATE telegram_links SET blocked=? WHERE telegram_id=?', (int(blocked),self.tid))
            if blocked:
                disable_recipient(self.db,self.tid)
            return
        text = self.message.get('text', '').strip()
        command = text.split()[0].split('@')[0] if text else ''
        action = (self.callback or {}).get('data', '')
        if command == '/start':
            self.db.execute('UPDATE telegram_links SET blocked=0 WHERE telegram_id=?', (self.tid,))
            return self.reply('Qaldyq\n/link — привязать существующий аккаунт (роль только из Qaldyq).\n/employee — сотрудник\n/student — студент (новый профиль, если аккаунта нет)\n/subscriptions — подписки\n/stop — отключить уведомления\n/unlink — отключить привязку\n/cancel — отменить ввод')
        if command == '/link':
            parts = text.split(maxsplit=1)
            if len(parts) == 2:
                bind_existing_code(self.db,self.tid,parts[1])
                return self.reply('Аккаунт привязан. /employee — сотрудник, /student — студент, /subscriptions — уведомления.')
            code = issue_link(self.db, self.tid, self.chat['id'])
            return self.reply('Войдите в существующий аккаунт Qaldyq и подтвердите Telegram ID. Ссылка действует 10 минут; не пересылайте её.',
                {'inline_keyboard': [[{'text': 'Подтвердить привязку', 'url': self.cfg.app_url+'/telegram-link.html#'+code}]]})
        if command == '/cancel':
            self.clear()
            return self.reply('Ввод отменён.')
        if command == '/student':
            link = self.db.execute('SELECT 1 FROM telegram_links WHERE telegram_id=?', (self.tid,)).fetchone()
            if not link:
                # Explicitly created low-privilege account, never guessed by name/username.
                salt = secrets.token_hex(16)
                user_id = self.db.execute("INSERT INTO users(email,name,role,salt,password_hash) VALUES (?,?,'student',?,?)",
                    (f'telegram-{self.tid}-{secrets.token_hex(8)}@telegram.invalid', f'Student {self.tid}', salt, secrets.token_hex(32))).lastrowid
                self.db.execute('INSERT INTO telegram_links(telegram_id,user_id,chat_id) VALUES (?,?,?)', (self.tid,user_id,self.chat['id']))
            user = linked_user(self.db, self.tid)
            self.clear()
            return self.student_home(user)
        user = linked_user(self.db, self.tid)  # Always read current role and organization.
        if command == '/unlink':
            unlink(self.db, user['id'])
            return self.reply('Привязка и подписки отключены. /link — привязать другой аккаунт.')
        if command in ('/stop', '/subscriptions') or action.startswith('sub:'):
            if command == '/stop':
                subscriptions(self.db, user['id'], {k:False for k in KINDS})
            if action.startswith('sub:'):
                _, kind, value = action.split(':')
                subscriptions(self.db, user['id'], {kind:value == '1'})
            prefs = subscriptions(self.db, user['id'])
            return self.reply('Подписки (кнопка переключает состояние). /stop — отключить все.', buttons([
                [(f'{k}: {"вкл" if v else "выкл"}', f'sub:{k}:{0 if v else 1}')] for k,v in prefs.items()]))
        if command == '/employee' or action == 'employee':
            self.employee(user)
            self.clear()
            return self.reply('Сотрудник Qaldyq', buttons([[('Новое взвешивание', 'weigh')], [('Итоги и статус', 'reports')], [('Веб-форма', 'web')]]))
        if action in ('weigh', 'reports', 'web') or action.startswith(('cat:', 'stage:', 'route:', 'confirm:')):
            self.employee(user)
        if action == 'web':
            return self.reply('Откройте форму и войдите в служебный аккаунт.', {'inline_keyboard': [[{'text':'Веб-форма','url':self.cfg.app_url+'/?org='+str(user['org_id'])+'#new-report'}]]})
        if action == 'reports':
            reports = ReportDomain().list_reports(self.db, user, {})[:10]
            return self.reply('\n'.join(f'№{r["id"]} · {r["report_date"]} · {r["kg"]} kg / {r["liters"]} l · {r["status"]}' for r in reports) or 'Отчётов нет.')
        if action == 'weigh':
            self.save('category', {'org_id': user['org_id'], 'user_id':user['id']})
            cats = self.db.execute('SELECT c.* FROM categories c JOIN org_categories oc ON oc.category_id=c.id WHERE c.active=1 AND oc.org_id=?', (user['org_id'],)).fetchall()
            return self.reply('Выберите вид отхода вашей организации.', buttons([[(f'{r["name"]} ({r["unit"]})', f'cat:{r["id"]}')] for r in cats]))
        if action == 'student':
            self.clear()
            return self.student_home(user)
        if action.startswith('lang:'):
            campus.preferences(self.db, user['id'], {'language':action.split(':')[1]})
            return self.student_home(user)
        if action == 'canteens':
            return self.reply('Столовая / Асхана', buttons([[(r['name'],f'canteen:{r["id"]}')] for r in campus.canteens(self.db)]))
        if action.startswith('canteen:'):
            campus.preferences(self.db, user['id'], {'org_id':int(action.split(':')[1])})
            return self.student_home(user)
        if action == 'menu':
            pref = campus.preferences(self.db, user['id'])
            if not pref['org_id']:
                return self.reply('Выберите столовую / Асхананы таңдаңыз.', buttons([[('Столовая / Асхана','canteens')]]))
            foods = campus.menu(self.db, pref['org_id'])
            return self.reply('\n'.join(f'{r["name_"+pref["language"]]} · {r["price"]} ₸' for r in foods) or 'Меню пока не опубликовано / Мәзір әлі жарияланбаған.')
        if action == 'orders':
            orders = campus.own_orders(self.db, user['id'])[:10]
            return self.reply('\n'.join(f'№{r["id"]} · {r["total"]} ₸ · {r["status"]}' for r in orders) or 'Заказов нет / Тапсырыс жоқ.')
        row = self.db.execute('SELECT * FROM telegram_conversations WHERE telegram_id=? AND expires>?', (self.tid,time.time())).fetchone()
        if not row:
            return self.reply('Выберите /employee или /student. Сессия ввода могла истечь.')
        self.employee(user)
        data, state = json.loads(row['data']), row['state']
        if data['user_id'] != user['id'] or data['org_id'] != user['org_id']:
            self.clear()
            raise APIError('Организация или аккаунт изменились. Начните заново.',403)
        if action.startswith('cat:') and state == 'category':
            cat_id = int(action.split(':')[1])
            cat = self.db.execute('SELECT c.* FROM categories c JOIN org_categories oc ON oc.category_id=c.id WHERE c.active=1 AND c.id=? AND oc.org_id=?', (cat_id,user['org_id'])).fetchone()
            if not cat:
                raise APIError('Вид отхода недоступен.',403)
            data.update(category_id=cat_id, unit=cat['unit'], category_name=cat['name'])
            self.save('quantity',data)
            return self.reply(f'Введите количество ({cat["unit"]}), 0.01–10000.')
        if state == 'quantity' and not action:
            from common import number
            data['quantity'] = number(text.replace(',', '.'), 'Количество', 0.01,10000)
            self.save('stage',data)
            return self.reply('Выберите этап образования отхода.', buttons([[(label,'stage:'+key)] for key,label in [('prep','Приготовление'),('unsold','Не продано'),('plate','С тарелок'),('storage','Хранение'),('other','Другое')]]))
        if state == 'stage' and action.startswith('stage:'):
            from common import STAGES
            stage = action.split(':')[1]
            if stage not in STAGES:
                raise APIError('Неверный этап.')
            data['stage'] = stage
            self.save('route',data)
            routes = self.db.execute('SELECT code,name FROM routes WHERE active=1 ORDER BY position,code').fetchall()
            return self.reply('Выберите утилизацию.',buttons([[(r['name'],'route:'+r['code'])] for r in routes]))
        if state == 'route' and action.startswith('route:'):
            route = action.split(':')[1]
            if not self.db.execute('SELECT 1 FROM routes WHERE code=? AND active=1',(route,)).fetchone():
                raise APIError('Неизвестная утилизация.')
            data['route'] = route
            self.save('photo',data)
            return self.reply('Прикрепите фото до 2 МБ или отправьте /skip.')
        if state == 'photo' and not action:
            if command != '/skip' and not self.photo:
                raise APIError('Прикрепите фото до 2 МБ или /skip.')
            data['photo'] = None if command == '/skip' else self.photo
            data['confirmation'] = secrets.token_hex(12)
            data['report_date'] = local_day().isoformat()
            self.save('confirm',data)
            return self.reply(f'{data["category_name"]}: {data["quantity"]} {data["unit"]}\n{data["route"]} · {data["report_date"]}\nФото: {"да" if data["photo"] else "нет"}. Сохранить в черновой отчёт?',buttons([[('Подтвердить',f'confirm:{data["confirmation"]}')]]))
        if state == 'confirm' and action == 'confirm:'+data['confirmation']:
            if data['report_date'] != local_day().isoformat():
                raise APIError('Дата изменилась. Отправьте /cancel и начните взвешивание заново.')
            # A confirmation key plus inbox PK protect both repeated updates and repeated clicks.
            result = ReportDomain().save_quick(self.db,user,{'org_id':data['org_id'],
                'photo':data['photo'],'note':'Telegram: взвешивание','request_id':'tg-'+data['confirmation'],
                'category_id':data['category_id'],'kg':data['quantity'],'route':data['route'],'stage':data.get('stage','other')})
            self.clear()
            return self.reply(f'Сохранено: черновик №{result["id"]}.', {'inline_keyboard': [[{'text':'Открыть отчёт','url':self.cfg.app_url+f'/?report={result["id"]}#report'}]]})
        self.reply('Эта кнопка устарела. Продолжите ввод или /cancel.')

    def employee(self, user):
        if not user['active'] or user['role'] not in ('operator','admin') or not user['org_id']:
            raise APIError('Нужен служебный аккаунт с правом ввода и назначенной организацией. Telegram не подтверждает роль.',403)
        self.staff_org=user['org_id']

    def student_home(self, user):
        pref = campus.preferences(self.db, user['id'])
        kk = pref['language'] == 'kk'
        markup = buttons([[('Асхана' if kk else 'Столовая','canteens'),('Қазақша','lang:kk'),('Русский','lang:ru')],
                          [('Мәзір' if kk else 'Меню','menu'),('Тапсырыстарым' if kk else 'Мои заказы','orders')]])
        markup['inline_keyboard'].append([{'text':'Qaldyq Mini App','web_app':{'url':self.cfg.app_url+'/student/'}}])
        self.reply('Студент · Qaldyq\n'+('Тілді және асхананы таңдаңыз.' if kk else 'Выберите язык и столовую. /subscriptions — уведомления (по умолчанию выключены).'),markup)


def process(db, cfg, update, photo=None):
    row = db.execute('SELECT state FROM telegram_inbox WHERE update_id=?', (update['update_id'],)).fetchone()
    if not row or row['state'] != 'pending':
        return
    conversation = Conversation(db,cfg,update,photo)
    db.execute('SAVEPOINT telegram_business')
    try:
        conversation.run()
    except (APIError, ValueError, TypeError, KeyError) as error:
        db.execute('ROLLBACK TO telegram_business')
        conversation.serial = 100
        if conversation.chat.get('type') == 'private' and conversation.chat.get('id') == conversation.tid:
            conversation.reply(error.message if isinstance(error,APIError) else 'Некорректный ввод. Повторите шаг или /cancel.')
    finally:
        db.execute('RELEASE telegram_business')
    db.execute("UPDATE telegram_inbox SET state='done',error=NULL WHERE update_id=?",(update['update_id'],))


def claim_delivery(db, cfg, clock=None):
    clock = time.time() if clock is None else clock
    db.execute("UPDATE telegram_outbox SET state='pending',lease_token=NULL WHERE state='sending' AND lease_until<?",(clock,))
    while True:
        row = db.execute("SELECT * FROM telegram_outbox WHERE state='pending' AND available_at<=? ORDER BY id LIMIT 1",(clock,)).fetchone()
        if not row:
            return None
        link = db.execute('SELECT * FROM telegram_links WHERE telegram_id=?',(row['telegram_id'],)).fetchone()
        eligible = row['kind'] == 'system' or (link and link['user_id'] == row['user_id'] and not link['blocked'] and subscriptions(db,row['user_id'])[row['kind']])
        payload = json.loads(row['payload'])
        if eligible and row['user_id'] is not None:
            user=db.execute('SELECT active,role,org_id FROM users WHERE id=?',(row['user_id'],)).fetchone()
            eligible=bool(user and user['active'] and link and link['user_id']==row['user_id'] and not link['blocked'])
            if eligible and '_staff_org_id' in payload:
                eligible=user['role'] in ('operator','admin') and user['org_id']==payload['_staff_org_id']
        if eligible and row['kind'] in ('reports','reminders'):
            user = db.execute('SELECT role,org_id FROM users WHERE id=?',(row['user_id'],)).fetchone()
            eligible = bool(user and user['role'] in ('operator','admin') and user['org_id'] == payload.get('_org_id'))
        if eligible and row['kind'] == 'reminders' and '_notification_id' in payload:
            eligible = bool(db.execute('SELECT 1 FROM notifications WHERE id=? AND user_id=? AND resolved_at IS NULL', (payload['_notification_id'],row['user_id'])).fetchone())
        if row['attempts'] >= cfg.max_attempts or not eligible:
            db.execute('UPDATE telegram_outbox SET state=? WHERE id=?', ('failed' if eligible else 'cancelled',row['id']))
            continue
        lease = secrets.token_hex(16)
        db.execute("UPDATE telegram_outbox SET state='sending',attempts=attempts+1,lease_until=?,lease_token=? WHERE id=?",(clock+120,lease,row['id']))
        result = dict(row)
        result.update(attempts=row['attempts']+1,lease_token=lease)
        return result


def finish_delivery(db, cfg, row, result='sent', retry_after=None):
    current = db.execute("SELECT 1 FROM telegram_outbox WHERE id=? AND state='sending' AND lease_token=?",(row['id'],row['lease_token'])).fetchone()
    if not current:
        return
    if result == 'blocked':
        disable_recipient(db,row['telegram_id'])
        return
    state = 'sent' if result == 'sent' else ('failed' if result == 'permanent' or row['attempts'] >= cfg.max_attempts else 'pending')
    delay = max(2**row['attempts'], min(retry_after or 0,86400))
    db.execute('UPDATE telegram_outbox SET state=?,available_at=?,lease_until=0,lease_token=NULL,error=? WHERE id=?',
               (state,time.time()+delay,None if result=='sent' else result,row['id']))


def disable_recipient(db, tid):
    db.execute("UPDATE external_links SET active=0 WHERE channel='telegram' AND address=?",(str(tid),))
    db.execute("UPDATE subscriptions SET enabled=0 WHERE channel='telegram' AND user_id IN (SELECT user_id FROM external_links WHERE channel='telegram' AND address=?)",(str(tid),))
    db.execute("UPDATE outbox SET status='skipped',last_error='blocked' WHERE channel='telegram' AND status IN ('pending','sending') AND user_id IN (SELECT user_id FROM external_links WHERE channel='telegram' AND address=?)",(str(tid),))
    db.execute("UPDATE telegram_outbox SET state='cancelled',error='blocked' WHERE telegram_id=? AND state IN ('pending','sending')",(tid,))


def claim_notification(db, cfg, clock=None):
    """Lease an item from the EXISTING shared notification outbox; do not copy messages."""
    from datetime import datetime, timezone
    clock = time.time() if clock is None else clock
    stamp = datetime.fromtimestamp(clock,timezone.utc).isoformat(timespec='microseconds')
    db.execute("UPDATE outbox SET status='pending',lease_token=NULL WHERE channel='telegram' AND status='sending' AND lease_until<?",(clock,))
    while True:
        row = db.execute("SELECT * FROM outbox WHERE channel='telegram' AND status='pending' AND next_attempt_at<=? ORDER BY id LIMIT 1",(stamp,)).fetchone()
        if not row:
            return None
        link = db.execute("SELECT * FROM external_links WHERE user_id=? AND channel='telegram' AND active=1",(row['user_id'],)).fetchone()
        user = db.execute('SELECT * FROM users WHERE id=?',(row['user_id'],)).fetchone()
        payload = json.loads(row['payload'])
        eligible = bool(link and user and user['active'] and re.fullmatch(r'[1-9][0-9]{0,18}',link['address']) and notices.subscribed(db,row['user_id'],'telegram',row['kind']))
        if eligible and row['kind'] in ('report_deadline','report_returned'):
            eligible = user['role'] in ('operator','admin') and user['org_id'] == payload.get('org_id')
        if eligible and 'notification_id' in payload:
            eligible = bool(db.execute('SELECT 1 FROM notifications WHERE id=? AND user_id=? AND resolved_at IS NULL',(payload['notification_id'],row['user_id'])).fetchone())
        if not eligible or row['attempts'] >= cfg.max_attempts:
            db.execute('UPDATE outbox SET status=? WHERE id=?',('failed' if eligible else 'skipped',row['id']))
            continue
        lease = secrets.token_hex(16)
        db.execute("UPDATE outbox SET status='sending',attempts=attempts+1,lease_until=?,lease_token=? WHERE id=?",(clock+120,lease,row['id']))
        return {**dict(row),'attempts':row['attempts']+1,'lease_token':lease,'telegram_id':int(link['address'])}


def finish_notification(db,cfg,row,result='sent',retry_after=None):
    from datetime import datetime, timezone
    if not db.execute("SELECT 1 FROM outbox WHERE id=? AND status='sending' AND lease_token=?",(row['id'],row['lease_token'])).fetchone():
        return
    if result == 'blocked':
        disable_recipient(db,row['telegram_id'])
        return
    status = 'sent' if result == 'sent' else ('failed' if result == 'permanent' or row['attempts'] >= cfg.max_attempts else 'pending')
    next_at = datetime.fromtimestamp(time.time()+max(2**row['attempts'],min(retry_after or 0,86400)),timezone.utc).isoformat(timespec='microseconds')
    db.execute('UPDATE outbox SET status=?,sent_at=?,next_attempt_at=?,lease_until=0,lease_token=NULL,last_error=? WHERE id=?',
        (status,datetime.now(timezone.utc).isoformat() if status=='sent' else None,next_at,None if result=='sent' else result,row['id']))
