"""Shared persistence and business rules for the local DailyBasket MVP."""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_RULES = {"spinach": {"refrigerated": 5, "room": 1}, "vegetable": {"refrigerated": 5, "room": 2}}
CATEGORY_ICONS = {"vegetable": "🥬", "fruit": "🍎", "dairy": "🥛", "meat": "🥩", "other": "🛒"}
LOGGER = logging.getLogger(__name__)

def database_path() -> str:
    return os.environ.get("DAILYBASKET_DB", "dailybasket.db")

def connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or database_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def initialize(path: str | None = None) -> None:
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    with connect(path) as conn:
        conn.executescript(schema)
        for statement in (
            "ALTER TABLE users ADD COLUMN pending_email TEXT",
            "ALTER TABLE users ADD COLUMN pending_token TEXT",
            "ALTER TABLE products ADD COLUMN image_data BLOB",
            "ALTER TABLE products ADD COLUMN image_mime TEXT",
            "ALTER TABLE shopping ADD COLUMN category TEXT NOT NULL DEFAULT 'other'",
            "ALTER TABLE shopping ADD COLUMN nutrition_json TEXT NOT NULL DEFAULT '{}'",
            "ALTER TABLE shopping ADD COLUMN nutrition_basis TEXT",
        ):
            try: conn.execute(statement)
            except sqlite3.OperationalError: pass

def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
    return f"{salt}${digest}"

def verify_password(password: str, encoded: str) -> bool:
    salt, expected = encoded.split("$", 1)
    return hmac.compare_digest(hash_password(password, salt), encoded)

def development_mode() -> bool:
    return os.getenv("DAILYBASKET_DEV_MODE", "").lower() in {"1", "true", "yes"}

def ensure_verification_delivery() -> None:
    if development_mode(): return
    host, sender, port, timeout = os.getenv("SMTP_HOST"), os.getenv("SMTP_FROM"), os.getenv("SMTP_PORT", "587"), os.getenv("SMTP_TIMEOUT", "20")
    try: valid_port = 1 <= int(port) <= 65535; valid_timeout = 0 < float(timeout) <= 120
    except ValueError: valid_port = valid_timeout = False
    if not host or not sender or not valid_port or not valid_timeout:
        raise RuntimeError("Verification email is unavailable. Configure SMTP_HOST, SMTP_FROM, a valid SMTP_PORT, and SMTP_TIMEOUT from 0 to 120 seconds, or explicitly set DAILYBASKET_DEV_MODE=1 for local development.")

def send_verification_email(email: str, token: str) -> str | None:
    """Send a token; only return it in explicitly local/simulated development mode."""
    if development_mode(): return token
    ensure_verification_delivery()
    import smtplib
    from email.message import EmailMessage
    message = EmailMessage(); message["Subject"] = "Verify your DailyBasket email"; message["From"] = os.environ["SMTP_FROM"]; message["To"] = email
    message.set_content(f"Enter this verification token in DailyBasket: {token}")
    try:
        with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587")), timeout=float(os.getenv("SMTP_TIMEOUT", "20"))) as smtp:
            smtp.starttls()
            if os.getenv("SMTP_USER"): smtp.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
            smtp.send_message(message)
    except Exception as error:
        if isinstance(error, TimeoutError):
            error_class, summary = "TimeoutError", "connection_timeout"
        elif isinstance(error, smtplib.SMTPAuthenticationError):
            error_class, summary = "SMTPAuthenticationError", "smtp_authentication_failure"
        elif isinstance(error, smtplib.SMTPNotSupportedError):
            error_class, summary = "SMTPNotSupportedError", "smtp_tls_not_supported"
        elif isinstance(error, smtplib.SMTPRecipientsRefused):
            error_class, summary = "SMTPRecipientsRefused", "smtp_recipient_rejected"
        elif isinstance(error, smtplib.SMTPDataError):
            error_class, summary = "SMTPDataError", "smtp_data_rejected"
        elif isinstance(error, smtplib.SMTPException):
            error_class, summary = "SMTPException", "smtp_delivery_failure"
        elif isinstance(error, OSError):
            error_class, summary = "OSError", "network_or_connection_failure"
        else:
            error_class, summary = "Exception", "unexpected_delivery_failure"
        LOGGER.warning(
            "Verification email delivery failed; exception_class=%s summary=%s",
            error_class,
            summary,
        )
        raise RuntimeError("Could not send verification email. Check SMTP configuration and try again.") from None
    return None

def register(conn, email: str, password: str) -> str | None:
    ensure_verification_delivery()
    token = secrets.token_urlsafe(24)
    email = email.strip().lower()
    with conn:
        conn.execute("INSERT INTO users(email,password_hash,verification_token) VALUES(?,?,?)", (email, hash_password(password), token))
        return send_verification_email(email, token)

def authenticate(conn, email: str, password: str):
    user = conn.execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
    return user if user and verify_password(password, user["password_hash"]) else None

def verify_email(conn, token: str) -> bool:
    row = conn.execute("SELECT * FROM users WHERE verification_token=? OR pending_token=?", (token, token)).fetchone()
    if not row: return False
    if row["pending_token"] == token:
        conn.execute("UPDATE users SET email=pending_email, pending_email=NULL, pending_token=NULL, verified=1 WHERE id=?", (row["id"],))
    else: conn.execute("UPDATE users SET verified=1, verification_token=NULL WHERE id=?", (row["id"],))
    conn.commit(); return True

def request_email_change(conn, owner_id: int, email: str) -> str | None:
    email = email.strip().lower()
    ensure_verification_delivery()
    if not email or conn.execute("SELECT 1 FROM users WHERE email=? AND id!=?", (email, owner_id)).fetchone(): raise ValueError("Email unavailable")
    token = secrets.token_urlsafe(24)
    with conn:
        if not conn.execute("UPDATE users SET pending_email=?,pending_token=? WHERE id=?", (email, token, owner_id)).rowcount: raise ValueError("Account not found")
        return send_verification_email(email, token)

def resend_verification(conn, email: str) -> str | None:
    """Rotate and send an unverified account token without revealing account existence."""
    ensure_verification_delivery()
    email = email.strip().lower()
    account = conn.execute("SELECT id,verified FROM users WHERE email=?", (email,)).fetchone()
    if not account or account["verified"]: return None
    token = secrets.token_urlsafe(24)
    with conn:
        conn.execute("UPDATE users SET verification_token=? WHERE id=? AND verified=0", (token, account["id"]))
        return send_verification_email(email, token)

def require_owned(conn, table: str, owner_id: int, record_id: int):
    return conn.execute(f"SELECT * FROM {table} WHERE id=? AND owner_id=?", (record_id, owner_id)).fetchone()

def upsert_product(conn, owner_id, name, category="other", nutrition=None, basis=None, use_rate=None, use_unit=None, _commit=True):
    row = conn.execute("SELECT * FROM products WHERE owner_id=? AND lower(name)=lower(?)", (owner_id, name.strip())).fetchone()
    values = (category, nutrition or {}, basis, use_rate, use_unit, owner_id, name.strip())
    if row:
        conn.execute("UPDATE products SET category=?, nutrition_json=?, nutrition_basis=?, use_rate=?, use_unit=? WHERE owner_id=? AND name=?", (category, json_dump(nutrition or json_load(row['nutrition_json'])), basis or row['nutrition_basis'], use_rate, use_unit, owner_id, name.strip()))
        product_id = row["id"]
    else:
        cur = conn.execute("INSERT INTO products(owner_id,name,category,nutrition_json,nutrition_basis,use_rate,use_unit) VALUES(?,?,?,?,?,?,?)", (owner_id, name.strip(), category, json_dump(nutrition or {}), basis, use_rate, use_unit)); product_id = cur.lastrowid
    if _commit: conn.commit()
    return product_id

def add_shopping(conn, owner_id, name, quantity, unit, category="other", nutrition=None, nutrition_basis=None):
    if quantity <= 0: raise ValueError("Quantity must be positive")
    cur = conn.execute(
        "INSERT INTO shopping(owner_id,name,quantity,unit,category,nutrition_json,nutrition_basis) VALUES(?,?,?,?,?,?,?)",
        (owner_id, name.strip(), quantity, unit, category, json_dump(nutrition or {}), nutrition_basis),
    )
    conn.commit(); return cur.lastrowid

def edit_shopping(conn, owner_id, shopping_id, name, quantity, unit, category="other", nutrition=None, nutrition_basis=None):
    if not name.strip() or quantity <= 0: raise ValueError("Name and positive quantity are required")
    if not conn.execute(
        "UPDATE shopping SET name=?,quantity=?,unit=?,category=?,nutrition_json=?,nutrition_basis=? WHERE id=? AND owner_id=?",
        (name.strip(), quantity, unit, category, json_dump(nutrition or {}), nutrition_basis, shopping_id, owner_id),
    ).rowcount: raise ValueError("Shopping entry not found")
    conn.commit()

def set_shopping_checked(conn, owner_id, shopping_id, checked):
    if not conn.execute("UPDATE shopping SET checked=? WHERE id=? AND owner_id=?", (int(checked),shopping_id,owner_id)).rowcount: raise ValueError("Shopping entry not found")
    conn.commit()

def remove_shopping(conn, owner_id, shopping_id, _commit=True):
    if not conn.execute("DELETE FROM shopping WHERE id=? AND owner_id=?", (shopping_id,owner_id)).rowcount: raise ValueError("Shopping entry not found")
    if _commit: conn.commit()

def list_shopping(conn, owner_id):
    return conn.execute("SELECT s.*, COALESCE(SUM(b.remaining_quantity),0) on_hand FROM shopping s LEFT JOIN products p ON p.owner_id=s.owner_id AND lower(p.name)=lower(s.name) LEFT JOIN batches b ON b.product_id=p.id AND b.owner_id=s.owner_id AND b.status='active' WHERE s.owner_id=? GROUP BY s.id ORDER BY s.checked,s.name", (owner_id,)).fetchall()

def buy_shopping(conn, owner_id, shopping_id, purchase_date=None, storage="refrigerated"):
    """Move one owned shopping entry into a new inventory batch and remove the entry."""
    item = require_owned(conn, "shopping", owner_id, shopping_id)
    if not item: raise ValueError("Shopping entry not found")
    preferences(conn, owner_id)
    with conn:
        product_id = upsert_product(
            conn,
            owner_id,
            item["name"],
            item["category"] or "other",
            json_load(item["nutrition_json"]),
            item["nutrition_basis"],
            _commit=False,
        )
        batch_id = add_batch(conn, owner_id, product_id, item["quantity"], item["unit"], purchase_date or date.today(), storage, _commit=False)
        remove_shopping(conn, owner_id, shopping_id, _commit=False)
    return batch_id, item["name"]

def estimate_expiry(conn, owner_id, category, product_name, purchase_date: date, storage):
    prefs = preferences(conn, owner_id); rules = json_load(prefs['estimate_rules'])
    days = rules.get(product_name.lower(), rules.get(category.lower(), rules.get("vegetable", {}))).get(storage, 5)
    return purchase_date + timedelta(days=int(days))

def add_batch(conn, owner_id, product_id, quantity, unit, purchase_date, storage, expiry_date=None, source="entered", _commit=True):
    if quantity <= 0 or not require_owned(conn, "products", owner_id, product_id): raise ValueError("Invalid batch")
    product = require_owned(conn, "products", owner_id, product_id)
    if not expiry_date:
        expiry_date = estimate_expiry(conn, owner_id, product['category'], product['name'], purchase_date, storage); source = "estimated"
    cur = conn.execute("INSERT INTO batches(owner_id,product_id,quantity,remaining_quantity,unit,purchase_date,storage,expiry_date,expiry_source) VALUES(?,?,?,?,?,?,?,?,?)", (owner_id, product_id, quantity, quantity, unit, str(purchase_date), storage, str(expiry_date), source))
    if _commit: conn.commit()
    return cur.lastrowid

def change_batch(conn, owner_id, batch_id, amount, reason):
    batch = require_owned(conn, "batches", owner_id, batch_id)
    if not batch or amount <= 0 or amount > batch['remaining_quantity']: raise ValueError("Invalid quantity or batch")
    remaining = batch['remaining_quantity'] - amount
    status = "finished" if remaining == 0 and reason == "consumed" else ("discarded" if remaining == 0 and reason == "discarded" else "active")
    conn.execute("UPDATE batches SET remaining_quantity=?,status=? WHERE id=? AND owner_id=?", (remaining,status,batch_id,owner_id))
    conn.execute("INSERT INTO events(owner_id,batch_id,quantity_change,reason,occurred_at) VALUES(?,?,?,?,?)", (owner_id,batch_id,-amount,reason,datetime.now(timezone.utc).isoformat())); conn.commit()

def correct_batch(conn, owner_id, batch_id, new_remaining):
    batch = require_owned(conn, "batches", owner_id, batch_id)
    if not batch or new_remaining < 0: raise ValueError("Invalid quantity or batch")
    delta = new_remaining - batch["remaining_quantity"]
    status = "active" if new_remaining > 0 else "finished"
    conn.execute("UPDATE batches SET remaining_quantity=?,status=? WHERE id=? AND owner_id=?", (new_remaining,status,batch_id,owner_id))
    conn.execute("INSERT INTO events(owner_id,batch_id,quantity_change,reason,occurred_at) VALUES(?,?,?,?,?)", (owner_id,batch_id,delta,"correction",datetime.now(timezone.utc).isoformat())); conn.commit()

def finish_batch(conn, owner_id, batch_id):
    batch = require_owned(conn, "batches", owner_id, batch_id)
    if not batch: raise ValueError("Batch not found")
    change_batch(conn, owner_id, batch_id, batch["remaining_quantity"], "consumed") if batch["remaining_quantity"] else None

def remove_batch(conn, owner_id, batch_id):
    batch = require_owned(conn, "batches", owner_id, batch_id)
    if not batch: raise ValueError("Batch not found")
    if batch["remaining_quantity"]: change_batch(conn, owner_id, batch_id, batch["remaining_quantity"], "discarded")
    conn.execute("UPDATE batches SET status='removed' WHERE id=? AND owner_id=?", (batch_id,owner_id)); conn.commit()

def edit_batch(conn, owner_id, batch_id, quantity, unit, purchase_date, storage, expiry_date=None):
    batch = require_owned(conn, "batches", owner_id, batch_id)
    if not batch or quantity <= 0: raise ValueError("Invalid batch")
    product = require_owned(conn, "products", owner_id, batch["product_id"])
    if expiry_date:
        source = "entered"
    else:
        expiry_date = estimate_expiry(conn, owner_id, product["category"], product["name"], purchase_date, storage); source = "estimated"
    consumed = batch["quantity"] - batch["remaining_quantity"]
    if quantity < consumed: raise ValueError("Quantity cannot be less than recorded consumption")
    remaining = quantity - consumed
    conn.execute("UPDATE batches SET quantity=?,remaining_quantity=?,unit=?,purchase_date=?,storage=?,expiry_date=?,expiry_source=?,status=? WHERE id=? AND owner_id=?", (quantity,remaining,unit,str(purchase_date),storage,str(expiry_date),source,"active" if remaining else "finished",batch_id,owner_id)); conn.commit()

def product_detail(conn, owner_id, product_id):
    return require_owned(conn, "products", owner_id, product_id)

def update_product(conn, owner_id, product_id, category, nutrition, basis, use_rate, use_unit, image_data=None, image_mime=None):
    if use_rate is not None and use_rate < 0: raise ValueError("Use rate cannot be negative")
    params=[category,json_dump(nutrition),basis,use_rate or None,use_unit or None]
    sql="UPDATE products SET category=?,nutrition_json=?,nutrition_basis=?,use_rate=?,use_unit=?"
    if image_data is not None: sql += ",image_data=?,image_mime=?"; params.extend([image_data,image_mime])
    params.extend([product_id,owner_id])
    if not conn.execute(sql+" WHERE id=? AND owner_id=?",params).rowcount: raise ValueError("Product not found")
    conn.commit()

def preferences(conn, owner_id):
    row = conn.execute("SELECT * FROM preferences WHERE owner_id=?", (owner_id,)).fetchone()
    if not row:
        conn.execute("INSERT INTO preferences(owner_id,estimate_rules) VALUES(?,?)", (owner_id, json_dump(DEFAULT_RULES))); conn.commit()
        row = conn.execute("SELECT * FROM preferences WHERE owner_id=?", (owner_id,)).fetchone()
    return row

def update_preferences(conn, owner_id, **values):
    allowed = {"timezone", "reminder_time", "paused", "soon_days", "estimate_rules"}
    values = {key: value for key, value in values.items() if key in allowed}; preferences(conn, owner_id)
    if values:
        sets = ", ".join(f"{key}=?" for key in values)
        conn.execute(f"UPDATE preferences SET {sets} WHERE owner_id=?", (*values.values(), owner_id)); conn.commit()

def alerts(conn, owner_id, today=None):
    prefs = preferences(conn, owner_id); today = today or datetime.now(ZoneInfo(prefs['timezone'])).date(); soon_end = today + timedelta(days=prefs['soon_days'] - 1)
    rows = conn.execute("SELECT b.*,p.name,p.category,p.use_rate,p.use_unit,p.nutrition_json,p.nutrition_basis FROM batches b JOIN products p ON p.id=b.product_id WHERE b.owner_id=? AND b.status='active' AND b.remaining_quantity>0 ORDER BY b.expiry_date", (owner_id,)).fetchall()
    grouped = {}
    result = []
    for row in rows:
        expiry = date.fromisoformat(row['expiry_date']); state = 'expired' if expiry < today else ('today' if expiry == today else ('soon' if expiry <= soon_end else None))
        key = (row['product_id'], row['unit']); consumed_before = grouped.get(key, 0); grouped[key] = consumed_before + row['remaining_quantity']
        surplus = None
        if row['use_rate'] and row['use_unit'] == row['unit'] and expiry >= today:
            days = (expiry - today).days + 1; usable = max(0, row['use_rate'] * days / 7 - consumed_before)
            if row['remaining_quantity'] > usable: surplus = {"remaining": row['remaining_quantity'], "expected": round(usable, 2)}
        if state or surplus or (expiry <= soon_end and not row['use_rate']): result.append({**dict(row), "state": state, "surplus": surplus, "usage_rate_needed": expiry <= soon_end and not row['use_rate']})
    order = {'expired': 0, 'today': 1, 'soon': 2, None: 3}; return sorted(result, key=lambda item: (order[item['state']], item['expiry_date']))

def dashboard_groups(conn, owner_id, today=None):
    """Return all active batches divided into fresh stock and items needing attention."""
    notices = {item["id"]: item for item in alerts(conn, owner_id, today)}
    fresh, needs_attention = [], []
    for batch in inventory(conn, owner_id, status="Active"):
        item = dict(batch)
        alert = notices.get(item["id"])
        if alert:
            item.update({key: alert[key] for key in ("state", "surplus", "usage_rate_needed")})
            needs_attention.append(item)
        else:
            item.update({"state": None, "surplus": None, "usage_rate_needed": False})
            fresh.append(item)
    return {"fresh": fresh, "needs_attention": needs_attention}

def inventory(conn, owner_id, query="", category="All", status="All"):
    sql = "SELECT b.*,p.name,p.category,p.nutrition_json,p.nutrition_basis FROM batches b JOIN products p ON p.id=b.product_id WHERE b.owner_id=?"; params=[owner_id]
    if status == "Active": sql += " AND b.status='active'"
    elif status == "Expired": sql += " AND b.status='active' AND b.expiry_date < date('now')"
    elif status == "Soon": sql += " AND b.status='active' AND b.expiry_date <= date('now', '+3 days')"
    if category != "All": sql += " AND p.category=?"; params.append(category)
    if query: sql += " AND lower(p.name) LIKE ?"; params.append(f"%{query.lower()}%")
    return conn.execute(sql + " ORDER BY b.expiry_date", params).fetchall()

def json_dump(value):
    import json; return json.dumps(value)
def json_load(value):
    import json; return json.loads(value or "{}")
