import pandas as pd
import plotly.express as px
import streamlit as st
import db
from auth import require_login

user = require_login()
st.title("🔎 Account Search")

q = st.text_input("Account ID (full or partial)")
if not q.strip():
    st.info("Type part of an account ID. Both senders and receivers are searchable.")
    st.stop()

acc = db.query("SELECT * FROM account WHERE account_id LIKE ? ORDER BY max_risk DESC LIMIT 50", (f"%{q.strip()}%",))
if acc.empty:
    st.warning("No account found.")
    st.stop()
acct = st.selectbox("Matching accounts", acc["account_id"].tolist()) if len(acc) > 1 else acc.iloc[0]["account_id"]
if st.session_state.get("last_search") != acct:
    st.session_state["last_search"] = acct
    db.log(user["username"], "account_view", acct)

a = acc[acc["account_id"] == acct].iloc[0]
k = st.columns(5)
k[0].metric("Transactions", int(a.tx_count))
k[1].metric("Total sent", f"{a.total_sent:,.0f}")
k[2].metric("Total received", f"{(a.total_received or 0):,.0f}")
k[3].metric("Highest risk", a.max_risk)
k[4].metric("Last active", a.last_seen[:10])
if (a.total_sent or 0) > 0 and (a.total_received or 0) > 0:
    st.caption(f"Money out / money in: {a.total_sent / a.total_received:.0%}. "
               "A ratio close to 100% means funds pass straight through, which is typical of mule accounts.")

hist = db.query("""SELECT t.id, t.tx_date, t.sender, t.receiver, t.amount, t.channel, t.device_id, t.ip,
                          t.risk_score, t.flagged, t.reasons, a.status AS alert_status,
                          CASE WHEN t.sender=? THEN 'out' ELSE 'in' END AS direction
                   FROM transactions t LEFT JOIN alert a ON a.tx_id=t.id
                   WHERE t.sender=? OR t.receiver=? ORDER BY t.tx_date""", (acct, acct, acct))
hist["tx_date"] = pd.to_datetime(hist["tx_date"])
hist["flag"] = hist["flagged"].map({1: "Flagged", 0: "Normal"})
st.plotly_chart(px.scatter(hist, x="tx_date", y="amount", color="flag", symbol="direction",
                           color_discrete_map={"Flagged": "red", "Normal": "steelblue"},
                           hover_data=["sender", "receiver", "risk_score"], title="Money in and out"))

devs = [d for d in hist.loc[hist["direction"] == "out", "device_id"].dropna().unique() if str(d).lower() not in ("", "nan")]
if devs:
    ph = ",".join("?" * len(devs))
    linked = db.query(f"""SELECT device_id, sender AS linked_account, COUNT(*) AS tx_count FROM transactions
                          WHERE device_id IN ({ph}) AND sender!=? GROUP BY device_id, sender""", (*devs, acct))
    if not linked.empty:
        st.warning("Other accounts used the same device(s) as this account.")
        st.dataframe(linked, hide_index=True)

t1, t2 = st.tabs(["Alerts", "Full history"])
t1.dataframe(hist[hist["flagged"] == 1].drop(columns=["flag"]), hide_index=True)
t2.dataframe(hist.drop(columns=["reasons", "flag"]), hide_index=True)
