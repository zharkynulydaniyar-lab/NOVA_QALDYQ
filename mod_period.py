"""Periodic reports, the unified registry of accepted measurements, summaries and exports (ТТ 6–7)."""
import calendar
import io
import re
import zipfile
from datetime import date, timedelta
from xml.sax.saxutils import escape

from common import APIError, UNITS, add_column, can_review, iso_day, now, org_scope, own_org, rows

LOCKED = ("submitted", "in_review", "accepted")
LABELS = {
    "kk": {"title": "АТУ университет кешеніндегі тамақ қалдықтарын есепке алу кестесі", "accepted": "Тек қабылданған өлшемдер (бірыңғай тізілім)",
           "journal": "ЖҰМЫС ЖУРНАЛЫ: барлық мәртебедегі жазбалар. Жиынтық есеп емес.", "period": "Кезең", "generated": "Жасалған уақыты",
           "summary": "Жиынтық", "months": "Айлар бойынша", "date": "Күні", "waste": "Қалдық атауы", "quantity": "Салмағы (кг) / Көлемі (л)", "unit": "Бірлік",
           "route": "Қайта өңдеу / кәдеге жарату тәсілі", "responsible": "Жауапты тұлға", "org": "Ұйым", "records": "Жазба саны", "month": "Ай",
           "status": "Мәртебе", "stage": "Пайда болу кезеңі", "total": "Барлығы", "total_type": "Атауы бойынша жиыны", "empty": "Таңдалған кезеңде жазба жоқ",
           "demo": "Демо деректер: синтетикалық, нақты өлшем емес.", "units_note": "Килограмм мен литр бөлек есептеледі және қосылмайды."},
    "ru": {"title": "Таблица учёта пищевых отходов в университетском комплексе АО «АТУ»", "accepted": "Только принятые измерения (единый реестр)",
           "journal": "РАБОЧИЙ ЖУРНАЛ: записи во всех статусах. Не является сводным отчётом.", "period": "Период", "generated": "Сформировано",
           "summary": "Свод", "months": "По месяцам", "date": "Дата", "waste": "Наименование отходов", "quantity": "Вес (кг) / Объём (л)", "unit": "Ед.",
           "route": "Способ переработки / утилизации", "responsible": "Ответственное лицо", "org": "Организация", "records": "Записей", "month": "Месяц",
           "status": "Статус", "stage": "Этап образования", "total": "Итого", "total_type": "Итого по наименованию", "empty": "За выбранный период записей нет",
           "demo": "Демонстрационные данные: синтетические, не реальные измерения.", "units_note": "Килограммы и литры считаются отдельно и не суммируются."},
}
STATUS_NAMES = {"kk": {"draft": "Черновик", "submitted": "Жіберілді", "in_review": "Тексерілуде", "accepted": "Қабылданды", "returned": "Қайтарылды"},
                "ru": {"draft": "Черновик", "submitted": "Отправлен", "in_review": "На проверке", "accepted": "Принят", "returned": "Возвращён"}}
STAGE_NAMES = {"kk": {"prep": "Дайындау", "unsold": "Сатылмаған тағам", "plate": "Тәрелке қалдығы", "storage": "Сақтаудағы бұзылу", "other": "Басқа"},
               "ru": {"prep": "Подготовка / приготовление", "unsold": "Нереализованная еда", "plate": "Остатки с тарелок", "storage": "Порча при хранении", "other": "Другое"}}


def migrate(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS period_reports(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL REFERENCES organizations(id),
      period_start TEXT NOT NULL, period_end TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft', submitted_at TEXT,
      reviewer_id INTEGER REFERENCES users(id), decided_at TEXT, created_by INTEGER REFERENCES users(id),
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(org_id,period_start,period_end));
    CREATE TABLE IF NOT EXISTS period_history(id INTEGER PRIMARY KEY, period_id INTEGER NOT NULL REFERENCES period_reports(id) ON DELETE CASCADE,
      from_status TEXT, to_status TEXT NOT NULL, action TEXT NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id),
      comment TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
    """)
    add_column(db, "reports", "period_id", "INTEGER REFERENCES period_reports(id)")


def month_range(value):
    if not re.fullmatch(r"\d{4}-\d{2}", str(value or "")):
        raise APIError("Айды ЖЖЖЖ-АА түрінде көрсетіңіз.")
    year, month = int(value[:4]), int(value[5:])
    if not 2020 <= year <= 2100 or not 1 <= month <= 12:
        raise APIError("Айды дұрыс көрсетіңіз.")
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def locking_period(db, org_id, day):
    """A submitted, in-review or accepted period report freezes its organization's records for those dates."""
    return db.execute("SELECT * FROM period_reports WHERE org_id=? AND period_start<=? AND period_end>=? AND status IN ('submitted','in_review','accepted')",
                      (org_id, str(day), str(day))).fetchone()


def ensure_unlocked(db, org_id, day):
    period = locking_period(db, org_id, day)
    if period:
        state = "қабылданған" if period["status"] == "accepted" else "тексеруге жіберілген"
        raise APIError(f"{period['period_start']} – {period['period_end']} кезеңінің есебі {state}. Осы күндердің өлшемдері өзгертілмейді.", 409)


def measurements(db, user, query, accepted_only=True, period=None):
    """One row per measurement. Filters select measurements, never whole reports."""
    clauses, args = ["1=1"], []
    if accepted_only:
        clauses.append("r.status='accepted'")
    for key, op in (("start", ">="), ("end", "<=")):
        if query.get(key):
            clauses.append(f"r.report_date {op} ?")
            args.append(iso_day(query[key][0]).isoformat())
    org = org_scope(user, query.get("org", [0])[0])
    if org:
        clauses.append("r.org_id=?")
        args.append(org)
    if int(query.get("category", [0])[0] or 0):
        clauses.append("i.category_id=?")
        args.append(int(query["category"][0]))
    if query.get("route", [""])[0]:
        clauses.append("i.route=?")
        args.append(query["route"][0])
    if query.get("unit", [""])[0] in UNITS:
        clauses.append("c.unit=?")
        args.append(query["unit"][0])
    return rows(db.execute(f"""SELECT i.id,r.id AS report_id,r.report_date AS date,r.org_id,o.name AS org_name,o.name_ru AS org_name_ru,o.short AS org_short,
        i.category_id,c.name AS waste,c.name_ru AS waste_ru,c.unit,c.recyclable,i.kg AS quantity,i.route,rt.name AS route_name,rt.name_ru AS route_name_ru,
        COALESCE(rt.diverted,0) AS diverted,i.stage,i.note,u.name AS responsible,r.status,ROUND(i.kg*i.cost,2) AS cost,ROUND(i.kg*i.co2,2) AS co2
        FROM items i JOIN reports r ON r.id=i.report_id JOIN organizations o ON o.id=r.org_id JOIN categories c ON c.id=i.category_id
        JOIN users u ON u.id=r.author_id LEFT JOIN routes rt ON rt.code=i.route WHERE {' AND '.join(clauses)}
        ORDER BY r.report_date,r.org_id,i.id""", args))


def summarize(items):
    """Totals by organization, waste type, month and unit. Kilograms and litres never share a total."""
    def table(key):
        groups = {}
        for item in items:
            entry = groups.setdefault(key(item), {"quantity": 0.0, "records": 0, "cost": 0.0, "co2": 0.0})
            entry["quantity"] += item["quantity"]
            entry["records"] += 1
            entry["cost"] += item["cost"]
            entry["co2"] += item["co2"]
        return [dict(zip(("a", "b", "unit"), k), **{f: round(v, 2) if isinstance(v, float) else v for f, v in g.items()}) for k, g in sorted(groups.items())]
    return {
        "by_org_type": table(lambda i: (i["org_name"], i["waste"], i["unit"])),
        "by_org": table(lambda i: (i["org_name"], "", i["unit"])),
        "by_type": table(lambda i: (i["waste"], "", i["unit"])),
        "by_month": table(lambda i: (i["date"][:7], i["org_name"], i["unit"])),
        "by_day": table(lambda i: (i["date"], "", i["unit"])),
        "totals": table(lambda i: ("", "", i["unit"])),
    }


def period_detail(db, period):
    detail = dict(period)
    org = db.execute("SELECT name FROM organizations WHERE id=?", (period["org_id"],)).fetchone()
    detail["org_name"] = org["name"]
    items = measurements(db, {"role": "admin", "org_id": None}, {"start": [period["period_start"]], "end": [period["period_end"]], "org": [period["org_id"]]}, accepted_only=False)
    detail["measurements"] = items
    detail["summary"] = summarize(items)
    detail["record_statuses"] = {r["status"]: r["n"] for r in db.execute("SELECT status,COUNT(*) AS n FROM reports WHERE org_id=? AND report_date BETWEEN ? AND ? GROUP BY status", (period["org_id"], period["period_start"], period["period_end"]))}
    detail["history"] = rows(db.execute("SELECT h.*,u.name FROM period_history h JOIN users u ON u.id=h.user_id WHERE period_id=? ORDER BY h.id", (period["id"],)))
    reviewer = db.execute("SELECT name FROM users WHERE id=?", (period["reviewer_id"],)).fetchone() if period["reviewer_id"] else None
    detail["reviewer"] = reviewer["name"] if reviewer else None
    return detail


def log(db, period_id, user_id, source, target, action, comment=""):
    db.execute("INSERT INTO period_history(period_id,from_status,to_status,action,user_id,comment,created_at) VALUES (?,?,?,?,?,?,?)",
               (period_id, source, target, action, user_id, comment, now()))


def cascade(db, period, user_id, sources, target, comment=""):
    """Move the period's measurement records together with it and write each step to their own history."""
    marks = ",".join("?" for _ in sources)
    records = db.execute(f"SELECT id,status FROM reports WHERE org_id=? AND report_date BETWEEN ? AND ? AND status IN ({marks})",
                         (period["org_id"], period["period_start"], period["period_end"], *sources)).fetchall()
    stamp = now()
    for record in records:
        db.execute("UPDATE reports SET status=?,updated_at=?,period_id=? WHERE id=?", (target, stamp, period["id"], record["id"]))
        db.execute("INSERT INTO history(report_id,user_id,action,comment,created_at,from_status) VALUES (?,?,?,?,?,?)",
                   (record["id"], user_id, target, comment, stamp, record["status"]))
    return len(records)


def transition(db, user, period, target, comment=""):
    source = period["status"]
    if target == "submitted":
        allowed = user["role"] in ("operator", "admin") and source in ("draft", "returned")
    elif target == "in_review":
        allowed = can_review(user) and source == "submitted"
    elif target in ("accepted", "returned"):
        allowed = can_review(user) and source == "in_review"
    else:
        allowed = False
    if not allowed:
        raise APIError("Бұл мәртебеге ауыстыруға рұқсат жоқ.", 403)
    comment = str(comment or "").strip()[:2000]
    if target == "returned" and not comment:
        raise APIError("Қайтару себебін жазыңыз.")
    stamp = now()
    if target == "submitted":
        if not db.execute("SELECT 1 FROM reports WHERE org_id=? AND report_date BETWEEN ? AND ? LIMIT 1", (period["org_id"], period["period_start"], period["period_end"])).fetchone():
            raise APIError("Кезеңде бірде-бір өлшем жоқ. Алдымен өлшемдерді енгізіңіз.")
        cascade(db, period, user["id"], ("draft", "returned"), "submitted", "Кезең есебімен бірге жіберілді")
        db.execute("UPDATE period_reports SET status=?,submitted_at=?,decided_at=NULL,updated_at=? WHERE id=?", (target, stamp, stamp, period["id"]))
    elif target == "in_review":
        cascade(db, period, user["id"], ("submitted",), "in_review")
        db.execute("UPDATE period_reports SET status=?,reviewer_id=?,updated_at=? WHERE id=?", (target, user["id"], stamp, period["id"]))
    else:
        cascade(db, period, user["id"], ("submitted", "in_review"), target, comment)
        db.execute("UPDATE period_reports SET status=?,reviewer_id=?,decided_at=?,updated_at=? WHERE id=?", (target, user["id"], stamp, stamp, period["id"]))
    log(db, period["id"], user["id"], source, target, target, comment)


def overview(db, user, start, end):
    """Two different gaps: nothing submitted at all, and submitted but not accepted yet."""
    org = org_scope(user)
    orgs = rows(db.execute("SELECT id,name FROM organizations WHERE active=1" + (" AND id=?" if org else "") + " ORDER BY id", (org,) if org else ()))
    result = {"not_submitted": [], "not_accepted": [], "accepted": []}
    for item in orgs:
        statuses = [r["status"] for r in db.execute("SELECT status FROM period_reports WHERE org_id=? AND period_start<=? AND period_end>=?", (item["id"], end, start))]
        if any(s == "accepted" for s in statuses):
            result["accepted"].append(item)
        elif any(s in ("submitted", "in_review", "returned") for s in statuses):
            # Sent at least once, but there is no accepted report yet (waiting for review or returned for rework).
            item["status"] = next(s for s in ("returned", "in_review", "submitted") if s in statuses)
            result["not_accepted"].append(item)
        else:
            result["not_submitted"].append(item)
    return result


def handle(h, db, user, method, path, query):
    if path == "/api/periods" and method == "GET":
        org = org_scope(user, query.get("org", [0])[0])
        periods = rows(db.execute("""SELECT p.*,o.name AS org_name,
            (SELECT COUNT(*) FROM reports r WHERE r.org_id=p.org_id AND r.report_date BETWEEN p.period_start AND p.period_end) AS records
            FROM period_reports p JOIN organizations o ON o.id=p.org_id WHERE (?=0 OR p.org_id=?) ORDER BY p.period_start DESC,p.org_id""", (org, org)))
        return h.respond({"periods": periods}) or True
    if path == "/api/periods/overview" and method == "GET":
        start, end = iso_day(query.get("start", [""])[0]).isoformat(), iso_day(query.get("end", [""])[0]).isoformat()
        return h.respond(overview(db, user, start, end)) or True
    if path == "/api/periods" and method == "POST":
        if user["role"] not in ("operator", "admin"):
            raise APIError("Кезең есебін жауапты қызметкер немесе әкімші ашады.", 403)
        data = h.body()
        org_id = own_org(db, user, data.get("org_id") or user["org_id"])
        if data.get("month"):
            start, end = month_range(data["month"])
        else:
            start, end = iso_day(data.get("start"), "Кезең басы"), iso_day(data.get("end"), "Кезең соңы")
        if start > end or (end - start).days > 366:
            raise APIError("Кезең шекараларын дұрыс көрсетіңіз.")
        existing = db.execute("SELECT id FROM period_reports WHERE org_id=? AND period_start=? AND period_end=?", (org_id, start.isoformat(), end.isoformat())).fetchone()
        if existing:
            return h.respond({"id": existing["id"], "existing": True}) or True
        if db.execute("SELECT 1 FROM period_reports WHERE org_id=? AND period_start<=? AND period_end>=?", (org_id, end.isoformat(), start.isoformat())).fetchone():
            raise APIError("Бұл күндерді басқа кезең есебі қамтиды.", 409)
        stamp = now()
        period_id = db.execute("INSERT INTO period_reports(org_id,period_start,period_end,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                               (org_id, start.isoformat(), end.isoformat(), user["id"], stamp, stamp)).lastrowid
        log(db, period_id, user["id"], None, "draft", "created")
        return h.respond({"id": period_id}, 201) or True
    match = re.fullmatch(r"/api/periods/(\d+)(/transition)?", path)
    if match:
        period = db.execute("SELECT * FROM period_reports WHERE id=?", (int(match[1]),)).fetchone()
        if not period:
            raise APIError("Кезең есебі табылмады.", 404)
        if user["role"] == "operator" and period["org_id"] != user["org_id"]:
            raise APIError("Бұл ұйымның есебіне рұқсат жоқ.", 403)
        if method == "GET" and not match[2]:
            return h.respond(period_detail(db, period)) or True
        if method == "POST" and match[2]:
            data = h.body()
            if data.get("updated_at") != period["updated_at"]:
                raise APIError("Есеп басқа терезеде өзгерді. Жаңартып, қайта көріңіз.", 409)
            transition(db, user, period, data.get("status"), data.get("comment"))
            return h.respond({"ok": True}) or True
    if path == "/api/registry" and method == "GET":
        items = measurements(db, user, query)
        return h.respond({"measurements": items, "summary": summarize(items)}) or True
    if path == "/api/export" and method == "GET" and query.get("format", [""])[0] in ("xlsx", "print"):
        journal = query.get("scope", [""])[0] == "journal"
        lang = "ru" if query.get("lang", ["kk"])[0] == "ru" else "kk"
        items = measurements(db, user, query, accepted_only=not journal)
        period = f"{query.get('start', ['…'])[0]} – {query.get('end', ['…'])[0]}"
        if query["format"][0] == "xlsx":
            body = xlsx(workbook(items, lang, journal, period))
            return send(h, body, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "qaldyq-journal.xlsx" if journal else "qaldyq-summary.xlsx") or True
        return send(h, print_page(workbook(items, lang, journal, period), lang).encode(), "text/html; charset=utf-8", None) or True
    return False


def send(h, body, mime, filename):
    h.send_response(200)
    h.send_header("Content-Type", mime)
    if filename:
        h.send_header("Content-Disposition", f'attachment; filename="{filename}"')
    h.send_header("Cache-Control", "no-store")
    h.send_header("Content-Length", str(len(body)))
    h.end_headers()
    h.wfile.write(body)


def workbook(items, lang, journal, period):
    """Sheets as (title, rows). The per-organization sheets follow the column structure of the ATU tables."""
    L, ru = LABELS[lang], lang == "ru"
    name = lambda item, key: (item.get(key + "_ru") if ru else None) or item[key]
    unit = lambda code: UNITS.get(code, code)
    head = [[L["title"]], [L["journal"] if journal else L["accepted"]], [f"{L['period']}: {period}"], [L["demo"]], [L["units_note"]], []]
    by_org_type, by_month = {}, {}
    for item in items:
        key = (item["org_id"], name(item, "org_name"), name(item, "waste"), unit(item["unit"]))
        entry = by_org_type.setdefault(key, [0.0, 0])
        entry[0] += item["quantity"]
        entry[1] += 1
        month = by_month.setdefault((item["date"][:7], item["org_id"], name(item, "org_name"), unit(item["unit"])), [0.0, 0])
        month[0] += item["quantity"]
        month[1] += 1
    summary = head + [[L["org"], L["waste"], L["unit"], L["quantity"], L["records"]]]
    summary += [[org, waste, u, round(v[0], 2), v[1]] for (_, org, waste, u), v in sorted(by_org_type.items())] or [[L["empty"]]]
    totals = {}
    for (_, org, _, u), v in by_org_type.items():
        totals[(org, u)] = totals.get((org, u), 0) + v[0]
    summary += [[]] + [[org, L["total"], u, round(v, 2), ""] for (org, u), v in sorted(totals.items())]
    months = head + [[L["month"], L["org"], L["unit"], L["quantity"], L["records"]]]
    months += [[m, org, u, round(v[0], 2), v[1]] for (m, _, org, u), v in sorted(by_month.items())] or [[L["empty"]]]
    sheets = [(L["summary"], summary), (L["months"], months)]
    orgs = {}
    for item in items:
        orgs.setdefault((item["org_id"], item.get("org_short") or name(item, "org_name"), name(item, "org_name")), []).append(item)
    for (_, short, full), entries in sorted(orgs.items()):
        header = [L["date"], L["waste"], L["quantity"], L["unit"], L["route"], L["responsible"], L["stage"]] + ([L["status"]] if journal else [])
        table = head[:3] + [[f"{L['org']}: {full}"], [], header]
        per_type = {}
        for item in entries:
            row = [item["date"], name(item, "waste"), item["quantity"], unit(item["unit"]), (item.get("route_name_ru") if ru else None) or item["route_name"] or item["route"],
                   item["responsible"], STAGE_NAMES[lang].get(item["stage"], item["stage"])]
            table.append(row + ([STATUS_NAMES[lang].get(item["status"], item["status"])] if journal else []))
            key = (name(item, "waste"), unit(item["unit"]))
            per_type[key] = per_type.get(key, 0) + item["quantity"]
        table += [[]] + [[L["total_type"], waste, round(v, 2), u] for (waste, u), v in sorted(per_type.items())]
        sheets.append((short, table))
    return sheets


def safe_cell(value):
    text = str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


def xlsx(sheets):
    """A real Office Open XML workbook, written with the standard library only."""
    def column(index):
        letters = ""
        while index >= 0:
            letters = chr(65 + index % 26) + letters
            index = index // 26 - 1
        return letters

    def sheet_xml(table):
        out = []
        for r, row in enumerate(table, 1):
            cells = []
            for c, value in enumerate(row):
                ref = f"{column(c)}{r}"
                if isinstance(value, bool) or value is None or value == "":
                    continue
                if isinstance(value, (int, float)):
                    cells.append(f'<c r="{ref}"><v>{value}</v></c>')
                else:
                    cells.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(safe_cell(value))}</t></is></c>')
            out.append(f'<row r="{r}">{"".join(cells)}</row>')
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                '<cols><col min="1" max="1" width="16" customWidth="1"/><col min="2" max="2" width="44" customWidth="1"/><col min="3" max="8" width="22" customWidth="1"/></cols>'
                f'<sheetData>{"".join(out)}</sheetData></worksheet>')

    names, used = [], set()
    for title, _ in sheets:
        clean = re.sub(r"[\[\]:*?/\\]", " ", str(title)).strip()[:31] or "Sheet"
        base, n = clean, 2
        while clean.casefold() in used:
            clean = f"{base[:28]} {n}"
            n += 1
        used.add(clean.casefold())
        names.append(clean)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                         '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
                         '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                         + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, len(sheets) + 1))
                         + "</Types>")
        archive.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                         '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                         'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                         + "".join(f'<sheet name="{escape(n, {chr(34): "&quot;"})}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(names, 1)) + "</sheets></workbook>")
        archive.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                         + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1))
                         + "</Relationships>")
        for i, (_, table) in enumerate(sheets, 1):
            archive.writestr(f"xl/worksheets/sheet{i}.xml", sheet_xml(table))
    return buffer.getvalue()


def print_page(sheets, lang):
    """A print-ready page: the browser's own dialog saves it as PDF."""
    from html import escape as e
    parts = [f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Qaldyq</title>'
             '<link rel="stylesheet" href="/print.css"><script src="/print.js" defer></script></head><body>']
    for title, table in sheets:
        parts.append(f"<section><h2>{e(str(title))}</h2><table>")
        for row in table:
            if not row:
                continue
            if len(row) == 1:
                parts.append(f'<tr><td class="note" colspan="8">{e(str(row[0]))}</td></tr>')
            else:
                parts.append("<tr>" + "".join(f"<td>{e(str(v))}</td>" for v in row) + "</tr>")
        parts.append("</table></section>")
    return "".join(parts) + "</body></html>"


def seed(db):
    """Demo period reports: two accepted months for every organization and different October states."""
    stamp = lambda day, hour: f"{day}T{hour:02d}:00:00+00:00"
    authors = {r["org_id"]: r["id"] for r in db.execute("SELECT id,org_id FROM users WHERE role='operator'")}
    for org in range(1, 6):
        for month, decided in (("2026-08", "2026-09-04"), ("2026-09", "2026-10-05")):
            start, end = month_range(month)
            pid = db.execute("INSERT INTO period_reports(org_id,period_start,period_end,status,submitted_at,reviewer_id,decided_at,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                             (org, start.isoformat(), end.isoformat(), "accepted", stamp(decided, 9), 2, stamp(decided, 15), authors[org], stamp(end, 16), stamp(decided, 15))).lastrowid
            steps = [(None, "draft", "created", authors[org], ""), ("draft", "submitted", "submitted", authors[org], ""), ("submitted", "in_review", "in_review", 2, "")]
            if org == 3 and month == "2026-09":
                steps += [("in_review", "returned", "returned", 2, "Картон ыдыс массасын таразы журналымен салыстырып, нақтылаңыз."),
                          ("returned", "submitted", "submitted", authors[org], "Түзетілді"), ("submitted", "in_review", "in_review", 2, "")]
            steps.append(("in_review", "accepted", "accepted", 2, ""))
            for n, (source, target, action, uid, comment) in enumerate(steps):
                db.execute("INSERT INTO period_history(period_id,from_status,to_status,action,user_id,comment,created_at) VALUES (?,?,?,?,?,?,?)",
                           (pid, source, target, action, uid, comment, stamp(decided, 9 + min(n, 6))))
            db.execute("UPDATE reports SET period_id=? WHERE org_id=? AND report_date BETWEEN ? AND ?", (pid, org, start.isoformat(), end.isoformat()))
    start, end = month_range("2026-10")
    for org, status, comment in ((1, "draft", ""), (2, "submitted", ""), (3, "in_review", ""), (4, "returned", "Ет сүйегінің 14 қазандағы массасын нақтылаңыз.")):
        pid = db.execute("INSERT INTO period_reports(org_id,period_start,period_end,status,submitted_at,reviewer_id,decided_at,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (org, start.isoformat(), end.isoformat(), status, None if status == "draft" else stamp("2026-10-30", 10), 2 if status in ("in_review", "returned") else None,
                          stamp("2026-10-30", 14) if status == "returned" else None, authors[org], stamp("2026-10-30", 9), stamp("2026-10-30", 14))).lastrowid
        chain = {"draft": ["draft"], "submitted": ["draft", "submitted"], "in_review": ["draft", "submitted", "in_review"], "returned": ["draft", "submitted", "in_review", "returned"]}[status]
        previous = None
        for n, target in enumerate(chain):
            reviewer_step = target in ("in_review", "returned")
            db.execute("INSERT INTO period_history(period_id,from_status,to_status,action,user_id,comment,created_at) VALUES (?,?,?,?,?,?,?)",
                       (pid, previous, target, "created" if previous is None else target, 2 if reviewer_step else authors[org], comment if target == "returned" else "", stamp("2026-10-30", 9 + n)))
            previous = target
