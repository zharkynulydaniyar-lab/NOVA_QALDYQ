"""Organizations, users, roles and dictionaries (ТТ 2–4)."""
import re
import secrets
import time

from common import (APIError, EMAIL, ROLES, STAGES, UNITS, add_column, can_review, integer, now, number,
                    require, rows, text)

REGISTRATIONS: dict[str, list[float]] = {}


def migrate(db):
    for name, definition in (("address", "TEXT NOT NULL DEFAULT ''"), ("description", "TEXT NOT NULL DEFAULT ''"),
                             ("hours", "TEXT NOT NULL DEFAULT ''"), ("active", "INTEGER NOT NULL DEFAULT 1"),
                             ("is_public", "INTEGER NOT NULL DEFAULT 0"), ("name_ru", "TEXT")):
        add_column(db, "organizations", name, definition)
    add_column(db, "users", "active", "INTEGER NOT NULL DEFAULT 1")
    add_column(db, "users", "is_demo", "INTEGER NOT NULL DEFAULT 0")
    add_column(db, "users", "created_at", "TEXT")
    if add_column(db, "users", "can_review", "INTEGER NOT NULL DEFAULT 0"):
        # Earlier versions let every admin review; keep that for existing admins, but as an explicit flag.
        db.execute("UPDATE users SET can_review=1 WHERE role='admin'")
    for name, definition in (("name_ru", "TEXT"), ("co2_unit", "TEXT NOT NULL DEFAULT 'кг CO₂e / бірлік'"),
                             ("source", "TEXT NOT NULL DEFAULT ''"), ("boundary", "TEXT NOT NULL DEFAULT ''"),
                             ("active", "INTEGER NOT NULL DEFAULT 1")):
        add_column(db, "categories", name, definition)
    add_column(db, "routes", "active", "INTEGER NOT NULL DEFAULT 1")
    add_column(db, "routes", "name_ru", "TEXT")
    add_column(db, "items", "stage", "TEXT NOT NULL DEFAULT 'other'")
    add_column(db, "items", "note", "TEXT NOT NULL DEFAULT ''")
    add_column(db, "history", "from_status", "TEXT")
    for code, name_ru in (("tbo", "Вывоз ТБО"), ("tbo_bin", "Вывоз ТБО (мусорный бак)"), ("recycling", "Переработка"),
                          ("compost", "Компостирование"), ("disposal", "Утилизация")):
        db.execute("UPDATE routes SET name_ru=? WHERE code=? AND name_ru IS NULL", (name_ru, code))


def organizations(db, user=None):
    result = rows(db.execute("SELECT * FROM organizations ORDER BY id"))
    staff = rows(db.execute("SELECT id,name,org_id FROM users WHERE role='operator' AND active=1 ORDER BY id"))
    for org in result:
        org["responsible"] = [u["name"] for u in staff if u["org_id"] == org["id"]]
    return result


def public_user(row):
    return {k: row[k] for k in ("id", "email", "name", "role", "org_id", "active", "can_review", "is_demo")}


def check_password(value):
    value = str(value or "")
    if not 8 <= len(value) <= 200:
        raise APIError("Құпиясөз кемінде 8 таңба болсын.")
    return value


def create_user(db, email, name, role, org_id, password, can_review_flag=0, is_demo=0):
    from server import password_hash
    salt = secrets.token_hex(16)
    return db.execute("INSERT INTO users(email,name,role,org_id,salt,password_hash,can_review,is_demo,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                      (email, name, role, org_id, salt, password_hash(password, salt), can_review_flag, is_demo, now())).lastrowid


def public(h, db, method, path, query):
    if path == "/api/register" and method == "POST":
        # Self-registration always yields the student role; it is not proof of university membership.
        ip = h.client_address[0]
        recent = [t for t in REGISTRATIONS.get(ip, []) if t > time.time() - 3600]
        if len(recent) >= 20:
            raise APIError("Тіркелу саны шектелді. Кейінірек қайталаңыз.", 429)
        data = h.body()
        email = str(data.get("email", "")).lower().strip()
        if not EMAIL.fullmatch(email):
            raise APIError("Email мекенжайын дұрыс жазыңыз.")
        name = text(data.get("name"), "Аты-жөні", 2, 80)
        password = check_password(data.get("password"))
        if db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise APIError("Бұл email тіркелген. Жүйеге кіріңіз.", 409)
        user_id = create_user(db, email, name, "student", None, password)
        REGISTRATIONS[ip] = recent + [time.time()]
        return h.respond({"ok": True, "role": "student"}, 201, headers=h.start_session(user_id)) or True
    if path == "/api/public/demo-accounts" and method == "GET":
        import os
        if os.environ.get("QALDYQ_DEMO", "1") == "0":
            return h.respond({"accounts": []}) or True
        accounts = rows(db.execute("""SELECT u.email,u.name,u.role,o.name AS org_name FROM users u
            LEFT JOIN organizations o ON o.id=u.org_id WHERE u.is_demo=1 AND u.active=1 ORDER BY u.id"""))
        return h.respond({"accounts": accounts, "demo": True}) or True
    return False


def handle(h, db, user, method, path, query):
    if path == "/api/me" and method == "GET":
        return h.respond({"user": user, "csrf": h.current_session["csrf"]}) or True
    if path == "/api/users":
        require(user, "admin", message="Әкімші құқығы қажет.")
        if method == "GET":
            return h.respond({"users": [public_user(r) for r in db.execute("SELECT * FROM users ORDER BY id")]}) or True
        if method == "POST":
            data = h.body()
            email = str(data.get("email", "")).lower().strip()
            if not EMAIL.fullmatch(email):
                raise APIError("Email мекенжайын дұрыс жазыңыз.")
            role, org_id, flag = user_fields(db, data)
            user_id = create_user(db, email, text(data.get("name"), "Аты-жөні", 2, 80), role, org_id, check_password(data.get("password")), flag)
            return h.respond({"ok": True, "id": user_id}, 201) or True
    match = re.fullmatch(r"/api/users/(\d+)", path)
    if match and method == "PUT":
        require(user, "admin", message="Әкімші құқығы қажет.")
        target = db.execute("SELECT * FROM users WHERE id=?", (int(match[1]),)).fetchone()
        if not target:
            raise APIError("Пайдаланушы табылмады.", 404)
        data = h.body()
        merged = {**dict(target), **{k: data[k] for k in ("role", "org_id", "can_review") if k in data}}
        role, org_id, flag = user_fields(db, merged)
        active = 1 if data.get("active", target["active"]) in (True, 1, "1") else 0
        if target["id"] == user["id"] and (role != "admin" or not active):
            raise APIError("Өз әкімші құқығыңызды алып тастай алмайсыз.")
        name = text(data.get("name", target["name"]), "Аты-жөні", 2, 80)
        db.execute("UPDATE users SET name=?,role=?,org_id=?,can_review=?,active=? WHERE id=?", (name, role, org_id, flag, active, target["id"]))
        if data.get("password"):
            from server import password_hash
            salt = secrets.token_hex(16)
            db.execute("UPDATE users SET salt=?,password_hash=? WHERE id=?", (salt, password_hash(check_password(data["password"]), salt), target["id"]))
        if not active or role != target["role"] or org_id != target["org_id"]:
            h.drop_sessions(target["id"])  # a changed role or organization must not live on in an old session
        return h.respond({"ok": True}) or True
    match = re.fullmatch(r"/api/organizations(?:/(\d+))?", path)
    if match and method in ("POST", "PUT") and (match[1] or method == "POST"):
        require(user, "admin", message="Әкімші құқығы қажет.")
        data = h.body()
        current = dict(db.execute("SELECT * FROM organizations WHERE id=?", (int(match[1]),)).fetchone() or {}) if match[1] else {}
        if match[1] and not current:
            raise APIError("Ұйым табылмады.", 404)
        get = lambda key, default="": data.get(key, current.get(key, default))
        name = text(get("name"), "Атау", 2, 120)
        kind = text(get("kind", "Бөлімше"), "Түрі", 1, 80)
        values = (name, kind, text(get("short") or name[:12], "Қысқа атау", 1, 12), text(get("address"), "Мекенжай", 0, 200),
                  text(get("description"), "Сипаттама", 0, 500), text(get("hours"), "Жұмыс уақыты", 0, 120),
                  1 if get("active", 1) in (True, 1, "1") else 0, 1 if get("is_public", 0) in (True, 1, "1") else 0,
                  text(get("name_ru") or "", "Орысша атау", 0, 120) or None)
        if match[1]:
            db.execute("UPDATE organizations SET name=?,kind=?,short=?,address=?,description=?,hours=?,active=?,is_public=?,name_ru=? WHERE id=?", (*values, current["id"]))
            return h.respond({"ok": True}) or True
        org_id = db.execute("INSERT INTO organizations(name,kind,short,address,description,hours,active,is_public,name_ru) VALUES (?,?,?,?,?,?,?,?,?)", values).lastrowid
        # A new organization starts from the list of an organization of the same type; it is extended in the form.
        db.execute("INSERT OR IGNORE INTO org_categories SELECT ?,category_id FROM org_categories WHERE org_id=(SELECT id FROM organizations WHERE kind=? AND id!=? ORDER BY id LIMIT 1)", (org_id, kind, org_id))
        return h.respond({"ok": True, "id": org_id}, 201) or True
    match = re.fullmatch(r"/api/categories/(\d+)", path)
    if match and method == "PUT":
        if not (user["role"] == "admin" or can_review(user)):
            raise APIError("Анықтамалықты тексеруші немесе әкімші өзгертеді.", 403)
        cat = db.execute("SELECT * FROM categories WHERE id=?", (int(match[1]),)).fetchone()
        if not cat:
            raise APIError("Қалдық түрі табылмады.", 404)
        data = h.body()
        get = lambda key: data.get(key, cat[key])
        unit, route = get("unit"), get("default_route")
        if unit not in UNITS or not db.execute("SELECT 1 FROM routes WHERE code=?", (str(route),)).fetchone():
            raise APIError("Өлшем бірлігі мен кәдеге жарату тәсілін таңдаңыз.")
        if unit != cat["unit"] and db.execute("SELECT 1 FROM items WHERE category_id=? LIMIT 1", (cat["id"],)).fetchone():
            raise APIError("Өлшемдері бар түрдің бірлігін өзгертуге болмайды. Жаңа түр қосыңыз.")
        db.execute("""UPDATE categories SET unit=?,default_route=?,recyclable=?,cost=?,co2=?,co2_unit=?,source=?,boundary=?,active=?,name_ru=? WHERE id=?""",
                   (unit, route, 1 if get("recyclable") in (True, 1, "1") else 0, number(get("cost"), "Құн"), number(get("co2"), "CO₂", maximum=1000),
                    text(get("co2_unit"), "Коэффициент бірлігі", 1, 40), text(get("source"), "Дереккөз", 0, 300), text(get("boundary"), "Есеп шекарасы", 0, 300),
                    1 if get("active") in (True, 1, "1") else 0, text(get("name_ru") or "", "Орысша атау", 0, 120) or None, cat["id"]))
        return h.respond({"ok": True}) or True
    match = re.fullmatch(r"/api/routes(?:/([a-z0-9_]{1,40}))?", path)
    if match and method in ("POST", "PUT") and (match[1] or method == "POST"):
        if not (user["role"] == "admin" or can_review(user)):
            raise APIError("Анықтамалықты тексеруші немесе әкімші өзгертеді.", 403)
        data = h.body()
        if match[1]:
            route = db.execute("SELECT * FROM routes WHERE code=?", (match[1],)).fetchone()
            if not route:
                raise APIError("Тәсіл табылмады.", 404)
            db.execute("UPDATE routes SET name=?,diverted=?,active=?,name_ru=? WHERE code=?",
                       (text(data.get("name", route["name"]), "Атау", 2, 80), 1 if data.get("diverted", route["diverted"]) in (True, 1, "1") else 0,
                        1 if data.get("active", route["active"]) in (True, 1, "1") else 0, text(data.get("name_ru", route["name_ru"]) or "", "Орысша атау", 0, 80) or None, match[1]))
            return h.respond({"ok": True}) or True
        name = text(data.get("name"), "Атау", 2, 80)
        if any(r["name"].casefold() == name.casefold() for r in db.execute("SELECT name FROM routes")):
            raise APIError("Бұл тәсіл тізімде бар.", 409)
        code = "r" + secrets.token_hex(4)
        position = db.execute("SELECT COALESCE(MAX(position),0)+1 FROM routes").fetchone()[0]
        db.execute("INSERT INTO routes(code,name,diverted,position,name_ru) VALUES (?,?,?,?,?)",
                   (code, name, 1 if data.get("diverted") in (True, 1, "1") else 0, position, text(data.get("name_ru") or "", "Орысша атау", 0, 80) or None))
        return h.respond({"ok": True, "code": code}, 201) or True
    return False


def user_fields(db, data):
    role = data.get("role")
    if role not in ROLES:
        raise APIError("Рөлді таңдаңыз.")
    org_id = integer(data.get("org_id") or 0, "Ұйым") or None
    if role == "operator":
        if not org_id or not db.execute("SELECT 1 FROM organizations WHERE id=?", (org_id,)).fetchone():
            raise APIError("Жауапты қызметкерге ұйым тағайындаңыз.")
    else:
        org_id = None
    # Only an admin can hold the extra reviewing duty, and only when it is switched on explicitly.
    flag = 1 if role == "admin" and data.get("can_review") in (True, 1, "1") else 0
    return role, org_id, flag
