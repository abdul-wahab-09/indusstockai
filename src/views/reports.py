from datetime import datetime

import streamlit as st

from .. import auth, mailer, user_service
from .. import inventory_service as svc
from ..config import APP_NAME, APP_VERSION, DB_PATH, GEMINI_MODEL, SITE_NAME, get_secret
from ..database import backup_bytes
from ..ui import page_header, show_table
from .gemini_panel import render_panel


def render() -> None:
    if not auth.require_admin():
        return
    page_header("🧾 Reports, Backup & System", "Management reports, database backup and audit trail.")
    reports, backup, audit, system = st.tabs(["Management Report", "Backup", "Audit Log", "System"])
    stamp = datetime.now().strftime("%Y%m%d_%H%M")

    with reports:
        st.write("One Excel workbook with the inventory, reorder list, transactions, consumption and stock-cover forecast.")
        if st.button("📊 Build report workbook", type="primary"):
            parts = svc.list_parts()
            sheets = {
                "Inventory": svc.pretty_parts(parts),
                "Reorder List": svc.pretty_parts(svc.low_stock_parts()),
                "Transactions": svc.pretty_transactions(svc.transactions_df()),
                "Consumption": svc.consumption()[["part_name", "part_number", "category", "consumed", "issues"]],
                "Stock Cover": svc.stock_cover(90)[["part_name", "part_number", "quantity", "consumed",
                                                     "daily_usage", "days_of_cover", "cover_status"]],
            }
            st.session_state["report_bytes"] = svc.to_excel_bytes(sheets)
        if st.session_state.get("report_bytes"):
            st.download_button(
                "⬇️ Download report (.xlsx)", st.session_state["report_bytes"], f"spare_parts_report_{stamp}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    with backup:
        st.write("Download a complete copy of the database. Keep backups on another drive or cloud storage, "
                 "for example weekly.")
        st.download_button("💾 Download database backup", backup_bytes(), f"inventory_backup_{stamp}.db",
                           "application/octet-stream")
        st.caption("To restore: stop the app, replace `data/inventory.db` with the backup file, and start the app again.")

    with audit:
        log = svc.audit_df()
        if log.empty:
            st.info("No audit events yet.")
        else:
            show_table(log.rename(columns={"event_time": "Time", "actor": "User", "action": "Action",
                                            "entity": "Entity", "entity_id": "ID", "details": "Details"})
                       .drop(columns="id"))

    with system:
        k = svc.kpis()
        st.markdown(
            f"""
- **Application:** {APP_NAME} v{APP_VERSION}
- **Site:** {SITE_NAME}
- **Database:** `{DB_PATH}`
- **Spare part records:** {k['total_parts']}  |  **Units in stock:** {k['total_units']}
- **Gemini AI:** {'configured' if get_secret('GEMINI_API_KEY') else 'not configured'} (model `{get_secret('GEMINI_MODEL', GEMINI_MODEL)}`)
- **User accounts:** {user_service.count_users()} (sign-in required)
- **E-mail (password reset codes):** {'configured' if mailer.is_configured() else 'not configured (recovery codes and admin requests still work)'}
"""
        )
        render_panel(key_prefix="system")
        with st.expander("📧 E-mail (SMTP) test"):
            if not mailer.is_configured():
                st.info("Add SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD and SMTP_FROM to `.streamlit/secrets.toml` "
                        "(see `secrets.toml.example`), restart the app, then test here.")
            else:
                address = st.text_input("Send a test message to", key="smtp_test_to")
                if st.button("Send test e-mail", key="smtp_test_btn"):
                    try:
                        mailer.send_email(address.strip(), "IndusStock AI test message", "E-mail is working.")
                        st.success("Test e-mail sent.")
                    except mailer.MailError as error:
                        st.error(f"Could not send: {error}")
