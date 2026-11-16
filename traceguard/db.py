"""SQLite layer. Tables: users, upload_batch, account, transactions, alert, report,
audit_log, cases, case_alert, case_event, evidence_log."""
import hashlib, hmac, os, secrets, sqlite3
from datetime import datetime, timedelta
import pandas as pd

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "traceguard.db")
MAX_ATTEMPTS, LOCK_MINUTES = 5, 10

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL, salt TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('Admin','Analyst')),
    created_at TEXT,
    failed_attempts INTEGER DEFAULT 0, locked_until TEXT, must_change INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS upload_batch(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT, uploaded_by TEXT, uploaded_at TEXT, row_count INTEGER
);
CREATE TABLE IF NOT EXISTS account(
    account_id TEXT PRIMARY KEY,
    first_seen TEXT, last_seen TEXT, tx_count INTEGER, total_sent REAL, total_received REAL, max_risk REAL
);
CREATE TABLE IF NOT EXISTS transactions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL,
    sender TEXT, receiver TEXT, amount REAL, tx_date TEXT,
    sender_country TEXT, receiver_country TEXT, device_id TEXT, ip TEXT, channel TEXT, label REAL,
    rule_score REAL, ml_score REAL, risk_score REAL, reasons TEXT, flagged INTEGER,
    FOREIGN KEY(batch_id) REFERENCES upload_batch(id)
);
CREATE INDEX IF NOT EXISTS idx_tx_sender ON transactions(sender);
CREATE INDEX IF NOT EXISTS idx_tx_receiver ON transactions(receiver);
CREATE INDEX IF NOT EXISTS idx_tx_batch ON transactions(batch_id);
CREATE TABLE IF NOT EXISTS alert(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tx_id INTEGER UNIQUE NOT NULL, batch_id INTEGER,
    risk_score REAL, reasons TEXT,
    status TEXT NOT NULL DEFAULT 'Open' CHECK(status IN ('Open','Confirmed','False Positive')),
    reviewed_by TEXT, reviewed_at TEXT, note TEXT,
    FOREIGN KEY(tx_id) REFERENCES transactions(id)
);
CREATE TABLE IF NOT EXISTS report(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT, batch_id INTEGER, generated_by TEXT, generated_at TEXT, content TEXT
);
CREATE TABLE IF NOT EXISTS audit_log(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, username TEXT, action TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS cases(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT, status TEXT DEFAULT 'Open', owner TEXT, created_by TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS case_alert(
    case_id INTEGER NOT NULL, alert_id INTEGER NOT NULL, PRIMARY KEY(case_id, alert_id)
);
CREATE TABLE IF NOT EXISTS case_event(
    id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER, ts TEXT, username TEXT, event TEXT
);
CREATE TABLE IF NOT EXISTS evidence_log(
    id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER, filename TEXT, sha256 TEXT,
    created_at TEXT, created_by TEXT
);
"""

# columns added to databases created by an older version of the app
MIGRATIONS = {
    "users": {"failed_attempts": "INTEGER DEFAULT 0", "locked_until": "TEXT", "must_change": "INTEGER DEFAULT 0"},
    "transactions": {"device_id": "TEXT", "ip": "TEXT", "channel": "TEXT"},
    "account": {"total_received": "REAL"},
}

TX_COLS = ["sender", "receiver", "amount", "tx_date", "sender_country", "receiver_country",
           "device_id", "ip", "channel", "label", "rule_score", "ml_score", "risk_score", "reasons", "flagged"]


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def query(sql, params=()):
    conn = get_conn()
    try:
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()


def execute(sql, params=()):
    conn = get_conn()
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def log(username, action, detail=""):
    """Audit trail: who did what, when."""
    execute("INSERT INTO audit_log(ts,username,action,detail) VALUES(?,?,?,?)",
            (now(), username, action, str(detail)[:500]))


# ---------- passwords & users ----------
def _hash(password, salt_hex):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 200_000).hex()


def password_error(pw, username=""):
    """Returns a message if the password breaks the policy, else None."""
    if len(pw) < 8:
        return "Password must be at least 8 characters."
    if not (any(c.isalpha() for c in pw) and any(c.isdigit() for c in pw)):
        return "Password must contain letters and digits."
    if pw.lower() in ("admin123", "password1", "12345678", (username or "").lower()):
        return "That password is too easy to guess."
    return None


def create_user(username, password, role="Analyst", must_change=True):
    salt = secrets.token_hex(16)
    try:
        execute("INSERT INTO users(username,password_hash,salt,role,created_at,must_change) VALUES(?,?,?,?,?,?)",
                (username.strip(), _hash(password, salt), salt, role, now(), int(must_change)))
        return True, "User created. They must change the password at first login."
    except sqlite3.IntegrityError:
        return False, "That username already exists."


def set_password(user_id, password, must_change=True):
    salt = secrets.token_hex(16)
    execute("UPDATE users SET password_hash=?, salt=?, must_change=?, failed_attempts=0, locked_until=NULL WHERE id=?",
            (_hash(password, salt), salt, int(must_change), user_id))


def authenticate(username, password):
    """Returns (user_dict | None, message). Locks the account after repeated failures."""
    df = query("SELECT * FROM users WHERE username=?", (username.strip(),))
    if df.empty:
        log(username.strip() or "?", "login_failed", "unknown user")
        return None, "Invalid username or password."
    r = df.iloc[0]
    uid = int(r["id"])
    lock = r["locked_until"]
    if isinstance(lock, str) and lock > now():
        log(r["username"], "login_blocked", "account locked")
        return None, f"Account locked until {lock}. Ask an admin to unlock it."
    if hmac.compare_digest(_hash(password, r["salt"]), r["password_hash"]):
        execute("UPDATE users SET failed_attempts=0, locked_until=NULL WHERE id=?", (uid,))
        log(r["username"], "login_ok")
        return {"id": uid, "username": r["username"], "role": r["role"], "must_change": bool(r["must_change"])}, ""
    attempts = int(r["failed_attempts"] or 0) + 1
    if attempts >= MAX_ATTEMPTS:
        until = (datetime.now() + timedelta(minutes=LOCK_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
        execute("UPDATE users SET failed_attempts=0, locked_until=? WHERE id=?", (until, uid))
        log(r["username"], "account_locked", f"after {attempts} failed attempts")
        return None, f"Too many failed attempts. Account locked for {LOCK_MINUTES} minutes."
    execute("UPDATE users SET failed_attempts=? WHERE id=?", (attempts, uid))
    log(r["username"], "login_failed", f"attempt {attempts}")
    return None, f"Invalid username or password. ({MAX_ATTEMPTS - attempts} attempts left)"


def init_db():
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            for c, t in cols.items():
                if c not in have:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {c} {t}")
        conn.commit()
    finally:
        conn.close()
    if query("SELECT COUNT(*) AS n FROM users").iloc[0]["n"] == 0:
        create_user("admin", "admin123", "Admin", must_change=True)  # must be changed at first login


# ---------- saving an analysed upload ----------
def save_batch(df, filename, username):
    conn = get_conn()
    try:
        cur = conn.execute("INSERT INTO upload_batch(filename,uploaded_by,uploaded_at,row_count) VALUES(?,?,?,?)",
                           (filename, username, now(), len(df)))
        batch_id = cur.lastrowid
        conn.commit()
        out = df[TX_COLS].copy()
        out.insert(0, "batch_id", batch_id)
        out.to_sql("transactions", conn, if_exists="append", index=False, chunksize=20000)
        conn.execute("""INSERT INTO alert(tx_id,batch_id,risk_score,reasons)
                        SELECT id,batch_id,risk_score,reasons FROM transactions
                        WHERE batch_id=? AND flagged=1""", (batch_id,))
        conn.execute("DELETE FROM account")
        conn.execute("""INSERT INTO account(account_id,first_seen,last_seen,tx_count,total_sent,total_received,max_risk)
                        WITH x AS (
                          SELECT sender a, tx_date d, amount s, 0.0 r, risk_score k FROM transactions
                          UNION ALL
                          SELECT receiver, tx_date, 0.0, amount, risk_score FROM transactions)
                        SELECT a, MIN(d), MAX(d), COUNT(*), SUM(s), SUM(r), MAX(k) FROM x GROUP BY a""")
        conn.commit()
    finally:
        conn.close()
    log(username, "upload", f"{filename}: {len(df)} rows, batch {batch_id}")
    return batch_id
