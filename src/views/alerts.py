import streamlit as st

from .. import inventory_service as svc
from .. import widgets
from ..ui import download_row, html, page_header, show_table, with_status_icons


def render() -> None:
    page_header("🚨 Low Stock Alerts", "Parts at or below their minimum level, with suggested reorder quantities.")
    low = svc.low_stock_parts()
    if low.empty:
        html(widgets.empty_state("✅", "All stocked up", "Every spare part is above its minimum stock level."))
        return

    out_count = int((low["status"] == svc.STATUS_OUT).sum())
    html(widgets.kpi_grid([
        widgets.kpi_card("⚠️", "Parts needing attention", len(low), "at or below minimum", "amber"),
        widgets.kpi_card("⛔", "Out of stock", out_count, "zero units left", "red"),
        widgets.kpi_card("🛒", "Units to reorder", int(low["suggested_reorder"].sum()), "suggested total", "blue"),
    ]))

    html(widgets.section_title("Priority list", "most urgent first"))
    html(widgets.attention_list(low, limit=8))

    view = low[["status", "part_name", "category", "part_number", "quantity", "unit", "min_stock",
                "suggested_reorder", "location", "manufacturer"]].copy()
    view.columns = ["Status", "Part Name", "Category", "Part Number", "Quantity", "Unit", "Minimum Stock",
                    "Suggested Reorder", "Location", "Manufacturer"]
    html(widgets.section_title("Full reorder list"))
    show_table(with_status_icons(view, "Status"))
    st.caption("Suggested reorder restores stock to twice the minimum level (at least 1 unit). "
               "Use the export below as the basis for a purchase requisition.")
    download_row(view, "reorder_list", "alerts", "Reorder List")
