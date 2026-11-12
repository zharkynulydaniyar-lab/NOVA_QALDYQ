"""Qaldyq — campus food waste reporting. Python 3.12+, no packages required."""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import hmac
import io
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import sqlite3
import socket
import time
import threading
from features import migrate, generate_reminders, food_insights, local_day
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent
DEMO_DAY = date(2026, 10, 30)
PASSWORD = "demo2026"
SESSIONS: dict[str, dict] = {}
LOGIN_FAILURES: dict[str, list[float]] = {}
STATUSES = {"draft", "submitted", "in_review", "accepted", "returned"}
UNITS = {"kg": "кг", "l": "л"}
DEMO_DAYS = 91  # 2026-08-01 … 2026-10-30: үш ай

# Ұйымдар мен қалдық түрлері — «АТУ университет кешеніндегі тамақ қалдықтарын есепке алу кестесі» үлгілері бойынша (ТЗ, 3-бөлім).
ORGANIZATIONS = [
    ("1, 2-корпус асхана кешені (ЖК «Искандер»)", "Асхана", "Асхана"),
    ("ATU INN оқу-қонақүй кешені", "Қонақүй", "ATU INN"),
    ("АТУ кофеханасы (ЖК «Canella»)", "Кофехана", "Кофехана"),
    ("ТПП кафедрасы", "Кафедра", "ТПП"),
    ("ТХиПП кафедрасы", "Кафедра", "ТХиПП"),
]
USERS = [
    ("operator@atu.kz", "Демо қызметкер", "operator", 1), ("reviewer@atu.kz", "Демо тексеруші", "reviewer", None),
    ("manager@atu.kz", "Демо басшылық", "manager", None), ("admin@atu.kz", "Жүйе әкімшісі", "admin", None),
    ("inn@atu.kz", "ATU INN жауаптысы", "operator", 2), ("coffee@atu.kz", "Кофехана жауаптысы", "operator", 3),
    ("tpp@atu.kz", "ТПП жауаптысы", "operator", 4), ("thipp@atu.kz", "ТХиПП жауаптысы", "operator", 5),
]
# атауы, өлшем бірлігі, қайта өңдеуге жарамды, әдепкі тәсіл, демо құн ₸/бірлік, демо кг CO₂e/бірлік
WASTE_TYPES = [
    ("Көкөніс тазалағы", "kg", 1, "compost", 150, 0.8),
    ("Ет өнімдерінің кесінділері", "kg", 0, "tbo", 2500, 6.0),
    ("Залдан шыққан тамақ қалдығы", "kg", 0, "tbo", 1800, 2.5),
    ("Сатылмаған өнім қалдығы", "kg", 0, "tbo", 1800, 2.5),
    ("Пайдаланылған май", "l", 1, "recycling", 600, 3.0),
    ("Картон ыдыс", "kg", 1, "recycling", 40, 0.9),
    ("Кофе сығындысы", "kg", 1, "compost", 150, 0.4),
    ("Тамақ қалдығы", "kg", 0, "tbo_bin", 1500, 2.5),
    ("Қаптама қалдығы", "kg", 1, "recycling", 60, 1.5),
    ("Ет сүйегі", "kg", 0, "tbo", 800, 2.0),
    ("Балық сүйегі", "kg", 0, "tbo", 800, 1.5),
    ("Жұмыртқа қабығы", "kg", 1, "compost", 50, 0.3),
    ("Сахароза", "kg", 0, "tbo", 400, 0.6),
    ("ПЭТ-бөтелке 1,0 л (өсімдік майы)", "kg", 1, "recycling", 60, 2.2),
    ("Шыны бөтелке", "kg", 1, "recycling", 30, 0.9),
    ("Нан-тоқаш өнімдері үлгілерінің қалдығы", "kg", 0, "tbo", 700, 1.1),
    ("Кондитерлік өнімдер үлгілерінің қалдығы", "kg", 0, "tbo", 1200, 1.6),
    ("Жеміс-көкөніс қалдығы", "kg", 1, "compost", 550, 0.8),
    ("Алюминий банка", "kg", 1, "recycling", 80, 9.0),
]
_CATERING = ["Көкөніс тазалағы", "Ет өнімдерінің кесінділері", "Залдан шыққан тамақ қалдығы", "Сатылмаған өнім қалдығы", "Пайдаланылған май", "Картон ыдыс"]
ORG_WASTE = {
    1: _CATERING, 2: _CATERING,
    3: ["Кофе сығындысы", "Картон ыдыс", "Тамақ қалдығы"],
    4: ["Қаптама қалдығы", "Ет сүйегі", "Балық сүйегі"],
    5: ["Жұмыртқа қабығы", "Сахароза", "ПЭТ-бөтелке 1,0 л (өсімдік майы)", "Шыны бөтелке", "Нан-тоқаш өнімдері үлгілерінің қалдығы", "Кондитерлік өнімдер үлгілерінің қалдығы", "Жеміс-көкөніс қалдығы", "Алюминий банка"],
}
SESSION_TTL = 8 * 3600


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 180000).hex()


@contextmanager
def connect(db_path):
    db = sqlite3.connect(db_path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize(db_path):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as db:
        db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS organizations(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, kind TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
            role TEXT NOT NULL, org_id INTEGER REFERENCES organizations(id), salt TEXT NOT NULL, password_hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL,
            cost REAL NOT NULL CHECK(cost>=0), co2 REAL NOT NULL CHECK(co2>=0));
        CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL REFERENCES organizations(id),
            author_id INTEGER NOT NULL REFERENCES users(id), report_date TEXT NOT NULL, status TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '', photo TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS items(id INTEGER PRIMARY KEY, report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
            category_id INTEGER NOT NULL REFERENCES categories(id), kg REAL NOT NULL CHECK(kg>0),
            route TEXT NOT NULL, cost REAL NOT NULL CHECK(cost>=0), co2 REAL NOT NULL CHECK(co2>=0));
        CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY, report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id), action TEXT NOT NULL, comment TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS report_period ON reports(report_date, org_id, status);
        """)
        migrate(db)
        if db.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            return
        for name, kind, short in ORGANIZATIONS:
            db.execute("INSERT INTO organizations(name,kind,short) VALUES (?,?,?)", (name, kind, short))
        for email, name, role, org in USERS:
            salt = secrets.token_hex(16)
            db.execute("INSERT INTO users(email,name,role,org_id,salt,password_hash) VALUES (?,?,?,?,?,?)", (email, name, role, org, salt, password_hash(PASSWORD, salt)))
        for name, unit, recyclable, route, cost, co2 in WASTE_TYPES:
            db.execute("INSERT INTO categories(name,unit,recyclable,default_route,cost,co2) VALUES (?,?,?,?,?,?)", (name, unit, recyclable, route, cost, co2))
        cats = {r["name"]: dict(r) for r in db.execute("SELECT * FROM categories")}
        for org, names in ORG_WASTE.items():
            for name in names:
                db.execute("INSERT INTO org_categories(org_id,category_id) VALUES (?,?)", (org, cats[name]["id"]))
        db.execute("INSERT INTO settings VALUES ('factors_note',?)", ("Демо коэффициенттер — команданың жорамалы, дереккөзбен расталмаған. CO₂ және құн мәндері тек есептеу әдісін көрсетуге арналған. Пилотта сатып алу бағаларымен және шекарасы анықталған, дереккөзі көрсетілген эмиссия коэффициенттерімен ауыстырылады.",))
        import random
        rng = random.Random(42)
        authors = {u[3]: i for i, u in enumerate(USERS, 1) if u[2] == "operator"}
        scale = {1: 1.5, 2: 1.0, 3: 0.5, 4: 0.4, 5: 0.3}
        lab_days = {4: (1, 3), 5: (0, 2)}  # кафедралар: зертханалық сабақ күндері
        for offset in range(DEMO_DAYS):
            day = DEMO_DAY - timedelta(days=offset)
            if day.weekday() == 6:
                continue
            for org in range(1, 6):
                if org in lab_days and day.weekday() not in lab_days[org]:
                    continue
                stamp = f"{day.isoformat()}T09:00:00+00:00"
                status = "accepted"
                if offset == 0:
                    status = {1: "draft", 2: "submitted", 3: "in_review"}.get(org, "accepted")
                elif offset == 1 and org in (1, 3):
                    status = "submitted" if org == 1 else "returned"
                author = authors[org]
                report_id = db.execute("INSERT INTO reports(org_id,author_id,report_date,status,note,created_at,updated_at) VALUES (?,?,?,?,?,?,?)", (org, author, day.isoformat(), status, "Демонстрациялық есеп", stamp, stamp)).lastrowid
                names = ORG_WASTE[org]
                selected = [cats[n] for n in rng.sample(names, min(len(names), rng.randint(3, 4)))]
                unusual = next(c for c in selected if c["unit"] == "kg") if offset == 3 and org == 2 else None
                for cat in selected:
                    kg = round(rng.uniform(1.0, 8.0) * scale[org], 1)
                    if cat is unusual:
                        kg = 38.5
                    db.execute("INSERT INTO items(report_id,category_id,kg,route,cost,co2) VALUES (?,?,?,?,?,?)", (report_id, cat["id"], kg, cat["default_route"], cat["cost"], cat["co2"]))
                if org in (1, 2) and offset in (7, 14, 21):
                    served = {7:170, 14:180, 21:160}[offset]
                    db.execute('UPDATE reports SET portions=? WHERE id=?', (served, report_id))
                    dish_kg = round(db.execute('SELECT SUM(kg) FROM items WHERE report_id=?', (report_id,)).fetchone()[0] * .4, 2)
                    db.execute('INSERT INTO dishes(report_id,name,prepared,served,leftover,leftover_kg) VALUES (?,?,?,?,?,?)', (report_id, 'Палау', 200, served, 200-served, dish_kg))
                db.execute("INSERT INTO history(report_id,user_id,action,comment,created_at) VALUES (?,?,'created','Демо дерек',?)", (report_id, author, stamp))
                if status != "draft":
                    db.execute("INSERT INTO history(report_id,user_id,action,comment,created_at) VALUES (?,?,'submitted','',?)", (report_id, author, stamp))
                if status in ("accepted", "returned", "in_review"):
                    db.execute("INSERT INTO history(report_id,user_id,action,comment,created_at) VALUES (?,2,'in_review','',?)", (report_id, stamp))
                if status in ("accepted", "returned"):
                    comment = "Өлшем нәтижесімен салыстырып, массаны нақтылаңыз." if status == "returned" else ""
                    db.execute("INSERT INTO history(report_id,user_id,action,comment,created_at) VALUES (?,2,?,?,?)", (report_id, status, comment, stamp))

class APIError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def number(value, name, minimum=0, maximum=1e8):
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise APIError(f"{name}: сан енгізіңіз.")
    if not minimum <= result <= maximum:
        raise APIError(f"{name}: мән {minimum}–{maximum} аралығында болуы керек.")
    return result


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "static"), **kwargs)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        super().end_headers()

    def respond(self, payload, status=200, headers=None):
        db = getattr(self, "_active_db", None)
        if db is not None and db.in_transaction:
            # A successful HTTP response must never precede durable persistence.
            db.commit()
        raw = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    def session(self):
        from http.cookies import SimpleCookie
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            token = cookie["qaldyq_session"].value if "qaldyq_session" in cookie else ""
        except Exception:
            token = ""
        session = SESSIONS.get(token)
        if not session or session["expires"] < time.time():
            SESSIONS.pop(token, None)
            raise APIError("Жүйеге кіріңіз.", 401)
        return token, session

    def body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            raise APIError("JSON объектісі қажет.")
        if length > 3_000_000:
            raise APIError("Файл тым үлкен. Фото 2 МБ-тан аспасын.", 413)
        try:
            data = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError):
            raise APIError("JSON пішімі дұрыс емес.")
        if not isinstance(data, dict):
            raise APIError("JSON объектісі қажет.")
        return data

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.api("GET", parsed)
        elif parsed.path in ("/", "/index.html", "/app.js", "/i18n.js", "/i18n.css", "/features.js", "/features.css", "/offline-store.js", "/sw.js", "/vendor/qrcode.js", "/vendor/QRCODE-LICENSE.txt", "/styles.css", "/studio.css", "/animations.js", "/animations.css", "/vendor/three.module.js", "/vendor/three.core.js", "/vendor/THREE-LICENSE.txt", "/favicon.svg", "/campus-3d-v2.png", "/cycle-3d-v2.png"):
            super().do_GET()
        else:
            self.send_error(404)

    def do_POST(self):
        self.api("POST", urlparse(self.path))

    def do_PUT(self):
        self.api("PUT", urlparse(self.path))

    def api(self, method, parsed):
        try:
            with connect(self.server.db_path) as db:
                self._active_db = db
                try:
                    self.dispatch(db, method, parsed)
                finally:
                    self._active_db = None
        except APIError as error:
            self.respond({"error": error.message}, error.status)
        except sqlite3.IntegrityError:
            self.respond({"error": "Мұндай атау бар немесе дерек байланысы дұрыс емес."}, 409)
        except (ValueError, TypeError, KeyError):
            self.respond({"error": "Сұрау параметрлері дұрыс емес."}, 400)
        except Exception:
            import traceback
            traceback.print_exc()
            self.respond({"error": "Сервер қатесі. Қайта көріңіз."}, 500)

    def dispatch(self, db, method, parsed):
        path, query = parsed.path, parse_qs(parsed.query)
        if path == "/api/health" and method == "GET":
            return self.respond({"ok": True})
        if path == "/api/login" and method == "POST":
            data = self.body()
            ip = self.client_address[0]
            failures = [t for t in LOGIN_FAILURES.get(ip, []) if t > time.time() - 60]
            if len(failures) >= 15:
                raise APIError("Бір минуттан кейін қайта көріңіз.", 429)
            user = db.execute("SELECT * FROM users WHERE email=?", (str(data.get("email", "")).lower().strip(),)).fetchone()
            if not user or not hmac.compare_digest(user["password_hash"], password_hash(str(data.get("password", "")), user["salt"])):
                LOGIN_FAILURES[ip] = failures + [time.time()]
                raise APIError("Email немесе құпиясөз қате.", 401)
            LOGIN_FAILURES.pop(ip, None)
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
            SESSIONS[token] = {"user_id": user["id"], "csrf": csrf, "expires": time.time() + SESSION_TTL}
            return self.respond({"ok": True}, headers={"Set-Cookie": f"qaldyq_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_TTL}"})
        token, session = self.session()
        user = dict(db.execute("SELECT id,email,name,role,org_id FROM users WHERE id=?", (session["user_id"],)).fetchone())
        if method != "GET":
            if not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), session["csrf"]):
                raise APIError("Сессияны жаңартып, қайта көріңіз.", 403)
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).netloc != self.headers.get("Host"):
                raise APIError("Сұрау көзіне рұқсат жоқ.", 403)
            # Serialize state transitions so two reviewers cannot overwrite each other.
            db.execute("BEGIN IMMEDIATE")
        if path == "/api/logout" and method == "POST":
            SESSIONS.pop(token, None)
            return self.respond({"ok": True}, headers={"Set-Cookie": "qaldyq_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})
        if path == "/api/bootstrap" and method == "GET":
            return self.respond({"user": user, "csrf": session["csrf"], "organizations": [dict(r) for r in db.execute("SELECT * FROM organizations ORDER BY id")], "categories": [dict(r) for r in db.execute("SELECT * FROM categories ORDER BY id")], "org_categories": self.org_categories(db), "routes": [dict(r) for r in db.execute("SELECT code,name,diverted FROM routes ORDER BY position,code")], "factors_note": db.execute("SELECT value FROM settings WHERE key='factors_note'").fetchone()[0], "demo_date": DEMO_DAY.isoformat(), "today": local_day().isoformat()})
        if path == "/api/totals" and method == "GET":
            org = user["org_id"] if user["role"] == "operator" else int(query.get("org", [0])[0])
            day = date.fromisoformat(query.get("date", [local_day().isoformat()])[0]).isoformat()
            exclude = int(query.get("exclude", [0])[0])
            rows = db.execute("""SELECT c.id AS category_id,c.name,c.unit,
                ROUND(SUM(CASE WHEN r.report_date=? THEN i.kg ELSE 0 END),2) AS day,ROUND(SUM(i.kg),2) AS month
                FROM items i JOIN reports r ON r.id=i.report_id JOIN categories c ON c.id=i.category_id
                WHERE r.org_id=? AND substr(r.report_date,1,7)=? AND r.id!=? GROUP BY c.id ORDER BY c.id""", (day, org, day[:7], exclude)).fetchall()
            same_day = db.execute("SELECT COUNT(*) FROM reports WHERE org_id=? AND report_date=? AND id!=?", (org, day, exclude)).fetchone()[0]
            return self.respond({"date": day, "totals": [dict(r) for r in rows], "same_day_reports": same_day})
        if path == "/api/food-insights" and method == "GET":
            target = date.fromisoformat(query.get('target', [(local_day()+timedelta(days=1)).isoformat()])[0])
            if not date(2020,1,1) <= target <= date(2100,12,31):
                raise APIError('Жоспарлау күні 2020–2100 жыл аралығында болсын.')
            planning_query = {**query, 'start': [(target-timedelta(days=56)).isoformat()], 'end': [(target-timedelta(days=1)).isoformat()]}
            return self.respond(food_insights(self.list_reports(db, user, query), target, self.list_reports(db, user, planning_query)))
        if path == "/api/notifications" and method == "GET":
            generate_reminders(db)
            return self.respond({"notifications": [dict(r) for r in db.execute('SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 100', (user['id'],))], "deadline_day": int(db.execute("SELECT value FROM settings WHERE key='deadline_day'").fetchone()[0])})
        if path == "/api/notifications/read" and method == "POST":
            data = self.body()
            db.execute('UPDATE notifications SET read_at=? WHERE id=? AND user_id=?', (now(), int(data.get('id', 0)), user['id']))
            return self.respond({'ok': True})
        if path == "/api/reminder-settings" and method == "POST":
            if user['role'] != 'admin':
                raise APIError('Әкімші құқығы қажет.', 403)
            day = number(self.body().get('deadline_day'), 'Мерзім күні', 1, 28)
            if not day.is_integer():
                raise APIError('Күн бүтін сан болсын.')
            db.execute("UPDATE settings SET value=? WHERE key='deadline_day'", (str(int(day)),))
            generate_reminders(db)
            return self.respond({'ok': True})
        if path in ("/api/reports", "/api/export") and method == "GET":
            reports = self.list_reports(db, user, query)
            if path == "/api/export":
                return self.export(db, [r for r in reports if r["status"] == "accepted"], query.get("format", ["csv"])[0])
            return self.respond({"reports": reports})
        if path == "/api/reports" and method == "POST":
            if user["role"] not in ("operator", "admin"):
                raise APIError("Есепті жауапты қызметкер немесе әкімші жасайды.", 403)
            data = self.body()
            replay = self.request_replay(db, user, data, 'create')
            if replay:
                return self.respond({'id': replay, 'replayed': True}, 201)
            values, items = self.validate_report(db, user, data)
            stamp = now()
            status = 'submitted' if data.get('submit') is True else 'draft'
            report_id = db.execute("INSERT INTO reports(org_id,author_id,report_date,status,note,photo,created_at,updated_at,portions) VALUES (?,?,?,?,?,?,?,?,?)", (values["org_id"], user["id"], values["report_date"], status, values["note"], values["photo"], stamp, stamp, values['portions'])).lastrowid
            self.save_items(db, report_id, items)
            self.save_dishes(db, report_id, values['dishes'])
            self.history(db, report_id, user, "created", "Есеп жасалды")
            if status == 'submitted':
                self.history(db, report_id, user, 'submitted', 'Мобильді есеп жіберілді')
                generate_reminders(db)
            self.remember_request(db, user, data, 'create', report_id)
            return self.respond({"id": report_id}, 201)
        match = re.fullmatch(r"/api/reports/(\d+)(?:/(transition))?", path)
        if match:
            report_id = int(match[1])
            report = db.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
            if not report:
                raise APIError("Есеп табылмады.", 404)
            if user["role"] == "operator" and report["org_id"] != user["org_id"]:
                raise APIError("Бұл ұйымның есебіне рұқсат жоқ.", 403)
            if method == "GET" and not match[2]:
                detail = dict(report)
                detail["items"] = [dict(r) for r in db.execute("SELECT i.*, c.name, c.unit, c.recyclable FROM items i JOIN categories c ON c.id=i.category_id WHERE report_id=?", (report_id,))]
                detail["history"] = [dict(r) for r in db.execute("SELECT h.*,u.name FROM history h JOIN users u ON u.id=h.user_id WHERE report_id=? ORDER BY h.id", (report_id,))]
                detail['dishes'] = [dict(r) for r in db.execute('SELECT * FROM dishes WHERE report_id=? ORDER BY id', (report_id,))]
                return self.respond(detail)
            if method == "PUT" and not match[2]:
                if user["role"] not in ("operator", "admin"):
                    raise APIError("Тек черновик пен қайтарылған есепті өңдеуге болады.", 403)
                data = self.body()
                if self.request_replay(db, user, data, f'edit:{report_id}'):
                    return self.respond({'ok': True, 'replayed': True})
                if report['status'] not in ('draft','returned'):
                    raise APIError("Тек черновик пен қайтарылған есепті өңдеуге болады.", 403)
                self.check_version(data, report)
                values, items = self.validate_report(db, user, data)
                if values["org_id"] != report["org_id"]:
                    raise APIError("Есептің ұйымын өзгертуге болмайды.")
                db.execute("UPDATE reports SET report_date=?,note=?,photo=?,updated_at=?,portions=? WHERE id=?", (values["report_date"], values["note"], values["photo"], now(), values['portions'], report_id))
                db.execute("DELETE FROM items WHERE report_id=?", (report_id,))
                self.save_items(db, report_id, items)
                db.execute('DELETE FROM dishes WHERE report_id=?', (report_id,))
                self.save_dishes(db, report_id, values['dishes'])
                self.history(db, report_id, user, "edited", "Есеп жаңартылды")
                self.remember_request(db, user, data, f'edit:{report_id}', report_id)
                return self.respond({"ok": True})
            if method == "POST" and match[2]:
                data = self.body()
                self.check_version(data, report)
                target = data.get("status")
                allowed = False
                if target == "submitted":
                    allowed = user["role"] in ("operator", "admin") and report["status"] in ("draft", "returned")
                elif target == "in_review":
                    allowed = user["role"] in ("reviewer", "admin") and report["status"] == "submitted"
                elif target in ("accepted", "returned"):
                    allowed = user["role"] in ("reviewer", "admin") and report["status"] == "in_review"
                if not allowed:
                    raise APIError("Бұл мәртебеге ауыстыруға рұқсат жоқ.", 403)
                comment = str(data.get("comment", "")).strip()[:2000]
                if target == "returned" and not comment:
                    raise APIError("Қайтару себебін жазыңыз.")
                db.execute("UPDATE reports SET status=?,updated_at=? WHERE id=?", (target, now(), report_id))
                self.history(db, report_id, user, target, comment)
                generate_reminders(db)
                return self.respond({"ok": True})
        if path == "/api/organizations" and method == "POST":
            if user["role"] != "admin":
                raise APIError("Әкімші құқығы қажет.", 403)
            data = self.body()
            name = str(data.get("name", "")).strip()
            if len(name) < 2 or len(name) > 120:
                raise APIError("Атау 2–120 таңба болсын.")
            kind = str(data.get("kind", "Бөлімше")).strip()[:80] or "Бөлімше"
            short = str(data.get("short", "")).strip()[:12] or name[:12]
            org_id = db.execute("INSERT INTO organizations(name,kind,short) VALUES (?,?,?)", (name, kind, short)).lastrowid
            # Жаңа ұйым сол типтегі ұйымның қалдық тізімінен бастайды; тізім формада толықтырылады.
            db.execute("INSERT OR IGNORE INTO org_categories SELECT ?,category_id FROM org_categories WHERE org_id=(SELECT id FROM organizations WHERE kind=? AND id!=? ORDER BY id LIMIT 1)", (org_id, kind, org_id))
            return self.respond({"ok": True, "id": org_id}, 201)
        if path == "/api/categories" and method == "POST":
            if user["role"] not in ("operator", "reviewer", "admin"):
                raise APIError("Қалдық түрін жауапты қызметкер, тексеруші немесе әкімші қосады.", 403)
            data = self.body()
            name = " ".join(str(data.get("name", "")).split())
            if len(name) < 2 or len(name) > 120:
                raise APIError("Атау 2–120 таңба болсын.")
            org_id = user["org_id"] if user["role"] == "operator" else int(data.get("org_id") or 0)
            if org_id and not db.execute("SELECT 1 FROM organizations WHERE id=?", (org_id,)).fetchone():
                raise APIError("Ұйымды таңдаңыз.")
            existing = next((r for r in db.execute("SELECT id,name FROM categories") if r["name"].casefold() == name.casefold()), None)
            if existing:
                if not org_id or db.execute("SELECT 1 FROM org_categories WHERE org_id=? AND category_id=?", (org_id, existing["id"])).fetchone():
                    raise APIError("Бұл қалдық түрі тізімде бар.", 409)
                category_id = existing["id"]
            else:
                unit = data.get("unit", "kg")
                route = data.get("default_route", "tbo")
                if unit not in UNITS or not isinstance(route, str) or not db.execute("SELECT 1 FROM routes WHERE code=?", (route,)).fetchone():
                    raise APIError("Өлшем бірлігі мен кәдеге жарату тәсілін таңдаңыз.")
                # Коэффициенттерді тек әкімші мен тексеруші береді; қызметкер қосқан түрдің бағасы кейін толтырылады.
                priced = user["role"] != "operator"
                cost = number(data.get("cost") or 0, "Құн") if priced else 0
                co2 = number(data.get("co2") or 0, "CO₂", maximum=1000) if priced else 0
                category_id = db.execute("INSERT INTO categories(name,unit,recyclable,default_route,cost,co2) VALUES (?,?,?,?,?,?)", (name, unit, 1 if data.get("recyclable") in (True, 1, "1") else 0, route, cost, co2)).lastrowid
            if org_id:
                db.execute("INSERT OR IGNORE INTO org_categories(org_id,category_id) VALUES (?,?)", (org_id, category_id))
            else:
                db.execute("INSERT OR IGNORE INTO org_categories SELECT id,? FROM organizations", (category_id,))
            return self.respond({"ok": True, "id": category_id}, 201)
        raise APIError("Мұндай әрекет табылмады.", 404)

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

    def validate_report(self, db, user, data):
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
        if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= 30:
            raise APIError("Кемінде бір қалдық жолы қажет, ең көбі — 30.")
        items = []
        routes = {r["code"] for r in db.execute("SELECT code FROM routes")}
        for raw in raw_items:
            if not isinstance(raw, dict):
                raise APIError("Қалдық жолы дұрыс емес.")
            cat = db.execute("SELECT c.* FROM categories c JOIN org_categories oc ON oc.category_id=c.id WHERE c.id=? AND oc.org_id=?", (int(raw.get("category_id", 0)), org_id)).fetchone()
            if not cat or raw.get("route") not in routes:
                raise APIError("Қалдық түрі мен кәдеге жарату тәсілін ұйым тізімінен таңдаңыз.")
            items.append((cat["id"], number(raw.get("kg"), "Масса", 0.01, 10000), raw["route"], cat["cost"], cat["co2"]))
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
        db.executemany("INSERT INTO items(report_id,category_id,kg,route,cost,co2) VALUES (?,?,?,?,?,?)", [(report_id, *item) for item in items])

    def history(self, db, report_id, user, action, comment):
        db.execute("INSERT INTO history(report_id,user_id,action,comment,created_at) VALUES (?,?,?,?,?)", (report_id, user["id"], action, comment, now()))

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

    def export(self, db, reports, fmt):
        """Тек қабылданған жазбалар: тізілім (қолданыстағы кесте бағандары) және ұйым × қалдық түрі жиынтығы."""
        route_names = {r["code"]: r["name"] for r in db.execute("SELECT code,name FROM routes")}
        headers = ["ID", "Күні", "Ұйым", "Қалдық түрі", "Саны", "Өлшем бірлігі", "Кәдеге жарату тәсілі", "Жауапты тұлға", "Құн бағасы, ₸", "CO2 бағасы, кг", "Ескерту"]
        rows = [[r["id"], r["report_date"], r["org_name"], i["name"], i["kg"], UNITS.get(i["unit"], i["unit"]), route_names.get(i["route"], i["route"]), r["author"], round(i["kg"]*i["cost"],2), round(i["kg"]*i["co2"],2), r["note"]] for r in reports for i in r["items"]]
        summary = {}
        for r in reports:
            for i in r["items"]:
                key = (r["org_name"], i["name"], UNITS.get(i["unit"], i["unit"]))
                entry = summary.setdefault(key, [0, 0])
                entry[0] += i["kg"]
                entry[1] += 1
        summary_headers = ["Ұйым", "Қалдық түрі", "Өлшем бірлігі", "Саны", "Жазба саны"]
        summary_rows = [[org, name, unit, round(total, 2), count] for (org, name, unit), (total, count) in sorted(summary.items())]
        def safe(value):
            text = str(value)
            return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text
        if fmt == "xls":
            def sheet(title, table):
                cells = []
                for row in table:
                    cells.append("<Row>" + "".join(f'<Cell><Data ss:Type="{"Number" if isinstance(v,(int,float)) else "String"}">{escape(str(v) if isinstance(v,(int,float)) else safe(v))}</Data></Cell>' for v in row) + "</Row>")
                return f'<Worksheet ss:Name="{title}"><Table>' + "".join(cells) + "</Table></Worksheet>"
            body = ('<?xml version="1.0" encoding="UTF-8"?><Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">' + sheet("Жиынтық", [summary_headers] + summary_rows) + sheet("Тізілім", [headers] + rows) + "</Workbook>").encode()
            mime, extension = "application/vnd.ms-excel", "xls"
        elif fmt in ("csv", "summary"):
            output = io.StringIO()
            writer = csv.writer(output)
            table = [summary_headers] + summary_rows if fmt == "summary" else [headers] + rows
            writer.writerow(table[0])
            writer.writerows([[safe(v) for v in row] for row in table[1:]])
            body = ("\ufeff" + output.getvalue()).encode()
            mime, extension = "text/csv; charset=utf-8", "csv"
        else:
            raise APIError("Экспорт пішімі CSV немесе XLS болсын.")
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Disposition", f'attachment; filename="qaldyq-reports.{extension}"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def server_close(self):
        if hasattr(self, 'reminder_stop'):
            self.reminder_stop.set()
            self.reminder_thread.join(timeout=2)
        super().server_close()


def create_server(host="127.0.0.1", port=8765, db_path=None):
    # A new file name per data model: the pre-5.4 database (other organizations and waste types)
    # is left untouched on disk and is simply no longer opened.
    db_path = str(db_path or ROOT / "data" / "qaldyq-v5.4.sqlite3")
    initialize(db_path)
    server = LocalServer((host, port), Handler)
    server.db_path = db_path
    server.reminder_stop = threading.Event()
    def reminder_loop():
        while not server.reminder_stop.is_set():
            try:
                with connect(db_path) as db:
                    generate_reminders(db)
            except sqlite3.Error:
                import traceback
                traceback.print_exc()
            server.reminder_stop.wait(60)
    server.reminder_thread = threading.Thread(target=reminder_loop, daemon=True)
    server.reminder_thread.start()
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Qaldyq campus waste platform")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", default=None)
    args = parser.parse_args()
    server = create_server(args.host, args.port, args.db)
    print(f"Qaldyq: http://{args.host}:{server.server_port}", flush=True)
    print("Demo accounts: operator@atu.kz / reviewer@atu.kz / manager@atu.kz / admin@atu.kz (+ inn@, coffee@, tpp@, thipp@)", flush=True)
    print(f"Demo password: {PASSWORD}. Synthetic data only. Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
