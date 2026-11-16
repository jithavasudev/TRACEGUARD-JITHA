import streamlit as st
import db

st.set_page_config(page_title="TraceGuard AML", page_icon="🛡️", layout="wide")
db.init_db()
st.session_state.setdefault("user", None)

# ---------- login ----------
if not st.session_state.user:
    st.title("🛡️ TraceGuard")
    st.caption("Cyber-financial-crime monitoring: mule detection, network tracing and case management")
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        with st.form("login"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Log in", type="primary"):
                user, msg = db.authenticate(username, password)
                if user:
                    st.session_state.user = user
                    st.rerun()
                else:
                    st.error(msg)
        st.info("First run: **admin / admin123**. You will be asked to set a new password straight away.")
    st.stop()

user = st.session_state.user

# ---------- forced password change ----------
if user.get("must_change"):
    st.title("🔑 Set a new password")
    st.write(f"Hello **{user['username']}**. You must choose a new password before continuing.")
    with st.form("force_change"):
        p1 = st.text_input("New password", type="password")
        p2 = st.text_input("Confirm new password", type="password")
        if st.form_submit_button("Save password", type="primary"):
            err = db.password_error(p1, user["username"])
            if err:
                st.error(err)
            elif p1 != p2:
                st.error("Passwords do not match.")
            else:
                db.set_password(user["id"], p1, must_change=False)
                db.log(user["username"], "password_changed", "forced first-login change")
                user["must_change"] = False
                st.rerun()
    st.stop()

# ---------- role-based navigation ----------
pages = [
    st.Page("pages/dashboard.py", title="Dashboard", icon="📊", default=True),
    st.Page("pages/upload.py", title="Upload & Analyse", icon="📤"),
    st.Page("pages/alerts.py", title="Alerts", icon="🚨"),
    st.Page("pages/network.py", title="Network & Trace", icon="🕸️"),
    st.Page("pages/cases.py", title="Cases", icon="🗂️"),
    st.Page("pages/sender_search.py", title="Account Search", icon="🔎"),
    st.Page("pages/assistant.py", title="Assistant", icon="💬"),
    st.Page("pages/account.py", title="My Account", icon="⚙️"),
]
if user["role"] == "Admin":
    pages += [st.Page("pages/reports.py", title="Admin Reports", icon="📑"),
              st.Page("pages/users.py", title="User Management", icon="👥"),
              st.Page("pages/audit.py", title="Audit Log", icon="🧾")]

nav = st.navigation(pages)
with st.sidebar:
    st.markdown(f"**{user['username']}** · {user['role']}")
    if st.button("Log out"):
        db.log(user["username"], "logout")
        st.session_state.clear()
        st.rerun()
nav.run()
