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
from common import APIError, now, number, can_review, STAGES, UNITS
import mod_admin
import mod_period

import mod_student
import mod_kitchen
import mod_actions
import mod_forecast
import mod_demo
from report_domain import ReportDomain
import telegram_service

MODULES = [telegram_service, mod_admin, mod_period, mod_student, mod_kitchen, mod_actions, mod_forecast, mod_demo]
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
DEMO_DAYS = 91  # 2026-08-01 … 2026-10-30: үш ай

# Ұйымдар мен қалдық түрлері — «АТУ университет кешеніндегі тамақ қалдықтарын есепке алу кестесі» үлгілері бойынша (ТЗ, 3-бөлім).
ORGANIZATIONS = [  # атауы, түрі, қысқа атауы, орысша атауы, мекенжайы, жұмыс уақыты, студенттерге ашық, сипаттама
    ("1, 2-корпус асхана кешені (ЖК «Искандер»)", "Асхана", "Асхана", "Столовый комплекс корп. 1, 2 (ИП «Искандер»)", "1-корпус, 1-қабат (демо мекенжай)", "Дс–Сб 09:00–17:00", 1, "Түскі ас және ыстық тағам"),
    ("ATU INN оқу-қонақүй кешені", "Қонақүй", "ATU INN", "Учебно-гостиничный комплекс ATU INN", "ATU INN ғимараты (демо мекенжай)", "Күн сайын 08:00–20:00", 1, "Оқу-қонақүй кешенінің мейрамханасы"),
    ("АТУ кофеханасы (ЖК «Canella»)", "Кофехана", "Кофехана", "Кофейня АТУ (ИП «Canella»)", "Бас корпус, фойе (демо мекенжай)", "Дс–Сб 08:30–18:00", 1, "Кофе, сусындар және тәттілер"),
    ("ТПП кафедрасы", "Кафедра", "ТПП", "Кафедра ТПП", "Оқу зертханасы (демо мекенжай)", "", 0, "Оқу зертханасы: зертханалық сабақ күндері"),
    ("ТХиПП кафедрасы", "Кафедра", "ТХиПП", "Кафедра ТХиПП", "Оқу зертханасы (демо мекенжай)", "", 0, "Оқу зертханасы: зертханалық сабақ күндері"),
]
USERS = [
    ("operator@atu.kz", "Демо қызметкер", "operator", 1), ("reviewer@atu.kz", "Демо тексеруші", "reviewer", None),
    ("manager@atu.kz", "Демо басшылық", "manager", None), ("admin@atu.kz", "Жүйе әкімшісі", "admin", None),
    ("inn@atu.kz", "ATU INN жауаптысы", "operator", 2), ("coffee@atu.kz", "Кофехана жауаптысы", "operator", 3),
    ("tpp@atu.kz", "ТПП жауаптысы", "operator", 4), ("thipp@atu.kz", "ТХиПП жауаптысы", "operator", 5),
    ("student@atu.kz", "Демо студент", "student", None),
]
FACTOR_SOURCE = "Команданың жорамалы (демо); дереккөзбен расталмаған"
FACTOR_BOUNDARY = "Шекара анықталмаған — пилотта тіркеледі"
# атауы, өлшем бірлігі, қайта өңдеуге жарамды, әдепкі тәсіл, демо құн ₸/бірлік, демо кг CO₂e/бірлік, орысша атауы
WASTE_TYPES = [
    ("Көкөніс тазалағы", "kg", 1, "compost", 150, 0.8, "Очистки овощей"),
    ("Ет өнімдерінің кесінділері", "kg", 0, "tbo", 2500, 6.0, "Обрезки мясопродуктов"),
    ("Залдан шыққан тамақ қалдығы", "kg", 0, "tbo", 1800, 2.5, "Пищевые отходы из зала"),
    ("Сатылмаған өнім қалдығы", "kg", 0, "tbo", 1800, 2.5, "Остатки нереализованной продукции"),
    ("Пайдаланылған май", "l", 1, "recycling", 600, 3.0, "Отработанное масло"),
    ("Картон ыдыс", "kg", 1, "recycling", 40, 0.9, "Картонная тара"),
    ("Кофе сығындысы", "kg", 1, "compost", 150, 0.4, "Кофейный жмых"),
    ("Тамақ қалдығы", "kg", 0, "tbo_bin", 1500, 2.5, "Остатки еды"),
    ("Қаптама қалдығы", "kg", 1, "recycling", 60, 1.5, "Упаковочные отходы"),
    ("Ет сүйегі", "kg", 0, "tbo", 800, 2.0, "Мясные кости"),
    ("Балық сүйегі", "kg", 0, "tbo", 800, 1.5, "Рыбные кости"),
    ("Жұмыртқа қабығы", "kg", 1, "compost", 50, 0.3, "Яичная скорлупа"),
    ("Сахароза", "kg", 0, "tbo", 400, 0.6, "Сахароза"),
    ("ПЭТ-бөтелке 1,0 л (өсімдік майы)", "kg", 1, "recycling", 60, 2.2, "ПЭТ-бутылка 1,0 л (растительное масло)"),
    ("Шыны бөтелке", "kg", 1, "recycling", 30, 0.9, "Стеклобутылка"),
    ("Нан-тоқаш өнімдері үлгілерінің қалдығы", "kg", 0, "tbo", 700, 1.1, "Отходы образцов хлебобулочных изделий"),
    ("Кондитерлік өнімдер үлгілерінің қалдығы", "kg", 0, "tbo", 1200, 1.6, "Отходы образцов кондитерских изделий"),
    ("Жеміс-көкөніс қалдығы", "kg", 1, "compost", 550, 0.8, "Отходы фруктов и овощей"),
    ("Алюминий банка", "kg", 1, "recycling", 80, 9.0, "Алюминиевые банки"),
]
STAGE_OF = {"Көкөніс тазалағы": "prep", "Ет өнімдерінің кесінділері": "prep", "Залдан шыққан тамақ қалдығы": "plate", "Сатылмаған өнім қалдығы": "unsold", "Тамақ қалдығы": "plate", "Кофе сығындысы": "prep"}
_CATERING = ["Көкөніс тазалағы", "Ет өнімдерінің кесінділері", "Залдан шыққан тамақ қалдығы", "Сатылмаған өнім қалдығы", "Пайдаланылған май", "Картон ыдыс"]
ORG_WASTE = {
    1: _CATERING, 2: _CATERING,
    3: ["Кофе сығындысы", "Картон ыдыс", "Тамақ қалдығы"],
    4: ["Қаптама қалдығы", "Ет сүйегі", "Балық сүйегі"],
    5: ["Жұмыртқа қабығы", "Сахароза", "ПЭТ-бөтелке 1,0 л (өсімдік майы)", "Шыны бөтелке", "Нан-тоқаш өнімдері үлгілерінің қалдығы", "Кондитерлік өнімдер үлгілерінің қалдығы", "Жеміс-көкөніс қалдығы", "Алюминий банка"],
}
SESSION_TTL = 8 * 3600


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
        for module in MODULES:
            if hasattr(module, "migrate"):
                module.migrate(db)
        if db.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            return
        for name, kind, short, name_ru, address, hours, is_public, description in ORGANIZATIONS:
            db.execute("INSERT INTO organizations(name,kind,short,name_ru,address,hours,is_public,description) VALUES (?,?,?,?,?,?,?,?)", (name, kind, short, name_ru, address, hours, is_public, description))
        for email, name, role, org in USERS:
            mod_admin.create_user(db, email, name, role, org, PASSWORD, 1 if role == "admin" else 0, is_demo=1)
        for name, unit, recyclable, route, cost, co2, name_ru in WASTE_TYPES:
            db.execute("INSERT INTO categories(name,unit,recyclable,default_route,cost,co2,name_ru,source,boundary) VALUES (?,?,?,?,?,?,?,?,?)", (name, unit, recyclable, route, cost, co2, name_ru, FACTOR_SOURCE, FACTOR_BOUNDARY))
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
                    db.execute("INSERT INTO items(report_id,category_id,kg,route,cost,co2,stage) VALUES (?,?,?,?,?,?,?)", (report_id, cat["id"], kg, cat["default_route"], cat["cost"], cat["co2"], STAGE_OF.get(cat["name"], "other")))
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
        for module in MODULES:
            if hasattr(module, "seed"):
                module.seed(db)

def static_paths():
    """Everything under static/ is a public asset; nothing outside it is ever served."""
    base = ROOT / "static"
    paths = {"/"}
    for file in base.rglob("*"):
        if file.is_file():
            relative = "/" + file.relative_to(base).as_posix()
            paths.add(relative)
            if file.name == "index.html":
                paths.add(relative[:-len("index.html")])
    return paths


STATIC_PATHS = static_paths()


class Handler(ReportDomain, SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "static"), **kwargs)

    def log_message(self, format, *args):
        # Query strings can carry pickup codes and filters; keep them out of the access log.
        super().log_message(format, *[re.sub(r"\?[^ \"]*", "", a) if isinstance(a, str) else a for a in args])

    def start_session(self, user_id):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        SESSIONS[token] = {"user_id": user_id, "csrf": csrf, "expires": time.time() + SESSION_TTL}
        secure = '; Secure' if urlparse(self.server.telegram_config.app_url).scheme=='https' else ''
        return {"Set-Cookie": f"qaldyq_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_TTL}{secure}"}

    def drop_sessions(self, user_id):
        for token in [t for t, value in SESSIONS.items() if value["user_id"] == user_id]:
            SESSIONS.pop(token, None)

    def check_origin(self):
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            raise APIError("Сұрау көзіне рұқсат жоқ.", 403)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        mini_page = urlparse(self.path).path in ('/student/','/student/index.html')
        if not mini_page:
            self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        script_sources = "'self' https://telegram.org" if mini_page else "'self'"
        ancestors = 'https://web.telegram.org https://*.telegram.org' if mini_page else "'none'"
        self.send_header("Content-Security-Policy", f"default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src {script_sources}; connect-src 'self'; frame-ancestors {ancestors}; base-uri 'self'; form-action 'self'")
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
        elif parsed.path in STATIC_PATHS:
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
            cfg = self.server.telegram_config
            return self.respond({"ok": True, "service":"qaldyq", "app_url":cfg.app_url,
                "telegram_ready":bool(cfg.token and urlparse(cfg.app_url).scheme=='https')})
        if path == '/api/telegram/webhook' and method == 'POST':
            telegram_service.check_webhook(self.headers,self.server.telegram_config)
            data = self.body()
            db.execute('BEGIN IMMEDIATE')
            telegram_service.ingest(db,data)
            return self.respond({'ok':True})
        if path == '/api/public/telegram' and method == 'GET':
            return self.respond(telegram_service.public_config(db,self.server.telegram_config))
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
            if not user["active"]:
                raise APIError("Аккаунт өшірілген. Әкімшіге хабарласыңыз.", 403)
            LOGIN_FAILURES.pop(ip, None)
            return self.respond({"ok": True, "role": user["role"]}, headers=self.start_session(user["id"]))
        if path.startswith("/api/public/") or path == "/api/register":
            if method != "GET":
                self.check_origin()
                db.execute("BEGIN IMMEDIATE")
            for module in MODULES:
                if hasattr(module, "public") and module.public(self, db, method, path, query):
                    return
            raise APIError("Мұндай әрекет табылмады.", 404)
        mini = self.headers.get('Authorization','').startswith('tma ')
        if mini:
            if not path.startswith('/api/student/') and path != '/api/me':
                raise APIError('Mini App: только студенческий API.',403)
            tid = telegram_service.validate_init_data(self.headers['Authorization'][4:],self.server.telegram_config)
            linked = telegram_service.linked_user(db,tid)
            token, session = None, {'user_id':linked['id'],'csrf':''}
        else:
            token, session = self.session()
        row = db.execute("SELECT id,email,name,role,org_id,active,can_review FROM users WHERE id=?", (session["user_id"],)).fetchone()
        if not row or not row["active"]:
            SESSIONS.pop(token, None)
            raise APIError("Жүйеге кіріңіз.", 401)
        user = dict(row)
        self.current_session = session
        if method != "GET" and not mini:
            if not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), session["csrf"]):
                raise APIError("Сессияны жаңартып, қайта көріңіз.", 403)
            self.check_origin()
            # Serialize state transitions so two reviewers cannot overwrite each other.
            db.execute("BEGIN IMMEDIATE")
        elif mini and method != 'GET':
            db.execute('BEGIN IMMEDIATE')
        # Students reach only their own area; every staff endpoint is closed to them by default.
        if user["role"] == "student" and not path.startswith("/api/student/") and path not in ("/api/logout", "/api/me") and not path.startswith("/api/telegram/"):
            raise APIError("Бұл бөлім қызметкерлерге арналған.", 403)
        if path == "/api/logout" and method == "POST":
            SESSIONS.pop(token, None)
            return self.respond({"ok": True}, headers={"Set-Cookie": "qaldyq_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})
        if mini and path == '/api/me' and method == 'GET':
            import telegram_students
            return self.respond({'user':user,'csrf':'','preferences':telegram_students.preferences(db,user['id'])})
        if path == "/api/bootstrap" and method == "GET":
            return self.respond({"telegram": telegram_service.public_config(db,self.server.telegram_config), "user": user, "csrf": session["csrf"], "organizations": mod_admin.organizations(db), "stages": list(STAGES), "categories": [dict(r) for r in db.execute("SELECT * FROM categories ORDER BY id")], "org_categories": self.org_categories(db), "routes": [dict(r) for r in db.execute("SELECT code,name,diverted FROM routes ORDER BY position,code")], "factors_note": db.execute("SELECT value FROM settings WHERE key='factors_note'").fetchone()[0], "demo_date": DEMO_DAY.isoformat(), "today": local_day().isoformat()})
        for module in MODULES:
            if hasattr(module, "handle") and module.handle(self, db, user, method, path, query):
                return
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
            mod_period.ensure_unlocked(db, values["org_id"], values["report_date"])
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
            return self.respond({"id": report_id, "duplicates": self.content_duplicates(db, report_id)}, 201)
        if path == "/api/quick" and method == "POST":
            return self.respond(self.save_quick(db, user, self.body()), 201)
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
                detail["items"] = [dict(r) for r in db.execute("SELECT i.*, c.name, c.unit, c.recyclable, EXISTS(SELECT 1 FROM stock_moves m WHERE m.waste_item_id=i.id) AS locked FROM items i JOIN categories c ON c.id=i.category_id WHERE report_id=?", (report_id,))]
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
                # Measurements created by a stock write-off stay as they are: the stock move points at them.
                linked = {r[0] for r in db.execute("SELECT waste_item_id FROM stock_moves WHERE waste_item_id IN (SELECT id FROM items WHERE report_id=?)", (report_id,))}
                if linked and isinstance(data.get("items"), list):
                    data = {**data, "items": [i for i in data["items"] if not (isinstance(i, dict) and i.get("id") in linked)]}
                values, items = self.validate_report(db, user, data, minimum_items=0 if linked else 1)
                if values["org_id"] != report["org_id"]:
                    raise APIError("Есептің ұйымын өзгертуге болмайды.")
                mod_period.ensure_unlocked(db, report["org_id"], report["report_date"])
                mod_period.ensure_unlocked(db, report["org_id"], values["report_date"])
                db.execute("UPDATE reports SET report_date=?,note=?,photo=?,updated_at=?,portions=? WHERE id=?", (values["report_date"], values["note"], values["photo"], now(), values['portions'], report_id))
                db.execute(f"DELETE FROM items WHERE report_id=? AND id NOT IN ({','.join('?' for _ in linked) or 'NULL'})", (report_id, *linked))
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
                    allowed = can_review(user) and report["status"] == "submitted"
                elif target in ("accepted", "returned"):
                    allowed = can_review(user) and report["status"] == "in_review"
                if not allowed:
                    raise APIError("Бұл мәртебеге ауыстыруға рұқсат жоқ.", 403)
                # Records inside a submitted period report move only together with that report.
                mod_period.ensure_unlocked(db, report["org_id"], report["report_date"])
                comment = str(data.get("comment", "")).strip()[:2000]
                if target == "returned" and not comment:
                    raise APIError("Қайтару себебін жазыңыз.")
                db.execute("UPDATE reports SET status=?,updated_at=? WHERE id=?", (target, now(), report_id))
                self.history(db, report_id, user, target, comment, report["status"])
                if target == 'returned':
                    event_id = db.execute('SELECT MAX(id) FROM history WHERE report_id=?',(report_id,)).fetchone()[0]
                    telegram_service.report_returned(db,report['org_id'],report_id,comment,event_id)
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
    db_path = str(db_path or os.getenv("QALDYQ_DB") or ROOT / "data" / "qaldyq-v5.4.sqlite3")
    initialize(db_path)
    with connect(db_path) as db:
        for module in MODULES:
            if hasattr(module, "startup"):
                module.startup(db)
    server = LocalServer((host, port), Handler)
    server.db_path = db_path
    server.telegram_config = telegram_service.Config.from_env()
    server.reminder_stop = threading.Event()
    def reminder_loop():
        while not server.reminder_stop.is_set():
            try:
                with connect(db_path) as db:
                    db.execute('BEGIN IMMEDIATE')
                    telegram_service.collect_reminders(db)
                    for module in MODULES:
                        if hasattr(module, "tick"):
                            module.tick(db)
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
