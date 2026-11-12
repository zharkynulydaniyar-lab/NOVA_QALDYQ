"""Catalogue, published menu, pre-orders and notifications (ТТ 9–11 shared logic)."""
import os
import threading
import unittest
from datetime import datetime, timezone

import common
import notify
from helpers import Client, ServerCase

DAY = "2026-11-17"


class StudentOrders(ServerCase):
    @classmethod
    def setUpClass(cls):
        cls.real_clock = common.local_now
        common.local_now = lambda: cls.clock
        cls.clock = datetime(2026, 11, 16, 9, 0)
        os.environ["QALDYQ_DEMO"] = "0"  # no pre-published demo menus: every menu here is created by the test
        try:
            super().setUpClass()
        finally:
            os.environ.pop("QALDYQ_DEMO")
        cls.student = Client(cls.base).login("student")
        cls.other = Client(cls.base)
        assert cls.other.post("/api/register", {"email": "second@student.kz", "name": "Екінші студент", "password": "long-enough-1"})[0] == 201
        cls.other.csrf = cls.other.get("/api/me")[1]["csrf"]
        cls.inn = Client(cls.base).login("inn")
        dish = {"org_id": 1, "name": "Тест палауы", "name_ru": "Тестовый плов", "composition": "күріш, сәбіз, ет",
                "portions": [{"label": "Толық", "grams": 300, "price": "1200.50"}, {"label": "Жарты", "grams": 150, "price": 700}]}
        cls.dish_id = cls.operator.post("/api/catalog", dish)[1]["id"]
        cls.portions = [p["id"] for p in cls.operator.get("/api/catalog")[1]["dishes"][-1]["portions"]]

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        common.local_now = cls.real_clock

    def setUp(self):
        type(self).clock = datetime(2026, 11, 16, 9, 0)

    def menu(self, available=(5, 5), day=DAY, publish=True, **extra):
        body = {"org_id": 1, "day": day, "pickup_start": "12:00", "pickup_end": "14:00", "slot_minutes": 30, "slot_limit": 3, "cancel_minutes": 30,
                "order_deadline": f"{day}T11:00", "items": [{"portion_id": p, "available": n} for p, n in zip(self.portions, available)], **extra}
        menu_id = self.ok(self.operator.request("/api/menu", "PUT", body))["id"]
        if publish:
            self.ok(self.operator.post(f"/api/menu/{menu_id}/publish", {"publish": True}))
        view = self.ok(self.operator.get(f"/api/menu?date={day}"))["menu"]
        return menu_id, [i["id"] for i in view["items"]]

    def order(self, client, menu_id, items, key, slot="12:00"):
        return client.post("/api/student/orders", {"menu_id": menu_id, "pickup_slot": slot, "request_id": key, "items": [{"menu_item_id": i, "qty": q} for i, q in items]})

    def test_01_published_menu_is_public_and_catalog_is_scoped(self):
        guest = Client(self.base)
        self.assertEqual([c["id"] for c in self.ok(guest.get("/api/public/canteens"))["canteens"]], [1, 2, 3])
        menu_id, _ = self.menu(publish=False, day="2026-11-20")
        self.assertEqual(self.ok(guest.get("/api/public/menu?date=2026-11-20"))["menus"], [])
        self.ok(self.operator.post(f"/api/menu/{menu_id}/publish", {}))
        shown = self.ok(guest.get("/api/public/menu?date=2026-11-20&org=1"))["menus"][0]
        self.assertEqual([(i["name"], i["label"], i["price_tiyn"], i["remaining"]) for i in shown["items"]], [("Тест палауы", "Жарты", 70000, 5), ("Тест палауы", "Толық", 120050, 5)])
        self.assertTrue(all("reserved" not in i for i in shown["items"]))
        self.assertIs(shown["online_payment"], False)
        for client in (self.reviewer, self.manager):
            self.assertEqual(client.post("/api/catalog", {"org_id": 1, "name": "Жоқ", "portions": [{"label": "1", "grams": 100, "price": 1}]})[0], 403)
        self.assertEqual(self.inn.request(f"/api/catalog/{self.dish_id}", "PUT", {"name": "Бөтен", "portions": [{"label": "1", "grams": 100, "price": 1}]})[0], 403)
        self.assertEqual(self.inn.post(f"/api/menu/{menu_id}/publish", {"publish": False})[0], 404)
        for path in ("/api/catalog", f"/api/menu?date={DAY}", "/api/orders?org=1"):
            self.assertEqual(self.student.get(path)[0], 403, path)
        self.assertEqual(self.operator.request("/api/menu", "PUT", {"org_id": 1, "day": "2026-11-10", "pickup_start": "12:00", "pickup_end": "13:00", "order_deadline": "2026-11-10T11:00", "items": []})[0], 400)

    def test_02_order_is_idempotent_and_keeps_its_own_prices(self):
        menu_id, items = self.menu(day="2026-11-18")
        status, body, _ = self.order(self.student, menu_id, [(items[1], 2), (items[0], 1)], "order-key-000000001")
        self.assertEqual(status, 201, body)
        order = body["order"]
        self.assertEqual((order["status"], order["total_tiyn"], order["payment_status"], order["online_payment"]), ("confirmed", 2 * 120050 + 70000, "unpaid", False))
        self.assertRegex(order["code"], r"^[0-9A-F]{8}$")
        again = self.ok(self.order(self.student, menu_id, [(items[1], 2), (items[0], 1)], "order-key-000000001"), 201)
        self.assertEqual((again["order"]["id"], again["replayed"]), (order["id"], True))
        self.assertEqual(self.order(self.student, menu_id, [(items[1], 1)], "order-key-000000001")[0], 409)
        view = self.ok(self.operator.get("/api/menu?date=2026-11-18"))["menu"]
        self.assertEqual({i["id"]: i["reserved"] for i in view["items"]}, {items[0]: 1, items[1]: 2})  # the replay reserved nothing
        self.assertEqual(self.other.get(f"/api/student/orders/{order['id']}")[0], 404)
        self.assertEqual(self.other.post(f"/api/student/orders/{order['id']}/cancel")[0], 404)
        staff = self.ok(self.operator.get("/api/orders?date=2026-11-18"))
        self.assertTrue(all("code" not in o for o in staff["orders"]))
        self.assertEqual(self.inn.get("/api/orders?org=1&date=2026-11-18")[1]["orders"], [])  # scoped to its own canteen
        self.ok(self.operator.request(f"/api/catalog/{self.dish_id}", "PUT", {"name": "Жаңа атау", "portions": [{"id": self.portions[0], "label": "Толық", "grams": 300, "price": 9999}, {"id": self.portions[1], "label": "Жарты", "grams": 150, "price": 700}]}))
        kept = self.ok(self.student.get(f"/api/student/orders/{order['id']}"))["order"]
        self.assertEqual([(i["name"], i["price_tiyn"]) for i in kept["items"]], [("Тест палауы", 120050), ("Тест палауы", 70000)])
        self.ok(self.operator.request(f"/api/catalog/{self.dish_id}", "PUT", {"name": "Тест палауы", "portions": [{"id": self.portions[0], "label": "Толық", "grams": 300, "price": "1200.50"}, {"id": self.portions[1], "label": "Жарты", "grams": 150, "price": 700}]}))

    def test_03_last_portion_goes_to_exactly_one_buyer(self):
        menu_id, items = self.menu(available=(1, 0), day="2026-11-19")
        results = []
        def buy(client, key):
            results.append(self.order(client, menu_id, [(items[1], 1)], key)[0])
        threads = [threading.Thread(target=buy, args=(self.student, "race-key-00000000001")), threading.Thread(target=buy, args=(self.other, "race-key-00000000002"))]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sorted(results), [201, 409])
        with self.db() as db:
            self.assertEqual(db.execute("SELECT reserved,available FROM menu_items WHERE id=?", (items[1],)).fetchone()[:], (1, 1))

    def test_04_limits_deadline_and_slot_rules(self):
        menu_id, items = self.menu(available=(9, 9), day="2026-11-21", slot_limit=1)
        self.ok(self.order(self.student, menu_id, [(items[0], 1)], "slot-key-0000000001"), 201)
        self.assertEqual(self.order(self.other, menu_id, [(items[0], 1)], "slot-key-0000000002")[0], 409)  # the slot is full
        self.ok(self.order(self.other, menu_id, [(items[0], 1)], "slot-key-0000000003", slot="12:30"), 201)
        self.assertEqual(self.order(self.other, menu_id, [(items[0], 1)], "slot-key-0000000004", slot="15:00")[0], 400)
        self.assertEqual(self.order(self.other, menu_id, [(items[0], 5), (items[1], 5), (items[0], 1)], "slot-key-0000000005", slot="13:00")[0], 400)
        type(self).clock = datetime(2026, 11, 21, 11, 0)
        self.assertEqual(self.order(self.other, menu_id, [(items[0], 1)], "slot-key-0000000006", slot="13:00")[0], 409)  # after the deadline
        self.assertIs(self.ok(Client(self.base).get("/api/public/menu?date=2026-11-21"))["menus"][0]["accepting"], False)

    def test_05_cancel_returns_portions_only_while_allowed(self):
        menu_id, items = self.menu(available=(2, 2), day="2026-11-22")
        first = self.ok(self.order(self.student, menu_id, [(items[0], 2)], "cancel-key-000000001"), 201)["order"]
        self.assertEqual(self.order(self.other, menu_id, [(items[0], 1)], "cancel-key-000000002")[0], 409)
        self.ok(self.student.post(f"/api/student/orders/{first['id']}/cancel"))
        self.assertEqual(self.student.post(f"/api/student/orders/{first['id']}/cancel")[0], 409)
        second = self.ok(self.order(self.other, menu_id, [(items[0], 2)], "cancel-key-000000003"), 201)["order"]  # the portions came back
        type(self).clock = datetime(2026, 11, 22, 11, 45)
        self.assertEqual(self.other.post(f"/api/student/orders/{second['id']}/cancel")[0], 409)  # too late for the student
        self.ok(self.operator.post(f"/api/orders/{second['id']}/cancel"))
        self.assertEqual(self.ok(self.operator.get("/api/menu?date=2026-11-22"))["menu"]["items"][0]["reserved"], 0)

    def test_06_issue_once_and_register_one_sale(self):
        menu_id, items = self.menu(day="2026-11-23")
        order = self.ok(self.order(self.student, menu_id, [(items[0], 1), (items[1], 2)], "issue-key-0000000001"), 201)["order"]
        self.assertEqual(self.operator.post("/api/orders/issue", {"code": order["qr"]})[0], 409)  # not the pickup day yet
        type(self).clock = datetime(2026, 11, 23, 12, 5)
        self.assertEqual(self.student.post("/api/orders/issue", {"code": order["code"]})[0], 403)
        self.assertEqual(self.inn.post("/api/orders/issue", {"code": order["code"]})[0], 404)  # another canteen learns nothing
        self.assertEqual(self.operator.post("/api/orders/issue", {"code": "00000000"})[0], 404)
        issued = self.ok(self.operator.post("/api/orders/issue", {"code": order["qr"], "payment_method": "cash", "paid": True}))["order"]
        self.assertEqual((issued["status"], issued["payment_status"], issued["payment_method"]), ("issued", "paid", "cash"))
        self.assertEqual(self.operator.post("/api/orders/issue", {"code": order["code"]})[0], 409)  # second scan
        with self.db() as db:
            sales = db.execute("SELECT qty,total_tiyn,source FROM sales WHERE order_item_id IN (SELECT id FROM order_items WHERE order_id=?) ORDER BY qty", (order["id"],)).fetchall()
        self.assertEqual([tuple(s) for s in sales], [(1, 70000, "preorder"), (2, 240100, "preorder")])
        self.assertEqual(self.student.post(f"/api/student/orders/{order['id']}/cancel")[0], 409)
        line = issued["items"][0]["id"]
        self.assertEqual(self.student.post(f"/api/student/orders/{order['id']}/review", {"order_item_id": line, "rating": 6})[0], 400)
        self.ok(self.student.post(f"/api/student/orders/{order['id']}/review", {"order_item_id": line, "rating": 4, "leftover_reason": "portion_big"}), 201)
        self.assertEqual(self.student.post(f"/api/student/orders/{order['id']}/review", {"order_item_id": line, "rating": 5})[0], 409)
        reviews = self.ok(self.operator.get("/api/orders/reviews"))
        self.assertEqual((reviews["dishes"][0]["rating"], reviews["dishes"][0]["leftovers"]), (4.0, 1))
        self.assertNotIn("student", str(reviews))

    def test_07_no_show_only_after_the_slot_and_review_only_after_pickup(self):
        menu_id, items = self.menu(day="2026-11-24")
        order = self.ok(self.order(self.student, menu_id, [(items[0], 1)], "noshow-key-000000001"), 201)["order"]
        self.assertEqual(self.student.post(f"/api/student/orders/{order['id']}/review", {"order_item_id": order["items"][0]["id"], "rating": 5})[0], 409)
        type(self).clock = datetime(2026, 11, 24, 12, 10)
        self.assertEqual(self.operator.post(f"/api/orders/{order['id']}/no-show")[0], 409)
        type(self).clock = datetime(2026, 11, 24, 12, 31)
        self.assertEqual(self.inn.post(f"/api/orders/{order['id']}/no-show")[0], 404)
        self.ok(self.operator.post(f"/api/orders/{order['id']}/no-show"))
        self.assertEqual(self.ok(self.student.get(f"/api/student/orders/{order['id']}"))["order"]["status"], "no_show")
        self.assertEqual(self.operator.post("/api/orders/issue", {"code": order["code"]})[0], 409)
        summary = self.ok(self.operator.get("/api/orders?date=2026-11-24"))
        self.assertEqual(summary["by_dish"][0]["no_show"], 1)

    def test_08_menu_cannot_drop_below_reservations(self):
        menu_id, items = self.menu(available=(4, 4), day="2026-11-25")
        self.ok(self.order(self.student, menu_id, [(items[0], 3)], "menu-edit-key-0000001"), 201)
        base = {"org_id": 1, "day": "2026-11-25", "pickup_start": "12:00", "pickup_end": "14:00", "order_deadline": "2026-11-25T11:00"}
        self.assertEqual(self.operator.request("/api/menu", "PUT", {**base, "items": [{"portion_id": self.portions[1], "available": 2}, {"portion_id": self.portions[0], "available": 4}]})[0], 409)
        self.assertEqual(self.operator.request("/api/menu", "PUT", {**base, "items": [{"portion_id": self.portions[0], "available": 4}]})[0], 409)
        self.assertEqual(self.operator.post(f"/api/menu/{menu_id}/publish", {"publish": False})[0], 409)

    def test_09_notices_outbox_retries_and_blocking(self):
        menu_id, items = self.menu(day="2026-11-26")
        first = self.ok(self.order(self.other, menu_id, [(items[0], 1)], "notify-key-00000001"), 201)["order"]
        notices = self.ok(self.other.get("/api/student/notices"))["notices"]
        self.assertTrue(any(str(first["id"]) in n["body"] for n in notices))
        with self.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM outbox WHERE user_id=?", (self.other.get("/api/me")[1]["user"]["id"],)).fetchone()[0], 0)  # no Telegram link yet
        code = self.ok(self.other.post("/api/student/telegram-link"))["code"]
        uid = self.other.get("/api/me")[1]["user"]["id"]
        with self.db() as db:
            self.assertIsNone(notify.consume_link_code(db, "WRONG000", "chat-1"))
            self.assertEqual(notify.consume_link_code(db, code, "chat-1"), uid)
            self.assertIsNone(notify.consume_link_code(db, code, "chat-2"))  # one-time
        self.ok(self.other.post(f"/api/student/orders/{first['id']}/cancel"))
        sent, moment = [], [datetime(2026, 11, 16, 4, 0, tzinfo=timezone.utc)]
        def flaky(address, payload):
            sent.append(address)
            if len(sent) == 1:
                raise ConnectionError("telegram is down")
        with self.db() as db:
            self.assertEqual(db.execute("SELECT status FROM orders WHERE id=?", (first["id"],)).fetchone()[0], "cancelled")  # the order does not depend on delivery
            self.assertEqual(notify.process(db, "telegram", flaky, clock=lambda: moment[0])["retry"], 1)
            self.assertEqual(notify.process(db, "telegram", flaky, clock=lambda: moment[0])["sent"], 0)  # not due yet
            moment[0] = datetime(2026, 11, 16, 5, 0, tzinfo=timezone.utc)
            self.assertEqual(notify.process(db, "telegram", flaky, clock=lambda: moment[0])["sent"], 1)
            self.assertEqual(notify.process(db, "telegram", flaky, clock=lambda: moment[0]), {"sent": 0, "retry": 0, "failed": 0, "skipped": 0, "blocked": 0})  # no duplicate
            notify.enqueue(db, uid, "order_status", "T", "B", "manual:1")
            notify.enqueue(db, uid, "order_status", "T", "B", "manual:1")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM outbox WHERE dedupe_key=?", (f"{uid}:manual:1",)).fetchone()[0], 1)
            def blocked(address, payload):
                raise notify.Blocked()
            self.assertEqual(notify.process(db, "telegram", blocked, clock=lambda: moment[0])["blocked"], 1)
            self.assertEqual(db.execute("SELECT active FROM external_links WHERE user_id=?", (uid,)).fetchone()[0], 0)
            notify.enqueue(db, uid, "order_status", "T", "B", "manual:2")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM outbox WHERE dedupe_key=?", (f"{uid}:manual:2",)).fetchone()[0], 0)  # nothing is queued for a blocked address
            self.assertNotIn("chat-1", " ".join(str(r["last_error"]) for r in db.execute("SELECT last_error FROM outbox")))

    def test_10_favorites_and_profile_are_personal(self):
        self.ok(self.student.post("/api/student/favorites", {"dish_id": self.dish_id}))
        self.assertEqual([d["id"] for d in self.ok(self.student.get("/api/student/favorites"))["dishes"]], [self.dish_id])
        self.assertEqual(self.ok(self.other.get("/api/student/favorites"))["dishes"], [])
        self.ok(self.student.post("/api/student/favorites", {"dish_id": self.dish_id, "on": False}))
        self.assertEqual(self.ok(self.student.get("/api/student/favorites"))["dishes"], [])
        self.ok(self.student.request("/api/student/profile", "PUT", {"name": "Жаңа есім", "role": "admin", "subscriptions": {"order_status": False}}))
        profile = self.ok(self.student.get("/api/student/profile"))
        self.assertEqual((profile["user"]["name"], profile["user"]["role"], profile["subscriptions"]["order_status"]), ("Жаңа есім", "student", False))
        self.assertEqual(Client(self.base).get("/api/student/orders")[0], 401)


if __name__ == "__main__":
    unittest.main(verbosity=2)
