import streamlit as st
import db
from auth import require_login

me = require_login(["Admin"])
st.title("👥 User Management")

users = db.query("SELECT id, username, role, created_at FROM users ORDER BY id")
st.dataframe(users)

st.subheader("Add user")
with st.form("add_user", clear_on_submit=True):
    u = st.text_input("Username")
    p = st.text_input("Password", type="password")
    role = st.selectbox("Role", ["Analyst", "Admin"])
    if st.form_submit_button("Create"):
        if not u.strip() or len(p) < 6:
            st.error("Username required and password must be at least 6 characters.")
        else:
            ok, msg = db.create_user(u, p, role)
            (st.success if ok else st.error)(msg)
            if ok:
                st.rerun()

st.subheader("Edit user")
target = st.selectbox("User", users["username"].tolist())
row = users[users["username"] == target].iloc[0]
c1, c2 = st.columns(2)
new_role = c1.selectbox("Role", ["Analyst", "Admin"], index=["Analyst", "Admin"].index(row["role"]), key="role_edit")
if c1.button("Update role"):
    if row["id"] == me["id"] and new_role != "Admin":
        st.error("You cannot remove your own admin role.")
    else:
        db.execute("UPDATE users SET role=? WHERE id=?", (new_role, int(row["id"])))
        st.rerun()
pw = c2.text_input("New password", type="password", key="pw_edit")
if c2.button("Reset password"):
    if len(pw) < 6:
        st.error("Password must be at least 6 characters.")
    else:
        db.set_password(int(row["id"]), pw)
        st.success("Password updated.")
if st.button("Delete user", type="secondary"):
    if row["id"] == me["id"]:
        st.error("You cannot delete yourself.")
    else:
        db.execute("DELETE FROM users WHERE id=?", (int(row["id"]),))
        st.rerun()
