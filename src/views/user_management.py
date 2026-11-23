import streamlit as st

from .. import auth, security, user_service, widgets
from .. import inventory_service as svc
from ..ui import current_user, flash, html, page_header, show_flash, show_table

ROLE_LABELS = {"admin": "Administrator", "user": "User"}
ACCOUNT_EVENTS = ["LOGIN", "LOGIN_FAILED", "LOGOUT", "ACCOUNT_LOCKED", "PASSWORD_RESET", "PASSWORD_CHANGED",
                  "PASSWORD_RESET_RECOVERY", "PASSWORD_RESET_EMAIL", "RESET_REQUESTED", "USER_CREATED",
                  "USER_UPDATED", "RECOVERY_CODE_CREATED"]


def _when(moment) -> str:
    return moment.strftime("%d-%b-%Y %I:%M %p") if hasattr(moment, "strftime") and moment == moment else "-"


def _temp_password_notice() -> None:
    notice = st.session_state.pop("temp_pw_notice", None)  # shown exactly once
    if notice:
        username, password = notice
        st.success(f"Temporary password for **{username}** (shown only once). The user must change it at sign-in:")
        st.code(password, language=None)


def render() -> None:
    if not auth.require_admin():
        return
    page_header("👥 User Management", "Create accounts, assign roles, handle password-reset requests and review sign-in activity.")
    show_flash()
    _temp_password_notice()

    users = user_service.list_users()
    pending = user_service.pending_request_count()
    active_admins = int(((users["role"] == "admin") & (users["is_active"] == 1)).sum())
    html(widgets.kpi_grid([
        widgets.kpi_card("👥", "Accounts", len(users), "total", "blue"),
        widgets.kpi_card("🛡️", "Administrators", active_admins, "active", "violet"),
        widgets.kpi_card("🟢", "Active users", int((users["is_active"] == 1).sum()), "can sign in", "green"),
        widgets.kpi_card("🔒", "Locked", int(users["locked"].sum()), "too many attempts", "amber" if users["locked"].any() else "gray"),
        widgets.kpi_card("🔑", "Reset requests", pending, "waiting for you", "red" if pending else "gray"),
    ]))

    list_tab, add_tab, edit_tab, request_tab, activity_tab = st.tabs(
        ["All Users", "Add User", "Edit / Reset Password", "Reset Requests", "Sign-in Activity"])

    with list_tab:
        view = users.copy()
        view["status"] = [("🔒 Locked" if locked else ("🟢 Active" if active else "⚪ Deactivated"))
                          for locked, active in zip(view["locked"], view["is_active"])]
        view["role"] = view["role"].map(ROLE_LABELS)
        view["has_recovery"] = view["has_recovery"].map({1: "Yes", 0: "No"})
        view["must_change_password"] = view["must_change_password"].map({1: "Yes", 0: "No"})
        view = view[["username", "full_name", "email", "role", "status", "last_login", "has_recovery",
                     "must_change_password", "created_at"]]
        view.columns = ["Username", "Full Name", "E-mail", "Role", "Status", "Last Login", "Recovery Code",
                        "Must Change Password", "Created"]
        show_table(view)

    with add_tab:
        generate = st.checkbox("Generate a secure temporary password for me", value=True, key="add_generate")
        with st.form("add_user_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            username = c1.text_input("Username *", placeholder="e.g. ali.khan")
            full_name = c2.text_input("Full name")
            email = c1.text_input("E-mail (optional)", placeholder="enables e-mail password reset")
            role = c2.selectbox("Role", list(ROLE_LABELS), format_func=ROLE_LABELS.get)
            password = st.text_input("Temporary password", type="password",
                                     help="Only used when 'Generate' is unticked. The user must change it at first sign-in.")
            submitted = st.form_submit_button("Create user", type="primary")
        if submitted:
            try:
                temp = security.generate_password() if generate else password
                user_service.create_user(username, temp, full_name=full_name, role=role, must_change=True,
                                         email=email, actor=current_user())
                st.success(f"User '{username.strip().lower()}' created. Give them this temporary password (shown only once):")
                st.code(temp, language=None)
            except ValueError as error:
                st.error(str(error))

    with edit_tab:
        labels = {int(r.id): f"{r.username} ({r.full_name or 'no name'})" for r in users.itertuples()}
        user_id = st.selectbox("Select user", list(labels), format_func=labels.get)
        target = user_service.get_user(user_id)
        me = auth.current_user()

        with st.form(f"edit_user_{user_id}"):
            c1, c2 = st.columns(2)
            full_name = c1.text_input("Full name", target["full_name"] or "")
            email = c2.text_input("E-mail", target["email"] or "")
            role = c1.selectbox("Role", list(ROLE_LABELS), index=list(ROLE_LABELS).index(target["role"]),
                                format_func=ROLE_LABELS.get)
            active = c2.checkbox("Account active", value=bool(target["is_active"]))
            if st.form_submit_button("💾 Save changes", type="primary"):
                try:
                    user_service.update_user(user_id, full_name=full_name, role=role, is_active=active,
                                             actor=current_user(), actor_id=me["id"])
                    user_service.set_email(user_id, email, actor=current_user())
                    flash("User updated.")
                    st.rerun()
                except ValueError as error:
                    st.error(str(error))

        st.subheader("Reset password")
        generate = st.checkbox("Generate a secure temporary password", value=True, key=f"reset_generate_{user_id}")
        with st.form(f"reset_user_{user_id}", clear_on_submit=True):
            password = st.text_input("New temporary password", type="password",
                                     help="Only used when 'Generate' is unticked.")
            if st.form_submit_button("🔑 Reset password"):
                try:
                    temp = security.generate_password() if generate else password
                    user_service.reset_password(user_id, temp, must_change=True, actor=current_user())
                    st.session_state["temp_pw_notice"] = (target["username"], temp)
                    st.rerun()
                except ValueError as error:
                    st.error(str(error))

        c1, c2 = st.columns(2)
        if c1.button("🔓 Unlock account", key=f"unlock_{user_id}"):
            user_service.unlock_user(user_id, actor=current_user())
            flash("Account unlocked.")
            st.rerun()
        if c2.button("🧾 Issue a new recovery code", key=f"recovery_{user_id}",
                     help="Replaces any existing code. Hand it to the user in person."):
            code = user_service.create_recovery_code(user_id, actor=current_user())
            st.success(f"New recovery code for **{target['username']}** (shown only once):")
            st.code(code, language=None)

    with request_tab:
        requests = user_service.list_reset_requests("pending")
        if requests.empty:
            html(widgets.empty_state("📭", "No pending requests", "People who use 'Ask administrator' on the sign-in page appear here."))
        for row in requests.itertuples():
            matched = row.matched_username if isinstance(row.matched_username, str) else None
            html(f"<div class='att-row'><div class='att-main'><div class='att-name'>{widgets._e(row.identifier)}</div>"
                 f"<div class='att-meta'>{widgets._e(_when(row.created_at))} · "
                 + (f"matches account <b>{widgets._e(matched)}</b>" if matched else "no matching account found")
                 + f"</div><div class='att-meta'>{widgets._e(row.note) or 'No note'}</div></div></div>")
            c1, c2, _ = st.columns([2, 1, 2])
            if matched and c1.button("🔑 Create temporary password and resolve", key=f"req_ok_{row.id}"):
                temp = security.generate_password()
                user_service.reset_password(int(row.user_id), temp, must_change=True, actor=current_user())
                user_service.resolve_reset_request(int(row.id), "resolved", actor=current_user())
                st.session_state["temp_pw_notice"] = (matched, temp)
                st.rerun()
            if c2.button("Dismiss", key=f"req_no_{row.id}"):
                user_service.resolve_reset_request(int(row.id), "dismissed", actor=current_user())
                st.rerun()

    with activity_tab:
        log = svc.audit_df(1000)
        log = log[log["entity"] == "users"]
        choice = st.multiselect("Event types", ACCOUNT_EVENTS, default=["LOGIN", "LOGIN_FAILED", "LOGOUT", "ACCOUNT_LOCKED"])
        log = log[log["action"].isin(choice)] if choice else log
        if log.empty:
            st.info("No matching events.")
        else:
            show_table(log.rename(columns={"event_time": "Time", "actor": "User", "action": "Event",
                                           "details": "Details"})[["Time", "User", "Event", "Details"]])
