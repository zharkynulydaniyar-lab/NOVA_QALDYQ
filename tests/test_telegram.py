"""Acceptance against the current repository's domain, HTTP handlers and shared SQLite."""
import base64
from contextlib import closing
from datetime import datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import common
from common import APIError
from server import connect
import mod_student
import mod_period
import notify
import telegram_service as tg
from telegram_bot import deliver_one, deliver_notification, process_one, DeliveryFailure, poll
from http_memory import MemoryClient, create_memory_server

TOKEN='123456789:offline-test-not-a-real-token'


def signed(tid=101,stamp=None):
    data={'auth_date':str(int(time.time()) if stamp is None else stamp),'user':json.dumps({'id':tid,'first_name':'Admin','username':'operator'})}
    key=hmac.new(b'WebAppData',TOKEN.encode(),hashlib.sha256).digest()
    data['hash']=hmac.new(key,'\n'.join(f'{k}={v}' for k,v in sorted(data.items())).encode(),hashlib.sha256).hexdigest()
    return urlencode(data)


def ready(coroutine):
    # FakeAPI never suspends; no socket-backed event loop is needed in the sandbox.
    try:
        coroutine.send(None)
    except StopIteration as done:
        return done.value
    finally:
        coroutine.close()
    raise AssertionError('Unexpected real I/O in offline test')


class FakeAPI:
    def __init__(self,error=None):
        self.sent=[]
        self.error=error

    async def send(self,method,payload):
        self.sent.append((method,payload))
        if self.error:
            raise self.error

    async def photo(self,message):
        return 'data:image/jpeg;base64,'+base64.b64encode(b'\xff\xd8\xfftest').decode()


class TelegramAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_temp=tempfile.TemporaryDirectory()
        cls.base_db=str(Path(cls.base_temp.name)/'base.sqlite3')
        with patch.dict(os.environ,{'QALDYQ_DEMO':'0'}):
            cls.template=create_memory_server(db_path=cls.base_db)

    @classmethod
    def tearDownClass(cls):
        cls.template.server_close()
        cls.base_temp.cleanup()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=str(Path(self.temp.name)/'test.sqlite3')
        import sqlite3
        with closing(sqlite3.connect(self.base_db)) as source, closing(sqlite3.connect(self.db)) as target:
            source.backup(target)
        with patch.dict(os.environ,{'QALDYQ_DEMO':'0'}):
            self.server=create_memory_server(db_path=self.db)
        self.cfg=tg.Config(token=TOKEN,app_url='https://qaldyq.test',webhook_secret='x'*32,max_attempts=3)
        self.server.telegram_config=self.cfg
        self.base=f'http://127.0.0.1:{self.server.server_port}'
        self.operator=MemoryClient(self.base).login('operator')
        self.reviewer=MemoryClient(self.base).login('reviewer')
        self.student=MemoryClient(self.base).login('student')
        self.admin=MemoryClient(self.base).login('admin')
        self.link(101,self.operator.user)
        self.link(202,self.student.user)
        self.uid=0

    def tearDown(self):
        self.server.server_close()
        self.temp.cleanup()

    def link(self,tid,user):
        with connect(self.db) as db:
            db.execute('BEGIN IMMEDIATE')
            code=tg.issue_link(db,tid,tid)
            tg.confirm_link(db,user,code)
        return code

    def scalar(self,sql,args=()):
        with connect(self.db) as db:
            return db.execute(sql,args).fetchone()[0]

    def mini(self,path,method='GET',data=None,tid=202,raw=None):
        return MemoryClient(self.base).request(path,method,data,{'Authorization':'tma '+(raw if raw is not None else signed(tid))})

    def step(self,text=None,action=None,tid=101,chat='private',extra=None):
        self.uid+=1
        message={'message_id':self.uid,'chat':{'id':tid,'type':chat},'from':{'id':tid,'is_bot':False},**(extra or {})}
        if text is not None:
            message['text']=text
        update={'update_id':self.uid,'message':message} if action is None else {'update_id':self.uid,'callback_query':{'id':str(self.uid),'data':action,'message':message,'from':message['from']}}
        with connect(self.db) as db:
            tg.ingest(db,update)
        ready(process_one(self.db,self.cfg,FakeAPI()))
        return update

    def conversation(self):
        with connect(self.db) as db:
            r=db.execute('SELECT * FROM telegram_conversations WHERE telegram_id=101').fetchone()
            return r['state'],json.loads(r['data'])

    def weigh(self,category=1,quantity='2,5',photo=True):
        self.step(action='weigh')
        self.step(action=f'cat:{category}')
        self.step(text=quantity)
        self.step(action='stage:prep')
        self.step(action='route:compost')
        if photo:
            self.step(extra={'photo':[{'file_id':'fake'}]})
        else:
            self.step(text='/skip')
        state,data=self.conversation()
        self.assertEqual(state,'confirm')
        return data

    def test_init_data_signature_expiry_future_duplicates_and_revoked_account(self):
        self.assertEqual(tg.validate_init_data(signed(),self.cfg),101)
        for raw in [signed().replace('Admin','Owner'),signed(stamp=1),signed(stamp=int(time.time())+100),signed()+'&user=extra','']:
            with self.assertRaises(APIError):
                tg.validate_init_data(raw,self.cfg)
        self.assertEqual(self.mini('/api/me')[0],200)
        self.assertEqual(self.mini('/api/reports')[0],403)
        with connect(self.db) as db:
            db.execute('UPDATE users SET active=0 WHERE id=?',(self.student.user['id'],))
        self.assertEqual(self.mini('/api/me')[0],403)

    def test_link_uses_shared_identity_and_one_time_csrf_confirmation(self):
        with connect(self.db) as db:
            code=tg.issue_link(db,303,303)
        self.assertEqual(self.admin.post('/api/telegram/link/preview',{'code':code})[1]['telegram_id'],303)
        self.assertEqual(self.admin.request('/api/telegram/link/confirm','POST',{'code':code},{'X-CSRF-Token':'bad'})[0],403)
        self.assertEqual(self.admin.post('/api/telegram/link/confirm',{'code':code})[0],200)
        self.assertEqual(self.admin.post('/api/telegram/link/confirm',{'code':code})[0],409)
        self.assertEqual(self.scalar("SELECT address FROM external_links WHERE user_id=? AND channel='telegram'",(self.admin.user['id'],)),'303')
        self.assertEqual(self.scalar("SELECT type FROM sqlite_master WHERE name='telegram_links'"),'view')

    def test_existing_web_profile_link_code_is_accepted_once(self):
        code=self.admin.post('/api/student/telegram-link',{})[1]['code']
        self.assertGreaterEqual(len(code),32)
        self.step(text='/link '+code,tid=303)
        self.assertEqual(self.scalar("SELECT user_id FROM external_links WHERE address='303'"),self.admin.user['id'])
        self.step(text='/link '+code,tid=404)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM external_links WHERE address='404'"),0)

    def test_confirmed_photo_and_redelivery_share_web_reports(self):
        before=self.scalar('SELECT COUNT(*) FROM items')
        data=self.weigh()
        update=self.step(action='confirm:'+data['confirmation'])
        with connect(self.db) as db:
            tg.ingest(db,update)
            tg.process(db,self.cfg,update)
        self.step(action='confirm:'+data['confirmation'])
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM items'),before+1)
        rid=self.scalar('SELECT MAX(id) FROM reports')
        result=self.operator.get(f'/api/reports/{rid}')
        self.assertEqual(result[0],200)
        self.assertEqual(result[1]['status'],'draft')
        self.assertEqual(result[1]['items'][0]['kg'],2.5)
        self.assertTrue(result[1]['photo'].startswith('data:image/jpeg'))

    def test_litres_and_org_category_scope(self):
        data=self.weigh(category=5,quantity='1.25',photo=False)
        self.assertEqual(data['unit'],'l')
        self.step(action='confirm:'+data['confirmation'])
        self.assertEqual(self.scalar('SELECT category_id FROM items ORDER BY id DESC LIMIT 1'),5)
        self.step(action='weigh')
        self.step(action='cat:7')  # coffee grounds belong to another organization
        self.assertEqual(self.conversation()[0],'category')

    def test_role_and_org_change_prevent_pending_confirmation(self):
        data=self.weigh()
        before=self.scalar('SELECT COUNT(*) FROM items')
        with connect(self.db) as db:
            db.execute("UPDATE users SET role='student' WHERE id=?",(self.operator.user['id'],))
        self.step(action='confirm:'+data['confirmation'])
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM items'),before)
        with connect(self.db) as db:
            db.execute("UPDATE users SET role='operator',org_id=2 WHERE id=?",(self.operator.user['id'],))
        self.step(action='confirm:'+data['confirmation'])
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM items'),before)

    def test_locked_period_uses_existing_web_policy(self):
        data=self.weigh(photo=False)
        from common import local_day, now
        day=local_day().isoformat()
        with connect(self.db) as db:
            db.execute("INSERT INTO period_reports(org_id,period_start,period_end,status,created_by,created_at,updated_at) VALUES (?,?,?,'submitted',?,?,?)",(1,day[:7]+'-01',day,1,now(),now()))
        before=self.scalar('SELECT COUNT(*) FROM items')
        self.step(action='confirm:'+data['confirmation'])
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM items'),before)

    def test_unlinked_student_and_group_isolation(self):
        self.step(text='/student',tid=404,chat='group')
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM external_links WHERE address='404'"),0)
        self.step(text='/student',tid=404)
        self.assertEqual(self.mini('/api/me',tid=404)[1]['user']['role'],'student')
        self.assertEqual(self.mini('/api/catalog',tid=404)[0],403)
        self.step(action='lang:kk',tid=404)
        self.step(action='canteen:2',tid=404)
        self.assertEqual(self.scalar('SELECT language FROM telegram_preferences WHERE user_id=(SELECT user_id FROM external_links WHERE address=?)',('404',)),'kk')

    def publish(self):
        dish={'org_id':1,'name':'Telegram test','portions':[{'label':'1','grams':200,'price':'750.50'}]}
        dish_id=self.operator.post('/api/catalog',dish)[1]['id']
        with connect(self.db) as db:
            portion=db.execute('SELECT id FROM dish_portions WHERE dish_id=?',(dish_id,)).fetchone()[0]
        body={'org_id':1,'day':'2026-11-17','order_deadline':'2026-11-17T11:00','pickup_start':'12:00','pickup_end':'14:00','items':[{'portion_id':portion,'available':5}]}
        menu=self.operator.put('/api/menu',body)[1]['id']
        self.assertEqual(self.operator.post(f'/api/menu/{menu}/publish',{})[0],200)
        with connect(self.db) as db:
            item=db.execute('SELECT id FROM menu_items WHERE menu_id=?',(menu,)).fetchone()[0]
        return {'menu_id':menu,'pickup_slot':'12:00','request_id':'telegram-shared-order-0001','source':'miniapp','items':[{'menu_item_id':item,'qty':2}]}

    def test_mini_orders_reuse_existing_limits_prices_reservations_and_issue(self):
        with patch.object(common,'local_now',return_value=datetime(2026,11,16,9)):
            data=self.publish()
            with connect(self.db) as db:
                tg.subscriptions(db,self.student.user['id'],{'order_status':True})
            first=self.mini('/api/student/orders','POST',data)
            self.assertEqual(first[0],201,first[1])
            order=first[1]['order']
            again=self.student.post('/api/student/orders',data)
            self.assertEqual(again[0],201)
            self.assertEqual(again[1]['order']['id'],order['id'])
            self.assertTrue(again[1]['replayed'])
            self.assertEqual(order['total_tiyn'],150100)
            self.assertEqual(self.scalar('SELECT reserved FROM menu_items WHERE id=?',(data['items'][0]['menu_item_id'],)),2)
            self.assertEqual(self.mini('/api/student/orders','POST',{**data,'pickup_slot':'12:30'})[0],409)
            self.assertEqual(self.mini('/api/student/orders',tid=101)[1]['orders'],[])
        with patch.object(common,'local_now',return_value=datetime(2026,11,17,12,5)):
            self.assertEqual(self.operator.post('/api/orders/issue',{'code':order['code'],'payment_method':'cash','paid':True})[0],200)
            self.assertEqual(self.operator.post('/api/orders/issue',{'code':order['code']})[0],409)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM sales WHERE order_item_id IN (SELECT id FROM order_items WHERE order_id=?)',(order['id'],)),1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM outbox WHERE user_id=? AND kind='order_status'",(self.student.user['id'],)),2)
        api=FakeAPI()
        self.assertTrue(ready(deliver_notification(self.db,self.cfg,api)))
        self.assertEqual(api.sent[0][1]['reply_markup']['inline_keyboard'][0][0]['url'],'https://qaldyq.test/student/#orders')

    def test_webhook_secret_durable_ack_and_dedup(self):
        client=MemoryClient(self.base)
        update={'update_id':999,'message':{'chat':{'id':909,'type':'private'},'from':{'id':909},'text':'/student'}}
        self.assertEqual(client.post('/api/telegram/webhook',update)[0],403)
        for _ in range(2):
            self.assertEqual(client.request('/api/telegram/webhook','POST',update,{'X-Telegram-Bot-Api-Secret-Token':'x'*32})[0],200)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM telegram_inbox'),1)
        ready(process_one(self.db,self.cfg,FakeAPI()))
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM external_links WHERE address='909'"),1)

    def queue(self,kind='order_status'):
        with connect(self.db) as db:
            tg.subscriptions(db,self.student.user['id'],{kind:True})
            notify.enqueue(db,self.student.user['id'],kind,'Test','Body','acceptance:test')

    def test_shared_outbox_bounded_retries_and_lease_recovery(self):
        self.queue()
        api=FakeAPI(DeliveryFailure('retry',60))
        for _ in range(3):
            self.assertTrue(ready(deliver_notification(self.db,self.cfg,api)))
            with connect(self.db) as db:
                db.execute("UPDATE outbox SET next_attempt_at='2000-01-01'")
        self.assertEqual(self.scalar('SELECT status FROM outbox'),'failed')
        self.assertEqual(len(api.sent),3)
        with connect(self.db) as db:
            notify.enqueue(db,self.student.user['id'],'order_status','T','B','second')
            row=tg.claim_notification(db,self.cfg)
            db.execute('UPDATE outbox SET lease_until=0 WHERE id=?',(row['id'],))
        self.assertTrue(ready(deliver_notification(self.db,self.cfg,FakeAPI())))
        self.assertEqual(self.scalar('SELECT status FROM outbox WHERE id=?',(row['id'],)),'sent')

    def test_web_subscription_and_blocking_control_existing_outbox(self):
        self.queue()
        self.student.put('/api/student/profile',{'subscriptions':{'order_status':False}})
        self.assertFalse(ready(deliver_notification(self.db,self.cfg,FakeAPI())))
        with connect(self.db) as db:
            tg.subscriptions(db,self.student.user['id'],{'order_status':True})
            notify.enqueue(db,self.student.user['id'],'order_status','T','B','blocked-test')
        self.assertTrue(ready(deliver_notification(self.db,self.cfg,FakeAPI(DeliveryFailure('blocked')))))
        self.assertEqual(self.scalar("SELECT active FROM external_links WHERE address='202'"),0)
        self.assertEqual(self.scalar("SELECT SUM(enabled) FROM subscriptions WHERE user_id=?",(self.student.user['id'],)),0)
        self.step(text='/start',tid=202)
        self.assertEqual(self.scalar("SELECT SUM(enabled) FROM subscriptions WHERE user_id=?",(self.student.user['id'],)),0)

    def test_atomic_rollback_keeps_confirmation_for_retry(self):
        data=self.weigh()
        before=self.scalar('SELECT COUNT(*) FROM items')
        with patch.object(tg.Conversation,'reply',side_effect=RuntimeError('simulated crash')):
            self.step(action='confirm:'+data['confirmation'])
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM items'),before)
        self.assertEqual(self.conversation()[0],'confirm')
        with connect(self.db) as db:
            db.execute("UPDATE telegram_inbox SET available_at=0 WHERE state='pending'")
        ready(process_one(self.db,self.cfg,FakeAPI()))
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM items'),before+1)

    def test_domain_change_qr_identity_csp_and_secure_cookie(self):
        boot=self.operator.get('/api/bootstrap')[1]
        self.assertEqual(boot['telegram']['url'],'https://t.me/Qalqyq_NOVA_bot')
        self.server.telegram_config=tg.Config(token=TOKEN,app_url='https://new-domain.test')
        updated=self.operator.get('/api/bootstrap')[1]['telegram']
        self.assertEqual(updated['url'],boot['telegram']['url'])
        self.assertEqual(updated['mini_app_url'],'https://new-domain.test/student/')
        with patch.dict(os.environ,{'QALDYQ_PUBLIC_URL':'https://domain.test','QALDYQ_APP_URL':'https://old.trycloudflare.com'}):
            self.assertEqual(tg.Config.from_env().app_url,'https://domain.test')
        status,_,headers=MemoryClient(self.base).get('/student/')
        self.assertEqual(status,200)
        self.assertNotIn('X-Frame-Options',headers)
        self.assertIn('https://telegram.org',headers['Content-Security-Policy'])
        self.assertEqual(MemoryClient(self.base).get('/')[2]['X-Frame-Options'],'DENY')
        self.assertIn('Secure',MemoryClient(self.base).post('/api/login',{'email':'student@atu.kz','password':'demo2026'})[2]['Set-Cookie'])

    def test_returned_period_enqueues_comment_and_staff_role_is_rechecked(self):
        with connect(self.db) as db:
            tg.subscriptions(db,self.operator.user['id'],{'report_returned':True})
            period=db.execute("SELECT * FROM period_reports WHERE org_id=1 AND status='in_review' LIMIT 1").fetchone()
            if not period:
                stamp=common.now()
                pid=db.execute("INSERT INTO period_reports(org_id,period_start,period_end,status,created_by,created_at,updated_at) VALUES (1,'2026-11-01','2026-11-30','in_review',1,?,?)",(stamp,stamp)).lastrowid
                period=db.execute('SELECT * FROM period_reports WHERE id=?',(pid,)).fetchone()
            reviewer=dict(db.execute('SELECT * FROM users WHERE id=?',(self.reviewer.user['id'],)).fetchone())
            mod_period.transition(db,reviewer,period,'returned','Check the quantities')
        self.assertIn('Check the quantities',self.scalar("SELECT payload FROM outbox WHERE kind='report_returned'"))
        with connect(self.db) as db:
            db.execute("UPDATE users SET role='student' WHERE id=?",(self.operator.user['id'],))
        self.assertFalse(ready(deliver_notification(self.db,self.cfg,FakeAPI())))

    def test_queued_staff_reply_is_cancelled_after_role_revocation(self):
        self.step(action='reports')
        with connect(self.db) as db:
            db.execute("UPDATE telegram_outbox SET state='sent' WHERE method='answerCallbackQuery'")
            db.execute("UPDATE users SET role='student' WHERE id=?",(self.operator.user['id'],))
        self.assertFalse(ready(deliver_one(self.db,self.cfg,FakeAPI())))

    def test_polling_commits_inbox_before_next_offset(self):
        from types import SimpleNamespace
        calls=[]
        update={'update_id':876,'message':{'chat':{'id':101,'type':'private'},'from':{'id':101},'text':'/start'}}
        class StopPoll(BaseException):
            pass
        owner=self
        class FakeBot:
            async def get_updates(self,**kwargs):
                calls.append(kwargs['offset'])
                if len(calls)==1:
                    return [SimpleNamespace(update_id=876,model_dump=lambda **_:update)]
                owner.assertEqual(owner.scalar('SELECT COUNT(*) FROM telegram_inbox WHERE update_id=876'),1)
                raise StopPoll()
        with self.assertRaises(StopPoll):
            ready(poll(self.db,SimpleNamespace(bot=FakeBot())))
        self.assertEqual(calls,[None,877])


if __name__ == '__main__':
    unittest.main(verbosity=2)
