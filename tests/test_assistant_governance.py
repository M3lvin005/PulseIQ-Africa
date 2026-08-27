"""Governed assistant response tests."""

from __future__ import annotations

import pandas as pd

from pulseiq.anomaly import RULESET_VERSION, detect_anomalies
from pulseiq.assistant import answer_question
from pulseiq.portfolio_metrics import calculate_portfolio_metrics


def test_assistant_explains_unavailable_transaction_value_instead_of_zero() -> None:
    """Assistant answers inherit KPI availability and recovery semantics."""

    dataframe = pd.DataFrame({"customer_id": ["CUST-1"], "date": ["2026-01-01"]})
    metrics = calculate_portfolio_metrics(dataframe, currency="NGN")

    answer = answer_question("What is the revenue picture?", dataframe, metrics, pd.DataFrame())

    assert "unavailable" in answer.lower()
    assert "map" in answer.lower()
    assert "NGN 0" not in answer


def test_assistant_discloses_partial_rule_coverage() -> None:
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

    answer = answer_question("Why was this transaction flagged?", dataframe, metrics, anomalies)

    assert "coverage caveat" in answer.lower()
    assert "not evaluated" in answer.lower()
