from datetime import date, timedelta

import streamlit as st

from .. import inventory_service as svc
from ..ui import download_row, page_header, show_table

PERIODS = {"Last 30 days": 30, "Last 90 days": 90, "Last 180 days": 180, "Last 365 days": 365}


def render() -> None:
    page_header("📈 Stock Analytics", "Consumption trends, fast movers and stock-cover forecasting.")
    if svc.transactions_df(limit=1).empty:
        st.info("No transaction data available yet. Analytics appear after the first Stock In / Stock Out.")
        return

    label = st.selectbox("Analysis period", list(PERIODS), index=1)
    days = PERIODS[label]
    df = svc.transactions_df(start=date.today() - timedelta(days=days - 1))

    st.subheader("Stock movement trend")
    if df.empty:
        st.caption("No movements in this period.")
    else:
        st.line_chart(svc.movement_summary(df, "D" if days <= 90 else "M"))

    left, right = st.columns(2)
    with left:
        st.subheader("Most consumed parts")
        top = svc.consumption(days=days, top_n=10)
        if top.empty:
            st.caption("No stock-out records in this period.")
        else:
            st.bar_chart(top.set_index("label")["consumed"].rename("Units issued"))
    with right:
        st.subheader("Stock by category")
        cats = svc.category_summary()
        if not cats.empty:
            st.bar_chart(cats.set_index("category")["units"].rename("Units in stock"))

    st.subheader("Stock cover forecast")
    st.caption(f"Estimates how long current stock lasts at the average usage rate of the {label.lower()}.")
    cover = svc.stock_cover(days=days)
    view = cover[["part_name", "part_number", "category", "quantity", "consumed", "daily_usage",
                  "days_of_cover", "cover_status"]].copy()
    view.columns = ["Part Name", "Part Number", "Category", "In Stock", f"Used ({days}d)", "Avg Daily Usage",
                    "Days of Cover", "Cover Status"]
    risky = view[view["Cover Status"].str.startswith(("Critical", "Watch"))]
    if not risky.empty:
        st.warning(f"{len(risky)} part(s) may run out soon at the current usage rate.")
    show_table(view)
    download_row(view, "stock_cover", "cover", "Stock Cover")

    idle = cover[(cover["consumed"] == 0) & (cover["quantity"] > 0)]
    with st.expander(f"💤 Slow / idle stock: {len(idle)} part(s) with no issues in the period"):
        if idle.empty:
            st.caption("Every part in stock was used during this period.")
        else:
            show_table(svc.pretty_parts(idle)[["Part Name", "Part Number", "Category", "Quantity", "Location / Panel"]])
