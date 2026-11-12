"""Shared helpers for the Qaldyq server and its feature modules."""
from datetime import datetime, timezone
import re

from features import local_day  # re-exported for modules

ROLES = ("operator", "reviewer", "manager", "admin", "student")
STAFF = ("operator", "reviewer", "manager", "admin")
# Қалдықтың пайда болу кезеңі (ТТ 15): бір мөлшер тек бір кезеңге жазылады.
STAGES = ("prep", "unsold", "plate", "storage", "other")
UNITS = {"kg": "кг", "l": "л"}


class APIError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def number(value, name, minimum=0, maximum=1e8):
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise APIError(f"{name}: сан енгізіңіз.")
    if not minimum <= result <= maximum:
        raise APIError(f"{name}: мән {minimum}–{maximum} аралығында болуы керек.")
    return result


def integer(value, name, minimum=0, maximum=10**9):
    result = number(value, name, minimum, maximum)
    if not result.is_integer():
        raise APIError(f"{name}: бүтін сан болсын.")
    return int(result)


def text(value, name, minimum=0, maximum=200):
    result = " ".join(str(value if value is not None else "").split())
    if not minimum <= len(result) <= maximum:
        raise APIError(f"{name}: {minimum}–{maximum} таңба болсын.")
    return result


def iso_day(value, name="Күн"):
    from datetime import date
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise APIError(f"{name}: күнді ЖЖЖЖ-АА-КК түрінде көрсетіңіз.")


def can_review(user):
    """Reviewing is a reviewer duty; an admin reviews only when it is granted explicitly."""
    return user["role"] == "reviewer" or (user["role"] == "admin" and bool(user.get("can_review")))


def require(user, *roles, message="Бұл әрекетке рұқсат жоқ."):
    if user["role"] not in roles:
        raise APIError(message, 403)


def org_scope(user, requested=0):
    """Operators are always confined to their own organization, whatever the request says."""
    return user["org_id"] if user["role"] == "operator" else int(requested or 0)


def own_org(db, user, org_id, message="Бұл ұйымға рұқсат жоқ."):
    org_id = int(org_id or 0)
    if user["role"] == "operator" and org_id != user["org_id"]:
        raise APIError(message, 403)
    if not db.execute("SELECT 1 FROM organizations WHERE id=?", (org_id,)).fetchone():
        raise APIError("Ұйымды таңдаңыз.")
    return org_id


def columns(db, table):
    return {r[1] for r in db.execute(f"PRAGMA table_info({table})")}


def add_column(db, table, name, definition):
    """Re-runnable additive migration step."""
    if name not in columns(db, table):
        db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
        return True
    return False


def rows(cursor):
    return [dict(r) for r in cursor]


EMAIL = re.compile(r"^[a-z0-9._%+-]{1,64}@[a-z0-9.-]{1,120}\.[a-z]{2,24}$")


def local_now():
    """Campus wall-clock time (Asia/Qyzylorda, UTC+5) as a naive datetime. Tests replace this function."""
    from datetime import timedelta
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Qyzylorda")).replace(tzinfo=None)
    except Exception:
        return (datetime.now(timezone.utc) + timedelta(hours=5)).replace(tzinfo=None)


def money(value, name="Сома", maximum=10**11):
    """Money is stored as whole tiyn (1 ₸ = 100 tiyn); input is tenge with at most two decimals."""
    from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise APIError(f"{name}: сан енгізіңіз.")
    if not amount.is_finite() or amount < 0 or amount != amount.quantize(Decimal("0.01")):
        raise APIError(f"{name}: теріс емес, тиынға дейінгі дәлдікпен енгізіңіз.")
    tiyn = int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if tiyn > maximum:
        raise APIError(f"{name}: мән тым үлкен.")
    return tiyn
