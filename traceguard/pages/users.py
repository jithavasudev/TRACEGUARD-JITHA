import streamlit as st
import db
from auth import require_login

me = require_login(["Admin"])
st.title("👥 User Management")
users = db.query("SELECT id, username, role, created_at, failed_attempts, locked_until, must_change FROM users ORDER BY id")
st.dataframe(users, hide_index=True)

st.subheader("Add user")
with st.form("add_user", clear_on_submit=True):
    u = st.text_input("Username")
    p = st.text_input("Temporary password", type="password")
    role = st.selectbox("Role", ["Analyst", "Admin"])
    if st.form_submit_button("Create"):
        err = db.password_error(p, u) if p else "Password required."
        if not u.strip():
            st.error("Username required.")
        elif err:
            st.error(err)
        else:
            ok, msg = db.create_user(u, p, role, must_change=True)
            (st.success if ok else st.error)(msg)
            if ok:
                db.log(me["username"], "user_created", f"{u} ({role})")
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
        db.log(me["username"], "role_changed", f"{target} -> {new_role}")
        st.rerun()
pw = c2.text_input("New temporary password", type="password", key="pw_edit")
if c2.button("Reset password"):
    err = db.password_error(pw, target)
    if err:
        st.error(err)
    else:
        db.set_password(int(row["id"]), pw, must_change=True)
        db.log(me["username"], "password_reset", target)
        st.success("Password reset. The user must change it at next login.")
if st.button("Unlock account"):
    db.execute("UPDATE users SET failed_attempts=0, locked_until=NULL WHERE id=?", (int(row["id"]),))
    db.log(me["username"], "account_unlocked", target)
    st.rerun()
if st.button("Delete user"):
    if row["id"] == me["id"]:
        st.error("You cannot delete yourself.")
    else:
        db.execute("DELETE FROM users WHERE id=?", (int(row["id"]),))
        db.log(me["username"], "user_deleted", target)
        st.rerun()
