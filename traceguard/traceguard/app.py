import streamlit as st
import db

st.set_page_config(page_title="TraceGuard AML", page_icon="🛡️", layout="wide")
db.init_db()

if "user" not in st.session_state:
    st.session_state.user = None

# ---------- login ----------
if not st.session_state.user:
    st.title("🛡️ TraceGuard AML")
    st.caption("Transaction monitoring and suspicious-activity detection")
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        with st.form("login"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Log in", type="primary"):
                user = db.authenticate(username, password)
                if user:
                    st.session_state.user = user
                    st.rerun()
                else:
                    st.error("Invalid username or password.")
        st.info("First run: log in as **admin / admin123**, then change the password under User Management.")
    st.stop()

# ---------- role-based navigation ----------
user = st.session_state.user
pages = [
    st.Page("pages/dashboard.py", title="Dashboard", icon="📊", default=True),
    st.Page("pages/upload.py", title="Upload & Analyse", icon="📤"),
    st.Page("pages/alerts.py", title="Alerts", icon="🚨"),
    st.Page("pages/sender_search.py", title="Sender Search", icon="🔎"),
    st.Page("pages/assistant.py", title="Assistant", icon="💬"),
]
if user["role"] == "Admin":
    pages += [st.Page("pages/reports.py", title="Admin Reports", icon="📑"),
              st.Page("pages/users.py", title="User Management", icon="👥")]

nav = st.navigation(pages)
with st.sidebar:
    st.markdown(f"**{user['username']}** · {user['role']}")
    if st.button("Log out"):
        st.session_state.clear()
        st.rerun()
nav.run()
