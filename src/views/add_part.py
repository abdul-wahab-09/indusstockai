import streamlit as st

from .. import inventory_service as svc
from .. import widgets
from ..config import CATEGORIES, UNITS
from ..ui import current_user, flash, html, page_header, show_flash, show_table

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _single() -> None:
    with st.form("add_part_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        part_name = c1.text_input("Part Name *", placeholder="e.g. Contactor 25A 24VDC coil")
        category = c2.selectbox("Category *", CATEGORIES)
        part_number = c1.text_input("Part Number", placeholder="e.g. LC1D25BD")
        manufacturer = c2.text_input("Manufacturer / Brand", placeholder="e.g. Schneider, Siemens, ABB")
        quantity = c1.number_input("Opening Quantity", min_value=0, step=1)
        unit = c2.selectbox("Unit", UNITS)
        min_stock = c1.number_input("Minimum Stock Level", min_value=0, step=1,
                                    help="An alert is raised when stock falls to this level or below.")
        location = c2.text_input("Location / Panel", placeholder="e.g. MCC Panel 1, Store Rack A2")
        remarks = st.text_area("Remarks (optional)", height=80)
        submitted = st.form_submit_button("💾 Save Spare Part", type="primary")

    if submitted:
        try:
            part_id = svc.add_part(
                part_name=part_name, category=category, part_number=part_number, quantity=int(quantity),
                min_stock=int(min_stock), location=location, manufacturer=manufacturer, unit=unit,
                remarks=remarks, actor=current_user(),
            )
            st.success(f"Spare part saved successfully (ID {part_id}).")
        except svc.InventoryError as error:
            st.error(str(error))


def _bulk() -> None:
    st.write("Add many spare parts at once from an Excel or CSV file. Rows are checked first; "
             "nothing is saved until you confirm.")
    st.download_button("📄 Download Excel template", svc.import_template_bytes(), "indusstock_import_template.xlsx",
                       XLSX, key="bulk_template")
    upload_key = f"bulk_upload_{st.session_state.get('bulk_upload_n', 0)}"
    upload = st.file_uploader("Upload .xlsx or .csv", type=["xlsx", "csv"], key=upload_key)
    if upload is None:
        return
    try:
        preview = svc.validate_import(svc.read_upload(upload.getvalue(), upload.name))
    except svc.InventoryError as error:
        st.error(str(error))
        return
    if preview.empty:
        st.warning("The file has no data rows.")
        return

    ok = int((preview["status"] == "ok").sum())
    bad = len(preview) - ok
    html(widgets.kpi_grid([
        widgets.kpi_card("📄", "Rows read", len(preview), upload.name, "blue"),
        widgets.kpi_card("✅", "Ready to import", ok, "valid rows", "green"),
        widgets.kpi_card("⚠️", "Will be skipped", bad, "see the Message column", "amber" if bad else "gray"),
    ]))
    view = preview.copy()
    view["status"] = view["status"].map({"ok": "✅ OK", "error": "⚠️ Skip"})
    show_table(view.rename(columns={"row": "File row", "part_name": "Part Name", "category": "Category",
                                    "part_number": "Part Number", "quantity": "Quantity", "min_stock": "Min Stock",
                                    "location": "Location", "manufacturer": "Manufacturer", "unit": "Unit",
                                    "remarks": "Remarks", "status": "Status", "message": "Message"}))
    if ok and st.button(f"⬆️ Import {ok} spare part(s)", type="primary"):
        added, skipped = svc.import_parts(preview, actor=current_user())
        st.session_state["bulk_upload_n"] = st.session_state.get("bulk_upload_n", 0) + 1  # clears the uploader
        flash(f"Imported {added} spare part(s)" + (f"; {skipped} skipped." if skipped else "."))
        st.rerun()


def render() -> None:
    page_header("➕ Add Spare Parts", "Register a new part, or import many from Excel / CSV.")
    show_flash()
    single, bulk = st.tabs(["Single part", "Bulk import (Excel / CSV)"])
    with single:
        _single()
    with bulk:
        _bulk()
