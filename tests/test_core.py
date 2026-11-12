"""Roles, dictionaries, periodic reports, registry and exports (ТТ 2–7)."""
import io
import unittest
import zipfile

from helpers import Client, ServerCase


class RolesAndDictionaries(ServerCase):
    def test_01_registration_never_grants_a_staff_role(self):
        guest = Client(self.base)
        self.assertEqual(guest.post("/api/register", {"email": "new@student.kz", "name": "Жаңа студент", "password": "short"})[0], 400)
        body = self.ok(guest.post("/api/register", {"email": "new@student.kz", "name": "Жаңа студент", "password": "long-enough-1", "role": "admin", "org_id": 1, "can_review": 1}), 201)
        self.assertEqual(body["role"], "student")
        me = self.ok(guest.get("/api/me"))
        self.assertEqual((me["user"]["role"], me["user"]["org_id"], me["user"]["can_review"]), ("student", None, 0))
        self.assertEqual(Client(self.base).post("/api/register", {"email": "new@student.kz", "name": "Қайталау", "password": "long-enough-1"})[0], 409)

    def test_02_student_cannot_reach_staff_data(self):
        student = Client(self.base).login("student")
        for path in ("/api/bootstrap", "/api/reports", "/api/reports/1", "/api/export?format=csv", "/api/export?format=xlsx", "/api/registry",
                     "/api/periods", "/api/periods/1", "/api/users", "/api/totals", "/api/food-insights", "/api/notifications"):
            self.assertEqual(student.get(path)[0], 403, path)
        for path, data in (("/api/reports", {"org_id": 1}), ("/api/quick", {"category_id": 1, "kg": 1}), ("/api/categories", {"name": "Студент түрі"}),
                           ("/api/users", {"email": "x@y.kz"}), ("/api/periods", {"org_id": 1, "month": "2026-10"})):
            self.assertEqual(student.post(path, data)[0], 403, path)

    def test_03_admin_manages_users_and_sessions_follow_changes(self):
        for client in (self.operator, self.reviewer, self.manager):
            self.assertEqual(client.get("/api/users")[0], 403)
            self.assertEqual(client.post("/api/users", {"email": "a@b.kz", "name": "Жоқ", "role": "admin", "password": "long-enough-1"})[0], 403)
        self.assertEqual(self.admin.post("/api/users", {"email": "op2@atu.kz", "name": "Екінші қызметкер", "role": "operator", "password": "long-enough-1"})[0], 400)
        uid = self.ok(self.admin.post("/api/users", {"email": "op2@atu.kz", "name": "Екінші қызметкер", "role": "operator", "org_id": 3, "password": "long-enough-1"}), 201)["id"]
        second = Client(self.base).login("op2@atu.kz", "long-enough-1")
        self.assertTrue(all(r["org_id"] == 3 for r in self.ok(second.get("/api/reports"))["reports"]))
        self.ok(self.admin.put(f"/api/users/{uid}", {"org_id": 4}))
        self.assertEqual(second.get("/api/reports")[0], 401)  # the old session does not keep the old organization
        self.ok(self.admin.put(f"/api/users/{uid}", {"active": 0}))
        self.assertEqual(Client(self.base).post("/api/login", {"email": "op2@atu.kz", "password": "long-enough-1"})[0], 403)
        self.assertEqual(self.admin.put(f"/api/users/{self.admin.user['id']}", {"role": "manager"})[0], 400)

    def test_04_admin_reviews_only_with_the_explicit_duty(self):
        self.ok(self.admin.post("/api/users", {"email": "admin2@atu.kz", "name": "Тек әкімші", "role": "admin", "password": "long-enough-1"}), 201)
        plain = Client(self.base).login("admin2@atu.kz", "long-enough-1")
        self.assertEqual(plain.user["can_review"], 0)
        rid = self.ok(self.operator.post("/api/reports", {"org_id": 1, "report_date": "2026-10-28", "submit": True, "items": [{"category_id": 1, "kg": 2, "route": "compost"}]}), 201)["id"]
        report = self.ok(plain.get(f"/api/reports/{rid}"))
        self.assertEqual(plain.post(f"/api/reports/{rid}/transition", {"status": "in_review", "updated_at": report["updated_at"]})[0], 403)
        self.ok(self.admin.post(f"/api/reports/{rid}/transition", {"status": "in_review", "updated_at": report["updated_at"]}))

    def test_05_organization_fields_and_new_organization_without_code(self):
        self.assertEqual(self.reviewer.put("/api/organizations/1", {"hours": "x"})[0], 403)
        self.ok(self.admin.put("/api/organizations/1", {"address": "1-корпус", "hours": "09:00–18:00", "description": "Асхана", "is_public": 1}))
        org = next(o for o in self.ok(self.admin.get("/api/bootstrap"))["organizations"] if o["id"] == 1)
        self.assertEqual((org["address"], org["hours"], org["active"], org["responsible"]), ("1-корпус", "09:00–18:00", 1, ["Демо қызметкер"]))
        new_id = self.ok(self.admin.post("/api/organizations", {"name": "3-корпус буфеті", "kind": "Кофехана", "address": "3-корпус"}), 201)["id"]
        boot = self.ok(self.admin.get("/api/bootstrap"))
        self.assertEqual(boot["org_categories"][str(new_id)], boot["org_categories"]["3"])  # starts from the same type's list

    def test_06_waste_types_are_deactivated_not_deleted(self):
        self.assertEqual(self.operator.put("/api/categories/2", {"active": 0})[0], 403)
        self.assertEqual(self.reviewer.put("/api/categories/1", {"unit": "l"})[0], 400)  # has measurements
        self.ok(self.reviewer.put("/api/categories/2", {"active": 0, "source": "Тест дереккөзі", "boundary": "Қақпадан қақпаға", "co2_unit": "кг CO₂e/кг"}))
        payload = {"org_id": 1, "report_date": "2026-10-27", "items": [{"category_id": 2, "kg": 1, "route": "tbo"}]}
        self.assertEqual(self.operator.post("/api/reports", payload)[0], 400)
        with self.db() as db:
            self.assertGreater(db.execute("SELECT COUNT(*) FROM items WHERE category_id=2").fetchone()[0], 0)  # history is kept
        self.ok(self.reviewer.put("/api/categories/2", {"active": 1}))
        self.ok(self.operator.post("/api/reports", payload), 201)

    def test_07_disposal_methods_are_an_extensible_dictionary(self):
        self.assertEqual(self.operator.post("/api/routes", {"name": "Жануарларға жем"})[0], 403)
        code = self.ok(self.reviewer.post("/api/routes", {"name": "Жануарларға жем", "diverted": 1, "name_ru": "Корм животным"}), 201)["code"]
        self.assertEqual(self.reviewer.post("/api/routes", {"name": "жануарларға жем"})[0], 409)
        payload = {"org_id": 1, "report_date": "2026-10-26", "items": [{"category_id": 1, "kg": 3, "route": code, "stage": "prep", "note": "Тазалау"}]}
        rid = self.ok(self.operator.post("/api/reports", payload), 201)["id"]
        item = self.ok(self.operator.get(f"/api/reports/{rid}"))["items"][0]
        self.assertEqual((item["route"], item["stage"], item["note"]), (code, "prep", "Тазалау"))
        self.ok(self.admin.put(f"/api/routes/{code}", {"active": 0}))
        self.assertEqual(self.operator.post("/api/reports", payload)[0], 400)

    def test_08_measurement_validation_and_duplicate_warning(self):
        base = {"org_id": 1, "report_date": "2026-10-25"}
        for item in ({"category_id": 1, "kg": 1.234, "route": "tbo"}, {"category_id": 1, "kg": 1, "route": "tbo", "stage": "unknown"}):
            self.assertEqual(self.operator.post("/api/reports", {**base, "items": [item]})[0], 400, item)
        payload = {**base, "items": [{"category_id": 3, "kg": 7.25, "route": "tbo", "stage": "plate"}], "request_id": "duplicate-check-0001"}
        first = self.ok(self.operator.post("/api/reports", payload), 201)
        self.assertEqual(first["duplicates"], [])
        replay = self.ok(self.operator.post("/api/reports", payload), 201)
        self.assertEqual((replay["id"], replay.get("replayed")), (first["id"], True))  # idempotency: no second record
        second = self.ok(self.operator.post("/api/reports", {**payload, "request_id": "duplicate-check-0002"}), 201)
        self.assertNotEqual(second["id"], first["id"])
        self.assertEqual(second["duplicates"][0]["report_id"], first["id"])  # content duplicate: a warning, not a block

    def test_09_quick_entry_adds_to_todays_draft(self):
        self.assertEqual(self.reviewer.post("/api/quick", {"category_id": 1, "kg": 1})[0], 403)
        first = self.ok(self.operator.post("/api/quick", {"category_id": 1, "kg": 2.5}), 201)
        second = self.ok(self.operator.post("/api/quick", {"category_id": 5, "kg": 1}), 201)
        self.assertEqual(first["id"], second["id"])
        report = self.ok(self.operator.get(f"/api/reports/{first['id']}"))
        self.assertEqual([(i["category_id"], i["kg"], i["route"]) for i in report["items"]], [(1, 2.5, "compost"), (5, 1, "recycling")])
        self.assertEqual(report["status"], "draft")
        self.assertEqual(self.operator.post("/api/quick", {"category_id": 9, "kg": 1})[0], 400)  # not in this organization's list

    def test_10_demo_accounts_are_listed_for_switching(self):
        accounts = self.ok(Client(self.base).get("/api/public/demo-accounts"))["accounts"]
        self.assertEqual({a["role"] for a in accounts}, {"operator", "reviewer", "manager", "admin", "student"})
        self.assertEqual(len([a for a in accounts if a["role"] == "operator"]), 5)
        self.assertTrue(all("password" not in a and "id" not in a for a in accounts))


class PeriodReports(ServerCase):
    def period(self, client, period_id):
        return self.ok(client.get(f"/api/periods/{period_id}"))

    def move(self, client, period_id, status, comment=""):
        return client.post(f"/api/periods/{period_id}/transition", {"status": status, "comment": comment, "updated_at": self.period(client, period_id)["updated_at"]})

    def test_01_period_report_joins_measurements_of_many_dates(self):
        periods = self.ok(self.operator.get("/api/periods"))["periods"]
        self.assertTrue(all(p["org_id"] == 1 for p in periods))
        october = next(p for p in periods if p["period_start"] == "2026-10-01")
        detail = self.period(self.operator, october["id"])
        self.assertGreater(len({m["date"] for m in detail["measurements"]}), 15)
        self.assertEqual({t["unit"] for t in detail["summary"]["totals"]}, {"kg", "l"})  # two totals, never one
        self.assertEqual(self.ok(self.operator.post("/api/periods", {"org_id": 1, "month": "2026-10"}))["id"], october["id"])
        self.assertEqual(self.operator.post("/api/periods", {"org_id": 2, "month": "2026-11"})[0], 403)
        self.assertEqual(self.operator.get("/api/periods/3")[0], 403)  # organization 2
        empty = self.ok(self.operator.post("/api/periods", {"org_id": 1, "month": "2026-07"}), 201)["id"]
        self.assertEqual(self.move(self.operator, empty, "submitted")[0], 400)
        self.assertEqual(self.operator.post("/api/periods", {"org_id": 1, "start": "2026-07-15", "end": "2026-08-15"})[0], 409)

    def test_02_submit_return_fix_accept_and_lock(self):
        pid = next(p["id"] for p in self.ok(self.operator.get("/api/periods"))["periods"] if p["period_start"] == "2026-10-01")
        draft = self.ok(self.operator.post("/api/reports", {"org_id": 1, "report_date": "2026-10-20", "items": [{"category_id": 1, "kg": 4, "route": "compost"}]}), 201)["id"]
        stale = self.period(self.operator, pid)["updated_at"]
        self.assertEqual(self.move(self.reviewer, pid, "in_review")[0], 403)
        self.ok(self.move(self.operator, pid, "submitted"))
        self.assertEqual(self.operator.post(f"/api/periods/{pid}/transition", {"status": "submitted", "updated_at": stale})[0], 409)  # repeated send
        self.assertEqual(self.ok(self.operator.get(f"/api/reports/{draft}"))["status"], "submitted")
        new_record = {"org_id": 1, "report_date": "2026-10-21", "items": [{"category_id": 1, "kg": 1, "route": "compost"}]}
        self.assertEqual(self.operator.post("/api/reports", new_record)[0], 409)
        report = self.ok(self.reviewer.get(f"/api/reports/{draft}"))
        self.assertEqual(self.reviewer.post(f"/api/reports/{draft}/transition", {"status": "in_review", "updated_at": report["updated_at"]})[0], 409)
        self.assertEqual(self.move(self.operator, pid, "in_review")[0], 403)
        self.ok(self.move(self.reviewer, pid, "in_review"))
        self.assertEqual(self.move(self.reviewer, pid, "returned")[0], 400)
        self.ok(self.move(self.reviewer, pid, "returned", "20 қазандағы массаны нақтылаңыз"))
        returned = self.ok(self.operator.get(f"/api/reports/{draft}"))
        self.assertEqual(returned["status"], "returned")
        self.assertEqual(returned["history"][-1]["comment"], "20 қазандағы массаны нақтылаңыз")
        self.ok(self.operator.put(f"/api/reports/{draft}", {"org_id": 1, "report_date": "2026-10-20", "updated_at": returned["updated_at"], "items": [{"category_id": 1, "kg": 3.5, "route": "compost"}]}))
        self.ok(self.move(self.operator, pid, "submitted"))
        self.ok(self.move(self.reviewer, pid, "in_review"))
        self.ok(self.move(self.reviewer, pid, "accepted"))
        final = self.period(self.manager, pid)
        self.assertEqual((final["status"], final["reviewer"]), ("accepted", "Демо тексеруші"))
        self.assertTrue(final["submitted_at"] and final["decided_at"])
        self.assertEqual([(h["from_status"], h["to_status"]) for h in final["history"]][-6:],
                         [("draft", "submitted"), ("submitted", "in_review"), ("in_review", "returned"), ("returned", "submitted"), ("submitted", "in_review"), ("in_review", "accepted")])
        self.assertEqual(final["record_statuses"], {"accepted": final["record_statuses"]["accepted"]})  # every record moved with the report
        accepted = self.ok(self.operator.get(f"/api/reports/{draft}"))
        self.assertEqual(accepted["history"][-1]["from_status"], "in_review")
        self.assertEqual(self.operator.put(f"/api/reports/{draft}", {"org_id": 1, "report_date": "2026-10-20", "updated_at": accepted["updated_at"], "items": [{"category_id": 1, "kg": 9, "route": "compost"}]})[0], 403)
        self.assertEqual(self.operator.post("/api/reports", new_record)[0], 409)
        self.assertEqual(self.move(self.operator, pid, "submitted")[0], 403)

    def test_03_overview_separates_not_submitted_from_not_accepted(self):
        view = self.ok(self.manager.get("/api/periods/overview?start=2026-10-01&end=2026-10-31"))
        self.assertEqual([o["id"] for o in view["not_submitted"]], [5])
        self.assertEqual({o["id"]: o["status"] for o in view["not_accepted"]}, {2: "submitted", 3: "in_review", 4: "returned"})
        self.assertEqual([o["id"] for o in view["accepted"]], [1])
        own = self.ok(Client(self.base).login("thipp").get("/api/periods/overview?start=2026-10-01&end=2026-10-31"))
        self.assertEqual([o["id"] for o in own["not_submitted"] + own["not_accepted"] + own["accepted"]], [5])

    def test_04_registry_holds_accepted_measurements_and_filters_rows(self):
        registry = self.ok(self.manager.get("/api/registry?start=2026-08-01&end=2026-10-31"))
        self.assertTrue(all(m["status"] == "accepted" for m in registry["measurements"]))
        self.assertEqual(len({m["org_id"] for m in registry["measurements"]}), 5)
        oil = self.ok(self.manager.get("/api/registry?start=2026-08-01&end=2026-10-31&category=5"))["measurements"]
        self.assertTrue(oil and all(m["category_id"] == 5 and m["unit"] == "l" for m in oil))
        self.assertLess(len(oil), len(registry["measurements"]))
        compost = self.ok(self.manager.get("/api/registry?start=2026-08-01&end=2026-10-31&route=compost&unit=kg&org=3"))["measurements"]
        self.assertTrue(compost and all((m["route"], m["unit"], m["org_id"]) == ("compost", "kg", 3) for m in compost))
        own = self.ok(self.operator.get("/api/registry?org=2"))["measurements"]
        self.assertTrue(own and all(m["org_id"] == 1 for m in own))
        months = {(r["a"], r["unit"]) for r in registry["summary"]["by_month"]}
        self.assertTrue({("2026-08", "kg"), ("2026-09", "kg"), ("2026-10", "kg")} <= months)

    def test_05_xlsx_export_is_a_real_workbook(self):
        status, body, headers = self.manager.get("/api/export?format=xlsx&lang=ru&start=2026-07-01&end=2026-09-30")
        self.assertEqual(status, 200)
        self.assertIn("spreadsheetml.sheet", headers["Content-Type"])
        archive = zipfile.ZipFile(io.BytesIO(body))
        self.assertIsNone(archive.testzip())
        self.assertIn("xl/workbook.xml", archive.namelist())
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl is not installed; the archive structure was checked only")
        book = openpyxl.load_workbook(io.BytesIO(body))
        self.assertEqual(book.sheetnames[:2], ["Свод", "По месяцам"])
        self.assertEqual(len(book.sheetnames), 7)  # summary, months and one sheet per organization
        sheet = book["Асхана"]
        header = next(row for row in sheet.iter_rows(values_only=True) if row[0] == "Дата")
        self.assertEqual(header[:6], ("Дата", "Наименование отходов", "Вес (кг) / Объём (л)", "Ед.", "Способ переработки / утилизации", "Ответственное лицо"))
        self.assertIn("Очистки овощей", {row[1] for row in sheet.iter_rows(values_only=True)})
        self.assertIn("Только принятые", book["Свод"]["A2"].value)
        journal = openpyxl.load_workbook(io.BytesIO(self.manager.get("/api/export?format=xlsx&scope=journal&start=2026-10-01&end=2026-10-31")[1]))
        self.assertIn("ЖҰМЫС ЖУРНАЛЫ", journal["Жиынтық"]["A2"].value)
        own = openpyxl.load_workbook(io.BytesIO(self.operator.get("/api/export?format=xlsx&org=2&start=2026-08-01&end=2026-09-30")[1]))
        self.assertEqual(len(own.sheetnames), 3)
        page = self.manager.get("/api/export?format=print&lang=ru&start=2026-07-01&end=2026-09-30")[1].decode()
        self.assertIn("Таблица учёта пищевых отходов", page)


if __name__ == "__main__":
    unittest.main(verbosity=2)
