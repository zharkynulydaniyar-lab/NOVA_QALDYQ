"""Stock, recipes, production, sales, finance, balance and shift handover (ТТ 12–14)."""
import os
import unittest
from datetime import datetime

import common
import mod_kitchen
from helpers import Client, ServerCase

TODAY = "2026-11-16"


class Kitchen(ServerCase):
    @classmethod
    def setUpClass(cls):
        cls.real_clock = common.local_now
        common.local_now = lambda: datetime(2026, 11, 16, 9, 0)
        os.environ["QALDYQ_DEMO"] = "0"
        try:
            super().setUpClass()
        finally:
            os.environ.pop("QALDYQ_DEMO")
        cls.inn = Client(cls.base).login("inn")
        cls.rice = cls.operator.post("/api/ingredients", {"name": "Тест күріші", "unit": "kg"})[1]["id"]
        cls.carrot = cls.operator.post("/api/ingredients", {"name": "Тест сәбізі", "unit": "kg"})[1]["id"]
        cls.oil = cls.operator.post("/api/ingredients", {"name": "Тест майы", "unit": "l"})[1]["id"]
        cls.dish = cls.operator.post("/api/catalog", {"org_id": 1, "name": "Есеп палауы", "portions": [{"label": "Толық", "grams": 300, "price": 1500}]})[1]["id"]
        cls.portion = [d for d in cls.operator.get("/api/catalog")[1]["dishes"] if d["id"] == cls.dish][0]["portions"][0]["id"]

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        common.local_now = cls.real_clock

    def buy(self, ingredient, qty, total, key=None, **extra):
        return self.operator.post("/api/purchases", {"ingredient_id": ingredient, "qty": qty, "total": total, "supplier": "Демо жеткізуші", "day": TODAY, **({"request_id": key} if key else {}), **extra})

    def level(self, ingredient):
        return next(l for l in self.ok(self.operator.get("/api/stock"))["levels"] if l["ingredient_id"] == ingredient)

    def test_01_access_is_limited_to_canteen_staff(self):
        student = Client(self.base).login("student")
        for client, status in ((student, 403), (self.reviewer, 403)):
            self.assertEqual(client.get("/api/stock?org=1")[0], status)
            self.assertEqual(client.get("/api/finance?org=1")[0], status)
        self.assertEqual(self.manager.get("/api/stock?org=1")[0], 200)
        self.assertEqual(self.manager.post("/api/ingredients", {"org_id": 1, "name": "Жоқ", "unit": "kg"})[0], 403)
        self.assertEqual(self.inn.post("/api/purchases", {"ingredient_id": self.rice, "qty": 1, "total": 100, "supplier": "X"})[0], 400)  # another canteen's product
        self.assertEqual(self.inn.post("/api/ingredients", {"org_id": 1, "name": "Бөтен", "unit": "kg"})[0], 403)
        self.assertEqual([i["name"] for i in self.ok(self.inn.get("/api/ingredients?org=1"))["ingredients"]], [])  # scoped to its own organization

    def test_02_weighted_average_cost_and_idempotent_purchase(self):
        self.ok(self.buy(self.rice, 10, 10000, "purchase-key-0000001", expiry_day="2026-12-30"), 201)
        self.assertEqual(self.ok(self.buy(self.rice, 10, 10000, "purchase-key-0000001"), 201).get("replayed"), True)
        self.ok(self.buy(self.rice, 10, 20000, expiry_day="2026-11-20"), 201)
        level = self.level(self.rice)
        self.assertEqual((level["qty"], level["value_tiyn"], level["avg_cost_tiyn"]), (20.0, 3000000, 150000))  # 1 500 ₸ per kg
        self.assertEqual(self.buy(self.rice, "0.0001", 1)[0], 400)   # finer than a gram
        self.assertEqual(self.buy(self.rice, 1, "10.005")[0], 400)   # finer than a tiyn
        self.assertEqual(self.buy(self.rice, 1, 100, day="2099-01-01")[0], 400)
        self.assertEqual(self.buy(self.rice, 1, 100, expiry_day="2026-11-01")[0], 400)

    def test_03_units_convert_only_with_an_explicit_factor(self):
        self.assertEqual(mod_kitchen.milli("250", unit="g", base="kg"), 250)
        self.assertEqual(mod_kitchen.milli("1.5", unit="l", base="l"), 1500)
        self.assertEqual(mod_kitchen.milli("750", unit="ml", base="l"), 750)
        with self.assertRaises(common.APIError):
            mod_kitchen.milli("1", unit="l", base="kg")  # volume to mass needs a density
        self.assertEqual(self.operator.post("/api/recipes", {"dish_id": self.dish, "yield_portions": 10, "items": [{"ingredient_id": self.oil, "qty": 100, "unit": "g"}]})[0], 400)
        self.assertEqual(mod_kitchen.issue_value(3, 100, 1), 33)
        self.assertEqual(mod_kitchen.issue_value(2, 67, 1) + mod_kitchen.issue_value(1, 67 - mod_kitchen.issue_value(2, 67, 1), 1), 67)  # the last unit takes the rest: no drift

    def test_04_production_uses_recipe_fefo_and_never_twice(self):
        self.ok(self.buy(self.carrot, 5, 2500, expiry_day="2026-11-25"), 201)
        self.assertEqual(self.operator.post("/api/productions", {"dish_id": self.dish, "portions": 20, "day": TODAY})[0], 409)  # no recipe yet
        self.ok(self.operator.post("/api/recipes", {"dish_id": self.dish, "yield_portions": 10, "valid_from": "2026-11-01",
                                                    "items": [{"ingredient_id": self.rice, "qty": 2}, {"ingredient_id": self.carrot, "qty": 500, "unit": "g"}]}), 201)
        made = self.ok(self.operator.post("/api/productions", {"dish_id": self.dish, "portions": 20, "day": TODAY, "request_id": "production-key-00001"}), 201)
        self.assertEqual(made["cost_tiyn"], 4 * 150000 + 1 * 50000)  # 4 kg rice at 1 500 ₸ + 1 kg carrot at 500 ₸
        self.assertEqual(made["cost_per_portion_tiyn"], 32500)
        self.assertEqual(self.ok(self.operator.post("/api/productions", {"dish_id": self.dish, "portions": 20, "day": TODAY, "request_id": "production-key-00001"}), 201).get("replayed"), True)
        self.assertEqual(self.level(self.rice)["qty"], 16.0)  # the replay consumed nothing
        batches = [b for b in self.ok(self.operator.get("/api/stock"))["batches"] if b["ingredient_id"] == self.rice]
        self.assertEqual([(b["expiry_day"], b["qty_left"]) for b in batches], [("2026-11-20", 6.0), ("2026-12-30", 10.0)])  # the earliest expiry went first
        self.assertEqual(self.operator.post("/api/productions", {"dish_id": self.dish, "portions": 5000, "day": TODAY})[0], 409)
        self.assertEqual((self.level(self.rice)["qty"], self.level(self.carrot)["qty"]), (16.0, 4.0))  # a refused batch takes nothing

    def test_05_recipe_versions_keep_history(self):
        self.ok(self.operator.post("/api/recipes", {"dish_id": self.dish, "yield_portions": 10, "valid_from": "2026-11-16",
                                                    "items": [{"ingredient_id": self.rice, "qty": 1}]}), 201)
        recipes = [r for r in self.ok(self.operator.get("/api/recipes"))["recipes"] if r["dish_id"] == self.dish]
        self.assertEqual([(r["version"], r["valid_from"], r["valid_to"], r["current"]) for r in recipes], [(2, "2026-11-16", None, True), (1, "2026-11-01", "2026-11-15", False)])
        self.assertEqual(self.operator.post("/api/recipes", {"dish_id": self.dish, "yield_portions": 10, "valid_from": "2026-11-10", "items": [{"ingredient_id": self.rice, "qty": 1}]})[0], 400)
        earlier = self.ok(self.operator.post("/api/productions", {"dish_id": self.dish, "portions": 10, "day": "2026-11-14"}), 201)
        self.assertEqual(earlier["cost_tiyn"], 2 * 150000 + 25000)  # the version valid on that date
        self.assertEqual([p["version"] for p in self.ok(self.operator.get("/api/productions?date=2026-11-14"))["productions"]], [1])

    def test_06_expired_and_unfit_batches_are_not_used(self):
        milk = self.ok(self.operator.post("/api/ingredients", {"name": "Тест сүті", "unit": "l"}), 201)["id"]
        self.ok(self.buy(milk, 4, 2000, day="2026-11-10", expiry_day="2026-11-14"), 201)   # already expired
        fresh = self.ok(self.buy(milk, 2, 1200, expiry_day="2026-11-17"), 201)["batch_id"]
        view = self.ok(self.operator.get("/api/stock"))
        states = {b["expiry_day"]: (b["condition"], b["usable"]) for b in view["batches"] if b["ingredient_id"] == milk}
        self.assertEqual(states, {"2026-11-14": ("expired", False), "2026-11-17": ("soon", True)})
        self.assertIn("FEFO", view["method"])
        need = mod_kitchen.requirements
        with self.db() as db:
            dish = db.execute("INSERT INTO catalog_dishes(org_id,name,created_at,updated_at) VALUES (1,'Сүт ботқасы','x','x')").lastrowid
            recipe = db.execute("INSERT INTO recipes(dish_id,version,valid_from,yield_portions,created_at) VALUES (?,1,'2026-11-01',10,'x')", (dish,)).lastrowid
            db.execute("INSERT INTO recipe_items(recipe_id,ingredient_id,qty_milli,entered_qty,entered_unit) VALUES (?,?,3000,'3','l')", (recipe, milk))
            plan = need(db, 1, {dish: 10}, TODAY)["items"][0]
            self.assertEqual((plan["need"], plan["usable_stock"], plan["to_buy"]), (3.0, 2.0, 1.0))  # the expired 4 l do not count
        self.ok(self.operator.post("/api/stock/batch-state", {"batch_id": fresh, "state": "unfit"}))
        with self.db() as db:
            self.assertEqual(need(db, 1, {dish: 10}, TODAY)["items"][0]["to_buy"], 3.0)
            mod_kitchen.tick(db); mod_kitchen.tick(db)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM user_notices WHERE kind='stock_expiry' AND user_id=1 AND body LIKE 'Тест сүті%'").fetchone()[0], 1)  # the expired batch, once

    def test_07_writeoff_links_to_one_waste_measurement(self):
        peel = self.ok(self.operator.post("/api/ingredients", {"name": "Тест картобы", "unit": "kg"}), 201)["id"]
        batch = self.ok(self.buy(peel, 10, 3000, expiry_day="2026-11-18"), 201)["batch_id"]
        body = {"batch_id": batch, "qty": 2, "reason": "spoiled", "waste_category_id": 1, "day": TODAY, "request_id": "writeoff-key-0000001"}
        with self.db() as db:
            before = db.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        first = self.ok(self.operator.post("/api/stock/writeoff", body), 201)
        self.assertEqual(first["value_tiyn"], 60000)
        self.assertEqual(self.ok(self.operator.post("/api/stock/writeoff", body)).get("replayed"), True)
        with self.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM items").fetchone()[0], before + 1)  # one measurement, not two
            item = db.execute("SELECT kg,stage FROM items WHERE id=?", (first["waste_item_id"],)).fetchone()
            self.assertEqual((item["kg"], item["stage"]), (2.0, "storage"))
            self.assertEqual(db.execute("SELECT waste_item_id FROM stock_moves WHERE kind='writeoff' AND batch_id=?", (batch,)).fetchone()[0], first["waste_item_id"])
        self.assertEqual(self.level(peel)["qty"], 8.0)
        self.assertEqual(self.operator.post("/api/stock/writeoff", {"batch_id": batch, "qty": 1, "reason": "spoiled", "waste_category_id": 5})[0], 400)  # litres type for a kg product
        self.assertEqual(self.operator.post("/api/stock/writeoff", {"batch_id": batch, "qty": 99, "reason": "spoiled"})[0], 409)
        self.assertEqual(self.inn.post("/api/stock/writeoff", {"batch_id": batch, "qty": 1, "reason": "spoiled"})[0], 404)
        self.ok(self.operator.post("/api/stock/adjust", {"batch_id": batch, "qty_delta": "-0.5", "note": "Түгендеу айырмасы"}), 201)
        self.assertEqual(self.operator.post("/api/stock/adjust", {"batch_id": batch, "qty_delta": "-0.5", "note": ""})[0], 400)  # a correction needs its reason
        moves = [m for m in self.ok(self.operator.get("/api/stock/moves"))["moves"] if m["ingredient_id"] == peel]
        self.assertEqual([(m["kind"], m["qty_milli"]) for m in moves], [("adjustment", -500), ("writeoff", -2000), ("receipt", 10000)])

    def test_08_finance_counts_each_cost_once(self):
        start = "2026-11-01"
        base = self.ok(self.operator.get(f"/api/finance?start={start}&end={TODAY}"))
        self.ok(self.operator.post("/api/sales", {"portion_id": self.portion, "qty": 12, "day": TODAY, "request_id": "counter-sale-key-0001"}), 201)
        self.assertEqual(self.ok(self.operator.post("/api/sales", {"portion_id": self.portion, "qty": 12, "day": TODAY, "request_id": "counter-sale-key-0001"}), 201).get("replayed"), True)
        self.ok(self.operator.post("/api/expenses", {"period_start": "2026-11-01", "period_end": "2026-11-30", "category": "utilities", "amount": 30000}), 201)
        self.ok(self.buy(self.oil, 5, 4000), 201)  # bought but not used
        after = self.ok(self.operator.get(f"/api/finance?start={start}&end={TODAY}"))
        self.assertEqual(after["revenue_tiyn"] - base["revenue_tiyn"], 12 * 150000)
        self.assertEqual(after["other_expenses_tiyn"] - base["other_expenses_tiyn"], 30000 * 100 * 16 // 30)  # 16 of 30 days
        self.assertEqual(after["purchases_paid_tiyn"] - base["purchases_paid_tiyn"], 400000)
        self.assertEqual(after["cost_of_production_tiyn"], base["cost_of_production_tiyn"])  # an unused purchase is stock, not a cost
        self.assertEqual(after["result_tiyn"] - base["result_tiyn"], 12 * 150000 - 30000 * 100 * 16 // 30)
        self.assertEqual(after["result_tiyn"], after["revenue_tiyn"] - after["cost_of_production_tiyn"] - after["writeoffs_tiyn"] + after["adjustments_tiyn"] - after["other_expenses_tiyn"])
        self.assertIn("бухгалтерлік есеп емес", after["label"])
        self.assertIn("waste_estimate_tenge", after)
        self.assertTrue(all(isinstance(after[k], int) for k in after if k.endswith("_tiyn") and after[k] is not None))

    def test_09_portion_balance_is_never_written_to_waste_automatically(self):
        with self.db() as db:
            items_before = db.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        row = lambda: next(d for d in self.ok(self.operator.get(f"/api/balance?date={TODAY}"))["dishes"] if d["dish_id"] == self.dish)
        self.assertEqual((row()["prepared"], row()["sold"], row()["unsold"], row()["unexplained"], row()["state"]), (20, 12, None, None, "open"))  # unknown is not zero
        self.ok(self.operator.post("/api/balance", {"day": TODAY, "dish_id": self.dish, "unsold": 5}))
        self.assertEqual((row()["unexplained"], row()["state"]), (3, "clarify"))
        self.assertEqual(self.operator.post("/api/balance", {"day": TODAY, "dish_id": self.dish, "unsold": 5, "other": 3})[0], 400)  # another movement needs a document or note
        self.ok(self.operator.post("/api/balance", {"day": TODAY, "dish_id": self.dish, "unsold": 5, "other": 3, "other_note": "Қызметкерлер тамағы, акт №1"}))
        self.assertEqual((row()["unexplained"], row()["state"]), (0, "balanced"))
        with self.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM items").fetchone()[0], items_before)
        self.ok(self.operator.post("/api/shortages", {"day": TODAY, "dish_id": self.dish, "ended_at": "13:10", "substitute": "Лағман"}), 201)
        shortage = self.ok(self.operator.get("/api/shortages"))["shortages"][0]
        self.assertEqual((shortage["ended_at"], shortage["unmet"]), ("13:10", None))  # unmet demand unknown stays unknown
        self.assertTrue(row()["shortage"])
        self.assertEqual(self.operator.post("/api/shortages", {"dish_id": self.dish, "ended_at": "25:00"})[0], 400)

    def test_10_shift_handover_is_confirmed_by_another_person(self):
        hid = self.ok(self.operator.post("/api/handovers", {"tasks": "Картопты тазалап бітіру", "problems": "Тоңазытқыш №2 есігі"}), 201)["id"]
        self.assertEqual(self.operator.post(f"/api/handovers/{hid}/accept")[0], 409)
        self.assertEqual(self.inn.post(f"/api/handovers/{hid}/accept")[0], 404)
        self.ok(self.admin.post("/api/users", {"email": "shift2@atu.kz", "name": "Екінші ауысым", "role": "operator", "org_id": 1, "password": "long-enough-1"}), 201)
        second = Client(self.base).login("shift2@atu.kz", "long-enough-1")
        self.ok(second.post(f"/api/handovers/{hid}/accept"))
        self.assertEqual(second.post(f"/api/handovers/{hid}/accept")[0], 409)
        item = self.ok(second.get("/api/handovers"))["handovers"][0]
        self.assertEqual((item["from_name"], item["to_name"], item["tasks"]), ("Демо қызметкер", "Екінші ауысым", "Картопты тазалап бітіру"))
        self.assertTrue(item["accepted_at"] and item["snapshot"]["stock"])
        self.assertTrue(any(b["condition"] in ("expired", "soon", "unfit") for b in item["snapshot"]["priority_batches"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
