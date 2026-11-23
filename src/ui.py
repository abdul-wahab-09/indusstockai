"""Shared Streamlit UI helpers (styling, tables, downloads, flash messages)."""
from __future__ import annotations

from datetime import datetime
from html import escape

import pandas as pd
import streamlit as st

from . import inventory_service as svc

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
.stApp {font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif;}
.block-container {padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1280px;}
header[data-testid="stHeader"] {background: transparent;}

/* ---------- brand ---------- */
.brand {display: flex; align-items: center; gap: .75rem;}
.logo-mark {
    width: 42px; height: 42px; border-radius: 12px; display: flex; align-items: center; justify-content: center;
    font-size: 1.35rem; background: linear-gradient(135deg, #22b8cf 0%, #4c6ef5 100%); color: #fff;
    box-shadow: 0 6px 18px rgba(76,110,245,.45); flex: 0 0 auto;
}
.brand-name {font-weight: 800; font-size: 1.25rem; letter-spacing: .2px; line-height: 1.1;}
.brand-sub {font-size: .72rem; opacity: .7; line-height: 1.25; margin-top: 2px;}
.brand-lg .logo-mark {width: 54px; height: 54px; font-size: 1.7rem; border-radius: 15px;}
.brand-lg .brand-name {font-size: 1.7rem; color: #fff;}
.brand-lg .brand-sub {font-size: .85rem; color: #cfe3ff; opacity: .9;}

/* ---------- page header ---------- */
.page-head {margin-bottom: 1.1rem; padding-bottom: .8rem; border-bottom: 1px solid rgba(127,127,127,.22); position: relative;}
.page-head::after {content: ""; position: absolute; left: 0; bottom: -1px; width: 90px; height: 3px;
    border-radius: 3px; background: linear-gradient(90deg, #22b8cf, #4c6ef5);}
.page-head h1 {font-size: 1.75rem; font-weight: 800; margin: 0; padding: 0; letter-spacing: .1px;}
.page-head p {margin: .25rem 0 0; opacity: .68; font-size: .95rem;}

/* ---------- sidebar ---------- */
section[data-testid="stSidebar"] {border-right: 1px solid rgba(127,127,127,.22);}
section[data-testid="stSidebar"] .block-container {padding-top: 1rem;}
.user-chip {display: flex; align-items: center; gap: .65rem; padding: .6rem .7rem; border-radius: 12px;
    background: rgba(127,127,127,.10); border: 1px solid rgba(127,127,127,.22); margin: .6rem 0 .4rem;}
.avatar {width: 36px; height: 36px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
    font-weight: 700; font-size: .85rem; color: #fff; background: linear-gradient(135deg, #7048e8, #22b8cf);}
.user-name {font-weight: 600; font-size: .9rem; line-height: 1.15;}
.user-role {font-size: .72rem; opacity: .65;}
.nav-label {font-size: .68rem; letter-spacing: .12em; text-transform: uppercase; opacity: .5; margin: .9rem 0 .2rem .3rem;}
section[data-testid="stSidebar"] div[role="radiogroup"] {gap: .15rem;}
section[data-testid="stSidebar"] label[data-baseweb="radio"] {
    padding: .5rem .7rem; border-radius: 10px; width: 100%; margin: 0; transition: background .15s;
}
section[data-testid="stSidebar"] label[data-baseweb="radio"]:hover {background: rgba(127,127,127,.14);}
section[data-testid="stSidebar"] label[data-baseweb="radio"] > div:first-child {display: none;}
section[data-testid="stSidebar"] label[data-baseweb="radio"]:has(input:checked) {
    background: linear-gradient(90deg, rgba(34,184,207,.22), rgba(76,110,245,.14));
    box-shadow: inset 3px 0 0 #22b8cf; font-weight: 600;
}
.side-foot {font-size: .72rem; opacity: .55; margin-top: .5rem;}

/* ---------- KPI cards ---------- */
.kpi-grid {display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: .85rem; margin: .4rem 0 1.1rem;}
.kpi {display: flex; gap: .85rem; align-items: center; padding: .95rem 1rem; border-radius: 16px;
    background: rgba(127,127,127,.09); border: 1px solid rgba(127,127,127,.24); position: relative; overflow: hidden;
    box-shadow: 0 4px 16px rgba(0,0,0,.12); transition: transform .15s, box-shadow .15s;}
.kpi:hover {transform: translateY(-2px); box-shadow: 0 10px 26px rgba(0,0,0,.22);}
.kpi::before {content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 4px; background: var(--accent);}
.kpi-icon {width: 46px; height: 46px; border-radius: 13px; display: flex; align-items: center; justify-content: center;
    font-size: 1.35rem; flex: 0 0 auto;}
.kpi-label {font-size: .75rem; text-transform: uppercase; letter-spacing: .07em; opacity: .65; font-weight: 600;}
.kpi-value {font-size: 1.85rem; font-weight: 800; line-height: 1.15;}
.kpi-sub {font-size: .74rem; opacity: .6; margin-top: 1px;}

/* ---------- cards / sections ---------- */
.section-title {font-size: 1.05rem; font-weight: 700; margin: 1.1rem 0 .55rem; display: flex; align-items: baseline; gap: .6rem;}
.section-hint {font-size: .75rem; font-weight: 500; opacity: .55;}
.pill {display: inline-block; padding: .12rem .6rem; border-radius: 999px; font-size: .7rem; font-weight: 700; border: 1px solid;
    letter-spacing: .02em; white-space: nowrap;}
.empty {text-align: center; padding: 1.6rem 1rem; border: 1px dashed rgba(127,127,127,.35); border-radius: 14px; opacity: .85;}
.empty-icon {font-size: 1.9rem;} .empty-title {font-weight: 700; margin-top: .3rem;} .empty-text {font-size: .85rem; opacity: .7;}

.donut-wrap {display: flex; align-items: center; gap: 1.4rem; flex-wrap: wrap; padding: .4rem 0;}
.donut {width: 168px; height: 168px; border-radius: 50%; display: flex; align-items: center; justify-content: center; flex: 0 0 auto;}
.donut-hole {width: 112px; height: 112px; border-radius: 50%; background: var(--background-color, #0e1117);
    display: flex; flex-direction: column; align-items: center; justify-content: center; box-shadow: inset 0 0 0 1px rgba(127,127,127,.2);}
.donut-value {font-size: 1.9rem; font-weight: 800; line-height: 1;} .donut-label {font-size: .72rem; opacity: .65; margin-top: 3px;}
.donut-legend {flex: 1 1 140px; min-width: 140px;}
.legend-row {display: flex; align-items: center; gap: .5rem; padding: .28rem 0; font-size: .9rem;}
.dot {width: 10px; height: 10px; border-radius: 50%; flex: 0 0 auto;} .legend-label {flex: 1;} .legend-value {font-weight: 700;}

.bar-row {margin-bottom: .7rem;} .bar-head {display: flex; justify-content: space-between; gap: .6rem; font-size: .86rem; margin-bottom: 3px;}
.bar-label {font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;}
.bar-sub {font-weight: 400; opacity: .55; margin-left: .45rem; font-size: .78rem;} .bar-value {font-weight: 700; white-space: nowrap;}
.bar-track, .meter {height: 8px; border-radius: 99px; background: rgba(127,127,127,.22); overflow: hidden;}
.bar-fill, .meter-fill {height: 100%; border-radius: 99px;}

.att-row {display: flex; justify-content: space-between; gap: .9rem; padding: .75rem .85rem; margin-bottom: .55rem;
    border-radius: 13px; background: rgba(127,127,127,.08); border: 1px solid rgba(127,127,127,.2);}
.att-main {flex: 1; min-width: 0;} .att-name {font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;}
.att-meta {font-size: .76rem; opacity: .62; margin: 2px 0 7px;} .att-side {text-align: right; flex: 0 0 auto;}
.att-reorder {font-size: .78rem; font-weight: 700; margin-top: 6px; opacity: .85;} .att-more {font-size: .78rem; opacity: .6; text-align: center;}

.tl-row {display: flex; align-items: center; gap: .75rem; padding: .55rem 0; border-bottom: 1px solid rgba(127,127,127,.15);}
.tl-row:last-child {border-bottom: none;}
.tl-icon {width: 34px; height: 34px; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-weight: 800; flex: 0 0 auto;}
.tl-main {flex: 1; min-width: 0;} .tl-name {font-weight: 600; font-size: .9rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;}
.tl-meta {font-size: .74rem; opacity: .58;} .tl-qty {font-weight: 800; font-size: 1.05rem;}

.greeting {display: flex; justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap; padding: 1.15rem 1.4rem;
    border-radius: 18px; margin-bottom: 1rem; color: #fff; border: 1px solid rgba(255,255,255,.12);
    background: radial-gradient(900px 220px at 85% -40%, rgba(34,184,207,.55), transparent 60%), linear-gradient(120deg, #0a2540 0%, #12467a 60%, #1b5fa8 100%);
    box-shadow: 0 10px 32px rgba(10,37,64,.45);}
.greeting-title {font-size: 1.45rem; font-weight: 800;} .greeting-sub {opacity: .85; font-size: .92rem; margin-top: 2px; color: #dcecff;}
.hero-chip {display: inline-block; padding: .25rem .75rem; margin-left: .4rem; border-radius: 99px; font-size: .78rem; font-weight: 600;
    background: rgba(255,255,255,.14); border: 1px solid rgba(255,255,255,.22); color: #fff;}

/* ---------- native widgets ---------- */
div[data-testid="stMetric"] {background: rgba(127,127,127,.09); border: 1px solid rgba(127,127,127,.26);
    border-radius: 14px; padding: .75rem .95rem; box-shadow: 0 3px 12px rgba(0,0,0,.10);}
div[data-testid="stMetricValue"] {font-weight: 800;}
.stButton > button, .stDownloadButton > button, div[data-testid="stFormSubmitButton"] > button {border-radius: 11px; font-weight: 600;
    transition: transform .12s, box-shadow .12s;}
.stButton > button:hover, .stDownloadButton > button:hover, div[data-testid="stFormSubmitButton"] > button:hover {
    transform: translateY(-1px); box-shadow: 0 6px 16px rgba(34,184,207,.28);}
.stButton > button[kind="primary"], div[data-testid="stFormSubmitButton"] > button[kind="primary"],
.stButton > button[kind="primaryFormSubmit"], div[data-testid="stFormSubmitButton"] > button[kind="primaryFormSubmit"] {
    background: linear-gradient(120deg, #22b8cf, #4c6ef5); border: none; color: #fff;}
div[data-baseweb="input"], div[data-baseweb="select"] > div, div[data-baseweb="textarea"] {border-radius: 11px;}
div[data-testid="stForm"] {border-radius: 16px; border: 1px solid rgba(127,127,127,.26); padding: 1.1rem 1.2rem; background: rgba(127,127,127,.05);}
div[data-testid="stExpander"] {border-radius: 14px; border: 1px solid rgba(127,127,127,.26);}
div[data-testid="stDataFrame"] {border-radius: 12px; overflow: hidden;}
button[data-baseweb="tab"] {font-weight: 600;}
div[data-testid="stAlert"] {border-radius: 12px;}
div[data-testid="stChatMessage"] {border-radius: 14px;}
.footer-note {font-size: .75rem; opacity: .6; text-align: center; margin-top: 2rem;}

/* ---------- sign-in screens ---------- */
.auth-hero {min-height: 560px; padding: 2.2rem 2.2rem; border-radius: 22px; color: #fff; position: relative; overflow: hidden;
    background: radial-gradient(600px 300px at 90% 0%, rgba(34,184,207,.55), transparent 65%),
                radial-gradient(500px 300px at 0% 100%, rgba(112,72,232,.45), transparent 65%),
                linear-gradient(150deg, #071a30 0%, #0c3159 55%, #124a86 100%);
    border: 1px solid rgba(255,255,255,.12); box-shadow: 0 18px 50px rgba(5,20,40,.55);}
.auth-hero::after {content: ""; position: absolute; inset: 0; pointer-events: none; opacity: .5;
    background-image: linear-gradient(rgba(255,255,255,.045) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.045) 1px, transparent 1px);
    background-size: 38px 38px; mask-image: linear-gradient(180deg, #000 0%, transparent 85%);}
.auth-hero > * {position: relative; z-index: 1;}
.hero-headline {font-size: 2.15rem; font-weight: 800; line-height: 1.18; margin: 2.2rem 0 .8rem; color: #fff;}
.hero-headline span {background: linear-gradient(90deg, #66d9e8, #91a7ff); -webkit-background-clip: text; background-clip: text; color: transparent;}
.hero-copy {color: #cfe3ff; font-size: 1rem; margin-bottom: 1.6rem; max-width: 34rem;}
.hero-feature {display: flex; gap: .85rem; align-items: flex-start; margin-bottom: .95rem;}
.hero-feature-icon {width: 38px; height: 38px; border-radius: 11px; display: flex; align-items: center; justify-content: center;
    background: rgba(255,255,255,.12); border: 1px solid rgba(255,255,255,.18); font-size: 1.1rem; flex: 0 0 auto;}
.hero-feature-title {font-weight: 700; color: #fff;} .hero-feature-text {font-size: .85rem; color: #bcd4f5;}
.auth-title {font-size: 1.65rem; font-weight: 800; margin: .2rem 0 .1rem;} .auth-sub {opacity: .7; margin-bottom: .9rem;}
.auth-note {font-size: .78rem; opacity: .6; text-align: center; margin-top: .9rem;}
.code-box {font-family: ui-monospace, 'Cascadia Code', Consolas, monospace; font-size: 1.6rem; font-weight: 800; letter-spacing: .12em; text-align: center;
    padding: 1rem; border-radius: 14px; border: 2px dashed #22b8cf; background: rgba(34,184,207,.10); margin: .6rem 0;}
</style>
"""

STATUS_ICONS = {svc.STATUS_OUT: "🔴 ", svc.STATUS_LOW: "🟠 ", svc.STATUS_OK: "🟢 "}


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def page_header(title: str, description: str = "") -> None:
    sub = f"<p>{escape(description)}</p>" if description else ""
    st.markdown(f'<div class="page-head"><h1>{escape(title)}</h1>{sub}</div>', unsafe_allow_html=True)


def html(markup: str) -> None:
    """Render trusted HTML produced by src/widgets.py (all user text is escaped there)."""
    st.markdown(markup, unsafe_allow_html=True)


def show_table(df: pd.DataFrame, **kwargs) -> None:
    """Full-width table that works on both old and new Streamlit versions."""
    try:
        st.dataframe(df, width="stretch", hide_index=True, **kwargs)
    except TypeError:
        st.dataframe(df, use_container_width=True, hide_index=True, **kwargs)


def with_status_icons(df: pd.DataFrame, column: str = "status") -> pd.DataFrame:
    df = df.copy()
    if column in df.columns:
        df[column] = df[column].map(lambda s: STATUS_ICONS.get(s, "") + str(s))
    return df


def download_row(df: pd.DataFrame, basename: str, key: str, sheet_name: str = "Data") -> None:
    """CSV + Excel download buttons for a table."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    left, right, _ = st.columns([1, 1, 3])
    left.download_button("⬇️ Download CSV", svc.to_csv_bytes(df), f"{basename}_{stamp}.csv",
                         "text/csv", key=f"{key}_csv")
    right.download_button(
        "⬇️ Download Excel", svc.to_excel_bytes({sheet_name: df}), f"{basename}_{stamp}.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"{key}_xlsx",
    )


def flash(message: str, kind: str = "success") -> None:
    """Queue a message that survives the next st.rerun()."""
    st.session_state["_flash"] = (kind, message)


def show_flash() -> None:
    item = st.session_state.pop("_flash", None)
    if item:
        kind, message = item
        getattr(st, kind, st.info)(message)


def current_user() -> str:
    """Username of the signed-in person (stored with every movement and audit entry)."""
    user = st.session_state.get("auth_user")
    return user["username"] if user else "system"
