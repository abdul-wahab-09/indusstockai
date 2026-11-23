import streamlit as st

from .. import auth, widgets
from .. import inventory_service as svc
from ..config import CATEGORIES, UNITS
from ..ui import current_user, download_row, flash, html, page_header, show_flash, show_table, with_status_icons


def _details(df) -> None:
    """Drill-down card for one part: facts, stock meter and its movement history."""
    with st.expander("🔍 Part details and history"):
        labels = {int(r.id): f"{r.part_name} | {r.part_number}" for r in df.itertuples()}
        part_id = st.selectbox("Select part", list(labels), format_func=labels.get, key="detail_part")
        part = svc.get_part(part_id)
        if not part:
            return
        quantity, minimum = int(part["quantity"] or 0), int(part["min_stock"] or 0)
        status = svc.stock_status(quantity, minimum)
        left, right = st.columns([1, 1], gap="large")
        with left:
            html(f"<div class='att-name' style='font-size:1.15rem'>{widgets._e(part['part_name'])}</div>"
                 f"<div class='att-meta'>{widgets._e(part['category'])} · {widgets._e(part['part_number'] or 'no part number')}</div>"
                 f"{widgets.pill(status, widgets.STATUS_TONE[status])}"
                 f"<div style='margin:.7rem 0 .3rem'>{widgets._e(quantity)} {widgets._e(part['unit'] or 'pcs')} in stock "
                 f"· minimum {widgets._e(minimum)}</div>{widgets.stock_meter(quantity, minimum)}"
                 f"<div class='att-meta' style='margin-top:.8rem'>📍 {widgets._e(part['location'] or '-')} &nbsp; "
                 f"🏭 {widgets._e(part['manufacturer'] or '-')}</div>"
                 + (f"<div class='att-meta'>📝 {widgets._e(part['remarks'])}</div>" if part["remarks"] else ""))
        history = svc.transactions_df(part_id=part_id)
        with right:
            html(widgets.section_title("Recent movements"))
            html(widgets.timeline(history, limit=6))
        if not history.empty:
            st.bar_chart(svc.movement_summary(history, "M"))


def render() -> None:
    page_header("📦 Spare Parts Inventory", "Search, filter, edit, archive and export spare parts.")
    show_flash()
    admin = auth.is_admin()
    tab_names = ["Browse & Export"] + (["Edit / Archive", "Archived Parts"] if admin else [])
    tabs = st.tabs(tab_names)
    browse = tabs[0]
    manage = tabs[1] if admin else None
    archived = tabs[2] if admin else None
    if not admin:
        st.caption("Editing and archiving parts is available to administrators.")

    with browse:
        c1, c2, c3 = st.columns([2, 1, 1])
        search = c1.text_input("🔎 Search", placeholder="name, part number, category, location, brand...")
        category = c2.selectbox("Category", ["All"] + CATEGORIES)
        status = c3.selectbox("Status", ["All", svc.STATUS_OK, svc.STATUS_LOW, svc.STATUS_OUT])
        df = svc.list_parts(search=search, category=category, status=status)
        if df.empty:
            st.info("No spare parts match the current filters.")
        else:
            st.caption(f"{len(df)} record(s) | {int(df['quantity'].sum())} units in stock")
            pretty = svc.pretty_parts(df)
            show_table(with_status_icons(pretty, "Status"))
            download_row(pretty, "inventory", "inv", "Inventory")
            _details(df)

    if admin:
        with manage:
            df = svc.list_parts()
            if df.empty:
                st.info("No spare parts to manage yet.")
            else:
                labels = {int(r.id): f"{r.part_name} | {r.part_number} | {r.location}" for r in df.itertuples()}
                part_id = st.selectbox("Select spare part", list(labels), format_func=labels.get, key="manage_part")
                part = svc.get_part(part_id)
                st.caption("Stock quantity changes are made on the **Stock In / Stock Out** page so that every change is recorded.")
                with st.form(f"edit_form_{part_id}"):
                    c1, c2 = st.columns(2)
                    name = c1.text_input("Part Name", part["part_name"] or "")
                    cat_options = CATEGORIES if part["category"] in CATEGORIES else [part["category"]] + CATEGORIES
                    category = c2.selectbox("Category", cat_options, index=cat_options.index(part["category"]))
                    number = c1.text_input("Part Number", part["part_number"] or "")
                    maker = c2.text_input("Manufacturer / Brand", part["manufacturer"] or "")
                    min_stock = c1.number_input("Minimum Stock Level", min_value=0, step=1, value=int(part["min_stock"] or 0))
                    unit_options = UNITS if (part["unit"] or "pcs") in UNITS else [part["unit"]] + UNITS
                    unit = c2.selectbox("Unit", unit_options, index=unit_options.index(part["unit"] or "pcs"))
                    location = c1.text_input("Location / Panel", part["location"] or "")
                    remarks = st.text_area("Remarks", part["remarks"] or "", height=80)
                    if st.form_submit_button("💾 Save Changes", type="primary"):
                        try:
                            svc.update_part(part_id, part_name=name, category=category, part_number=number,
                                            manufacturer=maker, min_stock=int(min_stock), unit=unit,
                                            location=location, remarks=remarks, actor=current_user())
                            flash("Changes saved.")
                            st.rerun()
                        except svc.InventoryError as error:
                            st.error(str(error))

                with st.expander("🗄️ Archive this spare part"):
                    st.write("Archived parts disappear from the inventory but their transaction history is kept. "
                             "You can restore them at any time.")
                    confirm = st.checkbox("I confirm I want to archive this part", key=f"archive_confirm_{part_id}")
                    if st.button("Archive part", disabled=not confirm, key=f"archive_btn_{part_id}"):
                        svc.set_part_active(part_id, False, actor=current_user())
                        flash("Spare part archived.", "warning")
                        st.rerun()

    if admin:
        with archived:
            old = svc.list_parts(archived=True)
            if old.empty:
                st.info("No archived parts.")
            else:
                show_table(svc.pretty_parts(old))
                labels = {int(r.id): f"{r.part_name} | {r.part_number}" for r in old.itertuples()}
                restore_id = st.selectbox("Restore spare part", list(labels), format_func=labels.get)
                if st.button("♻️ Restore"):
                    svc.set_part_active(restore_id, True, actor=current_user())
                    flash("Spare part restored.")
                    st.rerun()
