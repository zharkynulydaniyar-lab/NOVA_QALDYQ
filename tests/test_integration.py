"""End-to-end scenario across all modules (ТТ 24): menu → pre-order → pickup → sale → stock → report → registry →
export → forecast → plan → ingredient need → action → evaluation, plus restart, channels and secrets."""
import io
import re
import sys
import threading
import unittest
import zipfile
from datetime import datetime
from pathlib import Path

import common
import forecast_core
import mod_student
import notify
from helpers import Client, ServerCase
from server import create_server

TODAY, TOMORROW = "2026-11-12", "2026-11-13"


class FullCycle(ServerCase):
    @classmethod
    def setUpClass(cls):
        cls.real_clock = common.local_now
        common.local_now = lambda: cls.clock
        cls.clock = datetime(2026, 11, 12, 10, 0)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        common.local_now = cls.real_clock

    def test_full_cycle(self):
        op, rv, mg = self.operator, self.reviewer, self.manager
        # 1. Staff publish today's menu.
        dishes = self.ok(op.get("/api/catalog"))["dishes"]
        plov = next(d for d in dishes if d["name"] == "Палау")
        portion = plov["portions"][0]["id"]
        menu_id = self.ok(op.put("/api/menu", {"org_id": 1, "day": TODAY, "pickup_start": "11:30", "pickup_end": "14:30", "order_deadline": f"{TODAY}T13:30",
                                                "items": [{"portion_id": portion, "available": 3}]}))["id"]
        self.ok(op.post(f"/api/menu/{menu_id}/publish", {"publish": True}))
        # 2. A student opens the public menu and registers.
        guest = Client(self.base)
        item = self.ok(guest.get(f"/api/public/menu?date={TODAY}&org=1"))["menus"][0]["items"][0]
        self.assertEqual((item["name"], item["remaining"]), ("Палау", 3))
        self.ok(guest.post("/api/register", {"email": "cycle@student.kz", "name": "Цикл студенті", "password": "long-enough-1"}), 201)
        me = self.ok(guest.get("/api/me"))
        guest.csrf, uid = me["csrf"], me["user"]["id"]
        # 3–4. One order from the site and one through the bot's entry point: same rules, same list, same staff board.
        web = self.ok(guest.post("/api/student/orders", {"menu_id": menu_id, "pickup_slot": "12:00", "request_id": "cycle-web-order-0001", "items": [{"menu_item_id": item["id"], "qty": 2}]}), 201)["order"]
        code = self.ok(guest.post("/api/student/telegram-link"))["code"]
        with self.db() as db:
            self.assertEqual(notify.consume_link_code(db, code, "tg-chat-77"), uid)
            bot_order, created = mod_student.create_order(db, uid, {"menu_id": menu_id, "pickup_slot": "12:30", "request_id": "cycle-bot-order-0001", "items": [{"menu_item_id": item["id"], "qty": 1}]}, source="bot")
            self.assertTrue(created)
            with self.assertRaises(common.APIError):  # the limit is shared by every channel
                mod_student.create_order(db, uid, {"menu_id": menu_id, "pickup_slot": "13:00", "request_id": "cycle-bot-order-0002", "items": [{"menu_item_id": item["id"], "qty": 1}]}, source="bot")
        mine = self.ok(guest.get("/api/student/orders"))["orders"]
        self.assertEqual({(o["id"], o["source"]) for o in mine}, {(web["id"], "web"), (bot_order["id"], "bot")})
        board = self.ok(op.get(f"/api/orders?date={TODAY}"))
        self.assertEqual(sum(1 for o in board["orders"] if o["student"] == "Цикл студенті"), 2)
        # 5. The bot worker delivers the confirmation; a Telegram outage does not undo the order.
        sent = []
        with self.db() as db:
            def down(address, payload):
                raise ConnectionError("telegram unavailable")
            self.assertEqual(notify.process(db, "telegram", down)["retry"], 1)
            self.assertEqual(db.execute("SELECT status FROM orders WHERE id=?", (bot_order["id"],)).fetchone()[0], "confirmed")
            db.execute("UPDATE outbox SET next_attempt_at='2000-01-01'")
            self.assertEqual(notify.process(db, "telegram", lambda address, payload: sent.append((address, payload["order_id"])))["sent"], 1)
        self.assertEqual(sent, [("tg-chat-77", bot_order["id"])])
        # 6–7. Pickup is confirmed once and the sale is counted once.
        type(self).clock = datetime(2026, 11, 12, 12, 5)
        before = self.ok(op.get(f"/api/finance?start={TODAY}&end={TODAY}"))
        self.ok(op.post("/api/orders/issue", {"code": web["qr"], "payment_method": "card", "paid": True}))
        self.assertEqual(op.post("/api/orders/issue", {"code": web["code"]})[0], 409)
        after = self.ok(op.get(f"/api/finance?start={TODAY}&end={TODAY}"))
        self.assertEqual(after["revenue_tiyn"] - before["revenue_tiyn"], web["total_tiyn"])
        with self.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*),SUM(qty) FROM sales WHERE order_item_id IN (SELECT id FROM order_items WHERE order_id=?)", (web["id"],)).fetchone()[:], (1, 2))
        # 8–9. Production consumes stock by recipe; a write-off is linked to exactly one waste measurement.
        stock = lambda: {l["name"]: l["qty"] for l in self.ok(op.get("/api/stock"))["levels"]}
        start = stock()
        made = self.ok(op.post("/api/productions", {"dish_id": plov["id"], "portions": 10, "day": TODAY, "request_id": "cycle-production-0001"}), 201)
        used = stock()
        self.assertAlmostEqual(start["Күріш"] - used["Күріш"], 1.2, places=3)
        self.assertGreater(made["cost_tiyn"], 0)
        batch = next(b for b in self.ok(op.get("/api/stock"))["batches"] if b["name"] == "Сәбіз" and b["usable"])
        written = self.ok(op.post("/api/stock/writeoff", {"batch_id": batch["id"], "qty": 0.5, "reason": "spoiled", "waste_category_id": 1, "day": TODAY, "request_id": "cycle-writeoff-000001"}), 201)
        self.assertAlmostEqual(used["Сәбіз"] - stock()["Сәбіз"], 0.5, places=3)
        result = self.ok(op.get(f"/api/finance?start={TODAY}&end={TODAY}"))
        self.assertEqual(result["writeoffs_tiyn"] - after["writeoffs_tiyn"], written["value_tiyn"])
        self.assertEqual(result["cost_of_production_tiyn"] - after["cost_of_production_tiyn"], made["cost_tiyn"])
        # 10–11. Measurements join the monthly report; it is returned, corrected and accepted.
        quick = self.ok(op.post("/api/quick", {"category_id": 3, "kg": 4.5, "stage": "plate"}), 201)
        period = self.ok(op.post("/api/periods", {"org_id": 1, "month": "2026-11"}), 201)["id"]
        move = lambda client, status, comment="": client.post(f"/api/periods/{period}/transition", {"status": status, "comment": comment, "updated_at": self.ok(client.get(f"/api/periods/{period}"))["updated_at"]})
        detail = self.ok(op.get(f"/api/periods/{period}"))
        self.assertIn(written["waste_item_id"], {m["id"] for m in detail["measurements"]})
        self.ok(move(op, "submitted"))
        self.ok(move(rv, "in_review"))
        self.ok(move(rv, "returned", "Залдан шыққан қалдықтың массасын нақтылаңыз"))
        record = self.ok(op.get(f"/api/reports/{quick['id']}"))
        self.assertEqual(record["status"], "returned")
        self.assertEqual([i["locked"] for i in record["items"]], [1, 0])  # the write-off measurement cannot be edited away
        items = [{"id": i["id"], "category_id": i["category_id"], "kg": 4.2 if i["category_id"] == 3 else i["kg"], "route": i["route"], "stage": i["stage"], "note": i["note"]} for i in record["items"]]
        self.ok(op.put(f"/api/reports/{quick['id']}", {"org_id": 1, "report_date": TODAY, "updated_at": record["updated_at"], "items": items}))
        self.ok(move(op, "submitted"))
        self.ok(move(rv, "in_review"))
        self.ok(move(rv, "accepted"))
        # 12–13. Accepted data reach the registry, the analytics and the quarterly export.
        registry = self.ok(mg.get(f"/api/registry?start={TODAY}&end={TODAY}&org=1"))["measurements"]
        self.assertEqual(sorted((m["waste"], m["quantity"], m["stage"]) for m in registry), [("Залдан шыққан тамақ қалдығы", 4.2, "plate"), ("Көкөніс тазалағы", 0.5, "storage")])
        reports = self.ok(mg.get(f"/api/reports?start={TODAY}&end={TODAY}&org=1"))["reports"]
        self.assertEqual([(r["status"], r["kg"]) for r in reports], [("accepted", 4.7)])
        status, body, headers = mg.get("/api/export?format=xlsx&lang=ru&start=2026-10-01&end=2026-12-31")
        self.assertEqual(status, 200)
        archive = zipfile.ZipFile(io.BytesIO(body))
        self.assertIn(TODAY, "".join(archive.read(n).decode() for n in archive.namelist() if n.startswith("xl/worksheets/")))
        # 14–16. The sale is in the forecast history; staff approve tomorrow's plan and get the ingredient need.
        with self.db() as db:
            today_rows = [r for r in forecast_core.load_history(db, 1) if r["day"] == TODAY and r["dish_id"] == plov["id"]]
        self.assertEqual(today_rows[0]["sold"], 2)
        tomorrow = next(i for i in self.ok(op.get(f"/api/forecast?date={TOMORROW}"))["items"] if i["dish_id"] == plov["id"])
        self.assertIsNotNone(tomorrow["suggested"])
        plan = self.ok(op.post("/api/forecast/plan", {"day": TOMORROW, "items": [{"dish_id": plov["id"], "approved": tomorrow["suggested"]}]}))
        rice = next(n for n in plan["requirements"]["items"] if n["name"] == "Күріш")
        self.assertAlmostEqual(rice["need"], round(1.2 * tomorrow["suggested"] / 10 + 0.0004, 3), places=2)
        self.assertEqual(rice["to_buy"], max(0, round(rice["need"] - rice["usable_stock"], 3)))
        # 17–18. An action is opened for the problem, carried out and evaluated against measured indicators.
        action = self.ok(op.post("/api/actions", {"org_id": 1, "problem": "Залдан шыққан тамақ қалдығы жоғары", "cause": "portion_size", "cause_source": "staff_opinion", "recommendation": "Жарты порцияны ұсыну",
                                                   "baseline_start": "2026-09-01", "baseline_end": "2026-09-30", "control_start": "2026-10-01", "control_end": "2026-10-30", "category_id": 3, "owner_id": 1}), 201)["id"]
        step = lambda client, status, **extra: client.post(f"/api/actions/{action}/transition", {"status": status, "updated_at": self.ok(client.get(f"/api/actions/{action}"))["updated_at"], **extra})
        self.ok(step(mg, "approved"))
        self.ok(step(op, "running"))
        self.ok(step(op, "evaluating"))
        self.ok(step(mg, "done", conclusion="Көрсеткіш өлшенді; себеп-салдар дәлелденген жоқ"))
        final = self.ok(mg.get(f"/api/actions/{action}"))
        self.assertEqual(final["status"], "done")
        self.assertIsNotNone(final["result"]["baseline"]["kg_per_100"])
        self.assertIn(final["result"]["verdict"], ("improved", "not_improved", "revise"))
        # Restart: everything is still there.
        second = create_server(port=0, db_path=self.db_path)
        thread = threading.Thread(target=second.serve_forever, daemon=True)
        thread.start()
        try:
            fresh = Client(f"http://127.0.0.1:{second.server_port}").login("cycle@student.kz", "long-enough-1")
            kept = {o["id"]: o["status"] for o in self.ok(fresh.get("/api/student/orders"))["orders"]}
            self.assertEqual(kept, {web["id"]: "issued", bot_order["id"]: "confirmed"})
            staff = Client(f"http://127.0.0.1:{second.server_port}").login("operator")
            self.assertEqual(self.ok(staff.get(f"/api/periods/{period}"))["status"], "accepted")
            self.assertEqual(next(i for i in self.ok(staff.get(f"/api/forecast?date={TOMORROW}"))["items"] if i["dish_id"] == plov["id"])["plan"]["approved"], tomorrow["suggested"])
        finally:
            second.shutdown()
            second.server_close()
            thread.join()

    def test_no_secrets_in_sources_or_access_log(self):
        root = Path(__file__).resolve().parents[1]
        patterns = [re.compile(p) for p in (r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b", r"sk-[A-Za-z0-9]{20,}", r"-----BEGIN [A-Z ]*PRIVATE KEY-----", r"(?i)\b(api[_-]?key|secret|token)\s*[=:]\s*['\"][A-Za-z0-9_\-]{16,}['\"]")]
        for path in list(root.glob("*.py")) + list(root.glob("static/**/*.js")) + list(root.glob("*.example")) + list(root.glob("docs/*.md")) + [root / "README.md"]:
            if "vendor" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for pattern in patterns:
                self.assertIsNone(pattern.search(text), f"{path.name}: {pattern.pattern}")
        captured, original = io.StringIO(), sys.stderr
        sys.stderr = captured
        try:
            Client(self.base).request("/api/public/menu?date=2026-11-12&code=TOPSECRET123")
            Client(self.base).request("/api/login", "POST", {"email": "operator@atu.kz", "password": "demo2026"})
        finally:
            sys.stderr = original
        log = captured.getvalue()
        self.assertIn("/api/public/menu", log)
        self.assertNotIn("TOPSECRET123", log)
        self.assertNotIn("demo2026", log)
        self.assertNotIn("qaldyq_session", log)


if __name__ == "__main__":
    unittest.main(verbosity=2)
