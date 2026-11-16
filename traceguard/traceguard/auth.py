import streamlit as st


def require_login(roles=None):
    """Call at the top of every page. Stops the page if not logged in or role not allowed."""
    user = st.session_state.get("user")
    if not user:
        st.warning("Please log in first.")
        st.stop()
    if roles and user["role"] not in roles:
        st.error("You do not have permission to view this page.")
        st.stop()
    return user
