import pandas as pd
import streamlit as st
import case_tools, db
from auth import require_login

user = require_login()
st.title("🗂️ Cases")

cl = case_tools.case_list()
if cl.empty:
    st.info("No cases yet. Create one from an alert, or from a ring under **Network & Trace**.")
    st.stop()

show_closed = st.checkbox("Show closed cases", value=False)
view = cl if show_closed else cl[cl["status"] != "Closed"]
st.caption("Priority queue: open cases ranked by money at risk.")
st.dataframe(view, hide_index=True)
if view.empty:
    st.stop()

titles = {int(r.id): f"#{r.id} · {r.title}" for r in view.itertuples()}
cid = int(st.selectbox("Open case", list(titles), format_func=titles.get))
case = cl[cl["id"] == cid].iloc[0]
tx = case_tools.case_transactions(cid)

m = st.columns(4)
m[0].metric("Money at risk", f"{case.money_at_risk:,.0f}")
m[1].metric("Linked alerts", int(case.alerts))
m[2].metric("Highest risk", case.max_risk if pd.notna(case.max_risk) else "-")
span = (pd.to_datetime(case.last_tx) - pd.to_datetime(case.first_tx)) if pd.notna(case.first_tx) else None
m[3].metric("Activity window", f"{span.days + 1} day(s)" if span is not None else "-")

st.subheader("Status & owner")
users = db.query("SELECT username FROM users ORDER BY username")["username"].tolist()
c1, c2, c3 = st.columns([1, 1, 1])
new_status = c1.selectbox("Status", case_tools.STATUSES, index=case_tools.STATUSES.index(case.status))
new_owner = c2.selectbox("Owner", users, index=users.index(case.owner) if case.owner in users else 0)
if c3.button("Save", type="primary"):
    db.execute("UPDATE cases SET status=?, owner=? WHERE id=?", (new_status, new_owner, cid))
    if new_status != case.status:
        case_tools.add_event(cid, user["username"], f"Status changed: {case.status} → {new_status}")
    if new_owner != case.owner:
        case_tools.add_event(cid, user["username"], f"Owner changed: {case.owner} → {new_owner}")
    db.log(user["username"], "case_update", f"case {cid}: {new_status}, {new_owner}")
    st.rerun()

st.subheader("Timeline")
note = st.text_input("Add a note", key=f"note_{cid}")
if st.button("Add note") and note.strip():
    case_tools.add_event(cid, user["username"], note.strip())
    st.rerun()
ev = db.query("SELECT ts, username, event FROM case_event WHERE case_id=? ORDER BY id DESC", (cid,))
st.dataframe(ev, hide_index=True)

st.subheader("Linked transactions")
st.dataframe(tx.drop(columns=["reasons"]), hide_index=True)

st.subheader("Accounts to review / freeze")
if tx.empty:
    st.caption("No transactions linked yet.")
else:
    acc = case_tools.accounts_in_case(tx)
    st.dataframe(acc, hide_index=True)
    st.download_button("⬇️ Freeze-request list (CSV)", acc.to_csv(index=False).encode(), f"case_{cid}_accounts.csv", "text/csv")

    st.subheader("Evidence package")
    st.caption("A ZIP with the case summary, transactions, accounts and a manifest of SHA-256 hashes. The package hash is "
               "logged so you can prove later that the files were not altered.")
    if st.button("Prepare evidence package"):
        st.session_state[f"evidence_{cid}"] = case_tools.evidence_zip(cid, user["username"])
    if f"evidence_{cid}" in st.session_state:
        data, sha, name = st.session_state[f"evidence_{cid}"]
        st.download_button(f"⬇️ Download {name}", data, name, "application/zip")
        st.code(f"SHA-256: {sha}")
    log = db.query("SELECT created_at, created_by, filename, sha256 FROM evidence_log WHERE case_id=? ORDER BY id DESC", (cid,))
    if not log.empty:
        st.caption("Previous exports")
        st.dataframe(log, hide_index=True)
