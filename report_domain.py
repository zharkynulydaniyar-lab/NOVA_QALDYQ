"""Existing report validation and persistence shared by HTTP and Telegram."""
import base64
import hashlib
import json
import re
from datetime import date
from common import APIError, now, number, STAGES, UNITS
from features import local_day
import mod_period

DEMO_DAY = date(2026, 10, 30)


class ReportDomain:
    def content_duplicates(self, db, report_id):
        """Likely repeated measurements: same organization, date, waste type and quantity in another record.
        This is a content warning only; replay protection is the separate request_id check."""
        return [dict(r) for r in db.execute("""SELECT other.report_id,c.name,mine.kg FROM items mine
            JOIN reports r ON r.id=mine.report_id JOIN items other ON other.category_id=mine.category_id AND other.kg=mine.kg AND other.report_id!=mine.report_id
            JOIN reports o ON o.id=other.report_id AND o.org_id=r.org_id AND o.report_date=r.report_date
            JOIN categories c ON c.id=mine.category_id WHERE mine.report_id=? GROUP BY other.report_id,c.id""", (report_id,))]

    def check_version(self, data, report):
        if data.get("updated_at") != report["updated_at"]:
            raise APIError("Есеп басқа терезеде өзгерді. Жаңартып, қайта көріңіз.", 409)

    def request_fingerprint(self, data, action):
        return hashlib.sha256((action + json.dumps(data, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()

    def request_replay(self, db, user, data, action):
        key = data.get('request_id')
        if key is None:
            return None
        if not isinstance(key, str) or not re.fullmatch(r'[a-zA-Z0-9-]{16,80}', key):
            raise APIError('Сұрау кілті дұрыс емес.')
        previous = db.execute('SELECT * FROM report_requests WHERE user_id=? AND request_id=?', (user['id'], key)).fetchone()
        if previous:
            if previous['fingerprint'] != self.request_fingerprint(data, action):
                raise APIError('Бұл сұрау кілті басқа есепке қолданылған.', 409)
            return previous['report_id']

    def remember_request(self, db, user, data, action, report_id):
        if data.get('request_id'):
            db.execute('INSERT INTO report_requests VALUES (?,?,?,?)', (user['id'], data['request_id'], self.request_fingerprint(data, action), report_id))

    def save_dishes(self, db, report_id, dishes):
        db.executemany('INSERT INTO dishes(report_id,name,prepared,served,leftover,leftover_kg) VALUES (?,?,?,?,?,?)', [(report_id, *d) for d in dishes])

    def validate_report(self, db, user, data, minimum_items=1):
        org_id = int(data.get("org_id", 0))
        if user["role"] == "operator" and org_id != user["org_id"]:
            raise APIError("Тек өз ұйымыңызға есеп енгізе аласыз.", 403)
        if not db.execute("SELECT 1 FROM organizations WHERE id=?", (org_id,)).fetchone():
            raise APIError("Ұйымды таңдаңыз.")
        report_date = str(data.get("report_date", ""))
        try:
            parsed_day = date.fromisoformat(report_date)
        except ValueError:
            raise APIError("Күнді дұрыс көрсетіңіз.")
        if not date(2020, 1, 1) <= parsed_day <= max(DEMO_DAY, local_day()):
            raise APIError("Болашақ күнге немесе 2020 жылға дейін есеп беруге болмайды.")
        photo = data.get("photo")
        if photo is not None and photo != "":
            if not isinstance(photo, str) or not re.match(r"^data:image/(png|jpeg|webp);base64,", photo):
                raise APIError("Фото PNG, JPEG немесе WebP болсын.")
            try:
                image_bytes = base64.b64decode(photo.split(",", 1)[1], validate=True)
            except ValueError:
                raise APIError("Фото пішімі қате.")
            if len(image_bytes) > 2_000_000:
                raise APIError("Фото 2 МБ-тан аспасын.")
            is_png = image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
            is_jpg = image_bytes.startswith(b"\xff\xd8\xff")
            is_webp = image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP"
            kind = photo.split(";", 1)[0]
            if not ((kind.endswith("png") and is_png) or (kind.endswith("jpeg") and is_jpg) or (kind.endswith("webp") and is_webp)):
                raise APIError("Файл сурет пішіміне сәйкес емес.")
        else:
            photo = None
        raw_items = data.get("items", [])
        if not isinstance(raw_items, list) or not minimum_items <= len(raw_items) <= 30:
            raise APIError("Кемінде бір қалдық жолы қажет, ең көбі — 30.")
        items = []
        routes = {r["code"] for r in db.execute("SELECT code FROM routes WHERE active=1")}
        for raw in raw_items:
            if not isinstance(raw, dict):
                raise APIError("Қалдық жолы дұрыс емес.")
            cat = db.execute("SELECT c.* FROM categories c JOIN org_categories oc ON oc.category_id=c.id WHERE c.id=? AND oc.org_id=? AND c.active=1", (int(raw.get("category_id", 0)), org_id)).fetchone()
            if not cat or raw.get("route") not in routes:
                raise APIError("Қалдық түрі мен кәдеге жарату тәсілін ұйым тізімінен таңдаңыз.")
            quantity = number(raw.get("kg"), "Масса", 0.01, 10000)
            if abs(quantity * 100 - round(quantity * 100)) > 1e-6:
                raise APIError("Мөлшерді үтірден кейін екі таңбаға дейін енгізіңіз.")
            stage = raw.get("stage") or "other"
            if stage not in STAGES:
                raise APIError("Қалдықтың пайда болу кезеңін таңдаңыз.")
            items.append((cat["id"], quantity, raw["route"], cat["cost"], cat["co2"], stage, str(raw.get("note") or "").strip()[:500]))
        portions = data.get('portions')
        if portions not in (None, ''):
            portions = number(portions, 'Сатылған порция', 1, 100000)
            if not portions.is_integer():
                raise APIError('Порция бүтін сан болсын.')
            portions = int(portions)
        else:
            portions = None
        dishes = data.get('dishes', [])
        if not isinstance(dishes, list) or len(dishes) > 30:
            raise APIError('Ең көбі 30 тағам жолы.')
        clean_dishes, seen = [], set()
        for dish in dishes:
            if not isinstance(dish, dict):
                raise APIError('Тағам жолы дұрыс емес.')
            name = str(dish.get('name', '')).strip()
            if not 2 <= len(name) <= 100 or name.casefold() in seen:
                raise APIError('Тағам атауы 2–100 таңба, әр атау бір рет енгізілсін.')
            seen.add(name.casefold())
            counts = [number(dish.get(k), 'Тағам порциясы', 0, 100000) for k in ('prepared', 'served', 'leftover')]
            if not all(n.is_integer() for n in counts) or counts[0] < 1 or counts[1] + counts[2] > counts[0]:
                raise APIError('Сатылған + артылған порция дайындалған саннан аспасын. Сандар бүтін болсын.')
            clean_dishes.append((name, *[int(n) for n in counts], number(dish.get('leftover_kg'), 'Артылған тағам массасы', 0, 10000)))
        if sum(d[-1] for d in clean_dishes) > sum(i[1] for i in items) + 0.001:
            raise APIError('Артылған тағам массасы жалпы қалдық массасынан аспасын. Ол жалпы массаға кіреді.')
        return {"org_id": org_id, "report_date": report_date, "note": str(data.get("note", "")).strip()[:2000], "photo": photo, 'portions': portions, 'dishes': clean_dishes}, items

    def save_items(self, db, report_id, items):
        db.executemany("INSERT INTO items(report_id,category_id,kg,route,cost,co2,stage,note) VALUES (?,?,?,?,?,?,?,?)", [(report_id, *item) for item in items])

    def history(self, db, report_id, user, action, comment, from_status=None):
        db.execute("INSERT INTO history(report_id,user_id,action,comment,created_at,from_status) VALUES (?,?,?,?,?,?)", (report_id, user["id"], action, comment, now(), from_status))

    def org_categories(self, db):
        result = {}
        for row in db.execute("SELECT org_id,category_id FROM org_categories ORDER BY org_id,category_id"):
            result.setdefault(str(row["org_id"]), []).append(row["category_id"])
        return result

    def list_reports(self, db, user, query):
        clauses, args = ["1=1"], []
        for key, op in (("start", ">="), ("end", "<=")):
            if query.get(key):
                day = date.fromisoformat(query[key][0]).isoformat()
                clauses.append(f"r.report_date {op} ?")
                args.append(day)
        org = user["org_id"] if user["role"] == "operator" else int(query.get("org", [0])[0])
        if org:
            clauses.append("r.org_id=?")
            args.append(org)
        # Қалдық түрі сүзгісі: есептің тек сол түрдегі жолдары мен жиынтығы қайтарылады.
        category = int(query.get("category", [0])[0])
        if category:
            clauses.append("i.category_id=?")
            args.append(category)
        rows = db.execute(f"""SELECT r.id,r.org_id,r.author_id,r.report_date,r.status,r.note,r.created_at,r.updated_at,r.portions,
            o.name AS org_name,u.name AS author,
            ROUND(SUM(CASE WHEN c.unit='l' THEN 0 ELSE i.kg END),2) AS kg,
            ROUND(SUM(CASE WHEN c.unit='l' THEN i.kg ELSE 0 END),2) AS liters,
            ROUND(SUM(i.kg*i.cost),2) AS cost,ROUND(SUM(i.kg*i.co2),2) AS co2,
            ROUND(SUM(CASE WHEN c.unit!='l' AND i.route IN (SELECT code FROM routes WHERE diverted=1) THEN i.kg ELSE 0 END),2) AS diverted_kg,
            ROUND(SUM(CASE WHEN c.unit!='l' AND c.recyclable=1 THEN i.kg ELSE 0 END),2) AS recyclable_kg
            FROM reports r JOIN organizations o ON o.id=r.org_id JOIN users u ON u.id=r.author_id
            JOIN items i ON i.report_id=r.id JOIN categories c ON c.id=i.category_id WHERE {' AND '.join(clauses)}
            GROUP BY r.id ORDER BY r.report_date DESC,r.id DESC""", args).fetchall()
        reports = [dict(r) for r in rows]
        by_id = {r["id"]: r for r in reports}
        for report in reports:
            report["items"] = []
            report['dishes'] = []
        if reports:
            ids = list(by_id)
            placeholders = ",".join("?" for _ in ids)
            only = " AND i.category_id=?" if category else ""
            for item in db.execute(f"SELECT i.*, c.name, c.unit, c.recyclable FROM items i JOIN categories c ON c.id=i.category_id WHERE report_id IN ({placeholders}){only} ORDER BY i.id", ids + ([category] if category else [])):
                by_id[item["report_id"]]["items"].append(dict(item))
            for dish in db.execute(f'SELECT * FROM dishes WHERE report_id IN ({placeholders})', ids):
                by_id[dish['report_id']]['dishes'].append(dict(dish))
        return reports

    def save_quick(self, db, user, data):
        # Fast entry: one measurement goes into today's draft record of this employee.
        if user["role"] not in ("operator", "admin"):
            raise APIError("Өлшемді жауапты қызметкер немесе әкімші енгізеді.", 403)
        replay = self.request_replay(db, user, data, 'quick')
        if replay:
            return {'id': replay, 'replayed': True}
        day = local_day().isoformat()
        item = {k: data.get(k) for k in ("category_id", "kg", "route", "stage", "note")}
        if not item["route"]:
            cat = db.execute("SELECT default_route FROM categories WHERE id=?", (int(data.get("category_id") or 0),)).fetchone()
            item["route"] = cat["default_route"] if cat else None
        values, items = self.validate_report(db, user, {"org_id": data.get("org_id") or user["org_id"], "report_date": day, "photo": data.get("photo"), "items": [item]})
        mod_period.ensure_unlocked(db, values["org_id"], day)
        stamp = now()
        record = db.execute("SELECT id FROM reports WHERE org_id=? AND author_id=? AND report_date=? AND status='draft' ORDER BY id DESC LIMIT 1", (values["org_id"], user["id"], day)).fetchone()
        if record and not values["photo"]:
            report_id = record["id"]
            db.execute("UPDATE reports SET updated_at=? WHERE id=?", (stamp, report_id))
        else:
            report_id = db.execute("INSERT INTO reports(org_id,author_id,report_date,status,note,created_at,updated_at) VALUES (?,?,?,?,?,?,?)", (values["org_id"], user["id"], day, "draft", "Жылдам енгізу", stamp, stamp)).lastrowid
            self.history(db, report_id, user, "created", "Жылдам енгізу")
        if values["photo"]:
            db.execute("UPDATE reports SET photo=? WHERE id=?", (values["photo"], report_id))
        self.save_items(db, report_id, items)
        self.remember_request(db, user, data, 'quick', report_id)
        total = db.execute("SELECT ROUND(SUM(i.kg),2) FROM items i JOIN reports r ON r.id=i.report_id WHERE r.org_id=? AND r.report_date=? AND i.category_id=?", (values["org_id"], day, items[0][0])).fetchone()[0]
        return {"id": report_id, "day_total": total, "duplicates": self.content_duplicates(db, report_id)}
