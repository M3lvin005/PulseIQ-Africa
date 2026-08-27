"""Governed narrative insight tests."""

from __future__ import annotations

import pandas as pd

from pulseiq.portfolio_metrics import build_metric_insights, calculate_portfolio_metrics


def test_insights_preserve_unavailable_transaction_and_rule_states() -> None:
    """Narrative text cannot reinterpret missing evidence as healthy zero activity."""

    metrics = calculate_portfolio_metrics(pd.DataFrame({"customer_id": ["CUST-1"]}))

    insights = build_metric_insights(metrics)
    combined = " ".join(insights).lower()

    assert "transaction value is unavailable" in combined
    assert "suspicious records (rules) is unavailable" in combined
    assert "no suspicious records" not in combined
