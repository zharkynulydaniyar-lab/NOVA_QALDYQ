"""Dish catalogue, published menus, the student area and pre-orders (ТТ 9–10).

The site, the Telegram Mini App and the bot all call the same functions here (create_order, cancel_order,
issue_order …) against the same database, so order rules cannot differ between channels."""
import base64
import hashlib
import hmac
import json
import re
import secrets
from datetime import date, datetime, timedelta

import common
import notify
from common import APIError, integer, money, now, org_scope, own_org, rows, text

ORDER_STATUSES = ("confirmed", "cancelled", "issued", "no_show")
LEFTOVER_REASONS = ("none", "portion_big", "taste", "cold", "no_time", "other")
PAYMENT_METHODS = ("cash", "card", "other")
MAX_ORDER_PORTIONS = 10


def migrate(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS catalog_dishes(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL REFERENCES organizations(id), name TEXT NOT NULL,
      name_ru TEXT, description TEXT NOT NULL DEFAULT '', description_ru TEXT, composition TEXT NOT NULL DEFAULT '', composition_ru TEXT,
      photo TEXT, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(org_id,name));
    CREATE TABLE IF NOT EXISTS dish_portions(id INTEGER PRIMARY KEY, dish_id INTEGER NOT NULL REFERENCES catalog_dishes(id) ON DELETE CASCADE,
      label TEXT NOT NULL, label_ru TEXT, grams INTEGER NOT NULL, price_tiyn INTEGER NOT NULL CHECK(price_tiyn>=0), active INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS menu_days(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL REFERENCES organizations(id), day TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'draft', order_deadline TEXT NOT NULL, pickup_start TEXT NOT NULL, pickup_end TEXT NOT NULL,
      slot_minutes INTEGER NOT NULL DEFAULT 30, slot_limit INTEGER NOT NULL DEFAULT 20, cancel_minutes INTEGER NOT NULL DEFAULT 30,
      published_at TEXT, updated_at TEXT NOT NULL, UNIQUE(org_id,day));
    CREATE TABLE IF NOT EXISTS menu_items(id INTEGER PRIMARY KEY, menu_id INTEGER NOT NULL REFERENCES menu_days(id) ON DELETE CASCADE,
      dish_id INTEGER NOT NULL REFERENCES catalog_dishes(id), portion_id INTEGER NOT NULL REFERENCES dish_portions(id),
      available INTEGER NOT NULL CHECK(available>=0), reserved INTEGER NOT NULL DEFAULT 0 CHECK(reserved>=0), UNIQUE(menu_id,portion_id));
    CREATE TABLE IF NOT EXISTS favorites(user_id INTEGER NOT NULL REFERENCES users(id), dish_id INTEGER NOT NULL REFERENCES catalog_dishes(id),
      created_at TEXT NOT NULL, PRIMARY KEY(user_id,dish_id));
    CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), org_id INTEGER NOT NULL REFERENCES organizations(id),
      menu_id INTEGER NOT NULL REFERENCES menu_days(id), day TEXT NOT NULL, pickup_slot TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'confirmed',
      code TEXT NOT NULL UNIQUE, request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, total_tiyn INTEGER NOT NULL, source TEXT NOT NULL DEFAULT 'web',
      payment_method TEXT, payment_status TEXT NOT NULL DEFAULT 'unpaid', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      issued_at TEXT, issued_by INTEGER REFERENCES users(id), cancelled_at TEXT, UNIQUE(user_id,request_id));
    CREATE TABLE IF NOT EXISTS order_items(id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
      menu_item_id INTEGER NOT NULL REFERENCES menu_items(id), dish_id INTEGER NOT NULL, portion_id INTEGER NOT NULL, name TEXT NOT NULL, name_ru TEXT,
      portion_label TEXT NOT NULL, grams INTEGER NOT NULL, price_tiyn INTEGER NOT NULL, qty INTEGER NOT NULL CHECK(qty>0));
    CREATE TABLE IF NOT EXISTS order_events(id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
      from_status TEXT, to_status TEXT NOT NULL, user_id INTEGER REFERENCES users(id), note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS dish_reviews(id INTEGER PRIMARY KEY, order_item_id INTEGER NOT NULL UNIQUE REFERENCES order_items(id), user_id INTEGER NOT NULL,
      dish_id INTEGER NOT NULL, rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5), leftover_reason TEXT NOT NULL DEFAULT 'none',
      comment TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS sales(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL REFERENCES organizations(id), day TEXT NOT NULL,
      dish_id INTEGER NOT NULL, portion_id INTEGER NOT NULL, name TEXT NOT NULL, portion_label TEXT NOT NULL, qty INTEGER NOT NULL CHECK(qty>0),
      price_tiyn INTEGER NOT NULL, total_tiyn INTEGER NOT NULL, source TEXT NOT NULL, order_item_id INTEGER UNIQUE REFERENCES order_items(id),
      payment_method TEXT, payment_status TEXT NOT NULL DEFAULT 'unpaid', created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL,
      request_id TEXT, UNIQUE(created_by,request_id));
    CREATE INDEX IF NOT EXISTS orders_day ON orders(org_id,day,status);
    """)
    notify.migrate(db)


# ---------- catalogue and menu ----------

def photo_value(value):
    if value in (None, ""):
        return None
    if isinstance(value, str) and value.startswith("/student/dishes/") and re.fullmatch(r"/student/dishes/[a-z0-9_-]+\.(svg|png|jpg|webp)", value):
        return value
    if not isinstance(value, str) or not re.match(r"^data:image/(png|jpeg|webp);base64,", value):
        raise APIError("Фото PNG, JPEG немесе WebP болсын.")
    try:
        raw = base64.b64decode(value.split(",", 1)[1], validate=True)
    except ValueError:
        raise APIError("Фото пішімі қате.")
    kind = value.split(";", 1)[0]
    valid = (kind.endswith("png") and raw.startswith(b"\x89PNG\r\n\x1a\n")) or (kind.endswith("jpeg") and raw.startswith(b"\xff\xd8\xff")) or \
        (kind.endswith("webp") and raw.startswith(b"RIFF") and raw[8:12] == b"WEBP")
    if not valid or len(raw) > 400_000:
        raise APIError("Фото 400 КБ-тан аспасын және сурет пішіміне сәйкес болсын.")
    return value


def dish_rows(db, where="1=1", args=()):
    dishes = rows(db.execute(f"SELECT * FROM catalog_dishes d WHERE {where} ORDER BY d.org_id,d.name", args))
    portions = rows(db.execute("SELECT * FROM dish_portions ORDER BY dish_id,price_tiyn,id"))
    for dish in dishes:
        dish["portions"] = [p for p in portions if p["dish_id"] == dish["id"]]
    return dishes


def save_dish(db, user, data, dish=None):
    org_id = own_org(db, user, data.get("org_id") or (dish["org_id"] if dish else user["org_id"]))
    if dish and org_id != dish["org_id"]:
        raise APIError("Тағамның ұйымын өзгертуге болмайды.")
    name = text(data.get("name"), "Тағам атауы", 2, 100)
    portions = data.get("portions")
    if not isinstance(portions, list) or not 1 <= len(portions) <= 6:
        raise APIError("Кемінде бір порция нұсқасын көрсетіңіз (ең көбі 6).")
    stamp = now()
    values = (name, text(data.get("name_ru") or "", "Орысша атауы", 0, 100) or None, text(data.get("description") or "", "Сипаттама", 0, 400),
              text(data.get("description_ru") or "", "Орысша сипаттама", 0, 400) or None, text(data.get("composition") or "", "Құрамы", 0, 400),
              text(data.get("composition_ru") or "", "Орысша құрамы", 0, 400) or None, photo_value(data.get("photo")), 1 if data.get("active", 1) in (True, 1, "1") else 0, stamp)
    if dish:
        db.execute("UPDATE catalog_dishes SET name=?,name_ru=?,description=?,description_ru=?,composition=?,composition_ru=?,photo=?,active=?,updated_at=? WHERE id=?", (*values, dish["id"]))
        dish_id = dish["id"]
    else:
        dish_id = db.execute("INSERT INTO catalog_dishes(name,name_ru,description,description_ru,composition,composition_ru,photo,active,updated_at,org_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (*values, org_id, stamp)).lastrowid
    keep = []
    for raw in portions:
        if not isinstance(raw, dict):
            raise APIError("Порция жолы дұрыс емес.")
        fields = (text(raw.get("label"), "Порция атауы", 1, 40), text(raw.get("label_ru") or "", "Орысша порция атауы", 0, 40) or None,
                  integer(raw.get("grams"), "Порция салмағы, г", 1, 5000), money(raw.get("price"), "Бағасы"), 1 if raw.get("active", 1) in (True, 1, "1") else 0)
        existing = db.execute("SELECT id FROM dish_portions WHERE id=? AND dish_id=?", (int(raw.get("id") or 0), dish_id)).fetchone()
        if existing:
            # Past orders keep their own snapshot of the name and price, so editing here is safe.
            db.execute("UPDATE dish_portions SET label=?,label_ru=?,grams=?,price_tiyn=?,active=? WHERE id=?", (*fields, existing["id"]))
            keep.append(existing["id"])
        else:
            keep.append(db.execute("INSERT INTO dish_portions(label,label_ru,grams,price_tiyn,active,dish_id) VALUES (?,?,?,?,?,?)", (*fields, dish_id)).lastrowid)
    # Portions that are no longer listed are switched off, not deleted: menus and orders may refer to them.
    db.execute(f"UPDATE dish_portions SET active=0 WHERE dish_id=? AND id NOT IN ({','.join('?' for _ in keep)})", (dish_id, *keep))
    return dish_id


def clock_text(value, name):
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(value or "")):
        raise APIError(f"{name}: уақытты СС:ММ түрінде көрсетіңіз.")
    return str(value)


def slots(menu):
    start = datetime.fromisoformat(f"{menu['day']}T{menu['pickup_start']}")
    end = datetime.fromisoformat(f"{menu['day']}T{menu['pickup_end']}")
    result = []
    while start < end and len(result) < 48:
        result.append(start.strftime("%H:%M"))
        start += timedelta(minutes=menu["slot_minutes"])
    return result


def menu_view(db, menu, public=False):
    """Menu with live availability. `accepting` is decided here, on the server clock only."""
    view = dict(menu)
    items = rows(db.execute("""SELECT mi.id,mi.dish_id,mi.portion_id,mi.available,mi.reserved,d.name,d.name_ru,d.description,d.description_ru,d.composition,d.composition_ru,d.photo,
        p.label,p.label_ru,p.grams,p.price_tiyn FROM menu_items mi JOIN catalog_dishes d ON d.id=mi.dish_id JOIN dish_portions p ON p.id=mi.portion_id
        WHERE mi.menu_id=? ORDER BY d.name,p.price_tiyn""", (menu["id"],)))
    for item in items:
        item["remaining"] = max(0, item["available"] - item["reserved"])
    current = common.local_now()
    taken = {r["pickup_slot"]: r["n"] for r in db.execute("SELECT pickup_slot,COUNT(*) AS n FROM orders WHERE menu_id=? AND status IN ('confirmed','issued') GROUP BY pickup_slot", (menu["id"],))}
    view["slots"] = [{"time": s, "free": max(0, menu["slot_limit"] - taken.get(s, 0)), "open": datetime.fromisoformat(f"{menu['day']}T{s}") > current} for s in slots(menu)]
    view["accepting"] = menu["status"] == "published" and current < datetime.fromisoformat(menu["order_deadline"])
    view["items"] = items
    view["server_time"] = current.isoformat(timespec="minutes")
    view["online_payment"] = False  # payment happens at pickup; an order is not a payment
    if public:
        for item in items:
            item.pop("reserved")
            item.pop("available")
    return view


def save_menu(db, user, data):
    org_id = own_org(db, user, data.get("org_id") or user["org_id"])
    day = common.iso_day(data.get("day"), "Мәзір күні")
    if day < common.local_now().date():
        raise APIError("Өткен күнге мәзір құруға болмайды.")
    start, end = clock_text(data.get("pickup_start"), "Беру басталуы"), clock_text(data.get("pickup_end"), "Беру аяқталуы")
    if start >= end:
        raise APIError("Беру уақытының басы соңынан ерте болсын.")
    try:
        deadline = datetime.fromisoformat(str(data.get("order_deadline")))
    except ValueError:
        raise APIError("Тапсырыс қабылдау мерзімін көрсетіңіз.")
    if deadline > datetime.fromisoformat(f"{day}T{end}"):
        raise APIError("Тапсырыс қабылдау беру уақыты біткенге дейін аяқталсын.")
    values = (deadline.isoformat(timespec="minutes"), start, end, integer(data.get("slot_minutes", 30), "Аралық, мин", 5, 240),
              integer(data.get("slot_limit", 20), "Бір аралықтағы тапсырыс шегі", 1, 1000), integer(data.get("cancel_minutes", 30), "Бас тарту мерзімі, мин", 0, 1440), now())
    menu = db.execute("SELECT * FROM menu_days WHERE org_id=? AND day=?", (org_id, day.isoformat())).fetchone()
    if menu:
        db.execute("UPDATE menu_days SET order_deadline=?,pickup_start=?,pickup_end=?,slot_minutes=?,slot_limit=?,cancel_minutes=?,updated_at=? WHERE id=?", (*values, menu["id"]))
        menu_id = menu["id"]
    else:
        menu_id = db.execute("INSERT INTO menu_days(order_deadline,pickup_start,pickup_end,slot_minutes,slot_limit,cancel_minutes,updated_at,org_id,day) VALUES (?,?,?,?,?,?,?,?,?)", (*values, org_id, day.isoformat())).lastrowid
    items = data.get("items")
    if not isinstance(items, list) or len(items) > 60:
        raise APIError("Мәзір жолдары дұрыс емес.")
    wanted = {}
    for raw in items:
        if not isinstance(raw, dict):
            raise APIError("Мәзір жолы дұрыс емес.")
        portion = db.execute("SELECT p.id,p.dish_id FROM dish_portions p JOIN catalog_dishes d ON d.id=p.dish_id WHERE p.id=? AND d.org_id=? AND p.active=1 AND d.active=1", (int(raw.get("portion_id") or 0), org_id)).fetchone()
        if not portion:
            raise APIError("Мәзірге тек өз ұйымыңыздың белсенді тағамдарын қосыңыз.")
        wanted[portion["id"]] = (portion["dish_id"], integer(raw.get("available"), "Порция саны", 0, 5000))
    for current in db.execute("SELECT * FROM menu_items WHERE menu_id=?", (menu_id,)).fetchall():
        if current["portion_id"] not in wanted:
            if current["reserved"]:
                raise APIError("Тапсырысы бар тағамды мәзірден алып тастауға болмайды. Порция санын азайтыңыз.", 409)
            db.execute("DELETE FROM menu_items WHERE id=?", (current["id"],))
        else:
            available = wanted.pop(current["portion_id"])[1]
            if available < current["reserved"]:
                raise APIError(f"Порция саны брондалған саннан ({current['reserved']}) кем болмасын.", 409)
            db.execute("UPDATE menu_items SET available=? WHERE id=?", (available, current["id"]))
    for portion_id, (dish_id, available) in wanted.items():
        db.execute("INSERT INTO menu_items(menu_id,dish_id,portion_id,available) VALUES (?,?,?,?)", (menu_id, dish_id, portion_id, available))
    return menu_id


# ---------- orders: one implementation for every channel ----------

def event(db, order_id, source, target, user_id, note=""):
    db.execute("INSERT INTO order_events(order_id,from_status,to_status,user_id,note,created_at) VALUES (?,?,?,?,?,?)", (order_id, source, target, user_id, note, now()))


def order_view(db, order, with_code=True):
    view = dict(order)
    view["items"] = rows(db.execute("""SELECT oi.*,r.rating,r.leftover_reason FROM order_items oi LEFT JOIN dish_reviews r ON r.order_item_id=oi.id WHERE oi.order_id=? ORDER BY oi.id""", (order["id"],)))
    view["events"] = rows(db.execute("SELECT from_status,to_status,note,created_at FROM order_events WHERE order_id=? ORDER BY id", (order["id"],)))
    org = db.execute("SELECT name,name_ru,address FROM organizations WHERE id=?", (order["org_id"],)).fetchone()
    view["org_name"], view["org_name_ru"], view["org_address"] = org["name"], org["name_ru"], org["address"]
    menu = db.execute("SELECT * FROM menu_days WHERE id=?", (order["menu_id"],)).fetchone()
    view["cancel_until"] = (datetime.fromisoformat(f"{order['day']}T{order['pickup_slot']}") - timedelta(minutes=menu["cancel_minutes"])).isoformat(timespec="minutes")
    view["can_cancel"] = order["status"] == "confirmed" and common.local_now() < datetime.fromisoformat(view["cancel_until"])
    view["online_payment"] = False
    view.pop("fingerprint", None)
    if with_code:
        view["qr"] = f"QALDYQ:{order['code']}"
    else:
        view.pop("code", None)
    return view


def create_order(db, user_id, data, source="web"):
    """Reserve portions and create the order in one transaction (the caller holds BEGIN IMMEDIATE).
    Returns (order_row, created). A repeated request_id returns the first order and reserves nothing."""
    request_id = data.get("request_id")
    if not isinstance(request_id, str) or not re.fullmatch(r"[a-zA-Z0-9-]{16,80}", request_id):
        raise APIError("Сұрау кілті дұрыс емес.")
    fingerprint = hashlib.sha256(json.dumps({k: data.get(k) for k in ("menu_id", "pickup_slot", "items")}, sort_keys=True).encode()).hexdigest()
    previous = db.execute("SELECT * FROM orders WHERE user_id=? AND request_id=?", (user_id, request_id)).fetchone()
    if previous:
        if previous["fingerprint"] != fingerprint:
            raise APIError("Бұл сұрау кілті басқа тапсырысқа қолданылған.", 409)
        return previous, False
    menu = db.execute("SELECT * FROM menu_days WHERE id=?", (int(data.get("menu_id") or 0),)).fetchone()
    if not menu or menu["status"] != "published":
        raise APIError("Бұл күннің мәзірі жарияланбаған.", 404)
    current = common.local_now()
    if current >= datetime.fromisoformat(menu["order_deadline"]):
        raise APIError("Бұл мәзірге тапсырыс қабылдау аяқталды.", 409)
    slot = str(data.get("pickup_slot") or "")
    if slot not in slots(menu) or datetime.fromisoformat(f"{menu['day']}T{slot}") <= current:
        raise APIError("Алу уақытын тізімнен таңдаңыз.")
    if db.execute("SELECT COUNT(*) FROM orders WHERE menu_id=? AND pickup_slot=? AND status IN ('confirmed','issued')", (menu["id"], slot)).fetchone()[0] >= menu["slot_limit"]:
        raise APIError("Бұл уақытқа тапсырыс толды. Басқа уақытты таңдаңыз.", 409)
    raw_items = data.get("items")
    if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= 10:
        raise APIError("Кемінде бір тағам таңдаңыз.")
    wanted = {}
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise APIError("Тапсырыс жолы дұрыс емес.")
        item_id = int(raw.get("menu_item_id") or 0)
        wanted[item_id] = wanted.get(item_id, 0) + integer(raw.get("qty"), "Саны", 1, 5)
    if sum(wanted.values()) > MAX_ORDER_PORTIONS:
        raise APIError(f"Бір тапсырыста ең көбі {MAX_ORDER_PORTIONS} порция.")
    lines, total = [], 0
    for item_id, qty in wanted.items():
        item = db.execute("""SELECT mi.*,d.name,d.name_ru,p.label,p.grams,p.price_tiyn FROM menu_items mi JOIN catalog_dishes d ON d.id=mi.dish_id
            JOIN dish_portions p ON p.id=mi.portion_id WHERE mi.id=? AND mi.menu_id=?""", (item_id, menu["id"])).fetchone()
        if not item:
            raise APIError("Тағам осы мәзірде жоқ.")
        # The limit check and the reservation are one statement: two buyers cannot both take the last portion.
        if db.execute("UPDATE menu_items SET reserved=reserved+? WHERE id=? AND reserved+?<=available", (qty, item_id, qty)).rowcount != 1:
            raise APIError(f"«{item['name']}» таусылды немесе қалғаны жеткіліксіз.", 409)
        lines.append((item_id, item["dish_id"], item["portion_id"], item["name"], item["name_ru"], item["label"], item["grams"], item["price_tiyn"], qty))
        total += item["price_tiyn"] * qty
    stamp = now()
    code = secrets.token_hex(4).upper()
    order_id = db.execute("""INSERT INTO orders(user_id,org_id,menu_id,day,pickup_slot,code,request_id,fingerprint,total_tiyn,source,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (user_id, menu["org_id"], menu["id"], menu["day"], slot, code, request_id, fingerprint, total, source if source in ("web", "miniapp", "bot") else "web", stamp, stamp)).lastrowid
    db.executemany("INSERT INTO order_items(order_id,menu_item_id,dish_id,portion_id,name,name_ru,portion_label,grams,price_tiyn,qty) VALUES (?,?,?,?,?,?,?,?,?,?)", [(order_id, *line) for line in lines])
    event(db, order_id, None, "confirmed", user_id)
    notify.enqueue(db, user_id, "order_status", "Тапсырыс расталды", f"№{order_id} · {menu['day']} {slot}. Төлем алу кезінде.", f"order:{order_id}:confirmed", {"order_id": order_id})
    return db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone(), True


def release(db, order_id):
    for line in db.execute("SELECT menu_item_id,qty FROM order_items WHERE order_id=?", (order_id,)).fetchall():
        db.execute("UPDATE menu_items SET reserved=MAX(0,reserved-?) WHERE id=?", (line["qty"], line["menu_item_id"]))


def cancel_order(db, order, actor, by_staff=False):
    if order["status"] != "confirmed":
        raise APIError("Тек расталған тапсырыстан бас тартуға болады.", 409)
    if not by_staff and not order_view(db, order)["can_cancel"]:
        raise APIError("Бас тарту мерзімі өтті. Асханаға хабарласыңыз.", 409)
    stamp = now()
    db.execute("UPDATE orders SET status='cancelled',cancelled_at=?,updated_at=? WHERE id=?", (stamp, stamp, order["id"]))
    release(db, order["id"])  # the portions go back on sale
    event(db, order["id"], "confirmed", "cancelled", actor, "Асхана" if by_staff else "")
    notify.enqueue(db, order["user_id"], "order_status", "Тапсырыс тоқтатылды", f"№{order['id']} · {order['day']} {order['pickup_slot']}", f"order:{order['id']}:cancelled", {"order_id": order["id"]})


def issue_order(db, staff, code, payment_method=None, paid=False):
    """Hand the order over exactly once and register the sale exactly once."""
    code = str(code or "").strip().upper().removeprefix("QALDYQ:")
    if not re.fullmatch(r"[0-9A-F]{8}", code):
        raise APIError("Кодты дұрыс енгізіңіз.")
    candidate = db.execute("SELECT * FROM orders WHERE code=?", (code,)).fetchone()
    # Constant-time comparison; an unknown code and another canteen's code look the same to the caller.
    if not candidate or not hmac.compare_digest(candidate["code"], code) or (staff["role"] == "operator" and candidate["org_id"] != staff["org_id"]):
        raise APIError("Мұндай кодпен тапсырыс табылмады.", 404)
    if candidate["status"] == "issued":
        issued = datetime.fromisoformat(candidate["issued_at"]).replace(tzinfo=None) + timedelta(hours=5)  # stored in UTC, shown in campus time
        raise APIError(f"Бұл тапсырыс берілген: {issued.strftime('%Y-%m-%d %H:%M')}.", 409)
    if candidate["status"] != "confirmed":
        raise APIError("Тапсырыс тоқтатылған немесе келмеген деп белгіленген.", 409)
    if candidate["day"] != common.local_now().date().isoformat():
        raise APIError(f"Бұл тапсырыс {candidate['day']} күніне арналған.", 409)
    if payment_method not in (None, "") and payment_method not in PAYMENT_METHODS:
        raise APIError("Төлем тәсілін таңдаңыз.")
    stamp = now()
    payment_status = "paid" if paid and payment_method else "unpaid"
    db.execute("UPDATE orders SET status='issued',issued_at=?,issued_by=?,payment_method=?,payment_status=?,updated_at=? WHERE id=? AND status='confirmed'",
               (stamp, staff["id"], payment_method or None, payment_status, stamp, candidate["id"]))
    for line in db.execute("SELECT * FROM order_items WHERE order_id=?", (candidate["id"],)).fetchall():
        db.execute("""INSERT OR IGNORE INTO sales(org_id,day,dish_id,portion_id,name,portion_label,qty,price_tiyn,total_tiyn,source,order_item_id,payment_method,payment_status,created_by,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (candidate["org_id"], candidate["day"], line["dish_id"], line["portion_id"], line["name"], line["portion_label"], line["qty"],
                                                    line["price_tiyn"], line["price_tiyn"] * line["qty"], "preorder", line["id"], payment_method or None, payment_status, staff["id"], stamp))
    event(db, candidate["id"], "confirmed", "issued", staff["id"])
    notify.enqueue(db, candidate["user_id"], "order_status", "Тапсырыс берілді", f"№{candidate['id']}. Ас болсын! Тағамды бағалай аласыз.", f"order:{candidate['id']}:issued", {"order_id": candidate["id"]})
    return db.execute("SELECT * FROM orders WHERE id=?", (candidate["id"],)).fetchone()


def mark_no_show(db, staff, order):
    if order["status"] != "confirmed":
        raise APIError("Тек расталған тапсырысты белгілеуге болады.", 409)
    menu = db.execute("SELECT slot_minutes FROM menu_days WHERE id=?", (order["menu_id"],)).fetchone()
    slot_end = datetime.fromisoformat(f"{order['day']}T{order['pickup_slot']}") + timedelta(minutes=menu["slot_minutes"])
    if common.local_now() < slot_end:
        raise APIError("Келмегенін алу аралығы біткен соң ғана белгілеуге болады.", 409)
    db.execute("UPDATE orders SET status='no_show',updated_at=? WHERE id=?", (now(), order["id"]))
    event(db, order["id"], "confirmed", "no_show", staff["id"])
    notify.enqueue(db, order["user_id"], "order_status", "Тапсырыс алынбады", f"№{order['id']} · {order['day']} {order['pickup_slot']}", f"order:{order['id']}:no_show", {"order_id": order["id"]})


def orders_summary(db, org_id, day):
    orders = rows(db.execute("""SELECT o.*,u.name AS student FROM orders o JOIN users u ON u.id=o.user_id WHERE o.org_id=? AND o.day=? ORDER BY o.pickup_slot,o.id""", (org_id, day)))
    lines = rows(db.execute("""SELECT oi.*,o.status,o.pickup_slot FROM order_items oi JOIN orders o ON o.id=oi.order_id WHERE o.org_id=? AND o.day=?""", (org_id, day)))
    by_dish, by_slot = {}, {}
    for line in lines:
        dish = by_dish.setdefault((line["name"], line["portion_label"]), {"name": line["name"], "portion": line["portion_label"], **{s: 0 for s in ORDER_STATUSES}})
        dish[line["status"]] += line["qty"]
        if line["status"] in ("confirmed", "issued"):
            by_slot[line["pickup_slot"]] = by_slot.get(line["pickup_slot"], 0) + line["qty"]
    for order in orders:
        order["items"] = [l for l in lines if l["order_id"] == order["id"]]
        order.pop("code")  # staff confirm a hand-over by the code the student shows, never the other way round
        order.pop("fingerprint")
    return {"orders": orders, "by_dish": sorted(by_dish.values(), key=lambda d: d["name"]), "by_slot": [{"slot": s, "portions": n} for s, n in sorted(by_slot.items())]}


# ---------- HTTP ----------

def public(h, db, method, path, query):
    if path == "/api/public/canteens" and method == "GET":
        return h.respond({"canteens": rows(db.execute("SELECT id,name,name_ru,kind,address,hours,description FROM organizations WHERE active=1 AND is_public=1 ORDER BY id"))}) or True
    if path == "/api/public/menu" and method == "GET":
        day = common.iso_day(query.get("date", [common.local_now().date().isoformat()])[0]).isoformat()
        org = int(query.get("org", [0])[0] or 0)
        menus = db.execute("""SELECT m.* FROM menu_days m JOIN organizations o ON o.id=m.org_id WHERE m.day=? AND m.status='published' AND o.active=1 AND o.is_public=1
            AND (?=0 OR m.org_id=?) ORDER BY m.org_id""", (day, org, org)).fetchall()
        return h.respond({"date": day, "menus": [menu_view(db, m, public=True) for m in menus], "generated_at": common.local_now().isoformat(timespec="minutes")}) or True
    return False


def handle(h, db, user, method, path, query):
    if path.startswith("/api/student/"):
        return student(h, db, user, method, path, query)
    staff_write = user["role"] in ("operator", "admin")
    if path == "/api/catalog" and method == "GET":
        org = org_scope(user, query.get("org", [0])[0])
        return h.respond({"dishes": dish_rows(db, "(?=0 OR d.org_id=?)", (org, org))}) or True
    match = re.fullmatch(r"/api/catalog(?:/(\d+))?", path)
    if match and method in ("POST", "PUT") and (match[1] or method == "POST"):
        if not staff_write:
            raise APIError("Каталогты асхана қызметкері немесе әкімші өзгертеді.", 403)
        dish = db.execute("SELECT * FROM catalog_dishes WHERE id=?", (int(match[1]),)).fetchone() if match[1] else None
        if match[1] and not dish:
            raise APIError("Тағам табылмады.", 404)
        if dish and user["role"] == "operator" and dish["org_id"] != user["org_id"]:
            raise APIError("Бұл ұйымға рұқсат жоқ.", 403)
        return h.respond({"ok": True, "id": save_dish(db, user, h.body(), dish)}, 200 if dish else 201) or True
    if path == "/api/menu" and method == "GET":
        org = org_scope(user, query.get("org", [0])[0])
        day = common.iso_day(query.get("date", [""])[0]).isoformat()
        menu = db.execute("SELECT * FROM menu_days WHERE org_id=? AND day=?", (org, day)).fetchone()
        return h.respond({"menu": menu_view(db, menu) if menu else None}) or True
    if path == "/api/menu" and method == "PUT":
        if not staff_write:
            raise APIError("Мәзірді асхана қызметкері немесе әкімші өзгертеді.", 403)
        menu_id = save_menu(db, user, h.body())
        return h.respond({"ok": True, "id": menu_id}) or True
    match = re.fullmatch(r"/api/menu/(\d+)/publish", path)
    if match and method == "POST":
        if not staff_write:
            raise APIError("Мәзірді асхана қызметкері немесе әкімші жариялайды.", 403)
        menu = db.execute("SELECT * FROM menu_days WHERE id=?", (int(match[1]),)).fetchone()
        if not menu or (user["role"] == "operator" and menu["org_id"] != user["org_id"]):
            raise APIError("Мәзір табылмады.", 404)
        publish = h.body().get("publish") is not False
        if publish and not db.execute("SELECT 1 FROM menu_items WHERE menu_id=? LIMIT 1", (menu["id"],)).fetchone():
            raise APIError("Бос мәзірді жариялауға болмайды.")
        if not publish and db.execute("SELECT 1 FROM orders WHERE menu_id=? AND status='confirmed' LIMIT 1", (menu["id"],)).fetchone():
            raise APIError("Расталған тапсырысы бар мәзірді жасыруға болмайды.", 409)
        db.execute("UPDATE menu_days SET status=?,published_at=?,updated_at=? WHERE id=?", ("published" if publish else "draft", now() if publish else None, now(), menu["id"]))
        return h.respond({"ok": True}) or True
    if path == "/api/orders" and method == "GET":
        org = org_scope(user, query.get("org", [0])[0])
        if not org:
            raise APIError("Асхананы таңдаңыз.")
        day = common.iso_day(query.get("date", [common.local_now().date().isoformat()])[0]).isoformat()
        return h.respond(orders_summary(db, org, day)) or True
    if path == "/api/orders/reviews" and method == "GET":
        org = org_scope(user, query.get("org", [0])[0])
        data = rows(db.execute("""SELECT oi.name,COUNT(*) AS reviews,ROUND(AVG(r.rating),2) AS rating,
            SUM(CASE WHEN r.leftover_reason NOT IN ('none','') THEN 1 ELSE 0 END) AS leftovers FROM dish_reviews r JOIN order_items oi ON oi.id=r.order_item_id
            JOIN orders o ON o.id=oi.order_id WHERE (?=0 OR o.org_id=?) GROUP BY oi.name ORDER BY reviews DESC""", (org, org)))
        reasons = rows(db.execute("""SELECT oi.name,r.leftover_reason AS reason,COUNT(*) AS n FROM dish_reviews r JOIN order_items oi ON oi.id=r.order_item_id
            JOIN orders o ON o.id=oi.order_id WHERE (?=0 OR o.org_id=?) AND r.leftover_reason NOT IN ('none','') GROUP BY oi.name,r.leftover_reason""", (org, org)))
        return h.respond({"dishes": data, "reasons": reasons}) or True  # aggregated: no student is identified
    if path == "/api/orders/issue" and method == "POST":
        if not staff_write:
            raise APIError("Тапсырысты асхана қызметкері береді.", 403)
        data = h.body()
        order = issue_order(db, user, data.get("code"), data.get("payment_method"), data.get("paid") is True)
        return h.respond({"ok": True, "order": order_view(db, order, with_code=False)}) or True
    match = re.fullmatch(r"/api/orders/(\d+)/(no-show|cancel)", path)
    if match and method == "POST":
        if not staff_write:
            raise APIError("Тапсырыс күйін асхана қызметкері өзгертеді.", 403)
        order = db.execute("SELECT * FROM orders WHERE id=?", (int(match[1]),)).fetchone()
        if not order or (user["role"] == "operator" and order["org_id"] != user["org_id"]):
            raise APIError("Тапсырыс табылмады.", 404)
        if match[2] == "cancel":
            cancel_order(db, order, user["id"], by_staff=True)
        else:
            mark_no_show(db, user, order)
        return h.respond({"ok": True}) or True
    return False


def student(h, db, user, method, path, query):
    uid = user["id"]
    if path == "/api/student/profile":
        if method == "GET":
            link = db.execute("SELECT linked_at,active FROM external_links WHERE user_id=? AND channel='telegram'", (uid,)).fetchone()
            subs = {k: notify.subscribed(db, uid, "telegram", k) for k in ("order_status", "pickup_reminder")}
            return h.respond({"user": {k: user[k] for k in ("id", "email", "name", "role")}, "telegram_linked": bool(link and link["active"]), "subscriptions": subs}) or True
        if method == "PUT":
            data = h.body()
            if "name" in data:
                db.execute("UPDATE users SET name=? WHERE id=?", (text(data["name"], "Аты-жөні", 2, 80), uid))
            for kind, enabled in (data.get("subscriptions") or {}).items():
                if kind in notify.KINDS:
                    db.execute("INSERT INTO subscriptions(user_id,channel,kind,enabled) VALUES (?,?,?,?) ON CONFLICT(user_id,channel,kind) DO UPDATE SET enabled=excluded.enabled", (uid, "telegram", kind, 1 if enabled else 0))
            return h.respond({"ok": True}) or True
    if path == "/api/student/telegram-link" and method == "POST":
        code, expires = notify.create_link_code(db, uid)
        return h.respond({"code": code, "expires_at": expires}) or True
    if path == "/api/student/favorites":
        if method == "GET":
            ids = [r["dish_id"] for r in db.execute("SELECT dish_id FROM favorites WHERE user_id=?", (uid,))]
            dishes = [d for d in dish_rows(db, "d.active=1") if d["id"] in ids]
            return h.respond({"dishes": dishes}) or True
        if method == "POST":
            data = h.body()
            dish = db.execute("SELECT id FROM catalog_dishes WHERE id=? AND active=1", (int(data.get("dish_id") or 0),)).fetchone()
            if not dish:
                raise APIError("Тағам табылмады.", 404)
            if data.get("on") is False:
                db.execute("DELETE FROM favorites WHERE user_id=? AND dish_id=?", (uid, dish["id"]))
            else:
                db.execute("INSERT OR IGNORE INTO favorites(user_id,dish_id,created_at) VALUES (?,?,?)", (uid, dish["id"], now()))
            return h.respond({"ok": True}) or True
    if path == "/api/student/notices":
        if method == "GET":
            return h.respond({"notices": rows(db.execute("SELECT id,kind,title,body,created_at,read_at FROM user_notices WHERE user_id=? ORDER BY id DESC LIMIT 50", (uid,)))}) or True
        if method == "POST":
            db.execute("UPDATE user_notices SET read_at=? WHERE user_id=? AND read_at IS NULL", (now(), uid))
            return h.respond({"ok": True}) or True
    if path == "/api/student/orders":
        if method == "GET":
            return h.respond({"orders": [order_view(db, o) for o in db.execute("SELECT * FROM orders WHERE user_id=? ORDER BY day DESC,id DESC LIMIT 100", (uid,)).fetchall()]}) or True
        if method == "POST":
            data = h.body()
            order, created = create_order(db, uid, data, data.get("source", "web"))
            return h.respond({"order": order_view(db, order), "replayed": not created}, 201) or True
    match = re.fullmatch(r"/api/student/orders/(\d+)(/cancel|/review)?", path)
    if match:
        # Another student's order is reported as missing, not as forbidden.
        order = db.execute("SELECT * FROM orders WHERE id=? AND user_id=?", (int(match[1]), uid)).fetchone()
        if not order:
            raise APIError("Тапсырыс табылмады.", 404)
        if method == "GET" and not match[2]:
            return h.respond({"order": order_view(db, order)}) or True
        if method == "POST" and match[2] == "/cancel":
            cancel_order(db, order, uid)
            return h.respond({"ok": True}) or True
        if method == "POST" and match[2] == "/review":
            if order["status"] != "issued":
                raise APIError("Тағамды алғаннан кейін ғана бағалауға болады.", 409)
            data = h.body()
            line = db.execute("SELECT * FROM order_items WHERE id=? AND order_id=?", (int(data.get("order_item_id") or 0), order["id"])).fetchone()
            if not line:
                raise APIError("Тағам осы тапсырыста жоқ.", 404)
            reason = data.get("leftover_reason") or "none"
            if reason not in LEFTOVER_REASONS:
                raise APIError("Себепті тізімнен таңдаңыз.")
            try:
                db.execute("INSERT INTO dish_reviews(order_item_id,user_id,dish_id,rating,leftover_reason,comment,created_at) VALUES (?,?,?,?,?,?,?)",
                           (line["id"], uid, line["dish_id"], integer(data.get("rating"), "Баға", 1, 5), reason, text(data.get("comment") or "", "Пікір", 0, 300), now()))
            except Exception as error:
                if "UNIQUE" in str(error):
                    raise APIError("Бұл тағам бағаланған.", 409)
                raise
            return h.respond({"ok": True}, 201) or True
    raise APIError("Мұндай әрекет табылмады.", 404)


DEMO_CATALOG = {  # org_id: [(name, name_ru, composition, composition_ru, [(label, label_ru, grams, price ₸)], daily portions)]
    1: [("Палау", "Плов", "күріш, сиыр еті, сәбіз, пияз", "рис, говядина, морковь, лук", [("Толық", "Полная", 300, 1400), ("Жарты", "Половина", 150, 800)], 60),
        ("Лағман", "Лагман", "кеспе, сиыр еті, көкөніс", "лапша, говядина, овощи", [("Толық", "Полная", 350, 1500)], 45),
        ("Тауық котлеті гарнирмен", "Куриная котлета с гарниром", "тауық еті, қарақұмық", "курица, гречка", [("Толық", "Полная", 280, 1300)], 50),
        ("Борщ", "Борщ", "қызылша, қырыққабат, картоп, сиыр еті", "свёкла, капуста, картофель, говядина", [("Толық", "Полная", 300, 900), ("Жарты", "Половина", 150, 500)], 40),
        ("Көкөніс салаты", "Овощной салат", "қияр, қызанақ, көк", "огурец, помидор, зелень", [("Порция", "Порция", 150, 600)], 35),
        ("Компот", "Компот", "кептірілген жеміс", "сухофрукты", [("Стақан", "Стакан", 200, 250)], 80)],
    2: [("Бешбармақ", "Бешбармак", "ет, қамыр, пияз", "мясо, тесто, лук", [("Толық", "Полная", 350, 2200)], 30),
        ("Манты", "Манты", "қамыр, ет, асқабақ", "тесто, мясо, тыква", [("5 дана", "5 штук", 250, 1600)], 35),
        ("Тауық сорпасы", "Куриный суп", "тауық еті, кеспе, сәбіз", "курица, лапша, морковь", [("Толық", "Полная", 300, 900)], 30),
        ("Цезарь салаты", "Салат «Цезарь»", "тауық, салат жапырағы, ірімшік", "курица, листья салата, сыр", [("Порция", "Порция", 200, 1500)], 20)],
    3: [("Американо", "Американо", "кофе, су", "кофе, вода", [("250 мл", "250 мл", 250, 700)], 90),
        ("Капучино", "Капучино", "кофе, сүт", "кофе, молоко", [("300 мл", "300 мл", 300, 950)], 80),
        ("Круассан", "Круассан", "ұн, сары май", "мука, сливочное масло", [("Дана", "Штука", 80, 650)], 40),
        ("Сэндвич", "Сэндвич", "нан, тауық, көкөніс", "хлеб, курица, овощи", [("Дана", "Штука", 180, 1100)], 30)],
}


def seed(db):
    stamp = now()
    for org_id, dishes in DEMO_CATALOG.items():
        for name, name_ru, composition, composition_ru, portions, _ in dishes:
            dish_id = db.execute("INSERT INTO catalog_dishes(org_id,name,name_ru,composition,composition_ru,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                                 (org_id, name, name_ru, composition, composition_ru, stamp, stamp)).lastrowid
            for label, label_ru, grams, price in portions:
                db.execute("INSERT INTO dish_portions(dish_id,label,label_ru,grams,price_tiyn) VALUES (?,?,?,?,?)", (dish_id, label, label_ru, grams, price * 100))


def startup(db):
    """Demo mode only: keep published menus for the coming week so the student app is never empty."""
    import os
    if os.environ.get("QALDYQ_DEMO", "1") == "0" or not db.execute("SELECT 1 FROM users WHERE is_demo=1 LIMIT 1").fetchone():
        return
    today = common.local_now().date()
    plan = {(org, name): daily for org, dishes in DEMO_CATALOG.items() for name, *_, daily in dishes}
    for org_id in DEMO_CATALOG:
        for offset in range(7):
            day = today + timedelta(days=offset)
            if day.weekday() == 6 or db.execute("SELECT 1 FROM menu_days WHERE org_id=? AND day=?", (org_id, day.isoformat())).fetchone():
                continue
            menu_id = db.execute("""INSERT INTO menu_days(org_id,day,status,order_deadline,pickup_start,pickup_end,slot_minutes,slot_limit,cancel_minutes,published_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (org_id, day.isoformat(), "published", f"{day.isoformat()}T13:30", "11:30", "14:30", 30, 25, 30, now(), now())).lastrowid
            for portion in db.execute("SELECT p.id,p.dish_id,d.name FROM dish_portions p JOIN catalog_dishes d ON d.id=p.dish_id WHERE d.org_id=? AND d.active=1 AND p.active=1", (org_id,)).fetchall():
                if (org_id, portion["name"]) in plan:
                    db.execute("INSERT INTO menu_items(menu_id,dish_id,portion_id,available) VALUES (?,?,?,?)", (menu_id, portion["dish_id"], portion["id"], max(5, plan[(org_id, portion["name"])] // 3)))
