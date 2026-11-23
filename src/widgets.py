"""Pure HTML builders for the dashboard and shared UI (no Streamlit import, so they are easy to test).

Every piece of user-supplied text goes through `_e()` (HTML escaping): part names, locations and
usernames are never inserted raw into markup.
"""
from __future__ import annotations

from html import escape

import pandas as pd

TONES = {  # accent colour, soft background
    "blue": ("#4c9ffe", "rgba(76,159,254,.15)"),
    "cyan": ("#22b8cf", "rgba(34,184,207,.15)"),
    "green": ("#40c057", "rgba(64,192,87,.15)"),
    "amber": ("#fab005", "rgba(250,176,5,.16)"),
    "red": ("#fa5252", "rgba(250,82,82,.16)"),
    "violet": ("#9775fa", "rgba(151,117,250,.16)"),
    "gray": ("#868e96", "rgba(134,142,150,.16)"),
}
STATUS_TONE = {"Out of Stock": "red", "Low Stock": "amber", "In Stock": "green"}


def _e(value) -> str:
    return escape("" if value is None else str(value), quote=True)


def initials(name: str) -> str:
    parts = [p for p in str(name or "?").replace(".", " ").replace("_", " ").split() if p]
    return ("".join(p[0] for p in parts[:2]) or "?").upper()


def pill(text: str, tone: str = "gray") -> str:
    color, soft = TONES.get(tone, TONES["gray"])
    return f'<span class="pill" style="color:{color};background:{soft};border-color:{color}55">{_e(text)}</span>'


def kpi_card(icon: str, label: str, value, sub: str = "", tone: str = "blue") -> str:
    color, soft = TONES.get(tone, TONES["blue"])
    sub_html = f'<div class="kpi-sub">{_e(sub)}</div>' if sub else ""
    return (f'<div class="kpi" style="--accent:{color}">'
            f'<div class="kpi-icon" style="background:{soft};color:{color}">{_e(icon)}</div>'
            f'<div class="kpi-body"><div class="kpi-label">{_e(label)}</div>'
            f'<div class="kpi-value">{_e(value)}</div>{sub_html}</div></div>')


def kpi_grid(cards: list[str]) -> str:
    return f'<div class="kpi-grid">{"".join(cards)}</div>'


def section_title(text: str, hint: str = "") -> str:
    hint_html = f'<span class="section-hint">{_e(hint)}</span>' if hint else ""
    return f'<div class="section-title">{_e(text)}{hint_html}</div>'


def empty_state(icon: str, title: str, text: str = "") -> str:
    return (f'<div class="empty"><div class="empty-icon">{_e(icon)}</div><div class="empty-title">{_e(title)}</div>'
            f'<div class="empty-text">{_e(text)}</div></div>')


def donut(segments: list[tuple[str, int, str]], center_value, center_label: str) -> str:
    """segments = [(label, value, tone)]. Pure-CSS ring chart (conic-gradient) with a legend."""
    total = sum(max(int(v), 0) for _, v, _ in segments)
    if total <= 0:
        gradient = "rgba(128,128,128,.28) 0% 100%"
    else:
        stops, start = [], 0.0
        for _, value, tone in segments:
            if value <= 0:
                continue
            end = start + value / total * 100
            stops.append(f"{TONES[tone][0]} {start:.2f}% {end:.2f}%")
            start = end
        gradient = ", ".join(stops)
    legend = "".join(
        f'<div class="legend-row"><span class="dot" style="background:{TONES[tone][0]}"></span>'
        f'<span class="legend-label">{_e(label)}</span><span class="legend-value">{int(value)}</span></div>'
        for label, value, tone in segments)
    return (f'<div class="donut-wrap"><div class="donut" style="background:conic-gradient({gradient})">'
            f'<div class="donut-hole"><div class="donut-value">{_e(center_value)}</div>'
            f'<div class="donut-label">{_e(center_label)}</div></div></div>'
            f'<div class="donut-legend">{legend}</div></div>')


def bar_list(items: list[tuple[str, float, str]], tone: str = "cyan", unit: str = "") -> str:
    """items = [(label, value, sublabel)] drawn as horizontal bars scaled to the largest value."""
    if not items:
        return empty_state("📭", "Nothing to show yet")
    color = TONES.get(tone, TONES["cyan"])[0]
    top = max(float(v) for _, v, _ in items) or 1.0
    rows = []
    for label, value, sub in items:
        width = max(float(value) / top * 100, 2)
        sub_html = f'<span class="bar-sub">{_e(sub)}</span>' if sub else ""
        rows.append(f'<div class="bar-row"><div class="bar-head"><span class="bar-label">{_e(label)}{sub_html}</span>'
                    f'<span class="bar-value">{_e(int(value) if float(value).is_integer() else value)}{_e(unit)}</span></div>'
                    f'<div class="bar-track"><div class="bar-fill" style="width:{width:.1f}%;background:{color}"></div></div></div>')
    return f'<div class="bar-list">{"".join(rows)}</div>'


def stock_meter(quantity: int, minimum: int) -> str:
    """Progress bar of stock against twice the minimum level (full bar = comfortable)."""
    target = max(int(minimum) * 2, 1)
    pct = max(min(int(quantity) / target * 100, 100), 0)
    tone = "red" if quantity <= 0 else ("amber" if quantity <= minimum else "green")
    return (f'<div class="meter"><div class="meter-fill" style="width:{max(pct, 3 if quantity > 0 else 0):.0f}%;'
            f'background:{TONES[tone][0]}"></div></div>')


def attention_list(df: pd.DataFrame, limit: int = 6) -> str:
    """Low / out-of-stock parts. Needs columns part_name, part_number, quantity, min_stock, status, suggested_reorder."""
    if df.empty:
        return empty_state("✅", "All stocked up", "No part is at or below its minimum level.")
    rows = []
    for r in df.head(limit).itertuples():
        tone = STATUS_TONE.get(r.status, "gray")
        rows.append(
            f'<div class="att-row"><div class="att-main"><div class="att-name">{_e(r.part_name)}</div>'
            f'<div class="att-meta">{_e(r.part_number or "no part number")} · {_e(r.quantity)} of min {_e(r.min_stock)}</div>'
            f'{stock_meter(r.quantity, r.min_stock)}</div>'
            f'<div class="att-side">{pill(r.status, tone)}<div class="att-reorder">Reorder +{_e(r.suggested_reorder)}</div></div></div>')
    more = len(df) - limit
    footer = f'<div class="att-more">+ {more} more on the Low Stock Alerts page</div>' if more > 0 else ""
    return f'<div class="att-list">{"".join(rows)}</div>{footer}'


def timeline(df: pd.DataFrame, limit: int = 8) -> str:
    """Recent transactions (columns part_name, transaction_type, quantity, reference, date, time, performed_by)."""
    if df.empty:
        return empty_state("🕒", "No activity yet", "Stock movements will appear here.")
    rows = []
    for r in df.head(limit).itertuples():
        incoming = r.transaction_type == "Stock In"
        tone = "green" if incoming else "red"
        sign = "+" if incoming else "−"
        who = f" · {_e(r.performed_by)}" if getattr(r, "performed_by", "") else ""
        ref = f" · {_e(r.reference)}" if getattr(r, "reference", "") else ""
        rows.append(
            f'<div class="tl-row"><div class="tl-icon" style="background:{TONES[tone][1]};color:{TONES[tone][0]}">'
            f'{"↗" if incoming else "↘"}</div><div class="tl-main"><div class="tl-name">{_e(r.part_name)}</div>'
            f'<div class="tl-meta">{_e(r.date)} {_e(r.time)}{ref}{who}</div></div>'
            f'<div class="tl-qty" style="color:{TONES[tone][0]}">{sign}{_e(r.quantity)}</div></div>')
    return f'<div class="tl-list">{"".join(rows)}</div>'


def greeting_banner(title: str, subtitle: str, chips: list[tuple[str, str]] | None = None) -> str:
    chip_html = "".join(f'<span class="hero-chip">{_e(i)} {_e(t)}</span>' for i, t in (chips or []))
    return (f'<div class="greeting"><div><div class="greeting-title">{_e(title)}</div>'
            f'<div class="greeting-sub">{_e(subtitle)}</div></div><div class="greeting-chips">{chip_html}</div></div>')


def brand_lockup(name: str, subtitle: str, size: str = "md") -> str:
    return (f'<div class="brand brand-{size}"><div class="logo-mark">⚡</div><div class="brand-text">'
            f'<div class="brand-name">{_e(name)}</div><div class="brand-sub">{_e(subtitle)}</div></div></div>')


def user_chip(name: str, role_label: str) -> str:
    return (f'<div class="user-chip"><div class="avatar">{_e(initials(name))}</div><div>'
            f'<div class="user-name">{_e(name)}</div><div class="user-role">{_e(role_label)}</div></div></div>')


def auth_hero(name: str, full_name: str, tagline: str, features: list[tuple[str, str, str]]) -> str:
    items = "".join(f'<div class="hero-feature"><div class="hero-feature-icon">{_e(i)}</div><div>'
                    f'<div class="hero-feature-title">{_e(t)}</div><div class="hero-feature-text">{_e(d)}</div></div></div>'
                    for i, t, d in features)
    return (f'<div class="auth-hero">{brand_lockup(name, full_name, "lg")}'
            f'<div class="hero-headline">Never run short of the part that <span>stops the line.</span></div>'
            f'<div class="hero-copy">{_e(tagline)}</div>{items}</div>')
