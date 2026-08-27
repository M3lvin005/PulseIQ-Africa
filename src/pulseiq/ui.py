"""Streamlit UI helpers."""

from __future__ import annotations

from collections.abc import Callable
from html import escape

import pandas as pd
import streamlit as st

from .analytics import format_currency
from .datasets import AssessmentStatus, DatasetAssessment, DatasetCapability, IssueSeverity
from .portfolio_metrics import MetricStatus, MetricValue

THEME_MODES = ("System", "Light", "Dark")

LIGHT_THEME_TOKENS = """
        --pulse-color-scheme: light;
        --pulse-heading: #0B1739;
        --pulse-text: #1D2433;
        --pulse-muted: #5F6B7C;
        --pulse-border: #DCE3EE;
        --pulse-border-strong: #C5D0E0;
        --pulse-accent: #3154F5;
        --pulse-accent-strong: #203EBB;
        --pulse-accent-soft: #E9EDFF;
        --pulse-accent-text: #203EBB;
        --pulse-on-accent: #FFFFFF;
        --pulse-info: #177FA8;
        --pulse-success: #087A5B;
        --pulse-warning: #976000;
        --pulse-danger: #B9382F;
        --pulse-warning-track: #E7B957;
        --pulse-danger-track: #D66B63;
        --pulse-canvas: #F3F6FA;
        --pulse-surface: #FFFFFF;
        --pulse-surface-raised: #FFFFFF;
        --pulse-field: #FFFFFF;
        --pulse-table-head: #EEF1FF;
        --pulse-hover: #F1F4FF;
        --pulse-overlay: rgba(255, 255, 255, 0.96);
        --pulse-shadow-sm: 0 5px 18px rgba(11, 23, 57, 0.035);
        --pulse-shadow-md: 0 10px 30px rgba(11, 23, 57, 0.06);
        --pulse-shadow-float: 0 12px 34px rgba(11, 23, 57, 0.18);
        --pulse-hero-start: #0B1739;
        --pulse-hero-mid: #132968;
        --pulse-hero-end: #3154F5;
        --pulse-hero-text: #FFFFFF;
        --pulse-hero-muted: #D7E0FF;
        --pulse-hero-pill: rgba(255, 255, 255, 0.13);
        --pulse-hero-pill-border: rgba(255, 255, 255, 0.24);
        --pulse-hero-glow: rgba(53, 191, 234, 0.22);
        --pulse-brand-shadow: 0 8px 18px rgba(49, 84, 245, 0.24);
"""

DARK_THEME_TOKENS = """
        --pulse-color-scheme: dark;
        --pulse-heading: #EDF2FF;
        --pulse-text: #DDE5F3;
        --pulse-muted: #AAB6C8;
        --pulse-border: #2C3A52;
        --pulse-border-strong: #43526B;
        --pulse-accent: #8398FF;
        --pulse-accent-strong: #A8B7FF;
        --pulse-accent-soft: #22315C;
        --pulse-accent-text: #C6D0FF;
        --pulse-on-accent: #09111F;
        --pulse-info: #66CAE9;
        --pulse-success: #58D2AD;
        --pulse-warning: #F0C66D;
        --pulse-danger: #FF938A;
        --pulse-warning-track: #A97922;
        --pulse-danger-track: #B85750;
        --pulse-canvas: #09111F;
        --pulse-surface: #111B2D;
        --pulse-surface-raised: #162238;
        --pulse-field: #0E1829;
        --pulse-table-head: #1B2A48;
        --pulse-hover: #182746;
        --pulse-overlay: rgba(17, 27, 45, 0.97);
        --pulse-shadow-sm: 0 5px 18px rgba(0, 0, 0, 0.18);
        --pulse-shadow-md: 0 10px 30px rgba(0, 0, 0, 0.26);
        --pulse-shadow-float: 0 12px 34px rgba(0, 0, 0, 0.42);
        --pulse-hero-start: #101B34;
        --pulse-hero-mid: #172B5B;
        --pulse-hero-end: #344FBE;
        --pulse-hero-text: #F7F9FF;
        --pulse-hero-muted: #D1DAF4;
        --pulse-hero-pill: rgba(255, 255, 255, 0.10);
        --pulse-hero-pill-border: rgba(255, 255, 255, 0.20);
        --pulse-hero-glow: rgba(102, 202, 233, 0.15);
        --pulse-brand-shadow: 0 8px 18px rgba(0, 0, 0, 0.30);
"""

CSS = """
<style>
    :root {
__THEME_TOKENS__
        --pulse-space-1: 0.25rem;
        --pulse-space-2: 0.5rem;
        --pulse-space-3: 0.75rem;
        --pulse-space-4: 1rem;
        --pulse-space-5: 1.5rem;
        --pulse-space-6: 2rem;
        --pulse-space-7: 3rem;
        --pulse-radius-sm: 0.5rem;
        --pulse-radius-md: 0.625rem;
        --pulse-radius-lg: 0.875rem;
        --pulse-radius-xl: 1rem;
        --pulse-transition: 180ms ease;
    }
__SYSTEM_THEME__
    html {
        color-scheme: __COLOR_SCHEME__;
        background: var(--pulse-canvas);
    }
    html, body, [class*="css"] {
        font-family: "Aptos", "Inter", "Segoe UI", system-ui, sans-serif;
    }
    .stApp {
        background: var(--pulse-canvas);
        color: var(--pulse-text);
        transition: background-color var(--pulse-transition), color var(--pulse-transition);
    }
    [data-testid="stHeader"] {
        background: transparent;
    }
    .stApp a {
        color: var(--pulse-accent-text);
    }
    .main .block-container, [data-testid="stMainBlockContainer"] {
        padding: 4.25rem clamp(var(--pulse-space-4), 2.5vw, 2.5rem) var(--pulse-space-7);
        max-width: 1440px;
    }
    [data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] {
        gap: var(--pulse-space-5);
    }
    [data-testid="stColumn"] > [data-testid="stVerticalBlock"] {
        gap: var(--pulse-space-4);
    }
    [data-testid="stHorizontalBlock"] {
        gap: var(--pulse-space-4);
    }
    h1, h2, h3 {
        color: var(--pulse-heading);
        letter-spacing: -0.025em;
    }
    h1 {
        font-size: clamp(1.8rem, 3vw, 2.6rem);
        line-height: 1.12;
    }
    h2 {
        font-size: clamp(1.25rem, 2vw, 1.55rem);
        line-height: 1.2;
    }
    [data-testid="stMainBlockContainer"] p,
    [data-testid="stMainBlockContainer"] li {
        line-height: 1.55;
    }
    [data-testid="stSidebar"] {
        background: var(--pulse-surface);
        border-right: 1px solid var(--pulse-border);
    }
    [data-testid="stSidebar"] > div:first-child {
        padding-top: 1.35rem;
    }
    [data-testid="stSidebar"] * {
        color: var(--pulse-text);
    }
    [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {
        color: var(--pulse-muted);
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }
    [data-testid="stSidebar"] div[role="radiogroup"] {
        gap: var(--pulse-space-1);
    }
    [data-testid="stSidebar"] div[role="radiogroup"] label {
        min-height: 44px;
        padding: 0.55rem 0.7rem;
        border-radius: var(--pulse-radius-md);
        transition: background-color var(--pulse-transition), color var(--pulse-transition);
    }
    [data-testid="stSidebar"] div[role="radiogroup"] label:hover {
        background: var(--pulse-hover);
    }
    [data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) {
        background: var(--pulse-accent-soft);
    }
    [data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) p {
        color: var(--pulse-accent-text);
        font-weight: 700;
    }
    .pulse-brand {
        display: flex;
        align-items: center;
        gap: var(--pulse-space-3);
        padding: var(--pulse-space-1) 0.15rem 1.35rem;
    }
    .pulse-brand-mark {
        display: grid;
        place-items: center;
        width: 42px;
        height: 42px;
        flex: 0 0 42px;
        border-radius: 0.75rem;
        color: var(--pulse-hero-text) !important;
        background: linear-gradient(145deg, var(--pulse-accent), var(--pulse-accent-strong));
        box-shadow: var(--pulse-brand-shadow);
        font-size: 0.72rem;
        font-weight: 800;
        letter-spacing: -0.04em;
    }
    .pulse-brand-name {
        display: block;
        color: var(--pulse-heading) !important;
        font-weight: 800;
        line-height: 1.1;
    }
    .pulse-brand-meta {
        display: block;
        margin-top: 0.18rem;
        color: var(--pulse-muted) !important;
        font-size: 0.76rem;
    }
    .pulse-hero {
        border: 1px solid var(--pulse-border);
        border-radius: var(--pulse-radius-xl);
        padding: clamp(1.2rem, 3vw, 2rem);
        background:
            radial-gradient(circle at 92% 20%, var(--pulse-hero-glow), transparent 24%),
            linear-gradient(
                118deg,
                var(--pulse-hero-start) 0%,
                var(--pulse-hero-mid) 62%,
                var(--pulse-hero-end) 120%
            );
        box-shadow: var(--pulse-shadow-md);
        margin-bottom: 1.15rem;
        overflow: hidden;
    }
    .pulse-hero h1 {
        max-width: 780px;
        margin: 0.65rem 0 0.45rem;
        color: var(--pulse-hero-text);
    }
    .pulse-hero p {
        max-width: 760px;
        color: var(--pulse-hero-muted);
        font-size: 1.02rem;
        margin-bottom: 0;
    }
    .pulse-card {
        border: 1px solid var(--pulse-border);
        border-radius: var(--pulse-radius-lg);
        padding: var(--pulse-space-4);
        background: var(--pulse-surface);
        min-height: 118px;
        box-shadow: var(--pulse-shadow-sm);
    }
    .pulse-card strong {
        color: var(--pulse-heading);
        display: block;
        margin-bottom: 0.25rem;
    }
    .pulse-card span {
        color: var(--pulse-muted);
        font-size: 0.92rem;
    }
    .pulse-workflow {
        margin: 0 0 var(--pulse-space-5);
        padding: var(--pulse-space-4);
        border: 1px solid var(--pulse-border);
        border-radius: var(--pulse-radius-lg);
        background: var(--pulse-surface);
        box-shadow: var(--pulse-shadow-sm);
    }
    .pulse-workflow-head {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: var(--pulse-space-4);
        margin-bottom: var(--pulse-space-4);
    }
    .pulse-workflow-head strong {
        color: var(--pulse-heading);
        font-size: 0.94rem;
    }
    .pulse-workflow-head span {
        color: var(--pulse-muted);
        font-size: 0.78rem;
    }
    .pulse-workflow ol {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: var(--pulse-space-3);
        margin: 0;
        padding: 0;
        list-style: none;
        counter-reset: pulse-stage;
    }
    .pulse-workflow li {
        position: relative;
        min-width: 0;
        min-height: 92px;
        padding: var(--pulse-space-3) var(--pulse-space-3) var(--pulse-space-3) 3.25rem;
        border: 1px solid var(--pulse-border);
        border-radius: var(--pulse-radius-md);
        background: var(--pulse-surface-raised);
        counter-increment: pulse-stage;
    }
    .pulse-workflow li::before {
        content: counter(pulse-stage);
        position: absolute;
        top: var(--pulse-space-3);
        left: var(--pulse-space-3);
        display: grid;
        width: 28px;
        height: 28px;
        place-items: center;
        border: 1px solid var(--pulse-border-strong);
        border-radius: 50%;
        color: var(--pulse-muted);
        background: var(--pulse-surface);
        font-size: 0.76rem;
        font-weight: 800;
    }
    .pulse-workflow li.is-current {
        border-color: var(--pulse-accent);
        background: var(--pulse-accent-soft);
    }
    .pulse-workflow li.is-current::before {
        color: var(--pulse-on-accent);
        background: var(--pulse-accent);
        border-color: var(--pulse-accent);
    }
    .pulse-workflow li.is-ready::before {
        color: var(--pulse-surface);
        background: var(--pulse-success);
        border-color: var(--pulse-success);
    }
    .pulse-workflow li.is-warning::before {
        color: var(--pulse-canvas);
        background: var(--pulse-warning);
        border-color: var(--pulse-warning);
    }
    .pulse-workflow li.is-blocked::before {
        color: var(--pulse-surface);
        background: var(--pulse-danger);
        border-color: var(--pulse-danger);
    }
    .pulse-workflow-label {
        display: block;
        overflow: hidden;
        color: var(--pulse-heading);
        font-size: 0.84rem;
        font-weight: 750;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .pulse-workflow-value {
        display: block;
        margin-top: var(--pulse-space-1);
        color: var(--pulse-muted);
        font-size: 0.76rem;
        line-height: 1.4;
    }
    .st-key-data_intake,
    .st-key-risk_filters,
    .st-key-portfolio_filters,
    .st-key-portfolio_insights,
    .st-key-report_context,
    .st-key-report_delivery {
        margin-bottom: var(--pulse-space-5);
        padding: var(--pulse-space-4);
        border: 1px solid var(--pulse-border);
        border-radius: var(--pulse-radius-lg);
        background: var(--pulse-surface);
        box-shadow: var(--pulse-shadow-sm);
    }
    .st-key-data_intake [data-testid="stFileUploaderDropzone"] {
        min-height: 112px;
    }
    .st-key-risk_filters [data-testid="stHorizontalBlock"] {
        gap: var(--pulse-space-3);
    }
    .st-key-portfolio_filters [data-testid="stHorizontalBlock"],
    .st-key-report_delivery [data-testid="stHorizontalBlock"] {
        gap: var(--pulse-space-3);
    }
    .st-key-portfolio_insights ul,
    .st-key-report_context ul {
        margin-bottom: 0;
        padding-left: var(--pulse-space-5);
    }
    .status-pill {
        display: inline-block;
        padding: 0.28rem 0.58rem;
        border-radius: 999px;
        background: var(--pulse-hero-pill);
        color: var(--pulse-hero-text);
        font-size: 0.78rem;
        font-weight: 700;
        border: 1px solid var(--pulse-hero-pill-border);
    }
    .pulse-trust {
        margin: 0 0 1.1rem;
        padding: 1rem 1.1rem;
        border: 1px solid var(--pulse-border);
        border-radius: var(--pulse-radius-lg);
        background: var(--pulse-surface);
        box-shadow: var(--pulse-shadow-sm);
    }
    .pulse-trust-head {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        gap: 1rem;
        margin-bottom: 0.75rem;
    }
    .pulse-trust-head strong {
        color: var(--pulse-heading);
        font-size: 0.93rem;
    }
    .pulse-trust-head span {
        color: var(--pulse-muted);
        font-size: 0.78rem;
    }
    .pulse-trust ol {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 0;
        margin: 0;
        padding: 0;
        list-style: none;
    }
    .pulse-trust li {
        position: relative;
        min-width: 0;
        padding: 0 1rem 0 1.35rem;
        border-top: 3px solid var(--pulse-border);
    }
    .pulse-trust li::before {
        content: "";
        position: absolute;
        top: -7px;
        left: 0;
        width: 11px;
        height: 11px;
        border: 2px solid var(--pulse-surface);
        border-radius: 50%;
        background: var(--pulse-border);
        box-shadow: 0 0 0 1px var(--pulse-border);
    }
    .pulse-trust li.is-ready { border-color: var(--pulse-accent); }
    .pulse-trust li.is-ready::before {
        background: var(--pulse-accent);
        box-shadow: 0 0 0 1px var(--pulse-accent);
    }
    .pulse-trust li.is-warning { border-color: var(--pulse-warning-track); }
    .pulse-trust li.is-warning::before {
        background: var(--pulse-warning-track);
        box-shadow: 0 0 0 1px var(--pulse-warning-track);
    }
    .pulse-trust li.is-blocked { border-color: var(--pulse-danger-track); }
    .pulse-trust li.is-blocked::before {
        background: var(--pulse-danger-track);
        box-shadow: 0 0 0 1px var(--pulse-danger-track);
    }
    .pulse-trust-label {
        display: block;
        margin-top: 0.7rem;
        color: var(--pulse-muted);
        font-size: 0.73rem;
        font-weight: 700;
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }
    .pulse-trust-value {
        display: block;
        margin-top: 0.16rem;
        overflow: hidden;
        color: var(--pulse-heading);
        font-size: 0.87rem;
        font-weight: 700;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    div[data-testid="stMetric"] {
        background: var(--pulse-surface);
        border: 1px solid var(--pulse-border);
        border-radius: var(--pulse-radius-lg);
        padding: 0.9rem 1rem;
        min-height: 112px;
        box-shadow: var(--pulse-shadow-sm);
    }
    div[data-testid="stMetricLabel"] p {
        color: var(--pulse-muted);
        font-size: 0.82rem;
    }
    div[data-testid="stMetricValue"] {
        color: var(--pulse-heading);
        font-size: clamp(1.45rem, 2vw, 1.85rem);
        font-variant-numeric: tabular-nums;
        font-weight: 750;
    }
    div[data-testid="stPlotlyChart"], [data-testid="stDataFrame"] {
        overflow: hidden;
        border: 1px solid var(--pulse-border);
        border-radius: var(--pulse-radius-lg);
        background: var(--pulse-surface);
        box-shadow: var(--pulse-shadow-sm);
    }
    .js-plotly-plot .plotly .main-svg,
    .js-plotly-plot .plotly .bg {
        background: transparent !important;
        fill: transparent !important;
    }
    .js-plotly-plot .xtick text,
    .js-plotly-plot .ytick text,
    .js-plotly-plot .gtitle,
    .js-plotly-plot .xtitle,
    .js-plotly-plot .ytitle,
    .js-plotly-plot .legendtext {
        fill: var(--pulse-text) !important;
    }
    .js-plotly-plot .gridlayer path {
        stroke: var(--pulse-border) !important;
    }
    .stButton > button, .stDownloadButton > button {
        min-height: 44px;
        border-radius: var(--pulse-radius-md);
        font-weight: 700;
        transition: background-color var(--pulse-transition), border-color var(--pulse-transition),
            color var(--pulse-transition);
    }
    .stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {
        color: var(--pulse-on-accent);
        background: var(--pulse-accent);
        border-color: var(--pulse-accent);
    }
    .stButton > button[kind="secondary"], .stDownloadButton > button[kind="secondary"] {
        color: var(--pulse-text);
        background: var(--pulse-surface);
        border-color: var(--pulse-border-strong);
    }
    @media (hover: hover) {
        .stButton > button[kind="secondary"]:hover,
        .stDownloadButton > button[kind="secondary"]:hover {
            color: var(--pulse-accent-text);
            background: var(--pulse-hover);
            border-color: var(--pulse-accent);
        }
    }
    [data-baseweb="input"] > div,
    [data-baseweb="select"] > div,
    [data-baseweb="textarea"] > div,
    [data-testid="stFileUploaderDropzone"],
    [data-testid="stNumberInputContainer"] {
        color: var(--pulse-text) !important;
        background: var(--pulse-field) !important;
        border-color: var(--pulse-border-strong) !important;
    }
    input, textarea, select {
        color: var(--pulse-text) !important;
        background: var(--pulse-field) !important;
    }
    [data-testid="stAlert"] {
        color: var(--pulse-text);
        background: var(--pulse-surface-raised);
        border: 1px solid var(--pulse-border);
        border-radius: var(--pulse-radius-md);
    }
    [data-testid="stExpander"] {
        overflow: hidden;
        color: var(--pulse-text);
        background: var(--pulse-surface);
        border-color: var(--pulse-border);
        border-radius: var(--pulse-radius-md);
    }
    [data-testid="stCaptionContainer"],
    [data-testid="stCaptionContainer"] p {
        color: var(--pulse-muted);
    }
    .small-muted {
        color: var(--pulse-muted);
        font-size: 0.88rem;
    }
    :focus-visible {
        outline: 3px solid var(--pulse-accent) !important;
        outline-offset: 2px !important;
    }
    .skip-link {
        position: fixed;
        top: 0.5rem;
        left: 0.5rem;
        z-index: 1000000;
        padding: 0.65rem 0.85rem;
        color: var(--pulse-canvas) !important;
        background: var(--pulse-heading);
        border-radius: var(--pulse-radius-sm);
        transform: translateY(-200%);
    }
    .skip-link:focus {
        transform: translateY(0);
    }
    .semantic-table {
        width: 100%;
        border-collapse: collapse;
        margin: 0.5rem 0 1rem;
        font-variant-numeric: tabular-nums;
    }
    .semantic-table caption {
        text-align: left;
        font-weight: 700;
        color: var(--pulse-heading);
        padding-bottom: 0.5rem;
    }
    .semantic-table th, .semantic-table td {
        border: 1px solid var(--pulse-border);
        padding: 0.5rem 0.65rem;
        text-align: left;
        vertical-align: top;
    }
    .semantic-table tbody {
        color: var(--pulse-text);
        background: var(--pulse-surface);
    }
    .semantic-table thead th {
        background: var(--pulse-table-head);
        color: var(--pulse-heading);
    }
    .st-key-mobile_navigation {
        display: none;
    }
    .st-key-theme_switcher {
        position: fixed;
        z-index: 999998;
        top: var(--pulse-space-2);
        right: var(--pulse-space-4);
        width: auto !important;
        padding: var(--pulse-space-1);
        border: 1px solid var(--pulse-border);
        border-radius: 0.75rem;
        background: var(--pulse-overlay);
        box-shadow: var(--pulse-shadow-sm);
        backdrop-filter: blur(14px);
    }
    .st-key-theme_switcher > [data-testid="stElementContainer"] {
        width: auto;
    }
    .st-key-theme_switcher [data-testid="stWidgetLabel"] {
        position: absolute;
        width: 1px;
        height: 1px;
        overflow: hidden;
        clip: rect(0 0 0 0);
        white-space: nowrap;
    }
    @media (max-width: 1023px) {
        [data-testid="stHorizontalBlock"] {
            flex-wrap: wrap;
        }
        [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
            flex: 1 1 220px;
            min-width: min(100%, 220px);
        }
        .pulse-trust ol {
            grid-template-columns: repeat(2, minmax(0, 1fr));
            row-gap: 1rem;
        }
        .pulse-workflow ol {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }
    }
    @media (max-width: 767.98px) {
        [data-testid="stSidebar"],
        [data-testid="stSidebarCollapsedControl"],
        [data-testid="stExpandSidebarButton"] {
            display: none;
        }
        [data-testid="stHeader"] {
            display: none;
        }
        .main .block-container, [data-testid="stMainBlockContainer"] {
            padding: var(--pulse-space-3) var(--pulse-space-3) 6.8rem;
        }
        .pulse-hero {
            border-radius: 14px;
            padding: 1.05rem 1.1rem 1.15rem;
        }
        .pulse-hero h1 {
            margin: 0.5rem 0 0.35rem;
            font-size: 1.75rem;
            line-height: 1.1;
        }
        .pulse-hero p {
            font-size: 0.88rem;
            line-height: 1.5;
        }
        .status-pill {
            font-size: 0.68rem;
        }
        .pulse-trust-head {
            align-items: flex-start;
            flex-direction: column;
            gap: 0.15rem;
        }
        .pulse-trust ol {
            grid-template-columns: 1fr;
            gap: 0.8rem;
        }
        .pulse-trust li {
            min-height: 48px;
        }
        .pulse-workflow {
            padding: var(--pulse-space-3);
        }
        .pulse-workflow-head {
            align-items: flex-start;
            flex-direction: column;
            gap: var(--pulse-space-1);
        }
        .pulse-workflow ol {
            grid-template-columns: 1fr;
            gap: var(--pulse-space-2);
        }
        .pulse-workflow li {
            min-height: 78px;
        }
        .st-key-data_intake,
        .st-key-risk_filters,
        .st-key-portfolio_filters,
        .st-key-portfolio_insights,
        .st-key-report_context,
        .st-key-report_delivery {
            padding: var(--pulse-space-3);
        }
        .st-key-mobile_navigation {
            position: fixed;
            z-index: 999999;
            right: 0.65rem;
            bottom: max(0.6rem, env(safe-area-inset-bottom));
            left: 0.65rem;
            width: auto !important;
            display: grid;
            grid-template-columns: minmax(0, 1fr);
            gap: 0.2rem;
            padding: 0.42rem;
            border: 1px solid var(--pulse-border);
            border-radius: var(--pulse-radius-xl);
            background: var(--pulse-overlay);
            box-shadow: var(--pulse-shadow-float);
            backdrop-filter: blur(14px);
        }
        .st-key-mobile_navigation > [data-testid="stElementContainer"],
        .st-key-mobile_navigation [data-testid="stRadio"] {
            width: 100%;
        }
        .st-key-mobile_navigation [data-testid="stWidgetLabel"] {
            position: absolute;
            width: 1px;
            height: 1px;
            overflow: hidden;
            clip: rect(0 0 0 0);
            white-space: nowrap;
        }
        .st-key-mobile_navigation div[role="radiogroup"] {
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 0.2rem;
        }
        .st-key-mobile_navigation div[role="radiogroup"] label {
            display: grid;
            min-width: 0;
            min-height: 50px;
            place-items: center;
            padding: 0.35rem 0.15rem;
            border-radius: 11px;
            color: var(--pulse-muted);
            font-size: 0.68rem;
            font-weight: 700;
            line-height: 1.15;
            text-align: center;
        }
        .st-key-mobile_navigation div[role="radiogroup"] label > div:first-child {
            width: 100%;
        }
        .st-key-mobile_navigation div[role="radiogroup"] label > div:first-child > div:first-child {
            width: 100%;
            justify-content: center;
        }
        .st-key-mobile_navigation div[role="radiogroup"] label div:has(+ [data-testid="stMarkdownContainer"]) {
            display: none;
        }
        .st-key-mobile_navigation [data-testid="stMarkdownContainer"] {
            width: 100%;
            text-align: center;
        }
        .st-key-mobile_navigation div[role="radiogroup"] label:has(input:checked) {
            color: var(--pulse-accent-text);
            background: var(--pulse-accent-soft);
        }
        .st-key-mobile_navigation div[role="radiogroup"] label:has(input:checked) p {
            color: var(--pulse-accent-text);
        }
        .st-key-theme_switcher {
            top: var(--pulse-space-2);
            right: var(--pulse-space-3);
        }
    }
    @media (prefers-reduced-motion: reduce) {
        *, *::before, *::after {
            animation-duration: 0.01ms !important;
            animation-iteration-count: 1 !important;
            scroll-behavior: auto !important;
            transition-duration: 0.01ms !important;
        }
    }
</style>
"""


def theme_css(theme_mode: str) -> str:
    """Return the complete semantic token sheet for one supported appearance mode."""

    if theme_mode not in THEME_MODES:
        raise ValueError(f"Unsupported theme mode: {theme_mode!r}.")
    tokens = DARK_THEME_TOKENS if theme_mode == "Dark" else LIGHT_THEME_TOKENS
    system_theme = (
        f"@media (prefers-color-scheme: dark) {{ :root {{ {DARK_THEME_TOKENS} }} }}" if theme_mode == "System" else ""
    )
    color_scheme = "light dark" if theme_mode == "System" else theme_mode.lower()
    return (
        CSS.replace("__THEME_TOKENS__", tokens)
        .replace("__SYSTEM_THEME__", system_theme)
        .replace("__COLOR_SCHEME__", color_scheme)
    )


def apply_page_style(theme_mode: str) -> None:
    st.markdown(theme_css(theme_mode), unsafe_allow_html=True)


def render_theme_switcher() -> None:
    """Render the single appearance control shared by phone and desktop layouts."""

    with st.container(key="theme_switcher"):
        st.segmented_control(
            "Appearance",
            THEME_MODES,
            key="theme_mode",
            label_visibility="collapsed",
        )


def sidebar_brand() -> None:
    """Render the compact product identity used by the workspace rail."""

    st.sidebar.markdown(
        """
        <div class="pulse-brand" aria-label="PulseIQ Africa">
            <span class="pulse-brand-mark" aria-hidden="true">PIQ</span>
            <span>
                <span class="pulse-brand-name">PulseIQ Africa</span>
                <span class="pulse-brand-meta">Decision assurance</span>
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def mobile_navigation(current_page: str, *, on_change: Callable[[], None]) -> None:
    """Render a native small-screen control bound to the workspace page state."""

    pages = ("Home", "Upload Data", "Dashboard", "Anomaly Detection", "About Project")
    labels = {
        "Home": "Overview",
        "Upload Data": "Data",
        "Dashboard": "Portfolio",
        "Anomaly Detection": "Risk",
        "About Project": "More",
    }
    target = current_page if current_page in pages else "About Project"
    if st.session_state.get("mobile_navigation_for") != current_page:
        st.session_state.mobile_workspace_page = target
        st.session_state.mobile_navigation_for = current_page

    with st.container(key="mobile_navigation"):
        st.radio(
            "Primary navigation",
            pages,
            format_func=labels.__getitem__,
            horizontal=True,
            key="mobile_workspace_page",
            on_change=on_change,
        )


def hero(title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="pulse-hero">
            <span class="status-pill">Governed decision workspace</span>
            <h1>{escape(title)}</h1>
            <p>{escape(subtitle)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_trust_ribbon(
    assessment: DatasetAssessment | None,
    *,
    source: str,
    mapping_review_required: bool = False,
) -> None:
    """Summarize the evidence chain and next governed action before metrics."""

    if assessment is None:
        stages = (
            ("Source", "Waiting for data", "is-pending"),
            ("Meaning", "Not mapped", "is-pending"),
            ("Quality", "Checks pending", "is-pending"),
            ("Next action", "Upload a dataset", "is-warning"),
        )
        summary = "No evidence is active"
    else:
        warnings = sum(issue.severity is IssueSeverity.WARN for issue in assessment.issues)
        blocked = sum(item.status is AssessmentStatus.BLOCKED for item in assessment.capabilities)
        if assessment.is_blocked:
            quality_value = f"{blocked} workflow{'s' if blocked != 1 else ''} blocked"
            quality_tone = "is-blocked"
            action_value = "Resolve blocking issues"
            action_tone = "is-blocked"
            summary = "Action required before decision use"
        elif warnings:
            quality_value = f"{assessment.composite_score:.1f}% · {warnings} warning{'s' if warnings != 1 else ''}"
            quality_tone = "is-warning"
            action_value = "Review quality warnings"
            action_tone = "is-warning"
            summary = "Usable with visible cautions"
        else:
            quality_value = f"{assessment.composite_score:.1f}% · checks passed"
            quality_tone = "is-ready"
            action_value = "Review portfolio evidence"
            action_tone = "is-ready"
            summary = "Evidence chain is ready"

        mapping_value = "Review suggestions" if mapping_review_required else "Semantic contract set"
        mapping_tone = "is-warning" if mapping_review_required else "is-ready"
        stages = (
            ("Source", source, "is-ready"),
            ("Meaning", mapping_value, mapping_tone),
            ("Quality", quality_value, quality_tone),
            ("Next action", action_value, action_tone),
        )

    stage_html = "".join(
        '<li class="{tone}"><span class="pulse-trust-label">{label}</span>'
        '<span class="pulse-trust-value" title="{value}">{value}</span></li>'.format(
            tone=tone,
            label=escape(label),
            value=escape(value, quote=True),
        )
        for label, value, tone in stages
    )
    st.markdown(
        '<section class="pulse-trust" aria-labelledby="pulse-trust-title">'
        '<div class="pulse-trust-head"><strong id="pulse-trust-title">Workspace trust</strong>'
        f"<span>{escape(summary)}</span></div><ol>{stage_html}</ol></section>",
        unsafe_allow_html=True,
    )


def value_card(title: str, body: str) -> None:
    st.markdown(
        f'<div class="pulse-card"><strong>{escape(title)}</strong><span>{escape(body)}</span></div>',
        unsafe_allow_html=True,
    )


def render_workflow_steps(title: str, summary: str, stages: tuple[tuple[str, str, str], ...]) -> None:
    """Render an escaped ordered workflow with explicit, non-colour status copy."""

    allowed_tones = {"is-pending", "is-current", "is-ready", "is-warning", "is-blocked"}
    if not stages or any(tone not in allowed_tones for _, _, tone in stages):
        raise ValueError("Workflow stages require a supported status tone.")
    stage_html = "".join(
        f'<li class="{tone}"><span class="pulse-workflow-label">{escape(label)}</span>'
        f'<span class="pulse-workflow-value">{escape(value)}</span></li>'
        for label, value, tone in stages
    )
    st.markdown(
        '<section class="pulse-workflow" aria-labelledby="pulse-workflow-title">'
        f'<div class="pulse-workflow-head"><strong id="pulse-workflow-title">{escape(title)}</strong>'
        f"<span>{escape(summary)}</span></div><ol>{stage_html}</ol></section>",
        unsafe_allow_html=True,
    )


def metric_value(label: str, value: str | int | float | None, help_text: str | None = None) -> None:
    st.metric(label, value, help=help_text)


def currency_metric(value: float | int) -> str:
    return format_currency(float(value))


def require_dataset_message() -> None:
    st.info("Load the demo dataset or upload a CSV from the Upload Data page to activate this section.")


def render_dataset_assessment(assessment: DatasetAssessment) -> None:
    """Render an accessible summary, exact dimension values, and recovery actions."""

    blocked = [
        item.capability.value.replace("_", " ")
        for item in assessment.capabilities
        if item.status is AssessmentStatus.BLOCKED
    ]
    warnings = [issue for issue in assessment.issues if issue.severity is IssueSeverity.WARN]
    if blocked:
        st.error(f"Dataset blocked for: {', '.join(blocked)}. Resolve the blocking issues below.")
    elif warnings:
        st.warning(f"Dataset ready with {len(warnings)} quality warning(s). Review them before relying on results.")
    else:
        st.success("Dataset ready for all supported prototype capabilities.")

    st.header("Quality dimensions")
    render_semantic_table(
        "Dataset quality dimensions",
        pd.DataFrame(
            [
                {
                    "Dimension": item.dimension.value.title(),
                    "Score": f"{item.score:.1f}%",
                }
                for item in assessment.dimensions
            ]
        ),
    )

    if assessment.issues:
        st.header("Validation issues and recovery")
    for issue in assessment.issues:
        count = f" Affected values: {issue.count:,}." if issue.count is not None else ""
        message = f"{issue.message}{count} Recovery: {issue.recovery}"
        if issue.severity is IssueSeverity.BLOCK:
            st.error(message)
        elif issue.severity is IssueSeverity.WARN:
            st.warning(message)
        else:
            st.info(message)


def render_chart_data_table(title: str, dataframe: pd.DataFrame) -> None:
    """Provide a keyboard-operable semantic table alternative for one chart."""

    st.caption(f"Chart: {title}. The exact values are available in the data table below.")
    with st.expander(f"Data table: {title}"):
        render_semantic_table(f"Data for {title}", dataframe)


def render_semantic_table(caption: str, dataframe: pd.DataFrame) -> None:
    """Render a compact escaped table with explicit caption and header scopes."""

    headers = "".join(f'<th scope="col">{escape(str(column))}</th>' for column in dataframe.columns)
    rows: list[str] = []
    for values in dataframe.itertuples(index=False, name=None):
        cells: list[str] = []
        for index, value in enumerate(values):
            tag = "th" if index == 0 else "td"
            scope = ' scope="row"' if index == 0 else ""
            cells.append(f"<{tag}{scope}>{escape(str(value))}</{tag}>")
        rows.append(f"<tr>{''.join(cells)}</tr>")
    st.markdown(
        f'<table class="semantic-table"><caption>{escape(caption)}</caption>'
        f"<thead><tr>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table>",
        unsafe_allow_html=True,
    )


def require_dataset_capability(
    assessment: DatasetAssessment,
    capability: DatasetCapability,
) -> bool:
    """Render recovery guidance and return false when an operation is blocked."""

    if assessment.can(capability):
        return True

    label = capability.value.replace("_", " ")
    st.error(f"{label.title()} is blocked because required dataset inputs are unavailable or invalid.")
    relevant_issues = [issue for issue in assessment.issues if capability in issue.affected_capabilities]
    for issue in relevant_issues:
        st.write(f"- {issue.message} Recovery: {issue.recovery}")
    return False


def render_governed_metric(metric: MetricValue) -> None:
    """Render a metric value together with its interpretation metadata."""

    if metric.status is MetricStatus.UNAVAILABLE:
        display_value = "Not available"
    elif metric.value is None:
        raise ValueError(f"Available metric {metric.metric_id.value} has no value.")
    elif metric.unit == "currency":
        display_value = f"{metric.currency} {float(metric.value):,.0f}"
    elif metric.unit == "percent":
        display_value = f"{float(metric.value):.1f}%"
    elif isinstance(metric.value, int):
        display_value = f"{metric.value:,}"
    else:
        display_value = str(metric.value)

    provenance = [
        f"Definition: {metric.definition_version}",
        f"Source: {metric.source_reference}",
        f"Quality: {metric.quality_status.value}",
    ]
    if metric.logic_version:
        provenance.append(f"Logic: {metric.logic_version}")
    if metric.period:
        provenance.append(f"Period: {metric.period.start.isoformat()} to {metric.period.end.isoformat()}")
    if metric.unavailable_reason:
        provenance.append(f"Unavailable: {metric.unavailable_reason}")
    if metric.recovery:
        provenance.append(f"Recovery: {metric.recovery}")
    st.metric(metric.label, display_value, help="\n\n".join(provenance))
