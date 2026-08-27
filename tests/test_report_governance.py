"""Accessible report provenance tests."""

from __future__ import annotations

import pandas as pd

from pulseiq.anomaly import RULESET_VERSION, detect_anomalies
from pulseiq.portfolio_metrics import calculate_portfolio_metrics
from pulseiq.report import build_report_html


def test_html_report_preserves_unavailable_metrics_and_provenance() -> None:
    """REQ-RPT-001/003: HTML is accessible and never converts unavailable to zero."""

    metrics = calculate_portfolio_metrics(
        pd.DataFrame({"customer_id": ["CUST-1"], "date": ["2026-01-01"]}),
        currency="NGN",
    )

    report = build_report_html(metrics, ["Review source mappings."])

    assert '<html lang="en">' in report
    assert "<caption>Governed metric summary</caption>" in report
    assert "Total transaction value" in report
    assert "Not available" in report
    assert "dataframe:sha256:" in report
    assert "Total revenue" not in report
    assert "Repayment rate" not in report


def test_html_report_discloses_partial_rule_coverage() -> None:
    dataframe = pd.DataFrame(
        {
            "transaction_id": ["TX-1", "TX-2"],
            "transaction_amount": [1200, None],
            "income": [100_000, 100_000],
            "loan_amount": [50_000, None],
            "existing_debt": [10_000, 10_000],
            "repayment_history_score": [80, 80],
            "transaction_frequency": [12, 12],
        }
    )
    anomalies = detect_anomalies(dataframe)
    metrics = calculate_portfolio_metrics(
        dataframe,
        anomaly_dataframe=anomalies,
        risk_rule_version=RULESET_VERSION,
    )

    report = build_report_html(metrics, [], anomalies)

    assert "Rule evidence coverage" in report
    assert "Not evaluated" in report
    assert "A not-evaluated result is not a clear result" in report
