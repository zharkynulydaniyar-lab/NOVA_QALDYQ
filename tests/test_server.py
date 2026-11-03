"""Integration tests against a real temporary HTTP server and SQLite database."""
import base64
import csv
import http.cookiejar
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import create_server, connect, initialize
from features import generate_reminders, food_insights
from datetime import date


class Client:
    def __init__(self, base):
        self.base = base
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))
        self.csrf = ""

    def request(self, path, method="GET", data=None, headers=None):
        request = urllib.request.Request(self.base + path, method=method,
            data=json.dumps(data).encode() if data is not None else None,
            headers={"Content-Type": "application/json", "X-CSRF-Token": self.csrf, **(headers or {})})
        try:
            response = self.opener.open(request)
        except urllib.error.HTTPError as error:
            response = error
        raw = response.read()
        is_json = "application/json" in response.headers.get("Content-Type", "")
        return response.status, json.loads(raw) if is_json else raw, response.headers

    def login(self, role):
        status, _, _ = self.request("/api/login", "POST", {"email": role + "@atu.kz", "password": "demo2026"})
        assert status == 200
        status, data, _ = self.request("/api/bootstrap")
        assert status == 200
        self.csrf = data["csrf"]
        return self


class QaldyqTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.db_path = str(Path(cls.temp.name) / "test.sqlite3")
        cls.server = create_server(port=0, db_path=cls.db_path)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.operator = Client(cls.base).login("operator")
        cls.reviewer = Client(cls.base).login("reviewer")
        cls.manager = Client(cls.base).login("manager")
        cls.admin = Client(cls.base).login("admin")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temp.cleanup()

    def payload(self, **overrides):
        return {"org_id": 1, "report_date": "2026-10-30", "note": "Тест есебі", "items": [
            {"category_id": 1, "kg": 2.5, "route": "disposal"},
            {"category_id": 2, "kg": 3, "route": "compost"}], **overrides}

    def create_report(self, client=None, **overrides):
        status, body, _ = (client or self.operator).request("/api/reports", "POST", self.payload(**overrides))
        self.assertEqual(status, 201, body)
        return body["id"]

    def detail(self, report_id, client=None):
        status, body, _ = (client or self.operator).request(f"/api/reports/{report_id}")
        self.assertEqual(status, 200, body)
        return body

    def transition(self, report_id, target, client=None, comment=""):
        client = client or self.operator
        report = self.detail(report_id, client)
        return client.request(f"/api/reports/{report_id}/transition", "POST", {
            "status": target, "comment": comment, "updated_at": report["updated_at"]})

    def test_01_unauthenticated_requests_rejected(self):
        for endpoint in ("/api/bootstrap", "/api/reports", "/api/export?format=csv", "/api/reports/1"):
            self.assertEqual(Client(self.base).request(endpoint)[0], 401)

    def test_02_wrong_password_and_cookie_flags(self):
        status, _, _ = Client(self.base).request("/api/login", "POST", {"email": "admin@atu.kz", "password": "bad"})
        self.assertEqual(status, 401)
        status, _, headers = Client(self.base).request("/api/login", "POST", {"email": "operator@atu.kz", "password": "demo2026"})
        self.assertEqual(status, 200)
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])

    def test_03_operator_is_scoped_to_organization(self):
        status, body, _ = self.operator.request("/api/reports?org=2")
        self.assertEqual(status, 200)
        self.assertTrue(body["reports"])
        self.assertTrue(all(r["org_id"] == 1 for r in body["reports"]))
        self.assertEqual(self.operator.request("/api/reports/2")[0], 403)
        self.assertEqual(self.operator.request("/api/reports", "POST", self.payload(org_id=2))[0], 403)

    def test_04_csrf_and_origin_checks(self):
        self.assertEqual(self.operator.request("/api/reports", "POST", self.payload(), {"X-CSRF-Token": "bad"})[0], 403)
        self.assertEqual(self.operator.request("/api/reports", "POST", self.payload(), {"Origin": "https://evil.example"})[0], 403)

    def test_05_manager_and_reviewer_cannot_create(self):
        for client in (self.manager, self.reviewer):
            self.assertEqual(client.request("/api/reports", "POST", self.payload())[0], 403)

    def test_06_full_return_edit_resubmit_accept_workflow(self):
        report_id = self.create_report()
        self.assertEqual(self.transition(report_id, "submitted")[0], 200)
        self.assertEqual(self.transition(report_id, "in_review", self.reviewer)[0], 200)
        self.assertEqual(self.transition(report_id, "returned", self.reviewer)[0], 400)
        self.assertEqual(self.transition(report_id, "returned", self.reviewer, "Массаны тексеріңіз")[0], 200)
        report = self.detail(report_id)
        payload = self.payload(note="Нақтыланды", updated_at=report["updated_at"])
        self.assertEqual(self.operator.request(f"/api/reports/{report_id}", "PUT", payload)[0], 200)
        self.assertEqual(self.transition(report_id, "submitted")[0], 200)
        self.assertEqual(self.transition(report_id, "in_review", self.reviewer)[0], 200)
        self.assertEqual(self.transition(report_id, "accepted", self.reviewer, "Расталды")[0], 200)
        final = self.detail(report_id)
        self.assertEqual(final["status"], "accepted")
        self.assertEqual([h["action"] for h in final["history"]], ["created", "submitted", "in_review", "returned", "edited", "submitted", "in_review", "accepted"])

    def test_07_illegal_transitions_and_edits_blocked(self):
        report_id = self.create_report()
        self.assertEqual(self.transition(report_id, "accepted", self.admin)[0], 403)
        self.assertEqual(self.transition(report_id, "submitted")[0], 200)
        self.assertEqual(self.transition(report_id, "accepted", self.operator)[0], 403)
        report = self.detail(report_id)
        self.assertEqual(self.operator.request(f"/api/reports/{report_id}", "PUT", self.payload(updated_at=report["updated_at"]))[0], 403)

    def test_08_stale_updates_cannot_overwrite(self):
        report_id = self.create_report()
        original = self.detail(report_id)
        self.assertEqual(self.operator.request(f"/api/reports/{report_id}", "PUT", self.payload(updated_at=original["updated_at"]))[0], 200)
        self.assertEqual(self.operator.request(f"/api/reports/{report_id}", "PUT", self.payload(note="Stale", updated_at=original["updated_at"]))[0], 409)

    def test_09_mass_validation(self):
        for kg in (0, -1, "NaN", "Infinity", "abc", 10001):
            body = self.payload(items=[{"category_id": 1, "kg": kg, "route": "disposal"}])
            self.assertEqual(self.operator.request("/api/reports", "POST", body)[0], 400, str(kg))

    def test_10_category_route_and_date_validation(self):
        for overrides in ({"items": []}, {"items": [{"category_id": 9999,"kg":2,"route":"compost"}]},
            {"items": [{"category_id":1,"kg":2,"route":"donation"}]}, {"report_date": "2026-02-30"},
            {"report_date": "2099-01-01"}):
            self.assertEqual(self.operator.request("/api/reports", "POST", self.payload(**overrides))[0], 400)

    def test_11_photo_validation_and_roundtrip(self):
        png = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"test").decode()
        report_id = self.create_report(photo=png)
        self.assertEqual(self.detail(report_id)["photo"], png)
        for photo in ("data:image/svg+xml;base64,AAAA", "data:image/png;base64," + base64.b64encode(b"not png").decode(), "data:image/png;base64,!!!"):
            self.assertEqual(self.operator.request("/api/reports", "POST", self.payload(photo=photo))[0], 400)

    def test_12_exports_have_correct_rows_and_formula_safety(self):
        self.create_report(note="=HYPERLINK(\"bad\")")
        status, body, headers = self.operator.request("/api/export?format=csv&start=2026-10-30&end=2026-10-30")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        rows = list(csv.reader(io.StringIO(body.decode("utf-8-sig"))))
        self.assertEqual(len(rows[0]), 10)
        self.assertTrue(any(row[-1].startswith("'=HYPERLINK") for row in rows[1:]))
        self.assertTrue(all(row[2] == "1-корпус асханасы" for row in rows[1:]))
        status, xml, _ = self.operator.request("/api/export?format=xls")
        self.assertEqual(status, 200)
        root = ET.fromstring(xml)
        self.assertTrue(root.tag.endswith("Workbook"))

    def test_13_totals_and_date_filters(self):
        status, body, _ = self.manager.request("/api/reports?start=2026-10-01&end=2026-10-10&org=2")
        self.assertEqual(status, 200)
        for report in body["reports"]:
            self.assertEqual(report["org_id"], 2)
            self.assertTrue("2026-10-01" <= report["report_date"] <= "2026-10-10")
            self.assertAlmostEqual(report["kg"], sum(i["kg"] for i in report["items"]), places=2)
            self.assertAlmostEqual(report["cost"], sum(i["kg"]*i["cost"] for i in report["items"]), places=2)
            self.assertAlmostEqual(report["co2"], sum(i["kg"]*i["co2"] for i in report["items"]), places=2)

    def test_14_registry_requires_admin(self):
        for client in (self.operator, self.reviewer, self.manager):
            self.assertEqual(client.request("/api/organizations", "POST", {"name":"No", "kind":"No"})[0], 403)
        self.assertEqual(self.admin.request("/api/organizations", "POST", {"name":"Тест зертханасы", "kind":"Кафедра"})[0], 201)
        self.assertEqual(self.admin.request("/api/organizations", "POST", {"name":"Тест зертханасы", "kind":"Кафедра"})[0], 409)
        self.assertEqual(self.admin.request("/api/categories", "POST", {"name":"Тест санаты", "cost":50, "co2":1.2})[0], 201)

    def test_15_coefficients_are_snapshotted(self):
        report_id = self.create_report()
        original = self.detail(report_id)["items"][0]["cost"]
        with connect(self.db_path) as db:
            db.execute("UPDATE categories SET cost=cost+1 WHERE id=1")
        self.assertEqual(self.detail(report_id)["items"][0]["cost"], original)

    def test_16_persistence_and_seed_idempotency(self):
        report_id = self.create_report()
        with connect(self.db_path) as db:
            count = db.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
        initialize(self.db_path)
        with connect(self.db_path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM reports").fetchone()[0], count)
            self.assertIsNotNone(db.execute("SELECT id FROM reports WHERE id=?", (report_id,)).fetchone())

    def test_17_private_source_paths_not_served(self):
        for path in ("/server.py", "/data/qaldyq.sqlite3", "/../server.py", "/tests/test_server.py"):
            self.assertEqual(Client(self.base).request(path)[0], 404)

    def test_18_logout_invalidates_session(self):
        client = Client(self.base).login("manager")
        self.assertEqual(client.request("/api/logout", "POST", {})[0], 200)
        self.assertEqual(client.request("/api/bootstrap")[0], 401)

    def test_19_forged_organization_on_edit_rejected(self):
        report_id = self.create_report()
        report = self.detail(report_id)
        self.assertEqual(self.admin.request(f"/api/reports/{report_id}", "PUT", self.payload(org_id=2, updated_at=report["updated_at"]))[0], 400)

    def test_20_static_app_and_security_headers(self):
        for path in ("/", "/app.js", "/styles.css", "/studio.css", "/animations.js", "/animations.css", "/vendor/three.module.js", "/vendor/three.core.js", "/vendor/THREE-LICENSE.txt", "/favicon.svg", "/campus-3d-v2.png", "/cycle-3d-v2.png"):
            status, body, headers = Client(self.base).request(path)
            self.assertEqual(status, 200)
            self.assertGreater(len(body), 50)
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
            self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])

    def test_21_portions_and_dishes_roundtrip(self):
        dishes=[{'name':'Палау','prepared':120,'served':100,'leftover':20,'leftover_kg':4}]
        report_id=self.create_report(portions=100,dishes=dishes)
        report=self.detail(report_id)
        self.assertEqual(report['portions'],100)
        self.assertEqual(report['dishes'][0]['leftover'],20)
        self.assertEqual(report['dishes'][0]['name'],'Палау')
        result=self.operator.request('/api/reports?start=2026-10-30&end=2026-10-30')[1]
        self.assertTrue(next(r for r in result['reports'] if r['id']==report_id)['dishes'])

    def test_22_food_validation(self):
        dish={'name':'Палау','prepared':120,'served':100,'leftover':20,'leftover_kg':4}
        for overrides in ({'portions':0},{'portions':2.5},{'portions':'NaN'},{'dishes':[dict(dish,served=110)]},
            {'dishes':[dict(dish,prepared=1.5)]},{'dishes':[dict(dish,leftover_kg=6)]},
            {'dishes':[dish,dish]},{'dishes':[dict(dish,name='<')]}):
            self.assertEqual(self.operator.request('/api/reports','POST',self.payload(**overrides))[0],400,overrides)

    def test_23_queue_replay_and_atomic_submit(self):
        payload=self.payload(request_id='offline-request-key-0001',portions=200,submit=True)
        first=self.operator.request('/api/reports','POST',payload)
        second=self.operator.request('/api/reports','POST',payload)
        self.assertEqual(first[0],201)
        self.assertEqual(first[1]['id'],second[1]['id'])
        self.assertEqual(self.detail(first[1]['id'])['status'],'submitted')
        self.assertEqual(self.operator.request('/api/reports','POST',dict(payload,portions=201))[0],409)
        report=self.detail(first[1]['id'])
        self.assertEqual([h['action'] for h in report['history']],['created','submitted'])

    def test_24_offline_edit_replay_and_conflict(self):
        report_id=self.create_report()
        report=self.detail(report_id)
        payload=self.payload(request_id='offline-edit-key-0001',updated_at=report['updated_at'],portions=50)
        self.assertEqual(self.operator.request(f'/api/reports/{report_id}','PUT',payload)[0],200)
        self.assertEqual(self.operator.request(f'/api/reports/{report_id}','PUT',payload)[0],200)
        self.assertEqual(self.operator.request(f'/api/reports/{report_id}','PUT',dict(payload,request_id='offline-edit-key-0002'))[0],409)

    def test_25_food_ratio_and_sparse_coverage(self):
        reports=[{'status':'accepted','portions':100,'kg':5,'dishes':[]},
          {'status':'accepted','portions':200,'kg':7,'dishes':[]},
          {'status':'accepted','portions':None,'kg':500,'dishes':[]},
          {'status':'draft','portions':1000,'kg':1000,'dishes':[]}]
        f=food_insights(reports,date(2026,10,31))
        self.assertEqual(f['kg_per_100'],4)
        self.assertEqual(f['covered_reports'],2)
        self.assertEqual(f['accepted_reports'],3)
        self.assertIsNone(food_insights([],date(2026,10,31))['kg_per_100'])

    def test_26_recommendations_group_daily_and_require_evidence(self):
        reports=[]
        for day,served in [('2026-10-09',80),('2026-10-16',100),('2026-10-23',120)]:
            reports.append({'status':'accepted','portions':100,'kg':5,'org_id':1,'org_name':'Асхана','report_date':day,
                'dishes':[{'name':'Палау','prepared':150,'served':served,'leftover':10,'leftover_kg':2}]})
        f=food_insights(reports,date(2026,10,30))
        r=f['recommendations'][0]
        self.assertEqual(r['suggested'],105)
        self.assertTrue(r['same_weekday'])
        self.assertEqual(f['excess'][0]['excess_days'],3)
        self.assertIsNone(food_insights(reports[:2],date(2026,10,30))['recommendations'][0]['suggested'])
        # Repeated reports on one day must not manufacture a three-day sample.
        repeated=food_insights([reports[0]]*3,date(2026,10,30))
        self.assertEqual(repeated['recommendations'][0]['sample_days'],1)
        self.assertIsNone(repeated['recommendations'][0]['suggested'])

    def test_27_insights_scope_and_notifications_auth(self):
        f=self.operator.request('/api/food-insights?org=2&target=2026-10-31')[1]
        self.assertTrue(all(r['org_id']==1 for r in f['excess']))
        self.assertEqual(Client(self.base).request('/api/notifications')[0],401)
        self.assertEqual(self.operator.request('/api/reminder-settings','POST',{'deadline_day':3})[0],403)
        self.assertEqual(self.admin.request('/api/reminder-settings','POST',{'deadline_day':2.5})[0],400)
        self.assertEqual(self.admin.request('/api/reminder-settings','POST',{'deadline_day':5})[0],200)

    def test_28_reminders_due_dedup_and_resolution(self):
        # A separate employee with no reports avoids depending on other test data.
        with connect(self.db_path) as db:
            org=db.execute("INSERT INTO organizations(name,kind) VALUES ('Reminder test','Асхана')").lastrowid
            uid=db.execute("INSERT INTO users(email,name,role,org_id,salt,password_hash) VALUES ('deadline@test','Тест','operator',?,'salt','hash')",(org,)).lastrowid
            generate_reminders(db,date(2026,11,4))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM notifications WHERE user_id=?',(uid,)).fetchone()[0],0)
            generate_reminders(db,date(2026,11,5));generate_reminders(db,date(2026,11,6))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM notifications WHERE user_id=?',(uid,)).fetchone()[0],1)
            db.execute("INSERT INTO reports(org_id,author_id,report_date,status,created_at,updated_at) VALUES (?,?,'2026-10-30','submitted','now','now')",(org,uid))
            generate_reminders(db,date(2026,11,6))
            self.assertIsNotNone(db.execute('SELECT resolved_at FROM notifications WHERE user_id=?',(uid,)).fetchone()[0])
            db.execute("UPDATE reports SET status='returned' WHERE org_id=?",(org,))
            generate_reminders(db,date(2026,11,6))
            self.assertIsNone(db.execute('SELECT resolved_at FROM notifications WHERE user_id=?',(uid,)).fetchone()[0])

    def test_29_offline_shell_assets_are_served(self):
        for path in ('/sw.js','/offline-store.js','/features.js','/features.css','/i18n.js','/i18n.css','/vendor/qrcode.js','/vendor/QRCODE-LICENSE.txt'):
            self.assertEqual(Client(self.base).request(path)[0],200,path)

    def test_30_notification_read_is_personal(self):
        with connect(self.db_path) as db:
            nid=db.execute("INSERT INTO notifications(user_id,period,title,message,created_at) VALUES (1,'test-read','Title','Message','2026-10-30T00:00:00+00:00')").lastrowid
        self.manager.request('/api/notifications/read','POST',{'id':nid})
        with connect(self.db_path) as db:
            self.assertIsNone(db.execute('SELECT read_at FROM notifications WHERE id=?',(nid,)).fetchone()[0])
        self.operator.request('/api/notifications/read','POST',{'id':nid})
        with connect(self.db_path) as db:
            self.assertIsNotNone(db.execute('SELECT read_at FROM notifications WHERE id=?',(nid,)).fetchone()[0])

    def test_31_planning_uses_56_days_independent_of_report_filter(self):
        for day,served in [('2026-10-09',80),('2026-10-16',100),('2026-10-23',120)]:
            rid=self.create_report(report_date=day,dishes=[{'name':'Жоспар тесті','prepared':150,'served':served,'leftover':10,'leftover_kg':2}])
            self.assertEqual(self.transition(rid,'submitted')[0],200)
            self.assertEqual(self.transition(rid,'in_review',self.reviewer)[0],200)
            self.assertEqual(self.transition(rid,'accepted',self.reviewer)[0],200)
        status,f,_=self.operator.request('/api/food-insights?start=2026-10-30&end=2026-10-30&target=2026-10-31')
        self.assertEqual(status,200)
        plan=next(r for r in f['recommendations'] if r['name']=='Жоспар тесті')
        self.assertEqual(plan['suggested'],105)
        self.assertEqual(plan['sample_days'],3)
        self.assertFalse(any(r['name']=='Жоспар тесті' for r in f['excess']))


    def test_32_malformed_nested_rows_return_400_without_writing(self):
        with connect(self.db_path) as db:
            before = db.execute('SELECT COUNT(*) FROM reports').fetchone()[0]
        for items in ([None], [1], ['invalid'], [[]]):
            with self.subTest(items=items):
                status, body, _ = self.operator.request('/api/reports', 'POST', self.payload(items=items))
                self.assertEqual(status, 400, body)
        for photo in ([], {}, 0, False):
            with self.subTest(photo=photo):
                self.assertEqual(self.operator.request('/api/reports', 'POST', self.payload(photo=photo))[0], 400)
        with connect(self.db_path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reports').fetchone()[0], before)

    def test_33_invalid_content_length_is_rejected_before_reading(self):
        from server import Handler, APIError
        from types import SimpleNamespace
        for length in ('-1', '0'):
            handler = SimpleNamespace(headers={'Content-Length': length}, rfile=io.BytesIO(b'{}'))
            with self.assertRaises(APIError):
                Handler.body(handler)
            self.assertEqual(handler.rfile.tell(), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
