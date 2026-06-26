"""Streamlit UI helpers."""

from __future__ import annotations

import streamlit as st

from .analytics import format_currency


CSS = """
<style>
    :root {
        --pulse-navy: #102033;
        --pulse-ink: #182B3A;
        --pulse-muted: #587180;
        --pulse-border: #D8E3E7;
        --pulse-teal: #18A999;
        --pulse-blue: #2C7BE5;
        --pulse-coral: #D95D39;
        --pulse-bg: #F7FAFC;
    }
    .main .block-container {
        padding-top: 1.6rem;
        padding-bottom: 2rem;
        max-width: 1180px;
    }
    h1, h2, h3 {
        color: var(--pulse-navy);
        letter-spacing: 0;
    }
    [data-testid="stSidebar"] {
        background: #0F1D2B;
    }
    [data-testid="stSidebar"] * {
        color: #F7FAFC;
    }
    .pulse-hero {
        border: 1px solid var(--pulse-border);
        border-radius: 8px;
        padding: 1.4rem 1.5rem;
        background:
            linear-gradient(135deg, rgba(24, 169, 153, 0.10), rgba(44, 123, 229, 0.08)),
            #FFFFFF;
        margin-bottom: 1rem;
    }
    .pulse-hero h1 {
        font-size: 2.25rem;
        margin-bottom: 0.35rem;
    }
    .pulse-hero p {
        max-width: 760px;
        color: var(--pulse-muted);
        font-size: 1.02rem;
        margin-bottom: 0;
    }
    .pulse-card {
        border: 1px solid var(--pulse-border);
        border-radius: 8px;
        padding: 1rem;
        background: #FFFFFF;
        min-height: 112px;
    }
    .pulse-card strong {
        color: var(--pulse-navy);
        display: block;
        margin-bottom: 0.25rem;
    }
    .pulse-card span {
        color: var(--pulse-muted);
        font-size: 0.92rem;
    }
    .status-pill {
        display: inline-block;
        padding: 0.22rem 0.52rem;
        border-radius: 999px;
        background: #E8F7F5;
        color: #0D5C63;
        font-size: 0.78rem;
        font-weight: 700;
        border: 1px solid #BCECE5;
    }
    div[data-testid="stMetric"] {
        background: #FFFFFF;
        border: 1px solid var(--pulse-border);
        border-radius: 8px;
        padding: 0.75rem 0.85rem;
        min-height: 102px;
    }
    div[data-testid="stMetricLabel"] p {
        color: var(--pulse-muted);
        font-size: 0.82rem;
    }
    div[data-testid="stMetricValue"] {
        color: var(--pulse-navy);
        font-size: 1.45rem;
    }
    .small-muted {
        color: var(--pulse-muted);
        font-size: 0.88rem;
    }
</style>
"""


def apply_page_style() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def hero(title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="pulse-hero">
            <span class="status-pill">AI decision dashboard for SMEs</span>
            <h1>{title}</h1>
            <p>{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def value_card(title: str, body: str) -> None:
    st.markdown(f'<div class="pulse-card"><strong>{title}</strong><span>{body}</span></div>', unsafe_allow_html=True)


def metric_value(label: str, value: object, help_text: str | None = None) -> None:
    st.metric(label, value, help=help_text)


def currency_metric(value: float | int) -> str:
    return format_currency(float(value))


def require_dataset_message() -> None:
    st.info("Load the demo dataset or upload a CSV from the Upload Data page to activate this section.")

