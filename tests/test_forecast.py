"""Demand forecast: no leakage from the future, time split, honest method choice, plan and ingredient need (ТТ 17)."""
import io
import json
import unittest
from datetime import datetime

import common
import forecast_core as core
import mod_forecast
import train_forecast
from helpers import Client, ServerCase

NOW = datetime(2026, 11, 12, 9, 0)


def series(days, value=lambda i: 50, **extra):
    return [{"org_id": 1, "dish_id": 1, "day": d, "sold": value(i), "price": 10.0, "synthetic": True, "censored": False, "available": None, **extra} for i, d in enumerate(days)]


def working_days(count, start="2026-06-01"):
    from datetime import date, timedelta
    day, result = date.fromisoformat(start), []
    while len(result) < count:
        if day.weekday() != 6:
            result.append(day.isoformat())
        day += timedelta(days=1)
    return result


class ForecastCore(unittest.TestCase):
    def test_01_features_use_only_the_past_and_known_preorders(self):
        days = working_days(40)
        history = series(days, lambda i: 40 + i % 6)
        orders = [{"org_id": 1, "dish_id": 1, "day": days[30], "qty": 4, "status": "confirmed", "created_at": "2026-07-04T10:00:00", "cancelled_at": None},
                  {"org_id": 1, "dish_id": 1, "day": days[30], "qty": 7, "status": "confirmed", "created_at": "2026-07-06T10:00:00", "cancelled_at": None},     # placed after the forecast moment
                  {"org_id": 1, "dish_id": 1, "day": days[30], "qty": 2, "status": "cancelled", "created_at": "2026-07-01T10:00:00", "cancelled_at": "2026-07-02T10:00:00"},
                  {"org_id": 1, "dish_id": 1, "day": days[30], "qty": 3, "status": "cancelled", "created_at": "2026-07-01T10:00:00", "cancelled_at": "2026-07-06T09:00:00"}]  # cancelled later: still known then
        context = {"events": set(), "orders": orders}
        cutoff = "2026-07-05T18:00:00"
        before = core.features_for(history, days[30], context, 1, 1, cutoff)
        self.assertEqual(before["preorders"], 4 + 3)
        tampered = [dict(r, sold=r["sold"] * 100) if r["day"] >= days[30] else r for r in history]
        after = core.features_for(tampered, days[30], context, 1, 1, cutoff)
        self.assertEqual(str(core.vector(before)), str(core.vector(after)))  # the target day and later days cannot influence the features
        self.assertEqual(before["last"], history[29]["sold"])
        dataset = core.build_dataset(history, context)
        row = next(r for r in dataset if r["day"] == days[30])
        self.assertNotIn(row["sold"], (row["features"]["last"],) if history[29]["sold"] != row["sold"] else ())
        self.assertTrue(all(r["features"]["history_days"] <= i for i, r in enumerate(dataset)))

    def test_02_split_is_by_date_and_censored_days_are_not_scored(self):
        days = working_days(60)
        history = series(days, lambda i: 50) + [dict(r, dish_id=2) for r in series(days, lambda i: 30)]
        for r in history[-5:]:
            r["censored"] = True
        dataset = core.build_dataset(history, {"events": set(), "orders": []})
        train, test, border = core.split_by_date(dataset)
        self.assertTrue(all(r["day"] < border for r in train) and all(r["day"] >= border for r in test))
        self.assertFalse({r["day"] for r in train} & {r["day"] for r in test})
        report = core.evaluate(dataset, with_ml=False)
        self.assertEqual(report["censored_excluded"], 5)
        self.assertEqual(report["methods"]["existing"]["rows"], len(test) - 5)
        self.assertEqual((report["methods"]["existing"]["mae"], report["methods"]["existing"]["bias"]), (0, 0))
        self.assertIsNone(core.split_by_date(dataset[:40]))

    def test_03_ml_is_not_assumed_to_be_better(self):
        days = working_days(90)
        constant = core.build_dataset(series(days) + [dict(r, dish_id=2) for r in series(days, lambda i: 20)] + [dict(r, dish_id=3) for r in series(days, lambda i: 35)], {"events": set(), "orders": []})
        report = core.evaluate(constant, with_ml=True)
        self.assertIn("ml", report["methods"])
        self.assertEqual(report["chosen"], "existing")  # equal error: the simpler method wins
        small = core.evaluate(core.build_dataset(series(working_days(34)), {"events": set(), "orders": []}), with_ml=True)
        self.assertNotIn("ml", small["methods"])
        self.assertIn("ML бағаланбады", small["ml_note"])
        self.assertIsNone(small["interval"])  # no interval without enough rows to check its coverage
        self.assertEqual(core.evaluate(constant[:20])["status"], "insufficient")
        self.assertIsNone(core.existing_rule(core.features_for(series(days[:2]), days[2], {"events": set(), "orders": []}, 1, 1, "2026-06-03")))


class ForecastApi(ServerCase):
    @classmethod
    def setUpClass(cls):
        cls.real_clock = common.local_now
        common.local_now = lambda: NOW
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        common.local_now = cls.real_clock

    def test_01_training_command_compares_methods_on_later_dates(self):
        log = io.StringIO()
        result = train_forecast.train(self.db_path, out=lambda line: log.write(str(line) + "\n"))
        report = result["report"]
        self.assertEqual(report["status"], "ok")
        self.assertLess(report["train_end"], report["test_start"])
        self.assertEqual(set(report["methods"]), {"existing", "weekday", "ml"})
        self.assertEqual(report["chosen"], min(report["methods"], key=lambda m: (report["methods"][m]["mae"], ["existing", "weekday", "ml"].index(m))))
        self.assertEqual(report["synthetic_share"], 1.0)
        self.assertIn("синтетикалық", report["warning"])
        self.assertGreater(report["censored_excluded"], 0)
        if report["interval"]:
            self.assertTrue(0 <= report["interval"]["coverage"] <= 1 and report["interval"]["check_rows"] >= 30)
        with self.db() as db:
            row = db.execute("SELECT * FROM forecast_models WHERE active=1").fetchone()
            self.assertEqual(row["version"], result["version"])
            self.assertEqual(json.loads(row["exploration"])["canteens"], 3)
            if row["chosen"] == "ml":
                path = mod_forecast.MODEL_DIR / row["file"]
                self.assertIsNotNone(mod_forecast.active_model(db)[1])
                original = path.read_bytes()
                try:
                    path.write_bytes(original + b"tampered")
                    mod_forecast._cache.clear()
                    _, model, warning = mod_forecast.active_model(db)
                    self.assertIsNone(model)  # a changed file is never loaded
                    self.assertIn("бақылау сомасы", warning)
                finally:
                    path.write_bytes(original)
                    mod_forecast._cache.clear()
                    path.unlink()

    def test_02_forecast_shows_method_history_and_preorders_as_a_floor(self):
        for client in (Client(self.base).login("student"), self.reviewer):
            self.assertEqual(client.get("/api/forecast?org=1")[0], 403)
        data = self.ok(self.operator.get("/api/forecast?date=2026-11-13"))
        self.assertIn("үстіне қосылмайды", data["target"])
        item = next(i for i in data["items"] if i["name"] == "Палау")
        self.assertTrue(item["predicted"] and item["history_days"] >= 20 and item["method"])
        self.assertEqual(item["suggested"], max(-(-item["predicted"] * 105 // 100), item["preorders"]))
        with self.db() as db:
            dish = db.execute("SELECT id FROM catalog_dishes WHERE org_id=1 AND name='Палау'").fetchone()[0]
            menu = db.execute("SELECT m.id,mi.id AS item FROM menu_days m JOIN menu_items mi ON mi.menu_id=m.id WHERE m.org_id=1 AND m.day='2026-11-13' AND mi.dish_id=? LIMIT 1", (dish,)).fetchone()
            db.execute("INSERT INTO orders(user_id,org_id,menu_id,day,pickup_slot,code,request_id,fingerprint,total_tiyn,created_at,updated_at) VALUES (9,1,?,'2026-11-13','12:00','ABCDEF12','forecast-test-key-01','x',1,'2026-11-12T03:00:00+00:00','x')", (menu["id"],))
            order = db.execute("SELECT MAX(id) FROM orders").fetchone()[0]
            db.execute("INSERT INTO order_items(order_id,menu_item_id,dish_id,portion_id,name,portion_label,grams,price_tiyn,qty) VALUES (?,?,?,1,'Палау','Толық',300,140000,5)", (order, menu["item"], dish))
        again = next(i for i in self.ok(self.operator.get("/api/forecast?date=2026-11-13"))["items"] if i["name"] == "Палау")
        self.assertEqual(again["preorders"], item["preorders"] + 5)
        self.assertLess(abs(again["suggested"] - item["suggested"]), 5)  # five pre-orders are not five extra portions on top
        with self.db() as db:
            db.execute("INSERT INTO catalog_dishes(org_id,name,created_at,updated_at) VALUES (1,'Жаңа тағам','x','x')")
            new = db.execute("SELECT MAX(id) FROM catalog_dishes").fetchone()[0]
            db.execute("INSERT INTO dish_portions(dish_id,label,grams,price_tiyn) VALUES (?,'Толық',200,90000)", (new,))
            portion = db.execute("SELECT MAX(id) FROM dish_portions").fetchone()[0]
            db.execute("INSERT INTO menu_items(menu_id,dish_id,portion_id,available) VALUES (?,?,?,10)", (menu["id"], new, portion))
        fresh = next(i for i in self.ok(self.operator.get("/api/forecast?date=2026-11-13"))["items"] if i["name"] == "Жаңа тағам")
        self.assertEqual((fresh["predicted"], fresh["suggested"], fresh["interval"]), (None, None, None))
        self.assertIn("Сенімді ұсыныс жоқ", fresh["note"])  # no number is invented without history

    def test_03_plan_is_approved_by_staff_and_gives_ingredient_need(self):
        data = self.ok(self.operator.get("/api/forecast?date=2026-11-14"))
        items = [i for i in data["items"] if i["suggested"] is not None][:2]
        body = lambda lines: {"day": "2026-11-14", "items": lines}
        self.assertEqual(self.manager.post("/api/forecast/plan", {"org_id": 1, **body([{"dish_id": items[0]["dish_id"], "approved": items[0]["suggested"]}])})[0], 403)
        changed = [{"dish_id": items[0]["dish_id"], "approved": items[0]["suggested"] + 10}, {"dish_id": items[1]["dish_id"], "approved": items[1]["suggested"]}]
        self.assertEqual(self.operator.post("/api/forecast/plan", body(changed))[0], 400)  # a change needs its reason
        changed[0]["reason"] = "Конференция қатысушылары күтіледі"
        result = self.ok(self.operator.post("/api/forecast/plan", body(changed)))
        need = result["requirements"]["items"]
        self.assertTrue(need and all(n["to_buy"] == max(0, round(n["need"] - n["usable_stock"], 3)) for n in need))
        again = self.ok(self.operator.get("/api/forecast?date=2026-11-14"))
        plan = next(i for i in again["items"] if i["dish_id"] == items[0]["dish_id"])["plan"]
        self.assertEqual((plan["approved"], plan["suggested"], plan["reason"]), (items[0]["suggested"] + 10, items[0]["suggested"], "Конференция қатысушылары күтіледі"))
        self.assertEqual(self.operator.post("/api/forecast/plan", {"day": "2026-11-10", "items": changed})[0], 400)
        inn = Client(self.base).login("inn")
        self.assertEqual(inn.post("/api/forecast/plan", {"org_id": 1, **body(changed)})[0], 403)
        accuracy = self.ok(self.operator.get("/api/forecast/accuracy"))["rows"]
        self.assertTrue(accuracy and all(r["actual"] is not None for r in accuracy))  # stored forecasts are compared with what was sold
        self.assertTrue(any(r["reason"] for r in accuracy))


if __name__ == "__main__":
    unittest.main(verbosity=2)
