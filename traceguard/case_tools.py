"""Case management and tamper-evident evidence export."""
import hashlib, io, json, zipfile
import pandas as pd
import db

STATUSES = ["Open", "Investigating", "Freeze Requested", "Closed"]


def add_event(case_id, username, text):
    db.execute("INSERT INTO case_event(case_id,ts,username,event) VALUES(?,?,?,?)",
               (int(case_id), db.now(), username, text))


def add_alerts(case_id, alert_ids, username):
    conn = db.get_conn()
    try:
        conn.executemany("INSERT OR IGNORE INTO case_alert(case_id,alert_id) VALUES(?,?)",
                         [(int(case_id), int(a)) for a in alert_ids])
        conn.commit()
    finally:
        conn.close()
    add_event(case_id, username, f"Added {len(alert_ids)} alert(s)")
    db.log(username, "case_add_alerts", f"case {case_id}: {len(alert_ids)} alerts")


def create_case(title, alert_ids, username):
    cid = db.execute("INSERT INTO cases(title,status,owner,created_by,created_at) VALUES(?,?,?,?,?)",
                     (title, "Open", username, username, db.now()))
    add_event(cid, username, "Case created")
    if len(alert_ids):
        add_alerts(cid, alert_ids, username)
    db.log(username, "case_created", f"case {cid}: {title}")
    return cid


def case_list():
    return db.query("""
        SELECT c.id, c.title, c.status, c.owner, c.created_at,
               COUNT(ca.alert_id) AS alerts, COALESCE(SUM(t.amount),0) AS money_at_risk,
               MAX(a.risk_score) AS max_risk, MIN(t.tx_date) AS first_tx, MAX(t.tx_date) AS last_tx
        FROM cases c LEFT JOIN case_alert ca ON ca.case_id=c.id
        LEFT JOIN alert a ON a.id=ca.alert_id LEFT JOIN transactions t ON t.id=a.tx_id
        GROUP BY c.id ORDER BY (c.status='Closed'), money_at_risk DESC""")


def case_transactions(case_id):
    return db.query("""SELECT t.id AS tx_id, a.id AS alert_id, t.sender, t.receiver, t.amount, t.tx_date,
                              t.device_id, t.ip, t.channel, a.risk_score, a.status, a.reasons
                       FROM case_alert ca JOIN alert a ON a.id=ca.alert_id JOIN transactions t ON t.id=a.tx_id
                       WHERE ca.case_id=? ORDER BY t.tx_date""", (int(case_id),))


def accounts_in_case(tx):
    """Per-account money in/out and a role hint, for freeze requests."""
    out = tx.groupby("sender")["amount"].sum().rename("sent")
    inn = tx.groupby("receiver")["amount"].sum().rename("received")
    acc = pd.concat([out, inn], axis=1).fillna(0).reset_index().rename(columns={"index": "account"})
    acc["role"] = acc.apply(lambda r: "Pass-through (mule)" if r.sent > 0 and r.received > 0
                            else ("Collector / destination" if r.received > 0 else "Source / payer"), axis=1)
    return acc.sort_values(["role", "received", "sent"], ascending=[True, False, False]).reset_index(drop=True)


def summary_text(case, tx, acc, username):
    return "\n".join([
        f"# Case #{case['id']}: {case['title']}", f"Status: {case['status']} · Owner: {case['owner']}",
        f"Exported by {username} on {db.now()}", "",
        f"- Linked alerts: {len(tx)}", f"- Money at risk: {tx['amount'].sum():,.2f}",
        f"- Period: {tx['tx_date'].min()} to {tx['tx_date'].max()}",
        f"- Accounts involved: {len(acc)}", "", "## Why these were flagged"] +
        [f"- {k}: {v}" for k, v in tx["reasons"].fillna("").str.split("; ").explode().str.split(":").str[0]
         .str.strip().replace("", pd.NA).dropna().value_counts().items()])


def evidence_zip(case_id, username):
    """Builds a zip (summary, transactions, accounts, manifest with SHA-256) and logs its hash."""
    case = db.query("SELECT * FROM cases WHERE id=?", (int(case_id),)).iloc[0]
    tx = case_transactions(case_id)
    acc = accounts_in_case(tx)
    files = {"case_summary.md": summary_text(case, tx, acc, username).encode(),
             "transactions.csv": tx.to_csv(index=False).encode(),
             "accounts_to_review.csv": acc.to_csv(index=False).encode()}
    manifest = {"case_id": int(case_id), "exported_by": username, "exported_at": db.now(),
                "files": {k: hashlib.sha256(v).hexdigest() for k, v in files.items()}}
    files["manifest.json"] = json.dumps(manifest, indent=2).encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in files.items():
            z.writestr(k, v)
    data = buf.getvalue()
    sha = hashlib.sha256(data).hexdigest()
    name = f"case_{case_id}_evidence.zip"
    db.execute("INSERT INTO evidence_log(case_id,filename,sha256,created_at,created_by) VALUES(?,?,?,?,?)",
               (int(case_id), name, sha, db.now(), username))
    add_event(case_id, username, f"Evidence package exported (SHA-256 {sha[:12]}...)")
    db.log(username, "evidence_export", f"case {case_id} sha256 {sha}")
    return data, sha, name
