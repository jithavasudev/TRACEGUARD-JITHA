import streamlit as st
import db
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

if df.empty:
    st.success("No alerts match these filters.")
    st.stop()
st.dataframe(df.drop(columns=["tx_id", "rule_score", "ml_score"]), height=300)

st.subheader("Review an alert")
aid = st.selectbox("Alert ID", df["alert_id"].tolist())
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
                   (new, user["username"], db.now(), note, int(aid)))
        st.success(f"Alert {aid} marked {new}.")
        st.rerun()
