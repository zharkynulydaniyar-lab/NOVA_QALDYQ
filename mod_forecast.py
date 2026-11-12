"""Demand forecast, preparation plan and ingredient need (ТТ 17). Training runs in train_forecast.py, never in a request."""
import hashlib
import json
import math
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

import common
import forecast_core as core
import mod_kitchen
from common import APIError, add_column, integer, iso_day, now, org_scope, own_org, rows, text

MODEL_DIR = Path(__file__).resolve().parent / "data" / "models"
METHOD_NAMES = {"existing": "Qaldyq ережесі: медиана", "weekday": "Апта күні бойынша орташа", "ml": "Градиенттік бустинг (scikit-learn)"}
_cache = {}


def migrate(db):
    add_column(db, "sales", "is_demo", "INTEGER NOT NULL DEFAULT 0")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS calendar_events(id INTEGER PRIMARY KEY, day TEXT NOT NULL, kind TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', UNIQUE(day,kind));
    CREATE TABLE IF NOT EXISTS forecast_models(id INTEGER PRIMARY KEY, version TEXT NOT NULL UNIQUE, chosen TEXT NOT NULL, params TEXT NOT NULL, report TEXT NOT NULL,
      exploration TEXT NOT NULL, file TEXT, sha256 TEXT, active INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS forecasts(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL, dish_id INTEGER NOT NULL, day TEXT NOT NULL, made_at TEXT NOT NULL, method TEXT NOT NULL,
      model_version TEXT, predicted REAL, preorders INTEGER NOT NULL, safety_pct INTEGER NOT NULL, suggested INTEGER, history_days INTEGER NOT NULL, created_by INTEGER REFERENCES users(id));
    CREATE TABLE IF NOT EXISTS plans(org_id INTEGER NOT NULL, day TEXT NOT NULL, dish_id INTEGER NOT NULL, forecast_id INTEGER REFERENCES forecasts(id), suggested INTEGER,
      approved INTEGER NOT NULL, reason TEXT NOT NULL DEFAULT '', approved_by INTEGER NOT NULL REFERENCES users(id), approved_at TEXT NOT NULL, PRIMARY KEY(org_id,day,dish_id));
    INSERT OR IGNORE INTO settings(key,value) VALUES ('forecast_safety_pct','5');
    """)


def active_model(db):
    """The active version and, for ML, its estimator. The file is loaded only from the server's model directory and only
    if its SHA-256 equals the one recorded at training time."""
    row = db.execute("SELECT * FROM forecast_models WHERE active=1 ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        return None, None, "Модель оқытылмаған: статистикалық ереже қолданылады."
    if row["chosen"] != "ml":
        return row, None, None
    if row["version"] in _cache:
        return row, _cache[row["version"]], None
    path = (MODEL_DIR / str(row["file"])).resolve()
    if MODEL_DIR.resolve() not in path.parents or not path.is_file():
        return row, None, "Модель файлы сенімді қоймада табылмады: статистикалық ереже қолданылады."
    if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
        return row, None, "Модель файлының бақылау сомасы сәйкес келмейді: файл қолданылмайды."
    try:
        import joblib
        _cache[row["version"]] = joblib.load(path)
    except Exception:
        return row, None, "scikit-learn орнатылмаған немесе модель оқылмады: статистикалық ереже қолданылады."
    return row, _cache[row["version"]], None


def forecast(db, org_id, day, cutoff=None):
    """Forecast for every dish of the canteen's menu (or catalogue) on `day`, as known at `cutoff`."""
    cutoff = cutoff or common.local_now()
    history, context = core.load_history(db, org_id), core.load_context(db)
    # Pre-order timestamps are stored in UTC; the cutoff is campus time.
    cutoff_utc = (cutoff - timedelta(hours=5)).isoformat()
    row, model, warning = active_model(db)
    method = row["chosen"] if row else "existing"
    if method == "ml" and model is None:
        method = "existing"
    report = json.loads(row["report"]) if row else None
    safety = int(db.execute("SELECT value FROM settings WHERE key='forecast_safety_pct'").fetchone()[0])
    menu = {r["dish_id"]: r["n"] for r in db.execute("SELECT mi.dish_id,SUM(mi.available) AS n FROM menu_items mi JOIN menu_days m ON m.id=mi.menu_id WHERE m.org_id=? AND m.day=? GROUP BY mi.dish_id", (org_id, day))}
    dishes = rows(db.execute("SELECT d.id,d.name,d.name_ru,(SELECT MIN(price_tiyn) FROM dish_portions p WHERE p.dish_id=d.id AND p.active=1) AS price FROM catalog_dishes d WHERE d.org_id=? AND d.active=1 ORDER BY d.name", (org_id,)))
    plans = {r["dish_id"]: dict(r) for r in db.execute("SELECT * FROM plans WHERE org_id=? AND day=?", (org_id, day))}
    result = []
    for dish in dishes:
        if menu and dish["id"] not in menu:
            continue
        series = [r for r in history if r["dish_id"] == dish["id"]]
        f = core.features_for(series, day, context, org_id, dish["id"], cutoff_utc, (dish["price"] or 0) / 100, menu.get(dish["id"]))
        predicted = core.predict_one(method, f, model)
        used = method if predicted is not None else None
        if predicted is None and method == "ml":
            predicted, used = core.existing_rule(f), "existing"
        # Pre-orders are already part of the demand being forecast: they set a floor, they are not added on top.
        suggested = max(math.ceil(predicted * (1 + safety / 100)), f["preorders"]) if predicted is not None else None
        band = report.get("interval") if report and used == report.get("chosen") else None
        result.append({"dish_id": dish["id"], "name": dish["name"], "name_ru": dish["name_ru"], "predicted": round(predicted, 1) if predicted is not None else None, "preorders": f["preorders"],
                       "safety_pct": safety, "suggested": suggested, "history_days": f["history_days"], "method": used, "method_name": METHOD_NAMES.get(used),
                       "interval": {"low": max(0, round(predicted + band["low"], 1)), "high": round(predicted + band["high"], 1), "coverage": band["coverage"], "check_rows": band["check_rows"]} if band and predicted is not None else None,
                       "note": None if predicted is not None else f"Сенімді ұсыныс жоқ: соңғы 56 күнде {f['history_days']} күндік сатылым бар (кемінде {core.MIN_HISTORY} қажет).",
                       "plan": plans.get(dish["id"])})
    return {"date": day, "made_at": cutoff.isoformat(timespec="minutes"), "items": result, "model": {"version": row["version"] if row else None, "chosen": row["chosen"] if row else "existing",
            "report": {k: v for k, v in (report or {}).items() if k != "methods"} if report else None, "methods": (report or {}).get("methods"), "exploration": json.loads(row["exploration"]) if row else None,
            "created_at": row["created_at"] if row else None}, "warning": warning,
            "target": "Болжанатын шама — сол күнгі жалпы сұраныс (порция). Алдын ала тапсырыстар оның ішінде: олар болжамға үстіне қосылмайды, тек төменгі шек болады.",
            "limits": "Ерте таусылған күндердегі сатылым сұраныстың төменгі шегі ғана, сондықтан ол қате есебіне кірмейді. Демо модель нақты пайдалануда тексерілмеген."}


def handle(h, db, user, method, path, query):
    if not path.startswith(("/api/forecast", "/api/calendar")):
        return False
    if user["role"] not in ("operator", "admin", "manager"):
        raise APIError("Бұл бөлім асхана қызметкері, әкімші және басшылыққа арналған.", 403)
    today = common.local_now().date()
    if path == "/api/calendar":
        if method == "GET":
            return h.respond({"events": rows(db.execute("SELECT * FROM calendar_events ORDER BY day"))}) or True
        if user["role"] == "manager":
            raise APIError("Басшылық деректі тек қарай алады.", 403)
        data = h.body()
        if data.get("kind") not in ("holiday", "vacation", "event"):
            raise APIError("Күн түрін таңдаңыз.")
        db.execute("INSERT OR IGNORE INTO calendar_events(day,kind,note) VALUES (?,?,?)", (iso_day(data.get("day")).isoformat(), data["kind"], text(data.get("note") or "", "Түсіндірме", 0, 120)))
        return h.respond({"ok": True}, 201) or True
    if path == "/api/forecast" and method == "GET":
        org = org_scope(user, query.get("org", [0])[0])
        if not org:
            raise APIError("Асхананы таңдаңыз.")
        day = iso_day(query.get("date", [(today + timedelta(days=1)).isoformat()])[0]).isoformat()
        return h.respond(forecast(db, org, day)) or True
    if path == "/api/forecast/accuracy" and method == "GET":
        org = org_scope(user, query.get("org", [0])[0])
        data = rows(db.execute("""SELECT p.day,d.name,f.predicted,p.suggested,p.approved,p.reason,f.method,f.model_version,
            (SELECT SUM(qty) FROM sales s WHERE s.org_id=p.org_id AND s.dish_id=p.dish_id AND s.day=p.day) AS actual,
            EXISTS(SELECT 1 FROM shortages x WHERE x.org_id=p.org_id AND x.dish_id=p.dish_id AND x.day=p.day) AS ran_out
            FROM plans p JOIN catalog_dishes d ON d.id=p.dish_id LEFT JOIN forecasts f ON f.id=p.forecast_id WHERE p.org_id=? AND p.day<? ORDER BY p.day DESC,d.name LIMIT 200""", (org, today.isoformat())))
        return h.respond({"rows": data}) or True
    if path == "/api/forecast/plan" and method == "POST":
        if user["role"] == "manager":
            raise APIError("Жоспарды асхана қызметкері немесе әкімші бекітеді.", 403)
        data = h.body()
        org_id = own_org(db, user, data.get("org_id") or user["org_id"])
        day = iso_day(data.get("day")).isoformat()
        if day < today.isoformat():
            raise APIError("Өткен күннің жоспары бекітілмейді.")
        current = {i["dish_id"]: i for i in forecast(db, org_id, day)["items"]}
        made_at, plan = common.local_now().isoformat(timespec="seconds"), {}
        for line in data.get("items") or []:
            item = current.get(int((line or {}).get("dish_id") or 0))
            if not item:
                raise APIError("Тағам осы күннің болжамында жоқ.")
            approved = integer(line.get("approved"), "Бекітілген порция", 0, 5000)
            reason = text(line.get("reason") or "", "Өзгерту себебі", 0, 300)
            if item["suggested"] is not None and approved != item["suggested"] and len(reason) < 3:
                raise APIError(f"«{item['name']}»: ұсыныстан өзгеше мәнді себебімен бірге сақтаңыз.")
            # The forecast is stored as it was at approval time, so it can later be compared with what was sold.
            forecast_id = db.execute("INSERT INTO forecasts(org_id,dish_id,day,made_at,method,model_version,predicted,preorders,safety_pct,suggested,history_days,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                                     (org_id, item["dish_id"], day, made_at, item["method"] or "none", (db.execute("SELECT version FROM forecast_models WHERE active=1").fetchone() or [None])[0],
                                      item["predicted"], item["preorders"], item["safety_pct"], item["suggested"], item["history_days"], user["id"])).lastrowid
            db.execute("""INSERT INTO plans(org_id,day,dish_id,forecast_id,suggested,approved,reason,approved_by,approved_at) VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(org_id,day,dish_id) DO UPDATE SET forecast_id=excluded.forecast_id,suggested=excluded.suggested,approved=excluded.approved,reason=excluded.reason,approved_by=excluded.approved_by,approved_at=excluded.approved_at""",
                       (org_id, day, item["dish_id"], forecast_id, item["suggested"], approved, reason, user["id"], now()))
            plan[item["dish_id"]] = approved
        if not plan:
            raise APIError("Кемінде бір тағамның жоспарын көрсетіңіз.")
        return h.respond({"ok": True, "requirements": mod_kitchen.requirements(db, org_id, plan, day)}) or True
    if path == "/api/forecast/requirements" and method == "GET":
        org = org_scope(user, query.get("org", [0])[0])
        day = iso_day(query.get("date", [""])[0]).isoformat()
        plan = {r["dish_id"]: r["approved"] for r in db.execute("SELECT dish_id,approved FROM plans WHERE org_id=? AND day=?", (org, day))}
        return h.respond(mod_kitchen.requirements(db, org, plan, day) if plan else {"items": [], "dishes_without_recipe": [], "empty": True}) or True
    raise APIError("Мұндай әрекет табылмады.", 404)
