import streamlit as st

from .. import inventory_service as svc
from ..config import STOCK_IN, STOCK_OUT
from ..ui import current_user, flash, page_header, show_flash


def render() -> None:
    page_header("🔄 Stock In / Stock Out", "Record receipts and issues. Every movement is stored with date, time and reference.")
    show_flash()

    parts = svc.list_parts()
    if parts.empty:
        st.warning("Please add a spare part first.")
        return

    labels = {int(r.id): f"{r.part_name} | {r.part_number} | Stock: {r.quantity} {r.unit}" for r in parts.itertuples()}
    part_id = st.selectbox("Select spare part", list(labels), format_func=labels.get)
    part = svc.get_part(part_id)
    current = int(part["quantity"] or 0)
    minimum = int(part["min_stock"] or 0)

    c1, c2, c3 = st.columns(3)
    c1.metric("Current stock", f"{current} {part['unit'] or 'pcs'}")
    c2.metric("Minimum stock", minimum)
    c3.metric("Location", part["location"] or "-")

    with st.form("stock_form", clear_on_submit=True):
        kind = st.radio("Transaction type", [STOCK_IN, STOCK_OUT], horizontal=True)
        amount = st.number_input("Quantity", min_value=1, step=1)
        reference = st.text_input("Reference", placeholder="Work order, breakdown no., PO / challan no., machine name")
        remarks = st.text_area("Remarks (optional)", height=70)
        submitted = st.form_submit_button("✅ Update Stock", type="primary")

    if submitted:
        try:
            new_stock = svc.record_transaction(
                part_id, kind, int(amount), reference=reference, remarks=remarks, performed_by=current_user()
            )
            message = f"{kind} recorded. New stock: {new_stock} {part['unit'] or 'pcs'}."
            if new_stock <= minimum:
                flash(message + " ⚠️ Stock is now at or below the minimum level.", "warning")
            else:
                flash(message)
            st.rerun()
        except svc.InventoryError as error:
            st.error(str(error))
