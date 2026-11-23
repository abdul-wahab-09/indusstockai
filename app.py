"""IndusStock AI - Electrical and Electronic Spare Parts Intelligence (Streamlit entry point).

Run with:  streamlit run app.py
"""
import streamlit as st

from src.config import APP_FULL_NAME, APP_ICON, APP_NAME, APP_VERSION, SITE_NAME

st.set_page_config(page_title=f"{APP_NAME} | {APP_FULL_NAME}", page_icon=APP_ICON, layout="wide")

from src import auth, ui, user_service, widgets  # noqa: E402  (must come after set_page_config)
from src.database import init_db  # noqa: E402
from src.views import (  # noqa: E402
    add_part, alerts, analytics, assistant, dashboard, history, inventory, my_account, reports,
    stock_movement, user_management,
)

ADMIN = ("admin",)
ALL = ("admin", "user")

# key -> (page function, roles allowed to open it)
PAGES = {
    "📊 Dashboard": (dashboard.render, ALL),
    "➕ Add Spare Parts": (add_part.render, ALL),
    "📦 View Inventory": (inventory.render, ALL),
    "🔄 Stock In / Stock Out": (stock_movement.render, ALL),
    "🚨 Low Stock Alerts": (alerts.render, ALL),
    "📜 Transaction History": (history.render, ALL),
    "📈 Stock Analytics": (analytics.render, ALL),
    "🤖 AI Assistant": (assistant.render, ALL),
    "🧾 Reports & Backup": (reports.render, ADMIN),
    "👥 User Management": (user_management.render, ADMIN),
    "👤 My Account": (my_account.render, ALL),
}


@st.cache_resource
def bootstrap() -> bool:
    init_db()
    return True


def _security_tip(user: dict) -> None:
    """Nudge people who could not recover a forgotten password (no e-mail and no recovery code)."""
    if st.session_state.get("tip_dismissed"):
        return
    details = user_service.get_user(user["id"])
    if details and not details["email"] and not details["has_recovery"]:
        left, right = st.columns([6, 1])
        left.warning("🔐 **Protect your account:** add an e-mail or create a recovery code in **My Account** "
                     "so you can reset your password if you ever forget it.")
        if right.button("Dismiss", key="tip_dismiss"):
            st.session_state["tip_dismissed"] = True
            st.rerun()


def main() -> None:
    ui.inject_css()
    bootstrap()
    user = auth.require_login()  # shows setup / sign-in / recovery screens and stops until signed in

    pending = user_service.pending_request_count() if user["role"] == "admin" else 0
    allowed = [key for key, (_, roles) in PAGES.items() if user["role"] in roles]

    def menu_label(key: str) -> str:  # badge text may change, but the option value (key) stays stable
        return f"{key}  ·  {pending}" if key == "👥 User Management" and pending else key

    with st.sidebar:
        ui.html(widgets.brand_lockup(APP_NAME, APP_FULL_NAME))
        ui.html(widgets.user_chip(auth.display_name(user), "Administrator" if user["role"] == "admin" else "User"))
        ui.html('<div class="nav-label">Menu</div>')
        choice = st.radio("Navigation", allowed, format_func=menu_label, label_visibility="collapsed")
        st.markdown("---")
        if st.button("🚪 Sign out"):
            auth.logout("manual")
        ui.html(f'<div class="side-foot">{widgets._e(SITE_NAME)}<br>Version {widgets._e(APP_VERSION)}</div>')

    _security_tip(user)
    PAGES[choice][0]()


main()
