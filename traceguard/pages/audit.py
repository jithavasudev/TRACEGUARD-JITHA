import streamlit as st
import db
from auth import require_login

require_login(["Admin"])
st.title("🧾 Audit Log")
st.caption("Every login, upload, search, trace, review, case change, export and user change is recorded here.")
log = db.query("SELECT id, ts, username, action, detail FROM audit_log ORDER BY id DESC LIMIT 5000")
c1, c2, c3 = st.columns(3)
users = c1.multiselect("User", sorted(log["username"].dropna().unique()))
actions = c2.multiselect("Action", sorted(log["action"].dropna().unique()))
text = c3.text_input("Search detail")
if users:
    log = log[log["username"].isin(users)]
if actions:
    log = log[log["action"].isin(actions)]
if text:
    log = log[log["detail"].fillna("").str.contains(text, case=False)]
st.dataframe(log, hide_index=True, height=500)
st.download_button("⬇️ Download audit log (CSV)", log.to_csv(index=False).encode(), "audit_log.csv", "text/csv")
