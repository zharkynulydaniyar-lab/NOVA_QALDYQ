"""Canteen management accounting: stock, recipes, production, sales, expenses, balance, shift handover (ТТ 12–14).

This is management accounting for decisions, not statutory bookkeeping.
Numbers: quantities are whole thousandths of the ingredient's base unit (g, ml, 0.001 pcs); money is whole tiyn.
Valuation: moving weighted average cost per organization and ingredient.
Physical picking: earliest expiry first (FEFO) among fit, unexpired batches — a separate rule from valuation."""
import json
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import common
from common import APIError, integer, money, now, org_scope, own_org, rows, text

BASE_UNITS = ("kg", "l", "pcs")
# Explicit, checkable conversions into a base unit. Mass ↔ volume needs a density and is refused.
CONVERSIONS = {("kg", "kg"): Decimal(1), ("g", "kg"): Decimal("0.001"), ("l", "l"): Decimal(1), ("ml", "l"): Decimal("0.001"), ("pcs", "pcs"): Decimal(1)}
EXPENSE_CATEGORIES = ("salary", "utilities", "rent", "equipment", "cleaning", "other")
WRITEOFF_REASONS = ("expired", "spoiled", "damaged", "other")


def migrate(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS ingredients(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL REFERENCES organizations(id), name TEXT NOT NULL, name_ru TEXT,
      unit TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, UNIQUE(org_id,name));
    CREATE TABLE IF NOT EXISTS purchases(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL REFERENCES organizations(id), day TEXT NOT NULL, supplier TEXT NOT NULL,
      ingredient_id INTEGER NOT NULL REFERENCES ingredients(id), qty_milli INTEGER NOT NULL CHECK(qty_milli>0), unit_price_tiyn INTEGER NOT NULL,
      total_tiyn INTEGER NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL, request_id TEXT, UNIQUE(created_by,request_id));
    CREATE TABLE IF NOT EXISTS stock_levels(org_id INTEGER NOT NULL, ingredient_id INTEGER NOT NULL REFERENCES ingredients(id), qty_milli INTEGER NOT NULL DEFAULT 0,
      value_tiyn INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(org_id,ingredient_id));
    CREATE TABLE IF NOT EXISTS stock_batches(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL, ingredient_id INTEGER NOT NULL REFERENCES ingredients(id),
      purchase_id INTEGER REFERENCES purchases(id), received_day TEXT NOT NULL, expiry_day TEXT, storage TEXT NOT NULL DEFAULT '', responsible_id INTEGER REFERENCES users(id),
      qty_milli_initial INTEGER NOT NULL, qty_milli_left INTEGER NOT NULL CHECK(qty_milli_left>=0), state TEXT NOT NULL DEFAULT 'ok');
    CREATE TABLE IF NOT EXISTS stock_moves(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL, ingredient_id INTEGER NOT NULL REFERENCES ingredients(id), batch_id INTEGER REFERENCES stock_batches(id),
      day TEXT NOT NULL, kind TEXT NOT NULL, qty_milli INTEGER NOT NULL, value_tiyn INTEGER NOT NULL, ref_type TEXT, ref_id INTEGER, reason TEXT, note TEXT NOT NULL DEFAULT '',
      waste_item_id INTEGER REFERENCES items(id), created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL, request_id TEXT);
    CREATE UNIQUE INDEX IF NOT EXISTS stock_moves_request ON stock_moves(created_by,request_id,batch_id) WHERE request_id IS NOT NULL;
    CREATE TABLE IF NOT EXISTS recipes(id INTEGER PRIMARY KEY, dish_id INTEGER NOT NULL REFERENCES catalog_dishes(id), version INTEGER NOT NULL, valid_from TEXT NOT NULL,
      valid_to TEXT, yield_portions INTEGER NOT NULL CHECK(yield_portions>0), note TEXT NOT NULL DEFAULT '', created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL, UNIQUE(dish_id,version));
    CREATE TABLE IF NOT EXISTS recipe_items(id INTEGER PRIMARY KEY, recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
      ingredient_id INTEGER NOT NULL REFERENCES ingredients(id), qty_milli INTEGER NOT NULL CHECK(qty_milli>0), entered_qty TEXT NOT NULL, entered_unit TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS productions(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL, day TEXT NOT NULL, dish_id INTEGER NOT NULL REFERENCES catalog_dishes(id),
      portions INTEGER NOT NULL CHECK(portions>0), recipe_id INTEGER NOT NULL REFERENCES recipes(id), cost_tiyn INTEGER NOT NULL, created_by INTEGER NOT NULL REFERENCES users(id),
      created_at TEXT NOT NULL, request_id TEXT, UNIQUE(created_by,request_id));
    CREATE TABLE IF NOT EXISTS expenses(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL, period_start TEXT NOT NULL, period_end TEXT NOT NULL, category TEXT NOT NULL,
      amount_tiyn INTEGER NOT NULL, note TEXT NOT NULL DEFAULT '', created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS day_close(org_id INTEGER NOT NULL, day TEXT NOT NULL, dish_id INTEGER NOT NULL REFERENCES catalog_dishes(id), unsold INTEGER NOT NULL DEFAULT 0,
      other INTEGER NOT NULL DEFAULT 0, other_note TEXT NOT NULL DEFAULT '', clarification TEXT NOT NULL DEFAULT '', updated_by INTEGER REFERENCES users(id), updated_at TEXT NOT NULL,
      PRIMARY KEY(org_id,day,dish_id));
    CREATE TABLE IF NOT EXISTS shortages(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL, day TEXT NOT NULL, dish_id INTEGER NOT NULL REFERENCES catalog_dishes(id), ended_at TEXT NOT NULL,
      unmet INTEGER, substitute TEXT NOT NULL DEFAULT '', comment TEXT NOT NULL DEFAULT '', created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS handovers(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL, from_user INTEGER NOT NULL REFERENCES users(id), to_user INTEGER REFERENCES users(id),
      created_at TEXT NOT NULL, accepted_at TEXT, snapshot TEXT NOT NULL, tasks TEXT NOT NULL DEFAULT '', problems TEXT NOT NULL DEFAULT '');
    """)


# ---------- quantities ----------

def milli(value, name="Мөлшер", unit=None, base=None, allow_negative=False):
    """Parse a decimal quantity into whole thousandths of the base unit, converting explicitly when a unit is given."""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise APIError(f"{name}: сан енгізіңіз.")
    if not amount.is_finite():
        raise APIError(f"{name}: сан енгізіңіз.")
    if unit is not None:
        factor = CONVERSIONS.get((unit, base))
        if factor is None:
            raise APIError(f"{name}: «{unit}» бірлігін «{base}» бірлігіне айналдыру коэффициенті жоқ.")
        amount *= factor
    result = amount * 1000
    if result != result.to_integral_value():
        raise APIError(f"{name}: дәлдік мыңнан бір бөлікке дейін болсын.")
    result = int(result)
    if (result <= 0 and not allow_negative) or result == 0 or abs(result) > 10**12:
        raise APIError(f"{name}: нөлден үлкен мән енгізіңіз.")
    return result


def qty(value_milli):
    return value_milli / 1000


def level(db, org_id, ingredient_id):
    row = db.execute("SELECT qty_milli,value_tiyn FROM stock_levels WHERE org_id=? AND ingredient_id=?", (org_id, ingredient_id)).fetchone()
    return (row["qty_milli"], row["value_tiyn"]) if row else (0, 0)


def set_level(db, org_id, ingredient_id, qty_milli, value_tiyn):
    db.execute("INSERT INTO stock_levels(org_id,ingredient_id,qty_milli,value_tiyn) VALUES (?,?,?,?) ON CONFLICT(org_id,ingredient_id) DO UPDATE SET qty_milli=excluded.qty_milli,value_tiyn=excluded.value_tiyn",
               (org_id, ingredient_id, qty_milli, value_tiyn))


def issue_value(on_hand_qty, on_hand_value, issued_qty):
    """Weighted average cost of an issue. Taking the last unit takes the whole remaining value, so rounding never drifts."""
    if issued_qty >= on_hand_qty:
        return on_hand_value
    return (on_hand_value * issued_qty + on_hand_qty // 2) // on_hand_qty


def usable_batches(db, org_id, ingredient_id, day):
    """Fit, unexpired batches in the order they should be used: earliest expiry first."""
    return db.execute("""SELECT * FROM stock_batches WHERE org_id=? AND ingredient_id=? AND qty_milli_left>0 AND state='ok' AND (expiry_day IS NULL OR expiry_day>=?)
        ORDER BY COALESCE(expiry_day,'9999-12-31'),received_day,id""", (org_id, ingredient_id, day)).fetchall()


def consume(db, user, org_id, ingredient_id, need_milli, day, kind, ref_type, ref_id, request_id=None, reason=None, note="", batch_id=None):
    """Take stock out: quantity from batches (FEFO or a named batch), value at weighted average cost. Returns the value in tiyn."""
    batches = [db.execute("SELECT * FROM stock_batches WHERE id=? AND org_id=? AND ingredient_id=?", (batch_id, org_id, ingredient_id)).fetchone()] if batch_id else usable_batches(db, org_id, ingredient_id, day)
    batches = [b for b in batches if b and b["qty_milli_left"] > 0]
    if sum(b["qty_milli_left"] for b in batches) < need_milli:
        name = db.execute("SELECT name FROM ingredients WHERE id=?", (ingredient_id,)).fetchone()["name"]
        raise APIError(f"«{name}» жеткіліксіз: жарамды қалдық {qty(sum(b['qty_milli_left'] for b in batches))}, қажеті {qty(need_milli)}.", 409)
    total_value, left = 0, need_milli
    for batch in batches:
        if not left:
            break
        take = min(left, batch["qty_milli_left"])
        on_hand_qty, on_hand_value = level(db, org_id, ingredient_id)
        value = issue_value(on_hand_qty, on_hand_value, take)
        set_level(db, org_id, ingredient_id, on_hand_qty - take, on_hand_value - value)
        db.execute("UPDATE stock_batches SET qty_milli_left=qty_milli_left-? WHERE id=?", (take, batch["id"]))
        db.execute("""INSERT INTO stock_moves(org_id,ingredient_id,batch_id,day,kind,qty_milli,value_tiyn,ref_type,ref_id,reason,note,created_by,created_at,request_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (org_id, ingredient_id, batch["id"], day, kind, -take, -value, ref_type, ref_id, reason, note, user["id"], now(), request_id))
        total_value += value
        left -= take
    return total_value


def replayed(db, table, user, request_id):
    if request_id is None:
        return None
    if not isinstance(request_id, str) or not re.fullmatch(r"[a-zA-Z0-9-]{16,80}", request_id):
        raise APIError("Сұрау кілті дұрыс емес.")
    return db.execute(f"SELECT id FROM {table} WHERE created_by=? AND request_id=?", (user["id"], request_id)).fetchone()


def active_recipe(db, dish_id, day):
    return db.execute("SELECT * FROM recipes WHERE dish_id=? AND valid_from<=? AND (valid_to IS NULL OR valid_to>=?) ORDER BY version DESC LIMIT 1", (dish_id, day, day)).fetchone()


def requirements(db, org_id, plan, day):
    """Ingredients needed for a plan {dish_id: portions}, minus fit unexpired stock on that day."""
    need, missing = {}, []
    for dish_id, portions in plan.items():
        recipe = active_recipe(db, dish_id, day)
        if not recipe:
            missing.append(dish_id)
            continue
        for item in db.execute("SELECT ingredient_id,qty_milli FROM recipe_items WHERE recipe_id=?", (recipe["id"],)):
            # Round up: a fraction of a gram short still means the batch cannot be cooked.
            need[item["ingredient_id"]] = need.get(item["ingredient_id"], 0) + -(-item["qty_milli"] * portions // recipe["yield_portions"])
    result = []
    for ingredient_id, amount in sorted(need.items()):
        info = db.execute("SELECT name,name_ru,unit FROM ingredients WHERE id=?", (ingredient_id,)).fetchone()
        on_hand = sum(b["qty_milli_left"] for b in usable_batches(db, org_id, ingredient_id, day))
        result.append({"ingredient_id": ingredient_id, "name": info["name"], "name_ru": info["name_ru"], "unit": info["unit"], "need": qty(amount), "usable_stock": qty(on_hand), "to_buy": qty(max(0, amount - on_hand))})
    return {"items": result, "dishes_without_recipe": missing}


def stock_view(db, org_id, today):
    levels = rows(db.execute("""SELECT i.id AS ingredient_id,i.name,i.name_ru,i.unit,COALESCE(l.qty_milli,0) AS qty_milli,COALESCE(l.value_tiyn,0) AS value_tiyn
        FROM ingredients i LEFT JOIN stock_levels l ON l.ingredient_id=i.id AND l.org_id=i.org_id WHERE i.org_id=? AND i.active=1 ORDER BY i.name""", (org_id,)))
    for item in levels:
        item["qty"] = qty(item["qty_milli"])
        item["avg_cost_tiyn"] = round(item["value_tiyn"] * 1000 / item["qty_milli"]) if item["qty_milli"] else None
    batches = rows(db.execute("""SELECT b.*,i.name,i.name_ru,i.unit,u.name AS responsible FROM stock_batches b JOIN ingredients i ON i.id=b.ingredient_id LEFT JOIN users u ON u.id=b.responsible_id
        WHERE b.org_id=? AND b.qty_milli_left>0 ORDER BY COALESCE(b.expiry_day,'9999-12-31'),b.id""", (org_id,)))
    soon = (today + timedelta(days=2)).isoformat()
    for batch in batches:
        batch["qty_left"] = qty(batch["qty_milli_left"])
        expired = bool(batch["expiry_day"]) and batch["expiry_day"] < today.isoformat()
        batch["condition"] = "unfit" if batch["state"] != "ok" else "expired" if expired else "soon" if batch["expiry_day"] and batch["expiry_day"] <= soon else "ok"
        batch["usable"] = batch["condition"] in ("ok", "soon")
    return {"levels": levels, "batches": batches, "method": "Қор бағасы: орташа өлшенген құн. Физикалық пайдалану реті: жарамдылық мерзімі ең жақын партия бірінші (FEFO)."}


def balance(db, org_id, day):
    """Portion balance per dish. Plate leftovers are waste mass, not portions: an issued portion stays sold."""
    dishes = {}
    def entry(dish_id, name):
        return dishes.setdefault(dish_id, {"dish_id": dish_id, "name": name, "prepared": 0, "sold": 0, "unsold": None, "other": 0, "other_note": "", "clarification": "", "shortage": False})
    for row in db.execute("SELECT p.dish_id,d.name,SUM(p.portions) AS n FROM productions p JOIN catalog_dishes d ON d.id=p.dish_id WHERE p.org_id=? AND p.day=? GROUP BY p.dish_id", (org_id, day)):
        entry(row["dish_id"], row["name"])["prepared"] = row["n"]
    for row in db.execute("SELECT s.dish_id,d.name,SUM(s.qty) AS n FROM sales s JOIN catalog_dishes d ON d.id=s.dish_id WHERE s.org_id=? AND s.day=? GROUP BY s.dish_id", (org_id, day)):
        entry(row["dish_id"], row["name"])["sold"] = row["n"]
    for row in db.execute("SELECT c.*,d.name FROM day_close c JOIN catalog_dishes d ON d.id=c.dish_id WHERE c.org_id=? AND c.day=?", (org_id, day)):
        item = entry(row["dish_id"], row["name"])
        item.update(unsold=row["unsold"], other=row["other"], other_note=row["other_note"], clarification=row["clarification"])
    for row in db.execute("SELECT DISTINCT dish_id FROM shortages WHERE org_id=? AND day=?", (org_id, day)):
        if row["dish_id"] in dishes:
            dishes[row["dish_id"]]["shortage"] = True
    for item in dishes.values():
        if item["unsold"] is None:
            item["unexplained"], item["state"] = None, "open"  # the unsold count is unknown, not zero
        else:
            item["unexplained"] = item["prepared"] - item["sold"] - item["unsold"] - item["other"]
            item["state"] = "balanced" if item["unexplained"] == 0 else "clarify"
    return sorted(dishes.values(), key=lambda d: d["name"])


def finance(db, org_id, start, end):
    """Management result for a period. Purchases are cash out and are shown apart: the same ingredients reduce the
    result only once, when they are used (cost of production) or written off."""
    one = lambda sql, args: db.execute(sql, args).fetchone()[0] or 0
    revenue = one("SELECT SUM(total_tiyn) FROM sales WHERE org_id=? AND day BETWEEN ? AND ?", (org_id, start, end))
    paid = one("SELECT SUM(total_tiyn) FROM sales WHERE org_id=? AND day BETWEEN ? AND ? AND payment_status='paid'", (org_id, start, end))
    cogs = -one("SELECT SUM(value_tiyn) FROM stock_moves WHERE org_id=? AND kind='production' AND day BETWEEN ? AND ?", (org_id, start, end))
    writeoffs = -one("SELECT SUM(value_tiyn) FROM stock_moves WHERE org_id=? AND kind='writeoff' AND day BETWEEN ? AND ?", (org_id, start, end))
    adjustments = one("SELECT SUM(value_tiyn) FROM stock_moves WHERE org_id=? AND kind='adjustment' AND day BETWEEN ? AND ?", (org_id, start, end))
    purchases = one("SELECT SUM(total_tiyn) FROM purchases WHERE org_id=? AND day BETWEEN ? AND ?", (org_id, start, end))
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    extra = 0
    for row in db.execute("SELECT * FROM expenses WHERE org_id=? AND period_start<=? AND period_end>=?", (org_id, end, start)):
        a, b = date.fromisoformat(row["period_start"]), date.fromisoformat(row["period_end"])
        overlap = (min(b, last) - max(a, first)).days + 1
        extra += (row["amount_tiyn"] * overlap + ((b - a).days + 1) // 2) // ((b - a).days + 1)  # pro rata by days
    portions = one("SELECT SUM(portions) FROM productions WHERE org_id=? AND day BETWEEN ? AND ?", (org_id, start, end))
    return {"revenue_tiyn": revenue, "paid_tiyn": paid, "unpaid_tiyn": revenue - paid, "cost_of_production_tiyn": cogs, "writeoffs_tiyn": writeoffs, "adjustments_tiyn": adjustments,
            "other_expenses_tiyn": extra, "result_tiyn": revenue - cogs - writeoffs + adjustments - extra, "purchases_paid_tiyn": purchases,
            "stock_value_tiyn": one("SELECT SUM(value_tiyn) FROM stock_levels WHERE org_id=?", (org_id,)), "portions_prepared": portions,
            "cost_per_portion_tiyn": round(cogs / portions) if portions else None,
            "formula": "Нәтиже = тіркелген сатылым − жұмсалған қор құны − есептен шығару ± түзетулер − кезең шығындары. Сатып алу төлемі нәтижеге қосылмайды: ол қорға айналады.",
            "label": "Басқарушылық есеп (бухгалтерлік есеп емес)"}


def waste_draft_item(db, user, org_id, day, category_id, quantity, note):
    """Register a stock write-off as one waste measurement (stage: storage). The move keeps the link, so it is counted once."""
    cat = db.execute("SELECT c.* FROM categories c JOIN org_categories oc ON oc.category_id=c.id WHERE c.id=? AND oc.org_id=? AND c.active=1", (category_id, org_id)).fetchone()
    if not cat:
        raise APIError("Қалдық түрін ұйым тізімінен таңдаңыз.")
    import mod_period
    mod_period.ensure_unlocked(db, org_id, day)
    stamp = now()
    record = db.execute("SELECT id FROM reports WHERE org_id=? AND author_id=? AND report_date=? AND status='draft' ORDER BY id DESC LIMIT 1", (org_id, user["id"], day)).fetchone()
    report_id = record["id"] if record else db.execute("INSERT INTO reports(org_id,author_id,report_date,status,note,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                                                        (org_id, user["id"], day, "draft", "Қоймадан есептен шығару", stamp, stamp)).lastrowid
    if not record:
        db.execute("INSERT INTO history(report_id,user_id,action,comment,created_at) VALUES (?,?,'created','Қоймадан есептен шығару',?)", (report_id, user["id"], stamp))
    return db.execute("INSERT INTO items(report_id,category_id,kg,route,cost,co2,stage,note) VALUES (?,?,?,?,?,?,?,?)",
                      (report_id, cat["id"], quantity, cat["default_route"], cat["cost"], cat["co2"], "storage", note)).lastrowid


def handle(h, db, user, method, path, query):
    prefixes = ("/api/ingredients", "/api/purchases", "/api/stock", "/api/recipes", "/api/productions", "/api/sales", "/api/expenses", "/api/finance", "/api/balance", "/api/shortages", "/api/handovers", "/api/requirements")
    if not path.startswith(prefixes):
        return False
    if user["role"] not in ("operator", "admin", "manager"):
        raise APIError("Бұл бөлім асхана қызметкері, әкімші және басшылыққа арналған.", 403)
    if method != "GET" and user["role"] == "manager":
        raise APIError("Басшылық деректі тек қарай алады.", 403)
    today = common.local_now().date()
    org = org_scope(user, query.get("org", [0])[0])
    if method == "GET" and not org:
        raise APIError("Асхананы таңдаңыз.")
    data = h.body() if method != "GET" else {}
    org_id = own_org(db, user, data.get("org_id") or user["org_id"]) if method != "GET" else org
    day = lambda key="day": common.iso_day(data.get(key) or today.isoformat()).isoformat()

    if path == "/api/ingredients":
        if method == "GET":
            return h.respond({"ingredients": rows(db.execute("SELECT * FROM ingredients WHERE org_id=? ORDER BY name", (org,)))}) or True
        unit = data.get("unit")
        if unit not in BASE_UNITS:
            raise APIError("Негізгі бірлікті таңдаңыз: кг, л немесе дана.")
        ingredient_id = db.execute("INSERT INTO ingredients(org_id,name,name_ru,unit) VALUES (?,?,?,?)", (org_id, text(data.get("name"), "Өнім атауы", 2, 80), text(data.get("name_ru") or "", "Орысша атауы", 0, 80) or None, unit)).lastrowid
        return h.respond({"ok": True, "id": ingredient_id}, 201) or True

    if path == "/api/purchases":
        if method == "GET":
            start, end = query.get("start", ["0000"])[0], query.get("end", ["9999"])[0]
            return h.respond({"purchases": rows(db.execute("""SELECT p.*,i.name,i.unit FROM purchases p JOIN ingredients i ON i.id=p.ingredient_id
                WHERE p.org_id=? AND p.day BETWEEN ? AND ? ORDER BY p.day DESC,p.id DESC LIMIT 300""", (org, start, end)))}) or True
        previous = replayed(db, "purchases", user, data.get("request_id"))
        if previous:
            return h.respond({"ok": True, "id": previous["id"], "replayed": True}, 201) or True
        ingredient = db.execute("SELECT * FROM ingredients WHERE id=? AND org_id=?", (int(data.get("ingredient_id") or 0), org_id)).fetchone()
        if not ingredient:
            raise APIError("Өнімді өз ұйымыңыздың тізімінен таңдаңыз.")
        amount = milli(data.get("qty"), "Саны", data.get("unit") or ingredient["unit"], ingredient["unit"])
        total = money(data.get("total"), "Сомасы")
        purchase_day, expiry = day(), common.iso_day(data["expiry_day"], "Жарамдылық мерзімі").isoformat() if data.get("expiry_day") else None
        if purchase_day > today.isoformat():
            raise APIError("Болашақ күнге сатып алу тіркелмейді.")
        if expiry and expiry < purchase_day:
            raise APIError("Жарамдылық мерзімі қабылдау күнінен ерте болмасын.")
        unit_price = (total * 1000 + amount // 2) // amount
        purchase_id = db.execute("INSERT INTO purchases(org_id,day,supplier,ingredient_id,qty_milli,unit_price_tiyn,total_tiyn,created_by,created_at,request_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                                 (org_id, purchase_day, text(data.get("supplier"), "Жеткізуші", 1, 120), ingredient["id"], amount, unit_price, total, user["id"], now(), data.get("request_id"))).lastrowid
        batch_id = db.execute("INSERT INTO stock_batches(org_id,ingredient_id,purchase_id,received_day,expiry_day,storage,responsible_id,qty_milli_initial,qty_milli_left) VALUES (?,?,?,?,?,?,?,?,?)",
                              (org_id, ingredient["id"], purchase_id, purchase_day, expiry, text(data.get("storage") or "", "Сақтау орны", 0, 80), user["id"], amount, amount)).lastrowid
        on_hand_qty, on_hand_value = level(db, org_id, ingredient["id"])
        set_level(db, org_id, ingredient["id"], on_hand_qty + amount, on_hand_value + total)
        db.execute("INSERT INTO stock_moves(org_id,ingredient_id,batch_id,day,kind,qty_milli,value_tiyn,ref_type,ref_id,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (org_id, ingredient["id"], batch_id, purchase_day, "receipt", amount, total, "purchase", purchase_id, user["id"], now()))
        return h.respond({"ok": True, "id": purchase_id, "batch_id": batch_id}, 201) or True

    if path == "/api/stock" and method == "GET":
        return h.respond(stock_view(db, org, today)) or True
    if path == "/api/stock/moves" and method == "GET":
        return h.respond({"moves": rows(db.execute("""SELECT m.*,i.name,i.unit,u.name AS author FROM stock_moves m JOIN ingredients i ON i.id=m.ingredient_id JOIN users u ON u.id=m.created_by
            WHERE m.org_id=? ORDER BY m.id DESC LIMIT 200""", (org,)))}) or True
    if path == "/api/stock/writeoff" and method == "POST":
        batch = db.execute("SELECT * FROM stock_batches WHERE id=? AND org_id=?", (int(data.get("batch_id") or 0), org_id)).fetchone()
        if not batch:
            raise APIError("Партия табылмады.", 404)
        request_id = data.get("request_id")
        if request_id and db.execute("SELECT 1 FROM stock_moves WHERE created_by=? AND request_id=?", (user["id"], request_id)).fetchone():
            return h.respond({"ok": True, "replayed": True}) or True  # the same request never writes stock off twice
        ingredient = db.execute("SELECT * FROM ingredients WHERE id=?", (batch["ingredient_id"],)).fetchone()
        amount = milli(data.get("qty"), "Саны", data.get("unit") or ingredient["unit"], ingredient["unit"])
        if data.get("reason") not in WRITEOFF_REASONS:
            raise APIError("Есептен шығару себебін таңдаңыз.")
        write_day = day()
        before = db.execute("SELECT COALESCE(MAX(id),0) FROM stock_moves").fetchone()[0]
        value = consume(db, user, org_id, ingredient["id"], amount, write_day, "writeoff", "batch", batch["id"], request_id, data["reason"], text(data.get("note") or "", "Ескертпе", 0, 300), batch_id=batch["id"])
        waste_item = None
        if data.get("waste_category_id"):
            if ingredient["unit"] not in ("kg", "l"):
                raise APIError("Данамен есептелетін өнімді қалдық өлшеміне автоматты қосуға болмайды. Массасын өлшеп, бөлек енгізіңіз.")
            cat = db.execute("SELECT unit FROM categories WHERE id=?", (int(data["waste_category_id"]),)).fetchone()
            if not cat or cat["unit"] != ingredient["unit"]:
                raise APIError("Қалдық түрінің бірлігі өнім бірлігіне сәйкес келмейді (кг ↔ л айналдыру коэффициенті жоқ).")
            waste_item = waste_draft_item(db, user, org_id, write_day, int(data["waste_category_id"]), qty(amount), f"Қоймадан есептен шығару: {ingredient['name']}")
            db.execute("UPDATE stock_moves SET waste_item_id=? WHERE id>? AND kind='writeoff' AND batch_id=?", (waste_item, before, batch["id"]))
        return h.respond({"ok": True, "value_tiyn": value, "waste_item_id": waste_item}, 201) or True
    if path == "/api/stock/adjust" and method == "POST":
        # A traceable correction: history is never edited, a signed move with a note is added instead.
        batch = db.execute("SELECT * FROM stock_batches WHERE id=? AND org_id=?", (int(data.get("batch_id") or 0), org_id)).fetchone()
        if not batch:
            raise APIError("Партия табылмады.", 404)
        ingredient = db.execute("SELECT * FROM ingredients WHERE id=?", (batch["ingredient_id"],)).fetchone()
        delta = milli(data.get("qty_delta"), "Түзету", data.get("unit") or ingredient["unit"], ingredient["unit"], allow_negative=True)
        note = text(data.get("note"), "Түзету себебі", 3, 300)
        if batch["qty_milli_left"] + delta < 0:
            raise APIError("Түзету партия қалдығынан аспасын.")
        on_hand_qty, on_hand_value = level(db, org_id, ingredient["id"])
        if delta < 0:
            value = -issue_value(on_hand_qty, on_hand_value, -delta)
        else:
            value = (on_hand_value * delta + on_hand_qty // 2) // on_hand_qty if on_hand_qty else 0  # found stock enters at the current average cost
        set_level(db, org_id, ingredient["id"], on_hand_qty + delta, on_hand_value + value)
        db.execute("UPDATE stock_batches SET qty_milli_left=qty_milli_left+? WHERE id=?", (delta, batch["id"]))
        db.execute("INSERT INTO stock_moves(org_id,ingredient_id,batch_id,day,kind,qty_milli,value_tiyn,ref_type,ref_id,note,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (org_id, ingredient["id"], batch["id"], today.isoformat(), "adjustment", delta, value, "batch", batch["id"], note, user["id"], now()))
        return h.respond({"ok": True}, 201) or True
    if path == "/api/stock/batch-state" and method == "POST":
        if data.get("state") not in ("ok", "unfit"):
            raise APIError("Күйді таңдаңыз.")
        if db.execute("UPDATE stock_batches SET state=? WHERE id=? AND org_id=?", (data["state"], int(data.get("batch_id") or 0), org_id)).rowcount != 1:
            raise APIError("Партия табылмады.", 404)
        return h.respond({"ok": True}) or True

    if path == "/api/recipes":
        if method == "GET":
            recipes = rows(db.execute("""SELECT r.*,d.name AS dish FROM recipes r JOIN catalog_dishes d ON d.id=r.dish_id WHERE d.org_id=? ORDER BY d.name,r.version DESC""", (org,)))
            items = rows(db.execute("""SELECT ri.*,i.name,i.unit FROM recipe_items ri JOIN ingredients i ON i.id=ri.ingredient_id JOIN recipes r ON r.id=ri.recipe_id
                JOIN catalog_dishes d ON d.id=r.dish_id WHERE d.org_id=?""", (org,)))
            for recipe in recipes:
                recipe["items"] = [i for i in items if i["recipe_id"] == recipe["id"]]
                recipe["current"] = recipe["valid_from"] <= today.isoformat() and (recipe["valid_to"] is None or recipe["valid_to"] >= today.isoformat())
            return h.respond({"recipes": recipes}) or True
        dish = db.execute("SELECT * FROM catalog_dishes WHERE id=? AND org_id=?", (int(data.get("dish_id") or 0), org_id)).fetchone()
        if not dish:
            raise APIError("Тағамды өз каталогыңыздан таңдаңыз.")
        valid_from = common.iso_day(data.get("valid_from") or today.isoformat(), "Қолданыс басы")
        raw = data.get("items")
        if not isinstance(raw, list) or not 1 <= len(raw) <= 40:
            raise APIError("Рецептураға кемінде бір өнім қосыңыз.")
        lines, seen = [], set()
        for line in raw:
            ingredient = db.execute("SELECT * FROM ingredients WHERE id=? AND org_id=?", (int((line or {}).get("ingredient_id") or 0), org_id)).fetchone()
            if not ingredient or ingredient["id"] in seen:
                raise APIError("Әр өнімді өз тізіміңізден бір рет таңдаңыз.")
            seen.add(ingredient["id"])
            unit = line.get("unit") or ingredient["unit"]
            lines.append((ingredient["id"], milli(line.get("qty"), f"{ingredient['name']} мөлшері", unit, ingredient["unit"]), str(line.get("qty")), unit))
        last = db.execute("SELECT * FROM recipes WHERE dish_id=? ORDER BY version DESC LIMIT 1", (dish["id"],)).fetchone()
        if last:
            if valid_from.isoformat() <= last["valid_from"]:
                raise APIError("Жаңа нұсқаның қолданыс басы алдыңғы нұсқадан кейін болсын.")
            # The earlier version is closed, not changed: productions made with it keep pointing at it.
            db.execute("UPDATE recipes SET valid_to=? WHERE id=?", ((valid_from - timedelta(days=1)).isoformat(), last["id"]))
        recipe_id = db.execute("INSERT INTO recipes(dish_id,version,valid_from,yield_portions,note,created_by,created_at) VALUES (?,?,?,?,?,?,?)",
                               (dish["id"], (last["version"] + 1) if last else 1, valid_from.isoformat(), integer(data.get("yield_portions"), "Шығымы, порция", 1, 5000), text(data.get("note") or "", "Ескертпе", 0, 300), user["id"], now())).lastrowid
        db.executemany("INSERT INTO recipe_items(recipe_id,ingredient_id,qty_milli,entered_qty,entered_unit) VALUES (?,?,?,?,?)", [(recipe_id, *line) for line in lines])
        return h.respond({"ok": True, "id": recipe_id}, 201) or True

    if path == "/api/productions":
        if method == "GET":
            when = common.iso_day(query.get("date", [today.isoformat()])[0]).isoformat()
            return h.respond({"productions": rows(db.execute("""SELECT p.*,d.name AS dish,r.version FROM productions p JOIN catalog_dishes d ON d.id=p.dish_id JOIN recipes r ON r.id=p.recipe_id
                WHERE p.org_id=? AND p.day=? ORDER BY p.id""", (org, when)))}) or True
        previous = replayed(db, "productions", user, data.get("request_id"))
        if previous:
            return h.respond({"ok": True, "id": previous["id"], "replayed": True}, 201) or True
        dish = db.execute("SELECT * FROM catalog_dishes WHERE id=? AND org_id=?", (int(data.get("dish_id") or 0), org_id)).fetchone()
        if not dish:
            raise APIError("Тағамды өз каталогыңыздан таңдаңыз.")
        cook_day, portions = day(), integer(data.get("portions"), "Порция саны", 1, 5000)
        if cook_day > today.isoformat():
            raise APIError("Болашақ күнге дайындау тіркелмейді.")
        recipe = active_recipe(db, dish["id"], cook_day)
        if not recipe:
            raise APIError("Бұл күнге қолданыстағы рецептура жоқ. Алдымен рецептураны енгізіңіз.", 409)
        production_id = db.execute("INSERT INTO productions(org_id,day,dish_id,portions,recipe_id,cost_tiyn,created_by,created_at,request_id) VALUES (?,?,?,?,?,0,?,?,?)",
                                   (org_id, cook_day, dish["id"], portions, recipe["id"], user["id"], now(), data.get("request_id"))).lastrowid
        cost = 0
        for item in db.execute("SELECT ingredient_id,qty_milli FROM recipe_items WHERE recipe_id=?", (recipe["id"],)).fetchall():
            cost += consume(db, user, org_id, item["ingredient_id"], -(-item["qty_milli"] * portions // recipe["yield_portions"]), cook_day, "production", "production", production_id)
        db.execute("UPDATE productions SET cost_tiyn=? WHERE id=?", (cost, production_id))
        return h.respond({"ok": True, "id": production_id, "cost_tiyn": cost, "cost_per_portion_tiyn": round(cost / portions)}, 201) or True

    if path == "/api/sales":
        if method == "GET":
            start, end = query.get("start", [today.isoformat()])[0], query.get("end", [today.isoformat()])[0]
            return h.respond({"sales": rows(db.execute("""SELECT day,name,portion_label,source,SUM(qty) AS qty,SUM(total_tiyn) AS total_tiyn,
                SUM(CASE WHEN payment_status='paid' THEN total_tiyn ELSE 0 END) AS paid_tiyn FROM sales WHERE org_id=? AND day BETWEEN ? AND ?
                GROUP BY day,name,portion_label,source ORDER BY day DESC,name""", (org, start, end)))}) or True
        # Counter sale without a pre-order. Issued pre-orders create their sale themselves, so they cannot be entered twice here.
        previous = replayed(db, "sales", user, data.get("request_id"))
        if previous:
            return h.respond({"ok": True, "id": previous["id"], "replayed": True}, 201) or True
        portion = db.execute("SELECT p.*,d.name,d.org_id FROM dish_portions p JOIN catalog_dishes d ON d.id=p.dish_id WHERE p.id=? AND d.org_id=?", (int(data.get("portion_id") or 0), org_id)).fetchone()
        if not portion:
            raise APIError("Порцияны өз каталогыңыздан таңдаңыз.")
        amount, sale_day = integer(data.get("qty"), "Саны", 1, 2000), day()
        if sale_day > today.isoformat():
            raise APIError("Болашақ күнге сатылым тіркелмейді.")
        method_name = data.get("payment_method") or "cash"
        if method_name not in ("cash", "card", "other"):
            raise APIError("Төлем тәсілін таңдаңыз.")
        sale_id = db.execute("""INSERT INTO sales(org_id,day,dish_id,portion_id,name,portion_label,qty,price_tiyn,total_tiyn,source,payment_method,payment_status,created_by,created_at,request_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (org_id, sale_day, portion["dish_id"], portion["id"], portion["name"], portion["label"], amount, portion["price_tiyn"], portion["price_tiyn"] * amount,
                                                  "counter", method_name, "paid" if data.get("paid", True) else "unpaid", user["id"], now(), data.get("request_id"))).lastrowid
        return h.respond({"ok": True, "id": sale_id}, 201) or True

    if path == "/api/expenses":
        if method == "GET":
            return h.respond({"expenses": rows(db.execute("SELECT * FROM expenses WHERE org_id=? ORDER BY period_start DESC,id DESC LIMIT 200", (org,)))}) or True
        start, end = common.iso_day(data.get("period_start"), "Кезең басы"), common.iso_day(data.get("period_end"), "Кезең соңы")
        if start > end or data.get("category") not in EXPENSE_CATEGORIES:
            raise APIError("Кезең мен шығын санатын дұрыс көрсетіңіз.")
        expense_id = db.execute("INSERT INTO expenses(org_id,period_start,period_end,category,amount_tiyn,note,created_by,created_at) VALUES (?,?,?,?,?,?,?,?)",
                                (org_id, start.isoformat(), end.isoformat(), data["category"], money(data.get("amount"), "Сомасы"), text(data.get("note") or "", "Ескертпе", 0, 300), user["id"], now())).lastrowid
        return h.respond({"ok": True, "id": expense_id}, 201) or True

    if path == "/api/finance" and method == "GET":
        start = common.iso_day(query.get("start", [today.replace(day=1).isoformat()])[0]).isoformat()
        end = common.iso_day(query.get("end", [today.isoformat()])[0]).isoformat()
        if start > end:
            raise APIError("Кезең шекараларын дұрыс көрсетіңіз.")
        report = finance(db, org, start, end)
        demo = db.execute("""SELECT ROUND(SUM(i.kg*i.cost),2) FROM items i JOIN reports r ON r.id=i.report_id WHERE r.org_id=? AND r.status='accepted' AND r.report_date BETWEEN ? AND ?""", (org, start, end)).fetchone()[0] or 0
        report["waste_estimate_tenge"] = demo
        report["waste_estimate_note"] = "Қалдық құнының демо бағасы (масса × санат коэффициенті). Бұл — есептен шығару сомасымен бір оқиғаның екі бағасы болуы мүмкін, сондықтан олар қосылмайды."
        return h.respond(report) or True

    if path == "/api/balance":
        if method == "GET":
            when = common.iso_day(query.get("date", [today.isoformat()])[0]).isoformat()
            return h.respond({"date": when, "dishes": balance(db, org, when)}) or True
        dish = db.execute("SELECT id FROM catalog_dishes WHERE id=? AND org_id=?", (int(data.get("dish_id") or 0), org_id)).fetchone()
        if not dish:
            raise APIError("Тағамды өз каталогыңыздан таңдаңыз.")
        if int(data.get("other") or 0) and not str(data.get("other_note") or "").strip():
            raise APIError("Басқа қозғалысты құжатпен немесе түсіндірмемен көрсетіңіз.")
        db.execute("""INSERT INTO day_close(org_id,day,dish_id,unsold,other,other_note,clarification,updated_by,updated_at) VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(org_id,day,dish_id) DO UPDATE SET unsold=excluded.unsold,other=excluded.other,other_note=excluded.other_note,clarification=excluded.clarification,updated_by=excluded.updated_by,updated_at=excluded.updated_at""",
                   (org_id, day(), dish["id"], integer(data.get("unsold"), "Сатылмаған порция", 0, 5000), integer(data.get("other") or 0, "Басқа қозғалыс", 0, 5000),
                    text(data.get("other_note") or "", "Басқа қозғалыс түсіндірмесі", 0, 200), text(data.get("clarification") or "", "Түсіндірме", 0, 300), user["id"], now()))
        return h.respond({"ok": True}) or True

    if path == "/api/shortages":
        if method == "GET":
            start, end = query.get("start", ["0000"])[0], query.get("end", ["9999"])[0]
            return h.respond({"shortages": rows(db.execute("""SELECT s.*,d.name AS dish FROM shortages s JOIN catalog_dishes d ON d.id=s.dish_id WHERE s.org_id=? AND s.day BETWEEN ? AND ? ORDER BY s.day DESC,s.id DESC""", (org, start, end)))}) or True
        dish = db.execute("SELECT id FROM catalog_dishes WHERE id=? AND org_id=?", (int(data.get("dish_id") or 0), org_id)).fetchone()
        if not dish or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(data.get("ended_at") or "")):
            raise APIError("Тағамды және таусылған уақытты (СС:ММ) көрсетіңіз.")
        unmet = integer(data["unmet"], "Қанағаттандырылмаған сұраныс", 0, 5000) if data.get("unmet") not in (None, "") else None  # unknown stays unknown
        shortage_id = db.execute("INSERT INTO shortages(org_id,day,dish_id,ended_at,unmet,substitute,comment,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                                 (org_id, day(), dish["id"], data["ended_at"], unmet, text(data.get("substitute") or "", "Ұсынылған алмастыру", 0, 120), text(data.get("comment") or "", "Түсіндірме", 0, 300), user["id"], now())).lastrowid
        return h.respond({"ok": True, "id": shortage_id}, 201) or True

    if path == "/api/handovers":
        if method == "GET":
            result = rows(db.execute("""SELECT x.*,a.name AS from_name,b.name AS to_name FROM handovers x JOIN users a ON a.id=x.from_user LEFT JOIN users b ON b.id=x.to_user
                WHERE x.org_id=? ORDER BY x.id DESC LIMIT 30""", (org,)))
            for item in result:
                item["snapshot"] = json.loads(item["snapshot"])
            return h.respond({"handovers": result}) or True
        view = stock_view(db, org_id, today)
        snapshot = {"stock": [{"name": l["name"], "qty": l["qty"], "unit": l["unit"]} for l in view["levels"] if l["qty_milli"]],
                    "priority_batches": [{"name": b["name"], "qty": b["qty_left"], "unit": b["unit"], "expiry_day": b["expiry_day"], "condition": b["condition"], "storage": b["storage"]} for b in view["batches"] if b["condition"] != "ok"],
                    "open_balance": [d["name"] for d in balance(db, org_id, today.isoformat()) if d["state"] != "balanced"]}
        if "actions" in {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
            snapshot["active_actions"] = [r["problem"] for r in db.execute("SELECT problem FROM actions WHERE org_id=? AND status IN ('approved','running','evaluating')", (org_id,))]
        handover_id = db.execute("INSERT INTO handovers(org_id,from_user,created_at,snapshot,tasks,problems) VALUES (?,?,?,?,?,?)",
                                 (org_id, user["id"], now(), json.dumps(snapshot, ensure_ascii=False), text(data.get("tasks") or "", "Аяқталмаған тапсырмалар", 0, 1000), text(data.get("problems") or "", "Ашық мәселелер", 0, 1000))).lastrowid
        return h.respond({"ok": True, "id": handover_id}, 201) or True
    match = re.fullmatch(r"/api/handovers/(\d+)/accept", path)
    if match and method == "POST":
        item = db.execute("SELECT * FROM handovers WHERE id=? AND org_id=?", (int(match[1]), org_id)).fetchone()
        if not item:
            raise APIError("Ауысым жазбасы табылмады.", 404)
        if item["accepted_at"]:
            raise APIError("Бұл ауысым қабылданған.", 409)
        if item["from_user"] == user["id"]:
            raise APIError("Ауысымды тапсырған адам өзі қабылдай алмайды.", 409)
        db.execute("UPDATE handovers SET to_user=?,accepted_at=? WHERE id=?", (user["id"], now(), item["id"]))
        return h.respond({"ok": True}) or True

    if path == "/api/requirements" and method == "POST":
        plan = {}
        for line in data.get("plan") or []:
            if db.execute("SELECT 1 FROM catalog_dishes WHERE id=? AND org_id=?", (int(line.get("dish_id") or 0), org_id)).fetchone():
                plan[int(line["dish_id"])] = plan.get(int(line["dish_id"]), 0) + integer(line.get("portions"), "Порция саны", 0, 5000)
        return h.respond(requirements(db, org_id, plan, day())) or True
    raise APIError("Мұндай әрекет табылмады.", 404)


def tick(db):
    """Once a minute: tell each canteen's staff about batches that expire within two days (one notice per batch)."""
    import notify
    today = common.local_now().date()
    for batch in db.execute("""SELECT b.id,b.org_id,b.expiry_day,i.name FROM stock_batches b JOIN ingredients i ON i.id=b.ingredient_id
        WHERE b.qty_milli_left>0 AND b.state='ok' AND b.expiry_day IS NOT NULL AND b.expiry_day<=?""", ((today + timedelta(days=2)).isoformat(),)).fetchall():
        for staff in db.execute("SELECT id FROM users WHERE role='operator' AND active=1 AND org_id=?", (batch["org_id"],)).fetchall():
            notify.enqueue(db, staff["id"], "stock_expiry", "Жарамдылық мерзімі жақын", f"{batch['name']}: {batch['expiry_day']}", f"expiry:{batch['id']}")
