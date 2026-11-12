"""Causes, waste-reduction actions with measured results, data quality and transfers for recycling (ТТ 15–16, 18–19).

Chain: waste → cause → recommendation → approved action → execution → measured result.
A change in an indicator is reported as an observation; it is never presented as a proven causal effect."""
import json
import re
import statistics
from datetime import date, timedelta

import common
import notify
from common import APIError, can_review, integer, iso_day, money, now, org_scope, own_org, rows, text

STATUSES = ("proposed", "approved", "running", "evaluating", "done", "stopped")
CAUSES = ("overproduction", "attendance_drop", "portion_size", "quality", "storage", "process_loss", "other")
CAUSE_SOURCES = ("staff_opinion", "statistical", "both")
TRANSFER_STATUSES = ("planned", "handed", "confirmed")
CANTEEN_KINDS = ("Асхана", "Қонақүй", "Кофехана")


def migrate(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS actions(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL REFERENCES organizations(id), status TEXT NOT NULL DEFAULT 'proposed',
      problem TEXT NOT NULL, cause TEXT NOT NULL, cause_source TEXT NOT NULL, hypothesis TEXT NOT NULL DEFAULT '', recommendation TEXT NOT NULL DEFAULT '',
      approved_action TEXT NOT NULL DEFAULT '', owner_id INTEGER REFERENCES users(id), approver_id INTEGER REFERENCES users(id), due_day TEXT,
      baseline_start TEXT NOT NULL, baseline_end TEXT NOT NULL, control_start TEXT, control_end TEXT, targets TEXT NOT NULL DEFAULT '', limits TEXT NOT NULL DEFAULT '',
      cost_tiyn INTEGER NOT NULL DEFAULT 0, confirmed_savings_tiyn INTEGER, confirmed_doc TEXT NOT NULL DEFAULT '', category_id INTEGER REFERENCES categories(id),
      dish_id INTEGER, baseline TEXT NOT NULL DEFAULT '{}', result TEXT NOT NULL DEFAULT '{}', conclusion TEXT NOT NULL DEFAULT '',
      created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS action_events(id INTEGER PRIMARY KEY, action_id INTEGER NOT NULL REFERENCES actions(id) ON DELETE CASCADE, from_status TEXT, to_status TEXT NOT NULL,
      user_id INTEGER NOT NULL REFERENCES users(id), note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS transfers(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL REFERENCES organizations(id), category_id INTEGER NOT NULL REFERENCES categories(id),
      qty REAL NOT NULL CHECK(qty>0), unit TEXT NOT NULL, day TEXT NOT NULL, recipient TEXT NOT NULL, document TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'planned',
      confirmed_by INTEGER REFERENCES users(id), confirmed_at TEXT, processing_doc TEXT NOT NULL DEFAULT '', processing_by INTEGER REFERENCES users(id), processing_at TEXT,
      created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS clarifications(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL REFERENCES organizations(id), kind TEXT NOT NULL, ref TEXT NOT NULL DEFAULT '',
      question TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', asked_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
      answer TEXT NOT NULL DEFAULT '', answered_by INTEGER REFERENCES users(id), answered_at TEXT, closed_by INTEGER REFERENCES users(id), closed_at TEXT);
    """)


def working_days(start, end):
    days, current = 0, start
    while current <= end:
        days += current.weekday() != 6
        current += timedelta(days=1)
    return days


def metrics(db, org_id, start, end, category_id=None, dish_id=None):
    """Indicators of one period. Unknown values stay None; they are never replaced by zero."""
    one = lambda sql, args: db.execute(sql, args).fetchone()[0]
    cat = " AND i.category_id=?" if category_id else ""
    args = (org_id, start, end, *((category_id,) if category_id else ()))
    waste = one(f"""SELECT SUM(i.kg) FROM items i JOIN reports r ON r.id=i.report_id JOIN categories c ON c.id=i.category_id
        WHERE r.org_id=? AND r.status='accepted' AND r.report_date BETWEEN ? AND ? AND c.unit='kg'{cat}""", args)
    cost = one(f"""SELECT SUM(i.kg*i.cost) FROM items i JOIN reports r ON r.id=i.report_id WHERE r.org_id=? AND r.status='accepted' AND r.report_date BETWEEN ? AND ?{cat}""", args)
    dish = " AND dish_id=?" if dish_id else ""
    dargs = (org_id, start, end, *((dish_id,) if dish_id else ()))
    sold = one(f"SELECT SUM(qty) FROM sales WHERE org_id=? AND day BETWEEN ? AND ?{dish}", dargs)
    served = one("SELECT SUM(portions) FROM reports WHERE org_id=? AND status='accepted' AND report_date BETWEEN ? AND ? AND portions IS NOT NULL", (org_id, start, end))
    portions, source = (sold, "sales") if sold else (served, "reports") if served else (None, None)
    unsold = one(f"SELECT SUM(unsold) FROM day_close WHERE org_id=? AND day BETWEEN ? AND ?{dish}", dargs)
    shortages = db.execute(f"SELECT COUNT(*) AS n,SUM(unmet) AS unmet,SUM(unmet IS NULL) AS unknown FROM shortages WHERE org_id=? AND day BETWEEN ? AND ?{dish}", dargs).fetchone()
    data_days = [r[0] for r in db.execute("SELECT DISTINCT report_date FROM reports WHERE org_id=? AND status='accepted' AND report_date BETWEEN ? AND ?", (org_id, start, end))]
    expected = working_days(date.fromisoformat(start), date.fromisoformat(end))
    return {"start": start, "end": end, "waste_kg": round(waste, 2) if waste is not None else None, "waste_cost_estimate": round(cost, 2) if cost is not None else None,
            "portions": portions, "portions_source": source, "kg_per_100": round(waste / portions * 100, 2) if waste is not None and portions else None,
            "unsold_portions": unsold, "shortage_events": shortages["n"], "unmet_known": shortages["unmet"], "unmet_unknown_events": shortages["unknown"] or 0,
            "days_with_data": len(data_days), "working_days": expected, "completeness": round(len(data_days) / expected, 2) if expected else None,
            "weekdays": sorted({date.fromisoformat(d).weekday() for d in data_days}),
            "menu_dishes": sorted({r[0] for r in db.execute("""SELECT DISTINCT d.name FROM menu_items mi JOIN menu_days m ON m.id=mi.menu_id JOIN catalog_dishes d ON d.id=mi.dish_id
                WHERE m.org_id=? AND m.day BETWEEN ? AND ? AND m.status='published'""", (org_id, start, end))})}


def evaluation(db, action):
    """Compare the control period with the baseline and list what limits the comparison."""
    base = metrics(db, action["org_id"], action["baseline_start"], action["baseline_end"], action["category_id"], action["dish_id"])
    if not action["control_start"] or not action["control_end"]:
        return {"baseline": base, "control": None, "notes": ["Бақылау кезеңі белгіленбеген."], "verdict": "no_control"}
    control = metrics(db, action["org_id"], action["control_start"], action["control_end"], action["category_id"], action["dish_id"])
    notes = []
    for period, name in ((base, "Бастапқы"), (control, "Бақылау")):
        if period["completeness"] is not None and period["completeness"] < 0.8:
            notes.append(f"{name} кезеңінде дерек толық емес: {period['days_with_data']} / {period['working_days']} жұмыс күні.")
    if base["weekdays"] != control["weekdays"]:
        notes.append("Екі кезеңдегі апта күндерінің құрамы әртүрлі.")
    if base["portions"] and control["portions"]:
        change = (control["portions"] / max(1, control["days_with_data"])) / (base["portions"] / max(1, base["days_with_data"])) - 1
        if abs(change) > 0.2:
            notes.append(f"Күндік порция саны {round(change * 100)}% өзгерген: келушілер саны әсер етуі мүмкін.")
    else:
        notes.append("Порция саны белгісіз: кг / 100 порция есептелмейді.")
    if base["menu_dishes"] and control["menu_dishes"] and base["menu_dishes"] != control["menu_dishes"]:
        notes.append("Мәзір құрамы өзгерген.")
    overlapping = db.execute("""SELECT COUNT(*) FROM actions WHERE org_id=? AND id!=? AND status IN ('running','evaluating','done') AND control_start IS NOT NULL
        AND control_start<=? AND control_end>=?""", (action["org_id"], action["id"], action["control_end"], action["control_start"])).fetchone()[0]
    if overlapping:
        notes.append(f"Сол кезеңде тағы {overlapping} іс-шара жүрген: әсерлерді бөліп көрсету мүмкін емес.")
    delta = lambda key: round(control[key] - base[key], 2) if base[key] is not None and control[key] is not None else None
    waste_down = delta("kg_per_100") is not None and delta("kg_per_100") < 0
    shortage_up = control["shortage_events"] > base["shortage_events"]
    verdict = "insufficient" if delta("kg_per_100") is None else "revise" if waste_down and shortage_up else "improved" if waste_down else "not_improved"
    if verdict == "revise":
        notes.append("Қалдық азайды, бірақ тағамның ерте таусылуы көбейді: әрекетті қайта қарау ұсынылады.")
    unit_cost = base["waste_cost_estimate"] / base["waste_kg"] if base["waste_kg"] else None
    avoided_kg = round(-delta("kg_per_100") * control["portions"] / 100, 2) if waste_down and control["portions"] else None
    finance = {
        "registered_waste_cost": control["waste_cost_estimate"],                                   # demo valuation of what was registered
        "estimated_avoided_cost": round(avoided_kg * unit_cost, 2) if avoided_kg is not None and unit_cost else None,  # a calculation, not money received
        "confirmed_savings": action["confirmed_savings_tiyn"] / 100 if action["confirmed_savings_tiyn"] is not None else None,  # only with a document
        "confirmed_doc": action["confirmed_doc"], "action_cost": action["cost_tiyn"] / 100,
        "formula": "Болдырылмауы мүмкін шығын = (бастапқы кг/100 − бақылау кг/100) × бақылау порциясы / 100 × бастапқы кезеңдегі 1 кг-ның орташа демо бағасы. Бұл — есептік баға.",
    }
    finance["net_confirmed"] = round(finance["confirmed_savings"] - finance["action_cost"], 2) if finance["confirmed_savings"] is not None else None
    finance["net_estimated"] = round(finance["estimated_avoided_cost"] - finance["action_cost"], 2) if finance["estimated_avoided_cost"] is not None else None
    return {"baseline": base, "control": control, "delta": {k: delta(k) for k in ("kg_per_100", "waste_kg", "unsold_portions")},
            "shortage_delta": control["shortage_events"] - base["shortage_events"], "avoided_kg_estimate": avoided_kg, "finance": finance, "notes": notes, "verdict": verdict,
            "disclaimer": "Көрсеткіштің өзгеруі іс-шараның себептік әсерінің дәлелі емес: мәзір, келушілер саны, апта күні және қатар жүрген өзгерістер де әсер етеді."}


def action_view(db, row, full=False):
    view = dict(row)
    for key in ("baseline", "result"):
        view[key] = json.loads(view[key] or "{}")
    view["cost"] = view.pop("cost_tiyn") / 100
    view["confirmed_savings"] = view["confirmed_savings_tiyn"] / 100 if view["confirmed_savings_tiyn"] is not None else None
    names = {r["id"]: r["name"] for r in db.execute("SELECT id,name FROM users WHERE id IN (?,?,?)", (row["owner_id"], row["approver_id"], row["created_by"]))}
    view["owner"], view["approver"], view["author"] = names.get(row["owner_id"]), names.get(row["approver_id"]), names.get(row["created_by"])
    view["org_name"] = db.execute("SELECT name FROM organizations WHERE id=?", (row["org_id"],)).fetchone()["name"]
    if full:
        view["events"] = rows(db.execute("SELECT e.*,u.name FROM action_events e JOIN users u ON u.id=e.user_id WHERE action_id=? ORDER BY e.id", (row["id"],)))
        view["evaluation"] = evaluation(db, row)
        view["similar"] = similar(db, row["org_id"], row["cause"], row["category_id"], exclude=row["id"])
    return view


def similar(db, org_id, cause, category_id=None, exclude=0):
    """Experience base: finished actions for a similar situation, with what was done and what was recorded."""
    found = db.execute("""SELECT a.*,o.name AS org_name FROM actions a JOIN organizations o ON o.id=a.org_id WHERE a.status='done' AND a.id!=?
        AND (a.cause=? OR (a.category_id IS NOT NULL AND a.category_id=?)) ORDER BY (a.org_id=?) DESC,a.updated_at DESC LIMIT 5""", (exclude, cause, category_id or 0, org_id)).fetchall()
    return [{"id": a["id"], "org_name": a["org_name"], "problem": a["problem"], "approved_action": a["approved_action"], "cause": a["cause"],
             "result": json.loads(a["result"] or "{}"), "conclusion": a["conclusion"]} for a in found]


def action_fields(db, user, data, current=None):
    get = lambda key, default="": data.get(key, current[key] if current else default)
    cause, source = get("cause"), get("cause_source", "staff_opinion")
    if cause not in CAUSES or source not in CAUSE_SOURCES:
        raise APIError("Себепті және оның негізін таңдаңыз.")
    start, end = iso_day(get("baseline_start"), "Бастапқы кезең басы"), iso_day(get("baseline_end"), "Бастапқы кезең соңы")
    if start > end:
        raise APIError("Бастапқы кезеңді дұрыс көрсетіңіз.")
    control = (get("control_start", None), get("control_end", None))
    if any(control):
        control = (iso_day(control[0], "Бақылау кезеңі басы"), iso_day(control[1], "Бақылау кезеңі соңы"))
        if control[0] > control[1] or control[0] <= end:
            raise APIError("Бақылау кезеңі бастапқы кезеңнен кейін болсын.")
        control = (control[0].isoformat(), control[1].isoformat())
    else:
        control = (None, None)
    owner = int(get("owner_id", 0) or 0) or None
    return {"problem": text(get("problem"), "Мәселе", 5, 500), "cause": cause, "cause_source": source, "hypothesis": text(get("hypothesis"), "Гипотеза", 0, 500),
            "recommendation": text(get("recommendation"), "Ұсыныс", 0, 500), "approved_action": text(get("approved_action"), "Бекітілген әрекет", 0, 500), "owner_id": owner,
            "due_day": iso_day(get("due_day"), "Мерзімі").isoformat() if get("due_day", None) else None, "baseline_start": start.isoformat(), "baseline_end": end.isoformat(),
            "control_start": control[0], "control_end": control[1], "targets": text(get("targets"), "Мақсатты көрсеткіштер", 0, 300), "limits": text(get("limits"), "Шектеулер", 0, 300),
            "cost_tiyn": money(data["cost"], "Іс-шара құны") if "cost" in data else (current["cost_tiyn"] if current else 0),
            "category_id": int(get("category_id", 0) or 0) or None, "dish_id": int(get("dish_id", 0) or 0) or None}


def move_action(db, user, action, target, data):
    source, role = action["status"], user["role"]
    approver = role in ("manager", "admin")
    allowed = {("proposed", "approved"): approver, ("approved", "running"): role in ("operator", "admin"), ("running", "evaluating"): role in ("operator", "admin"),
               ("evaluating", "done"): approver}.get((source, target), target == "stopped" and source not in ("done", "stopped") and approver)
    if not allowed:
        raise APIError("Бұл күйге ауыстыруға рұқсат жоқ.", 403)
    note = text(data.get("note") or "", "Түсіндірме", 0, 500)
    updates = {"status": target, "updated_at": now()}
    if target == "approved":
        updates["approver_id"] = user["id"]
        updates["approved_action"] = text(data.get("approved_action") or action["approved_action"] or action["recommendation"], "Бекітілген әрекет", 5, 500)
    if target in ("running", "evaluating") and not action["control_start"]:
        raise APIError("Алдымен бақылау кезеңін белгілеңіз.")
    if target == "stopped" and not note:
        raise APIError("Тоқтату себебін жазыңыз.")
    if target == "done":
        updates["conclusion"] = text(data.get("conclusion"), "Қорытынды", 5, 1000)
        if data.get("confirmed_savings") not in (None, ""):
            # Confirmed savings count only with a named document; otherwise the figure stays an estimate.
            updates["confirmed_savings_tiyn"] = money(data["confirmed_savings"], "Расталған үнем")
            updates["confirmed_doc"] = text(data.get("confirmed_doc"), "Растайтын құжат", 3, 200)
        snapshot = evaluation(db, {**dict(action), **updates})
        updates["result"] = json.dumps({k: snapshot[k] for k in ("baseline", "control", "delta", "shortage_delta", "verdict", "notes", "finance")}, ensure_ascii=False)
    db.execute(f"UPDATE actions SET {','.join(k + '=?' for k in updates)} WHERE id=?", (*updates.values(), action["id"]))
    db.execute("INSERT INTO action_events(action_id,from_status,to_status,user_id,note,created_at) VALUES (?,?,?,?,?,?)", (action["id"], source, target, user["id"], note, now()))


# ---------- data quality ----------

def quality(db, org_id, start, end, today):
    """Problems that weaken reports, forecasts and action results. Nothing here is fixed automatically."""
    org = db.execute("SELECT * FROM organizations WHERE id=?", (org_id,)).fetchone()
    duplicates = rows(db.execute("""SELECT r.report_date AS date,c.name AS waste,i.kg AS quantity,c.unit,COUNT(*) AS copies,GROUP_CONCAT(DISTINCT r.id) AS records
        FROM items i JOIN reports r ON r.id=i.report_id JOIN categories c ON c.id=i.category_id WHERE r.org_id=? AND r.report_date BETWEEN ? AND ?
        GROUP BY r.report_date,i.category_id,i.kg HAVING COUNT(DISTINCT r.id)>1 ORDER BY r.report_date DESC LIMIT 50""", (org_id, start, end)))
    have = {r[0] for r in db.execute("SELECT DISTINCT report_date FROM reports WHERE org_id=? AND report_date BETWEEN ? AND ?", (org_id, start, end))}
    missing, current, last = [], date.fromisoformat(start), min(date.fromisoformat(end), today)
    daily = org["kind"] in CANTEEN_KINDS
    while daily and current <= last:
        if current.weekday() != 6 and current.isoformat() not in have:
            missing.append(current.isoformat())
        current += timedelta(days=1)
    totals = rows(db.execute("""SELECT r.id,r.report_date AS date,r.status,ROUND(SUM(CASE WHEN c.unit='kg' THEN i.kg ELSE 0 END),2) AS kg FROM reports r JOIN items i ON i.report_id=r.id
        JOIN categories c ON c.id=i.category_id WHERE r.org_id=? AND r.report_date BETWEEN ? AND ? GROUP BY r.id""", (org_id, start, end)))
    accepted = [t["kg"] for t in totals if t["status"] == "accepted" and t["kg"]]
    median = statistics.median(accepted) if len(accepted) >= 5 else None
    suspicious = [dict(t, median=median) for t in totals if median and t["kg"] > 2 * median]
    incomplete = rows(db.execute("""SELECT r.id,r.report_date AS date,'portions' AS missing FROM reports r WHERE r.org_id=? AND r.report_date BETWEEN ? AND ? AND r.status='accepted'
        AND r.portions IS NULL ORDER BY r.report_date DESC LIMIT 50""", (org_id, start, end))) if daily else []
    incomplete += rows(db.execute("""SELECT r.id,r.report_date AS date,'stage' AS missing FROM reports r JOIN items i ON i.report_id=r.id WHERE r.org_id=? AND r.report_date BETWEEN ? AND ?
        AND i.stage='other' GROUP BY r.id ORDER BY r.report_date DESC LIMIT 50""", (org_id, start, end)))
    import mod_kitchen
    contradictions = []
    for row in db.execute("SELECT DISTINCT day FROM (SELECT day FROM productions WHERE org_id=? AND day BETWEEN ? AND ? UNION SELECT day FROM sales WHERE org_id=? AND day BETWEEN ? AND ?)", (org_id, start, end, org_id, start, end)):
        for dish in mod_kitchen.balance(db, org_id, row["day"]):
            if dish["state"] == "clarify" or (dish["state"] == "open" and row["day"] < today.isoformat()):
                contradictions.append({"date": row["day"], "dish": dish["name"], "state": dish["state"], "unexplained": dish["unexplained"]})
    overdue, month = [], date.fromisoformat(start).replace(day=1)
    while month <= last:
        month_end = (month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        deadline = int(db.execute("SELECT value FROM settings WHERE key='deadline_day'").fetchone()[0])
        due = (month_end + timedelta(days=1)).replace(day=min(deadline, 28))
        if today >= due and not db.execute("SELECT 1 FROM period_reports WHERE org_id=? AND period_start<=? AND period_end>=? AND status IN ('submitted','in_review','accepted')", (org_id, month_end.isoformat(), month.isoformat())).fetchone():
            overdue.append({"month": month.isoformat()[:7], "due": due.isoformat()})
        month = month_end + timedelta(days=1)
    open_questions = rows(db.execute("""SELECT q.*,u.name AS asked_name FROM clarifications q JOIN users u ON u.id=q.asked_by WHERE q.org_id=? ORDER BY (q.status='closed'),q.id DESC LIMIT 100""", (org_id,)))
    expected = working_days(date.fromisoformat(start), last) if daily and date.fromisoformat(start) <= last else None
    return {"org_id": org_id, "duplicates": duplicates, "missing_days": missing, "missing_days_known": daily, "suspicious": suspicious, "incomplete": incomplete,
            "balance_contradictions": contradictions, "overdue_reports": overdue, "clarifications": open_questions,
            "impact": {"forecast": f"Болжам тарихында {len(missing)} күн жоқ: сол күндер оқытуға да, тексеруге де кірмейді." if missing else "Таңдалған кезеңде күнделікті жазба үзіліссіз.",
                       "results": f"Порциясы жоқ {sum(1 for i in incomplete if i['missing'] == 'portions')} есеп кг / 100 порция көрсеткішіне кірмейді.",
                       "completeness": round((expected - len(missing)) / expected, 2) if expected else None}}


def recycling(db, user, query):
    """Four different things, shown apart: suitable by type, directed by route, documented hand-over, confirmed processing."""
    org = org_scope(user, query.get("org", [0])[0])
    start, end = iso_day(query.get("start", ["2020-01-01"])[0]).isoformat(), iso_day(query.get("end", ["2100-01-01"])[0]).isoformat()
    row = db.execute("""SELECT SUM(i.kg) AS total,SUM(CASE WHEN c.recyclable=1 THEN i.kg ELSE 0 END) AS suitable,
        SUM(CASE WHEN i.route IN (SELECT code FROM routes WHERE diverted=1) THEN i.kg ELSE 0 END) AS directed FROM items i JOIN reports r ON r.id=i.report_id
        JOIN categories c ON c.id=i.category_id WHERE r.status='accepted' AND c.unit='kg' AND r.report_date BETWEEN ? AND ? AND (?=0 OR r.org_id=?)""", (start, end, org, org)).fetchone()
    moved = db.execute("""SELECT SUM(CASE WHEN status IN ('handed','confirmed') AND document!='' THEN qty ELSE 0 END) AS documented,
        SUM(CASE WHEN status='confirmed' THEN qty ELSE 0 END) AS receipt,SUM(CASE WHEN processing_doc!='' THEN qty ELSE 0 END) AS processed
        FROM transfers WHERE unit='kg' AND day BETWEEN ? AND ? AND (?=0 OR org_id=?)""", (start, end, org, org)).fetchone()
    value = lambda v: round(v or 0, 2)
    return {"total_kg": value(row["total"]), "suitable_kg": value(row["suitable"]), "directed_kg": value(row["directed"]), "documented_transfer_kg": value(moved["documented"]),
            "receipt_confirmed_kg": value(moved["receipt"]), "processing_confirmed_kg": value(moved["processed"]),
            "note": "Тапсыру құжаты қайта өңдеудің аяқталғанын дәлелдемейді. «Өңделгені расталған» мәні тек қабылдаушының өңдеу туралы құжаты тіркелген тапсыруларды қамтиды. Литрмен өлшенетін қалдық бұл жиынтыққа кірмейді."}


def handle(h, db, user, method, path, query):
    if not path.startswith(("/api/actions", "/api/quality", "/api/clarifications", "/api/transfers", "/api/recycling")):
        return False
    staff = user["role"] in ("operator", "admin")
    today = common.local_now().date()
    data = h.body() if method != "GET" else {}

    if path == "/api/recycling" and method == "GET":
        return h.respond(recycling(db, user, query)) or True

    if path == "/api/actions" and method == "GET":
        org = org_scope(user, query.get("org", [0])[0])
        found = db.execute("SELECT * FROM actions WHERE (?=0 OR org_id=?) ORDER BY (status IN ('done','stopped')),id DESC", (org, org)).fetchall()
        return h.respond({"actions": [action_view(db, a) for a in found]}) or True
    if path == "/api/actions/similar" and method == "GET":
        return h.respond({"similar": similar(db, org_scope(user, query.get("org", [0])[0]), query.get("cause", [""])[0], int(query.get("category", [0])[0] or 0))}) or True
    if path == "/api/actions" and method == "POST":
        if user["role"] not in ("operator", "admin", "manager"):
            raise APIError("Іс-шараны асхана қызметкері, басшылық немесе әкімші ұсынады.", 403)
        org_id = own_org(db, user, data.get("org_id") or user["org_id"])
        fields = action_fields(db, user, data)
        fields["baseline"] = json.dumps(metrics(db, org_id, fields["baseline_start"], fields["baseline_end"], fields["category_id"], fields["dish_id"]), ensure_ascii=False)
        stamp = now()
        action_id = db.execute(f"INSERT INTO actions(org_id,created_by,created_at,updated_at,{','.join(fields)}) VALUES (?,?,?,?,{','.join('?' for _ in fields)})",
                               (org_id, user["id"], stamp, stamp, *fields.values())).lastrowid
        db.execute("INSERT INTO action_events(action_id,from_status,to_status,user_id,created_at) VALUES (?,?,?,?,?)", (action_id, None, "proposed", user["id"], stamp))
        return h.respond({"ok": True, "id": action_id}, 201) or True
    match = re.fullmatch(r"/api/actions/(\d+)(/transition)?", path)
    if match:
        action = db.execute("SELECT * FROM actions WHERE id=?", (int(match[1]),)).fetchone()
        if not action or (user["role"] == "operator" and action["org_id"] != user["org_id"]):
            raise APIError("Іс-шара табылмады.", 404)
        if method == "GET" and not match[2]:
            return h.respond(action_view(db, action, full=True)) or True
        if user["role"] == "reviewer":
            raise APIError("Тексеруші іс-шараны тек қарай алады.", 403)
        if data.get("updated_at") != action["updated_at"]:
            raise APIError("Іс-шара басқа терезеде өзгерді. Жаңартып, қайта көріңіз.", 409)
        if method == "PUT" and not match[2]:
            if action["status"] in ("done", "stopped"):
                raise APIError("Аяқталған іс-шара өзгертілмейді.", 409)
            fields = action_fields(db, user, data, action)
            db.execute(f"UPDATE actions SET {','.join(k + '=?' for k in fields)},updated_at=? WHERE id=?", (*fields.values(), now(), action["id"]))
            return h.respond({"ok": True}) or True
        if method == "POST" and match[2]:
            move_action(db, user, action, data.get("status"), data)
            if action["owner_id"] and data.get("status") == "approved":
                notify.enqueue(db, action["owner_id"], "action_deadline", "Іс-шара бекітілді", f"№{action['id']}: {action['problem'][:80]}", f"action:{action['id']}:approved")
            return h.respond({"ok": True}) or True

    if path == "/api/quality" and method == "GET":
        org = org_scope(user, query.get("org", [0])[0])
        if not org:
            raise APIError("Ұйымды таңдаңыз.")
        start, end = iso_day(query.get("start", [""])[0]).isoformat(), iso_day(query.get("end", [""])[0]).isoformat()
        return h.respond(quality(db, org, start, end, today)) or True
    if path == "/api/clarifications" and method == "POST":
        if not (can_review(user) or user["role"] in ("admin", "manager")):
            raise APIError("Нақтылауды тексеруші, басшылық немесе әкімші сұрайды.", 403)
        org_id = own_org(db, user, data.get("org_id"))
        question_id = db.execute("INSERT INTO clarifications(org_id,kind,ref,question,asked_by,created_at) VALUES (?,?,?,?,?,?)",
                                 (org_id, text(data.get("kind"), "Түрі", 2, 40), text(data.get("ref") or "", "Сілтеме", 0, 120), text(data.get("question"), "Сұрақ", 5, 500), user["id"], now())).lastrowid
        for staff_user in db.execute("SELECT id FROM users WHERE role='operator' AND active=1 AND org_id=?", (org_id,)).fetchall():
            notify.enqueue(db, staff_user["id"], "clarification", "Деректі нақтылау сұралды", str(data.get("question"))[:120], f"clarification:{question_id}")
        return h.respond({"ok": True, "id": question_id}, 201) or True
    match = re.fullmatch(r"/api/clarifications/(\d+)/(answer|close)", path)
    if match and method == "POST":
        item = db.execute("SELECT * FROM clarifications WHERE id=?", (int(match[1]),)).fetchone()
        if not item or (user["role"] == "operator" and item["org_id"] != user["org_id"]):
            raise APIError("Сұрау табылмады.", 404)
        if match[2] == "answer":
            if not staff or item["status"] != "open":
                raise APIError("Ашық сұрауға ұйымның жауапты қызметкері жауап береді.", 403)
            db.execute("UPDATE clarifications SET status='answered',answer=?,answered_by=?,answered_at=? WHERE id=?", (text(data.get("answer"), "Жауап", 3, 500), user["id"], now(), item["id"]))
        else:
            if not (can_review(user) or user["role"] in ("admin", "manager")) or item["status"] == "closed":
                raise APIError("Сұрауды оны сұрай алатын рөл жабады.", 403)
            db.execute("UPDATE clarifications SET status='closed',closed_by=?,closed_at=? WHERE id=?", (user["id"], now(), item["id"]))
        return h.respond({"ok": True}) or True

    if path == "/api/transfers" and method == "GET":
        org = org_scope(user, query.get("org", [0])[0])
        return h.respond({"transfers": rows(db.execute("""SELECT t.*,c.name AS waste,o.name AS org_name,u.name AS confirmer FROM transfers t JOIN categories c ON c.id=t.category_id
            JOIN organizations o ON o.id=t.org_id LEFT JOIN users u ON u.id=t.confirmed_by WHERE (?=0 OR t.org_id=?) ORDER BY t.day DESC,t.id DESC LIMIT 200""", (org, org)))}) or True
    if path == "/api/transfers" and method == "POST":
        if not staff:
            raise APIError("Тапсыруды ұйымның жауапты қызметкері немесе әкімші тіркейді.", 403)
        org_id = own_org(db, user, data.get("org_id") or user["org_id"])
        cat = db.execute("SELECT c.* FROM categories c JOIN org_categories oc ON oc.category_id=c.id WHERE c.id=? AND oc.org_id=?", (int(data.get("category_id") or 0), org_id)).fetchone()
        if not cat:
            raise APIError("Қалдық түрін ұйым тізімінен таңдаңыз.")
        stamp = now()
        transfer_id = db.execute("INSERT INTO transfers(org_id,category_id,qty,unit,day,recipient,document,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                                 (org_id, cat["id"], common.number(data.get("qty"), "Саны", 0.01, 100000), cat["unit"], iso_day(data.get("day"), "Күні").isoformat(),
                                  text(data.get("recipient"), "Қабылдаушы", 2, 160), text(data.get("document") or "", "Құжат", 0, 200), user["id"], stamp, stamp)).lastrowid
        return h.respond({"ok": True, "id": transfer_id}, 201) or True
    match = re.fullmatch(r"/api/transfers/(\d+)/(hand|confirm|processing)", path)
    if match and method == "POST":
        item = db.execute("SELECT * FROM transfers WHERE id=?", (int(match[1]),)).fetchone()
        if not item or (user["role"] == "operator" and item["org_id"] != user["org_id"]):
            raise APIError("Тапсыру жазбасы табылмады.", 404)
        stamp = now()
        if match[2] == "hand":
            if not staff or item["status"] != "planned":
                raise APIError("Жоспарланған тапсыруды ұйым қызметкері «тапсырылды» деп белгілейді.", 403)
            document = text(data.get("document") or item["document"], "Тапсыру құжаты", 3, 200)
            db.execute("UPDATE transfers SET status='handed',document=?,updated_at=? WHERE id=?", (document, stamp, item["id"]))
        elif match[2] == "confirm":
            if not (can_review(user) or user["role"] == "admin") or item["status"] != "handed":
                raise APIError("Қабылдауды тексеруші немесе әкімші, тапсырылғаннан кейін растайды.", 403)
            db.execute("UPDATE transfers SET status='confirmed',confirmed_by=?,confirmed_at=?,updated_at=? WHERE id=?", (user["id"], stamp, stamp, item["id"]))
        else:
            if not (can_review(user) or user["role"] == "admin") or item["status"] != "confirmed":
                raise APIError("Өңдеу туралы құжатты қабылдау расталғаннан кейін тексеруші тіркейді.", 403)
            db.execute("UPDATE transfers SET processing_doc=?,processing_by=?,processing_at=?,updated_at=? WHERE id=?", (text(data.get("processing_doc"), "Өңдеу туралы құжат", 3, 200), user["id"], stamp, stamp, item["id"]))
        return h.respond({"ok": True}) or True
    raise APIError("Мұндай әрекет табылмады.", 404)


def tick(db):
    """Once a minute: remind the owner of an action whose due date is today or has passed (one notice per action)."""
    today = common.local_now().date().isoformat()
    for action in db.execute("SELECT id,owner_id,problem,due_day FROM actions WHERE status IN ('approved','running') AND owner_id IS NOT NULL AND due_day IS NOT NULL AND due_day<=?", (today,)).fetchall():
        notify.enqueue(db, action["owner_id"], "action_deadline", "Іс-шара мерзімі келді", f"№{action['id']}: {action['problem'][:80]} · {action['due_day']}", f"action:{action['id']}:due")
