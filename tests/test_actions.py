"""Waste-reduction actions, data quality, clarifications and transfers for recycling (ТТ 15–16, 18–19)."""
import os
import unittest
from datetime import datetime

import common
import mod_actions
from helpers import Client, ServerCase


class Actions(ServerCase):
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

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        common.local_now = cls.real_clock

    def new_action(self, client=None, **extra):
        body = {"org_id": 1, "problem": "Палау жиі артылады", "cause": "overproduction", "cause_source": "staff_opinion", "recommendation": "Жұма күні 15% аз дайындау",
                "baseline_start": "2026-09-01", "baseline_end": "2026-09-30", "cost": 120, **extra}
        return (client or self.operator).post("/api/actions", body)

    def move(self, client, action_id, status, **extra):
        current = self.ok(client.get(f"/api/actions/{action_id}"))
        return client.post(f"/api/actions/{action_id}/transition", {"status": status, "updated_at": current["updated_at"], **extra})

    def test_01_action_lifecycle_and_roles(self):
        self.assertEqual(Client(self.base).login("student").get("/api/actions")[0], 403)
        self.assertEqual(self.new_action(self.reviewer)[0], 403)
        self.assertEqual(self.new_action(cause="magic")[0], 400)
        self.assertEqual(self.new_action(self.inn)[0], 403)  # another organization
        action_id = self.ok(self.new_action(), 201)["id"]
        self.assertEqual(self.inn.get(f"/api/actions/{action_id}")[0], 404)
        view = self.ok(self.operator.get(f"/api/actions/{action_id}"))
        self.assertEqual((view["status"], view["cause_source"], view["cost"]), ("proposed", "staff_opinion", 120.0))
        self.assertGreater(view["baseline"]["waste_kg"], 0)  # the starting measurements are stored with the card
        self.assertEqual(self.move(self.operator, action_id, "approved")[0], 403)  # the proposer cannot approve
        self.ok(self.move(self.manager, action_id, "approved", approved_action="Жұма күні палауды 15% аз дайындау"))
        self.assertEqual(self.move(self.operator, action_id, "running")[0], 400)  # no control period yet
        current = self.ok(self.operator.get(f"/api/actions/{action_id}"))
        self.assertEqual(self.operator.put(f"/api/actions/{action_id}", {"updated_at": current["updated_at"], "control_start": "2026-09-15", "control_end": "2026-10-15"})[0], 400)  # overlaps the baseline
        self.ok(self.operator.put(f"/api/actions/{action_id}", {"updated_at": current["updated_at"], "control_start": "2026-10-01", "control_end": "2026-10-30", "owner_id": 1, "due_day": "2026-11-10", "targets": "кг/100 порция −10%"}))
        self.assertEqual(self.operator.put(f"/api/actions/{action_id}", {"updated_at": current["updated_at"], "problem": "Ескі нұсқа"})[0], 409)  # stale copy
        self.ok(self.move(self.operator, action_id, "running"))
        self.assertEqual(self.move(self.manager, action_id, "done", conclusion="Ерте")[0], 403)  # evaluation cannot be skipped
        self.ok(self.move(self.operator, action_id, "evaluating"))
        self.assertEqual(self.move(self.manager, action_id, "done")[0], 400)  # a conclusion is required
        self.assertEqual(self.move(self.manager, action_id, "done", conclusion="Нәтиже тіркелді", confirmed_savings=5000)[0], 400)  # savings need a document
        self.ok(self.move(self.manager, action_id, "done", conclusion="Қалдық азайды, бірақ дәлел жеткіліксіз", confirmed_savings=5000, confirmed_doc="Сатып алу актісі №14"))
        final = self.ok(self.operator.get(f"/api/actions/{action_id}"))
        self.assertEqual([(e["from_status"], e["to_status"]) for e in final["events"]], [(None, "proposed"), ("proposed", "approved"), ("approved", "running"), ("running", "evaluating"), ("evaluating", "done")])
        self.assertEqual((final["approver"], final["owner"], final["confirmed_savings"]), ("Демо басшылық", "Демо қызметкер", 5000.0))
        self.assertEqual(final["result"]["finance"]["net_confirmed"], 5000 - 120)
        self.assertIn("себептік әсерінің дәлелі емес", final["evaluation"]["disclaimer"])
        self.assertEqual(self.operator.put(f"/api/actions/{action_id}", {"updated_at": final["updated_at"], "problem": "Өзгерту"})[0], 409)
        with self.db() as db:
            mod_actions.tick(db)
        second = self.ok(self.new_action(problem="Борщ артылады"), 201)["id"]
        self.assertEqual(self.move(self.manager, second, "stopped")[0], 400)
        self.ok(self.move(self.manager, second, "stopped", note="Мәзірден алынды"))
        similar = self.ok(self.operator.get("/api/actions/similar?cause=overproduction"))["similar"]
        self.assertEqual([s["id"] for s in similar], [action_id])  # only finished actions enter the experience base

    def test_02_evaluation_flags_tradeoffs_and_limits(self):
        with self.db() as db:
            dish = db.execute("INSERT INTO catalog_dishes(org_id,name,created_at,updated_at) VALUES (2,'Бағалау тағамы','x','x')").lastrowid
            sale = lambda day, qty: db.execute("INSERT INTO sales(org_id,day,dish_id,portion_id,name,portion_label,qty,price_tiyn,total_tiyn,source,created_at) VALUES (2,?,?,1,'Бағалау тағамы','Толық',?,100000,?,'counter','x')", (day, dish, qty, qty * 100000))
            for day in ("2026-09-07", "2026-09-08", "2026-09-09"):
                sale(day, 1000)
            for day in ("2026-10-05", "2026-10-06", "2026-10-07"):
                sale(day, 1000)
            db.execute("INSERT INTO shortages(org_id,day,dish_id,ended_at,unmet,created_by,created_at) VALUES (2,'2026-10-06',?,'13:00',NULL,5,'x')", (dish,))
            db.execute("UPDATE items SET kg=kg*0.5 WHERE report_id IN (SELECT id FROM reports WHERE org_id=2 AND report_date BETWEEN '2026-10-01' AND '2026-10-29')")
            action = {"id": 0, "org_id": 2, "baseline_start": "2026-09-01", "baseline_end": "2026-09-30", "control_start": "2026-10-01", "control_end": "2026-10-29",
                      "category_id": None, "dish_id": None, "cost_tiyn": 500000, "confirmed_savings_tiyn": None, "confirmed_doc": ""}
            result = mod_actions.evaluation(db, action)
            self.assertLess(result["delta"]["kg_per_100"], 0)
            self.assertEqual((result["shortage_delta"], result["verdict"]), (1, "revise"))  # less waste but more shortages
            self.assertEqual(result["control"]["unmet_known"], None)
            self.assertEqual(result["control"]["unmet_unknown_events"], 1)  # unknown demand is not zero
            finance = result["finance"]
            self.assertIsNone(finance["confirmed_savings"])
            self.assertIsNone(finance["net_confirmed"])  # an estimate is never reported as confirmed
            self.assertAlmostEqual(finance["net_estimated"], finance["estimated_avoided_cost"] - 5000, places=2)
            empty = mod_actions.metrics(db, 5, "2026-07-01", "2026-07-31")
            self.assertEqual((empty["waste_kg"], empty["portions"], empty["kg_per_100"], empty["unsold_portions"]), (None, None, None, None))
            no_control = mod_actions.evaluation(db, {**action, "control_start": None, "control_end": None})
            self.assertEqual(no_control["verdict"], "no_control")

    def test_03_data_quality_lists_and_clarifications(self):
        payload = {"org_id": 1, "report_date": "2026-10-13", "items": [{"category_id": 3, "kg": 6.66, "route": "tbo"}]}
        first = self.ok(self.operator.post("/api/reports", payload), 201)["id"]
        self.ok(self.operator.post("/api/reports", payload), 201)
        with self.db() as db:
            db.execute("DELETE FROM reports WHERE org_id=1 AND report_date='2026-10-14' AND id!=?", (first,))
        quality = self.ok(self.reviewer.get("/api/quality?org=1&start=2026-10-01&end=2026-10-30"))
        self.assertTrue(any(d["date"] == "2026-10-13" and d["copies"] == 2 for d in quality["duplicates"]))
        self.assertIn("2026-10-14", quality["missing_days"])
        self.assertNotIn("2026-10-11", quality["missing_days"])  # Sunday
        self.assertTrue(any(i["missing"] == "portions" for i in quality["incomplete"]))
        self.assertIn("күн жоқ", quality["impact"]["forecast"])
        self.assertLess(quality["impact"]["completeness"], 1)
        lab = self.ok(self.reviewer.get("/api/quality?org=4&start=2026-10-01&end=2026-10-30"))
        self.assertEqual((lab["missing_days"], lab["missing_days_known"]), ([], False))  # lab days are not assumed
        self.assertEqual(self.inn.get("/api/quality?org=1&start=2026-10-01&end=2026-10-30")[1]["org_id"], 2)
        self.assertEqual(self.operator.post("/api/clarifications", {"org_id": 1, "kind": "duplicate", "question": "Қайталанған ба?"})[0], 403)
        qid = self.ok(self.reviewer.post("/api/clarifications", {"org_id": 1, "kind": "duplicate", "ref": "2026-10-13", "question": "13 қазандағы екі бірдей өлшем қайталанған ба?"}), 201)["id"]
        self.assertEqual(self.inn.post(f"/api/clarifications/{qid}/answer", {"answer": "Бөтен жауап"})[0], 404)
        self.assertEqual(self.reviewer.post(f"/api/clarifications/{qid}/answer", {"answer": "Өзім жауап беремін"})[0], 403)
        self.ok(self.operator.post(f"/api/clarifications/{qid}/answer", {"answer": "Иә, екінші жазба қате енгізілген"}))
        self.assertEqual(self.operator.post(f"/api/clarifications/{qid}/close")[0], 403)
        self.ok(self.reviewer.post(f"/api/clarifications/{qid}/close"))
        item = next(q for q in self.ok(self.reviewer.get("/api/quality?org=1&start=2026-10-01&end=2026-10-30"))["clarifications"] if q["id"] == qid)
        self.assertEqual((item["status"], item["answer"], bool(item["answered_at"]), bool(item["closed_at"])), ("closed", "Иә, екінші жазба қате енгізілген", True, True))
        with self.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM user_notices WHERE kind='clarification' AND user_id=1").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM reports WHERE org_id=1 AND report_date='2026-10-13'").fetchone()[0] >= 2, True)  # nothing was removed automatically

    def test_04_transfer_document_is_not_proof_of_processing(self):
        before = self.ok(self.manager.get("/api/recycling?start=2026-08-01&end=2026-11-30&org=1"))
        self.assertGreater(before["suitable_kg"], 0)
        self.assertEqual((before["documented_transfer_kg"], before["processing_confirmed_kg"]), (0, 0))
        self.assertEqual(self.reviewer.post("/api/transfers", {"org_id": 1, "category_id": 6, "qty": 40, "day": "2026-11-10", "recipient": "Демо қабылдаушы"})[0], 403)
        self.assertEqual(self.operator.post("/api/transfers", {"category_id": 9, "qty": 40, "day": "2026-11-10", "recipient": "Демо қабылдаушы"})[0], 400)  # not this organization's type
        tid = self.ok(self.operator.post("/api/transfers", {"category_id": 6, "qty": 40, "day": "2026-11-10", "recipient": "Демо қабылдаушы"}), 201)["id"]
        self.assertEqual(self.reviewer.post(f"/api/transfers/{tid}/confirm")[0], 403)  # not handed over yet
        self.assertEqual(self.operator.post(f"/api/transfers/{tid}/hand", {})[0], 400)  # a hand-over needs its document
        self.ok(self.operator.post(f"/api/transfers/{tid}/hand", {"document": "Қабылдау-тапсыру актісі №7"}))
        middle = self.ok(self.manager.get("/api/recycling?start=2026-08-01&end=2026-11-30&org=1"))
        self.assertEqual((middle["documented_transfer_kg"], middle["receipt_confirmed_kg"], middle["processing_confirmed_kg"]), (40, 0, 0))
        self.assertEqual(self.operator.post(f"/api/transfers/{tid}/confirm")[0], 403)
        self.assertEqual(self.reviewer.post(f"/api/transfers/{tid}/processing", {"processing_doc": "Өңдеу анықтамасы"})[0], 403)  # receipt first
        self.ok(self.reviewer.post(f"/api/transfers/{tid}/confirm"))
        confirmed = self.ok(self.manager.get("/api/recycling?start=2026-08-01&end=2026-11-30&org=1"))
        self.assertEqual((confirmed["receipt_confirmed_kg"], confirmed["processing_confirmed_kg"]), (40, 0))  # a receipt is still not processing
        self.ok(self.reviewer.post(f"/api/transfers/{tid}/processing", {"processing_doc": "Өңдеу туралы анықтама №3"}))
        self.assertEqual(self.ok(self.manager.get("/api/recycling?start=2026-08-01&end=2026-11-30&org=1"))["processing_confirmed_kg"], 40)
        self.assertEqual(self.ok(self.inn.get("/api/transfers?org=1"))["transfers"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
