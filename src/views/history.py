from datetime import date, timedelta

import streamlit as st

from .. import inventory_service as svc
from ..config import STOCK_IN, STOCK_OUT
from ..ui import download_row, page_header, show_table


def render() -> None:
    page_header("📜 Transaction History", "Filter, review and export stock movements (overall or part-wise).")

    everything = svc.transactions_df()
    if everything.empty:
        st.info("No transaction records available yet.")
        return

    first = everything["timestamp"].min().date()
    c1, c2, c3 = st.columns([2, 2, 1])
    period = c1.date_input("Date range", value=(max(first, date.today() - timedelta(days=89)), date.today()))
    parts = svc.list_parts()
    labels = {0: "All parts"} | {int(r.id): f"{r.part_name} | {r.part_number}" for r in parts.itertuples()}
    part_id = c2.selectbox("Spare part", list(labels), format_func=labels.get)
    kind = c3.selectbox("Type", ["All", STOCK_IN, STOCK_OUT])

    if isinstance(period, (tuple, list)):
        start, end = (period[0], period[1]) if len(period) == 2 else (period[0], period[0])
    else:
        start = end = period

    df = svc.transactions_df(start=start, end=end, part_id=part_id or None, transaction_type=kind)
    if df.empty:
        st.info("No transactions match the selected filters.")
        return

    total_in = int(df.loc[df["transaction_type"] == STOCK_IN, "quantity"].sum())
    total_out = int(df.loc[df["transaction_type"] == STOCK_OUT, "quantity"].sum())
    m = st.columns(4)
    m[0].metric("Total Stock In", total_in)
    m[1].metric("Total Stock Out", total_out)
    m[2].metric("Net Movement", total_in - total_out)
    m[3].metric("Transactions", len(df))

    if part_id:
        part = svc.get_part(part_id)
        st.caption(f"Current stock of selected part: **{part['quantity']} {part['unit'] or 'pcs'}**")

    st.subheader("Stock In vs Stock Out")
    freq = "D" if (end - start).days <= 92 else "M"
    summary = svc.movement_summary(df, freq)
    st.bar_chart(summary)

    st.subheader("Records")
    pretty = svc.pretty_transactions(df)
    show_table(pretty)
    st.caption(f"Total records displayed: {len(df)} | Times shown in local time")
    download_row(pretty, "transactions", "hist", "Transactions")
