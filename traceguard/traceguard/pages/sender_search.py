import pandas as pd
import plotly.express as px
import streamlit as st
import db
from auth import require_login

require_login()
st.title("🔎 Sender Search")

q = st.text_input("Sender account (full or partial ID)")
if not q.strip():
    st.info("Type part of an account ID to search.")
    st.stop()

acc = db.query("SELECT * FROM account WHERE account_id LIKE ? ORDER BY max_risk DESC LIMIT 50", (f"%{q.strip()}%",))
if acc.empty:
    st.warning("No sender found.")
    st.stop()
sender = st.selectbox("Matching accounts", acc["account_id"].tolist()) if len(acc) > 1 else acc.iloc[0]["account_id"]

a = acc[acc["account_id"] == sender].iloc[0]
k = st.columns(4)
k[0].metric("Transactions", int(a.tx_count))
k[1].metric("Total sent", f"{a.total_sent:,.0f}")
k[2].metric("Highest risk", a.max_risk)
k[3].metric("Active", f"{a.first_seen[:10]} → {a.last_seen[:10]}")

hist = db.query("""SELECT t.id, t.tx_date, t.receiver, t.amount, t.risk_score, t.flagged, t.reasons,
                          a.status AS alert_status
                   FROM transactions t LEFT JOIN alert a ON a.tx_id=t.id
                   WHERE t.sender=? ORDER BY t.tx_date""", (sender,))
hist["tx_date"] = pd.to_datetime(hist["tx_date"])
hist["flagged"] = hist["flagged"].map({1: "Flagged", 0: "Normal"})
st.plotly_chart(px.scatter(hist, x="tx_date", y="amount", color="flagged",
                           color_discrete_map={"Flagged": "red", "Normal": "steelblue"},
                           hover_data=["receiver", "risk_score"], title="Transaction history"))
t1, t2 = st.tabs(["Alerts", "Full history"])
t1.dataframe(hist[hist["flagged"] == "Flagged"].drop(columns=["flagged"]))
t2.dataframe(hist.drop(columns=["reasons"]))
