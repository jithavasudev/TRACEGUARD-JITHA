import streamlit as st
import db
from auth import require_login

user = require_login()
st.title("⚙️ My Account")
st.write(f"Signed in as **{user['username']}** ({user['role']})")
with st.form("pw"):
    cur = st.text_input("Current password", type="password")
    p1 = st.text_input("New password", type="password")
    p2 = st.text_input("Confirm new password", type="password")
    if st.form_submit_button("Change password", type="primary"):
        ok, _ = db.authenticate(user["username"], cur)
        err = db.password_error(p1, user["username"])
        if not ok:
            st.error("Current password is incorrect.")
        elif err:
            st.error(err)
        elif p1 != p2:
            st.error("Passwords do not match.")
        else:
            db.set_password(user["id"], p1, must_change=False)
            db.log(user["username"], "password_changed")
            st.success("Password updated.")
