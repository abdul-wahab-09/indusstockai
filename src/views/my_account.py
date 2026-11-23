import streamlit as st

from .. import auth, user_service, widgets
from .. import inventory_service as svc
from ..ui import flash, html, page_header, show_flash, show_table

XLSX_NOTE = "Keep it somewhere safe, such as a password manager or a locked drawer."


def render() -> None:
    page_header("👤 My Account", "Your profile, sign-in security and recovery options.")
    show_flash()
    session = auth.current_user()
    user = user_service.get_user(session["id"])

    html(widgets.kpi_grid([
        widgets.kpi_card("🪪", "Username", user["username"], "", "blue"),
        widgets.kpi_card("🛡️", "Role", "Administrator" if user["role"] == "admin" else "User", "", "violet"),
        widgets.kpi_card("📧", "E-mail", "Set" if user["email"] else "Not set", user["email"] or "needed for e-mail reset",
                         "green" if user["email"] else "amber"),
        widgets.kpi_card("🔑", "Recovery code", "Ready" if user["has_recovery"] else "Not set", "offline password reset",
                         "green" if user["has_recovery"] else "amber"),
    ]))

    profile, security_tab, activity = st.tabs(["Profile", "Password & recovery", "My activity"])

    with profile:
        with st.form("profile_form"):
            email = st.text_input("E-mail address", user["email"] or "", placeholder="you@company.com",
                                  help="Used only for password-reset codes and username reminders.")
            if st.form_submit_button("💾 Save e-mail", type="primary"):
                try:
                    user_service.set_email(user["id"], email, actor=user["username"])
                    flash("E-mail saved.")
                    st.rerun()
                except ValueError as error:
                    st.error(str(error))

    with security_tab:
        st.subheader("Change password")
        with st.form("change_password_form", clear_on_submit=True):
            current = st.text_input("Current password", type="password")
            new = st.text_input("New password", type="password", help="At least 8 characters with a letter and a number.")
            confirm = st.text_input("Confirm new password", type="password")
            submitted = st.form_submit_button("Update password", type="primary")
        if submitted:
            try:
                if new != confirm:
                    raise ValueError("Passwords do not match.")
                user_service.change_own_password(user["id"], current, new)
                st.success("Password updated.")
            except ValueError as error:
                st.error(str(error))

        st.subheader("Recovery code")
        st.caption("A one-time code that lets you reset your password without e-mail or an administrator. "
                   "Creating a new code cancels the old one. " + XLSX_NOTE)
        shown = st.session_state.pop("my_new_code", None)
        if shown:
            st.success("Your new recovery code (shown only once):")
            html(f'<div class="code-box">{widgets._e(shown)}</div>')
        with st.form("recovery_form", clear_on_submit=True):
            password = st.text_input("Confirm with your password", type="password")
            if st.form_submit_button("🧾 Create new recovery code"):
                if user_service.check_password(user["id"], password):
                    st.session_state["my_new_code"] = user_service.create_recovery_code(user["id"], actor=user["username"])
                    st.rerun()
                else:
                    st.error("Password is incorrect.")

    with activity:
        log = svc.audit_df(1000)
        mine = log[(log["entity"] == "users") & ((log["actor"] == user["username"]) | (log["entity_id"] == user["id"]))]
        if mine.empty:
            st.info("No activity recorded yet.")
        else:
            show_table(mine.head(25).rename(columns={"event_time": "Time", "action": "Event", "details": "Details"})
                       [["Time", "Event", "Details"]])
