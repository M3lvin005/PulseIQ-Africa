"""Accessible compact-table rendering tests."""

from __future__ import annotations

import pandas as pd
import pytest

from pulseiq import ui
from pulseiq.data import load_demo_data
from pulseiq.datasets import assess_dataset


@pytest.mark.parametrize(("mode", "scheme"), [("Light", "light"), ("Dark", "dark")])
def test_theme_css_resolves_manual_modes_without_placeholders(mode: str, scheme: str) -> None:
    css = ui.theme_css(mode)

    assert "__THEME_TOKENS__" not in css
    assert "__SYSTEM_THEME__" not in css
    assert "__COLOR_SCHEME__" not in css
    assert f"color-scheme: {scheme};" in css
    assert "prefers-color-scheme: dark" not in css


def test_theme_css_styles_react_controls_and_glass_surfaces() -> None:
    """The semantic sheet must cover Streamlit's current controls, not only legacy selectors."""

    css = ui.theme_css("Dark")

    assert "--pulse-glass:" in css
    assert ".react-aria-ComboBox" in css
    assert '[data-testid="stMetricLabel"] p' in css
    assert '.st-key-theme_switcher button[data-variant="segmented_control"]' in css


def test_theme_css_reserves_mobile_dock_and_reflows_workflow_cards() -> None:
    css = ui.theme_css("Dark")

    assert "calc(8rem + env(safe-area-inset-bottom))" in css
    assert "@media (min-width: 1024px) and (max-width: 1199px)" in css
    assert ".pulse-inspector" in css


def test_chart_export_names_are_safe_for_rule_titles() -> None:
    assert (
        ui._chart_export_name("Rule priority (prototype-risk-rules/2.0.0)")
        == "rule_priority_prototype_risk_rules_2_0_0.csv"
    )


def test_theme_css_follows_system_preference_without_losing_light_default() -> None:
    css = ui.theme_css("System")

    assert "color-scheme: light dark;" in css
    assert "@media (prefers-color-scheme: dark)" in css
    assert css.index("--pulse-canvas: #F3F6FA") < css.index("--pulse-canvas: #09111F")


def test_theme_css_rejects_unknown_modes() -> None:
    with pytest.raises(ValueError, match="Unsupported theme mode"):
        ui.theme_css("Sepia")


def test_semantic_table_escapes_values_and_declares_caption_and_scopes(monkeypatch: object) -> None:
    rendered: list[str] = []

    def capture(body: str, *, unsafe_allow_html: bool) -> None:
        assert unsafe_allow_html is True
        rendered.append(body)

    monkeypatch.setattr(ui.st, "markdown", capture)  # type: ignore[attr-defined]

    ui.render_semantic_table(
        "Risk <evidence>",
        pd.DataFrame({"Rule": ["<script>alert(1)</script>"], "Count": [3]}),
    )

    html = rendered[0]
    assert "<caption>Risk &lt;evidence&gt;</caption>" in html
    assert '<th scope="col">Rule</th>' in html
    assert '<th scope="row">&lt;script&gt;alert(1)&lt;/script&gt;</th>' in html
    assert "<script>" not in html


def test_trust_ribbon_escapes_source_and_exposes_textual_status(monkeypatch: object) -> None:
    rendered: list[str] = []

    def capture(body: str, *, unsafe_allow_html: bool) -> None:
        assert unsafe_allow_html is True
        rendered.append(body)

    monkeypatch.setattr(ui.st, "markdown", capture)  # type: ignore[attr-defined]

    ui.render_trust_ribbon(
        assess_dataset(load_demo_data()),
        source='<script>alert("source")</script>.csv',
    )

    html = rendered[0]
    assert 'aria-labelledby="pulse-trust-title"' in html
    assert "Workspace trust" in html
    assert "warning" in html.lower()
    assert "&lt;script&gt;" in html
    assert "<script>" not in html


def test_workflow_steps_escape_content_and_reject_unknown_tones(monkeypatch: object) -> None:
    rendered: list[str] = []

    def capture(body: str, *, unsafe_allow_html: bool) -> None:
        assert unsafe_allow_html is True
        rendered.append(body)

    monkeypatch.setattr(ui.st, "markdown", capture)  # type: ignore[attr-defined]

    ui.render_workflow_steps(
        "Evidence <intake>",
        "Needs review",
        (("Upload source", "<script>unsafe</script>", "is-current"),),
    )

    html = rendered[0]
    assert 'aria-labelledby="pulse-workflow-title"' in html
    assert "Evidence &lt;intake&gt;" in html
    assert "&lt;script&gt;unsafe&lt;/script&gt;" in html
    assert "<script>" not in html

    with pytest.raises(ValueError, match="supported status tone"):
        ui.render_workflow_steps("Evidence intake", "Unsafe", (("Source", "Bad tone", "is-injected"),))
