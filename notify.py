"""Notices and the durable outbox shared by the site, the Mini App and the Telegram bot.

In-app notices are written immediately. External deliveries (Telegram) are queued here and sent by a
separate worker process; a failed or blocked delivery never undoes the business action that caused it.
The bot process uses: consume_link_code(), process(), and the order functions in mod_student."""
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

from common import add_column, now

KINDS = ("order_status", "pickup_reminder", "report_deadline", "report_returned", "action_deadline", "stock_expiry", "clarification")
MAX_ATTEMPTS = 5


class Blocked(Exception):
    """The recipient blocked the bot: stop sending to this address."""


def migrate(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS user_notices(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), kind TEXT NOT NULL,
      title TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL, read_at TEXT, dedupe_key TEXT NOT NULL, UNIQUE(user_id,dedupe_key));
    CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), channel TEXT NOT NULL, kind TEXT NOT NULL,
      payload TEXT NOT NULL, dedupe_key TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
      next_attempt_at TEXT NOT NULL, last_error TEXT, created_at TEXT NOT NULL, sent_at TEXT, UNIQUE(channel,dedupe_key));
    CREATE TABLE IF NOT EXISTS subscriptions(user_id INTEGER NOT NULL REFERENCES users(id), channel TEXT NOT NULL, kind TEXT NOT NULL,
      enabled INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(user_id,channel,kind));
    CREATE TABLE IF NOT EXISTS external_links(user_id INTEGER NOT NULL REFERENCES users(id), channel TEXT NOT NULL, address TEXT NOT NULL,
      linked_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(user_id,channel), UNIQUE(channel,address));
    CREATE TABLE IF NOT EXISTS link_codes(code_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), channel TEXT NOT NULL,
      expires_at TEXT NOT NULL, used_at TEXT);
    """)


def subscribed(db, user_id, channel, kind):
    row = db.execute("SELECT enabled FROM subscriptions WHERE user_id=? AND channel=? AND kind=?", (user_id, channel, kind)).fetchone()
    return True if row is None else bool(row["enabled"])


def enqueue(db, user_id, kind, title, body, dedupe_key, data=None):
    """One notice per (user, dedupe_key). Repeating the call cannot create a second message."""
    stamp = now()
    db.execute("INSERT OR IGNORE INTO user_notices(user_id,kind,title,body,created_at,dedupe_key) VALUES (?,?,?,?,?,?)", (user_id, kind, title, body, stamp, dedupe_key))
    link = db.execute("SELECT 1 FROM external_links WHERE user_id=? AND channel='telegram' AND active=1", (user_id,)).fetchone()
    if link and subscribed(db, user_id, "telegram", kind):
        db.execute("INSERT OR IGNORE INTO outbox(user_id,channel,kind,payload,dedupe_key,next_attempt_at,created_at) VALUES (?,?,?,?,?,?,?)",
                   (user_id, "telegram", kind, json.dumps({"title": title, "body": body, **(data or {})}, ensure_ascii=False), f"{user_id}:{dedupe_key}", stamp, stamp))


def process(db, channel, send, limit=50, clock=None):
    """Deliver due messages. `send(address, payload_dict)` raises Blocked or any other exception on failure.
    Returns counters; the log line carries ids and outcomes only, never message text or addresses."""
    clock = clock or (lambda: datetime.now(timezone.utc))
    stamp = clock().isoformat(timespec="microseconds")
    result = {"sent": 0, "retry": 0, "failed": 0, "skipped": 0, "blocked": 0}
    due = db.execute("SELECT * FROM outbox WHERE channel=? AND status='pending' AND next_attempt_at<=? ORDER BY id LIMIT ?", (channel, stamp, limit)).fetchall()
    for row in due:
        link = db.execute("SELECT address FROM external_links WHERE user_id=? AND channel=? AND active=1", (row["user_id"], channel)).fetchone()
        if not link or not subscribed(db, row["user_id"], channel, row["kind"]):
            db.execute("UPDATE outbox SET status='skipped',last_error='no active link or subscription' WHERE id=?", (row["id"],))
            result["skipped"] += 1
            continue
        try:
            send(link["address"], json.loads(row["payload"]))
        except Blocked:
            db.execute("UPDATE outbox SET status='blocked',attempts=attempts+1,last_error='blocked by recipient' WHERE id=?", (row["id"],))
            db.execute("UPDATE external_links SET active=0 WHERE user_id=? AND channel=?", (row["user_id"], channel))
            result["blocked"] += 1
        except Exception as error:  # network or API failure: bounded retries with backoff
            attempts = row["attempts"] + 1
            if attempts >= MAX_ATTEMPTS:
                db.execute("UPDATE outbox SET status='failed',attempts=?,last_error=? WHERE id=?", (attempts, type(error).__name__, row["id"]))
                result["failed"] += 1
            else:
                retry_at = (clock() + timedelta(seconds=30 * 2 ** attempts)).isoformat(timespec="microseconds")
                db.execute("UPDATE outbox SET attempts=?,next_attempt_at=?,last_error=? WHERE id=?", (attempts, retry_at, type(error).__name__, row["id"]))
                result["retry"] += 1
        else:
            db.execute("UPDATE outbox SET status='sent',attempts=attempts+1,sent_at=?,last_error=NULL WHERE id=?", (stamp, row["id"]))
            result["sent"] += 1
    return result


def create_link_code(db, user_id, channel="telegram", minutes=10):
    """One-time code the user types to the bot. Only its hash is stored."""
    code = secrets.token_hex(4).upper()
    expires = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat(timespec="seconds")
    db.execute("DELETE FROM link_codes WHERE user_id=? AND channel=? AND used_at IS NULL", (user_id, channel))
    db.execute("INSERT INTO link_codes(code_hash,user_id,channel,expires_at) VALUES (?,?,?,?)", (hashlib.sha256(code.encode()).hexdigest(), user_id, channel, expires))
    return code, expires


def consume_link_code(db, code, address, channel="telegram"):
    """Bind an external address to the account that issued the code. A name or username is never proof."""
    digest = hashlib.sha256(str(code).strip().upper().encode()).hexdigest()
    row = db.execute("SELECT * FROM link_codes WHERE code_hash=? AND channel=?", (digest, channel)).fetchone()
    if not row or row["used_at"] or row["expires_at"] < datetime.now(timezone.utc).isoformat(timespec="seconds"):
        return None
    db.execute("UPDATE link_codes SET used_at=? WHERE code_hash=?", (now(), digest))
    db.execute("DELETE FROM external_links WHERE channel=? AND (address=? OR user_id=?)", (channel, str(address), row["user_id"]))
    db.execute("INSERT INTO external_links(user_id,channel,address,linked_at) VALUES (?,?,?,?)", (row["user_id"], channel, str(address), now()))
    return row["user_id"]
