import pandas as pd
import streamlit as st
import case_tools, db
from auth import require_login

user = require_login()
st.title("🚨 Alerts")

c1, c2, c3 = st.columns(3)
status = c1.multiselect("Status", ["Open", "Confirmed", "False Positive"], default=["Open"])
min_risk = c2.slider("Minimum risk score", 0, 100, 0)
limit = c3.selectbox("Show top", [100, 500, 1000], index=0)
if not status:
    st.info("Select at least one status.")
    st.stop()

ph = ",".join("?" * len(status))
df = db.query(f"""SELECT a.id AS alert_id, a.status, a.risk_score, t.sender, t.receiver, t.amount, t.tx_date,
                         a.reasons, a.reviewed_by, a.note, t.id AS tx_id, t.rule_score, t.ml_score
                  FROM alert a JOIN transactions t ON t.id=a.tx_id
                  WHERE a.status IN ({ph}) AND a.risk_score>=?
                  ORDER BY a.risk_score DESC LIMIT ?""", (*status, min_risk, limit))

counts = db.query("SELECT status, COUNT(*) AS n FROM alert GROUP BY status").set_index("status")["n"]
k = st.columns(3)
for i, s in enumerate(["Open", "Confirmed", "False Positive"]):
    k[i].metric(s, int(counts.get(s, 0)))

with st.expander("📈 Rule performance from analyst feedback"):
    fb = db.query("SELECT reasons, status FROM alert WHERE status IN ('Confirmed','False Positive')")
    if fb.empty:
        st.caption("Mark alerts as Confirmed or False Positive and this table shows which rules are most reliable.")
    else:
        ex = fb.assign(rule=fb["reasons"].fillna("").str.split("; ")).explode("rule")
        ex["rule"] = ex["rule"].str.split(":").str[0].str.strip()
        t = ex[ex["rule"] != ""].groupby("rule")["status"].value_counts().unstack(fill_value=0)
        for col in ("Confirmed", "False Positive"):
            if col not in t:
                t[col] = 0
        t["precision"] = t["Confirmed"] / (t["Confirmed"] + t["False Positive"])
        st.dataframe(t.sort_values("precision").style.format({"precision": "{:.0%}"}))
        st.caption("Rules with low precision are candidates for a higher threshold or a lower weight.")

if df.empty:
    st.success("No alerts match these filters.")
    st.stop()
st.dataframe(df.drop(columns=["tx_id", "rule_score", "ml_score"]), height=300)

st.subheader("Review an alert")
aid = int(st.selectbox("Alert ID", df["alert_id"].tolist()))
row = df[df["alert_id"] == aid].iloc[0]
st.markdown(f"**{row.sender} → {row.receiver}** · amount **{row.amount:,.2f}** · {row.tx_date}")
m = st.columns(3)
m[0].metric("Risk score", row.risk_score)
m[1].metric("Rule score", row.rule_score)
m[2].metric("ML score", row.ml_score)
st.markdown("**Why it was flagged:**")
for r in str(row.reasons).split("; "):
    if r:
        st.markdown(f"- {r}")

note = st.text_input("Analyst note", value=row.note or "")
b = st.columns(3)
for col, new in zip(b, ["Confirmed", "False Positive", "Open"]):
    if col.button(f"Mark {new}", key=f"{new}_{aid}"):
        db.execute("UPDATE alert SET status=?, reviewed_by=?, reviewed_at=?, note=? WHERE id=?",
                   (new, user["username"], db.now(), note, aid))
        db.log(user["username"], "alert_review", f"alert {aid} -> {new}")
        st.success(f"Alert {aid} marked {new}.")
        st.rerun()

st.subheader("Add to a case")
cases = db.query("SELECT id, title FROM cases WHERE status!='Closed' ORDER BY id DESC")
labels = {0: "➕ New case"} | {int(r.id): f"#{r.id} · {r.title}" for r in cases.itertuples()}
pick = st.selectbox("Case", list(labels), format_func=labels.get)
title = st.text_input("New case title", value=f"Suspicious activity: {row.sender}") if pick == 0 else None
if st.button("Add alert to case"):
    if pick == 0:
        cid = case_tools.create_case(title, [aid], user["username"])
        st.success(f"Created case #{cid}.")
    else:
        case_tools.add_alerts(pick, [aid], user["username"])
        st.success(f"Added to case #{pick}.")
