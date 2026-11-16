"""SQLite layer: six tables (users, upload_batch, account, transactions, alert, report)."""
import hashlib, hmac, os, secrets, sqlite3
from datetime import datetime
import pandas as pd

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "traceguard.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('Admin','Analyst')),
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS upload_batch(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT, uploaded_by TEXT, uploaded_at TEXT, row_count INTEGER
);
CREATE TABLE IF NOT EXISTS account(
    account_id TEXT PRIMARY KEY,
    first_seen TEXT, last_seen TEXT, tx_count INTEGER, total_sent REAL, max_risk REAL
);
CREATE TABLE IF NOT EXISTS transactions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL,
    sender TEXT, receiver TEXT, amount REAL, tx_date TEXT,
    sender_country TEXT, receiver_country TEXT, label REAL,
    rule_score REAL, ml_score REAL, risk_score REAL, reasons TEXT, flagged INTEGER,
    FOREIGN KEY(batch_id) REFERENCES upload_batch(id)
);
CREATE INDEX IF NOT EXISTS idx_tx_sender ON transactions(sender);
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
"""

# columns written to the transactions table (after batch_id)
TX_COLS = ["sender", "receiver", "amount", "tx_date", "sender_country", "receiver_country",
           "label", "rule_score", "ml_score", "risk_score", "reasons", "flagged"]


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


# ---------- users / passwords ----------
def _hash(password, salt_hex):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 200_000).hex()


def create_user(username, password, role="Analyst"):
    salt = secrets.token_hex(16)
    try:
        execute("INSERT INTO users(username,password_hash,salt,role,created_at) VALUES(?,?,?,?,?)",
                (username.strip(), _hash(password, salt), salt, role, now()))
        return True, "User created."
    except sqlite3.IntegrityError:
        return False, "That username already exists."


def set_password(user_id, password):
    salt = secrets.token_hex(16)
    execute("UPDATE users SET password_hash=?, salt=? WHERE id=?", (_hash(password, salt), salt, user_id))


def authenticate(username, password):
    df = query("SELECT * FROM users WHERE username=?", (username.strip(),))
    if df.empty:
        return None
    r = df.iloc[0]
    if hmac.compare_digest(_hash(password, r["salt"]), r["password_hash"]):
        return {"id": int(r["id"]), "username": r["username"], "role": r["role"]}
    return None


def init_db():
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
    if query("SELECT COUNT(*) AS n FROM users").iloc[0]["n"] == 0:
        create_user("admin", "admin123", "Admin")  # default admin: change the password after first login


# ---------- saving an analysed upload ----------
def save_batch(df, filename, username):
    """df must contain TX_COLS. Creates the batch, transactions, alerts and refreshes accounts."""
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
        conn.execute("""INSERT INTO account(account_id,first_seen,last_seen,tx_count,total_sent,max_risk)
                        SELECT sender, MIN(tx_date), MAX(tx_date), COUNT(*), SUM(amount), MAX(risk_score)
                        FROM transactions GROUP BY sender""")
        conn.commit()
        return batch_id
    finally:
        conn.close()
