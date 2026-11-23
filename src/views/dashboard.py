from datetime import date, timedelta

import streamlit as st

from .. import auth, widgets
from .. import inventory_service as svc
from ..config import SITE_NAME
from ..ui import html, page_header


def render() -> None:
    page_header("📊 Dashboard", "Live overview of spare parts stock, risks and recent activity.")
    user = auth.current_user()
    first_name = (auth.display_name(user).split() or ["there"])[0]
    now = svc.local_now()
    daypart = "Good morning" if now.hour < 12 else ("Good afternoon" if now.hour < 17 else "Good evening")
    k = svc.kpis()

    if k["out_of_stock"]:
        chips = [("🔴", f"{k['out_of_stock']} out of stock")]
    elif k["low_stock"]:
        chips = [("🟠", f"{k['low_stock']} running low")]
    else:
        chips = [("🟢", "All stock healthy")]
    chips.append(("🔄", f"{k['movements_30d']} movements in 30 days"))
    html(widgets.greeting_banner(f"{daypart}, {first_name} 👋", f"{now:%A, %d %B %Y} · {SITE_NAME}", chips))

    if k["total_parts"] == 0:
        html(widgets.empty_state("📦", "No spare parts yet", "Open Add Spare Part to add one, or import many from Excel."))
        return

    html(widgets.kpi_grid([
        widgets.kpi_card("📦", "Spare part records", k["total_parts"], f"{k['categories']} categories", "blue"),
        widgets.kpi_card("🔢", "Units in stock", k["total_units"], "across all parts", "cyan"),
        widgets.kpi_card("⚠️", "Low stock", k["low_stock"], "at or below minimum", "amber"),
        widgets.kpi_card("⛔", "Out of stock", k["out_of_stock"], "reorder now" if k["out_of_stock"] else "none", "red"),
        widgets.kpi_card("🔄", "Issued (30 days)", k["issued_30d"], "units consumed", "violet"),
    ]))

    parts = svc.list_parts()
    counts = parts["status"].value_counts()
    left, right = st.columns(2, gap="large")

    with left:
        html(widgets.section_title("Stock health", "share of parts by status"))
        html(widgets.donut(
            [("In stock", int(counts.get(svc.STATUS_OK, 0)), "green"),
             ("Low stock", int(counts.get(svc.STATUS_LOW, 0)), "amber"),
             ("Out of stock", int(counts.get(svc.STATUS_OUT, 0)), "red")],
            len(parts), "parts"))

        html(widgets.section_title("Parts by category", "units in stock"))
        categories = svc.category_summary().sort_values("units", ascending=False).head(7)
        html(widgets.bar_list([(r.category, r.units, f"{r.parts} part(s)") for r in categories.itertuples()], "blue"))

        html(widgets.section_title("Most consumed", "last 90 days"))
        top = svc.consumption(days=90, top_n=6)
        html(widgets.bar_list([(r.part_name, r.consumed, r.part_number) for r in top.itertuples()], "cyan", " units"))

    with right:
        low = svc.low_stock_parts()
        html(widgets.section_title("Needs attention", f"{len(low)} item(s)"))
        html(widgets.attention_list(low))
        html(widgets.section_title("Recent activity"))
        html(widgets.timeline(svc.transactions_df(limit=8)))

    recent = svc.transactions_df(start=date.today() - timedelta(days=29))
    if not recent.empty:
        html(widgets.section_title("Stock movement", "last 30 days: units in vs out"))
        st.bar_chart(svc.movement_summary(recent, "D"))
