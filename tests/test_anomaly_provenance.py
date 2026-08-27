"""Risk-rule provenance regression tests."""

from __future__ import annotations

import pandas as pd

from pulseiq.anomaly import (
    RULESET_VERSION,
    RuleStatus,
    detect_anomalies,
    rule_coverage,
)


def test_rule_evaluation_stamps_every_result_with_ruleset_version() -> None:
    """Every risk output identifies the exact prototype rule definition."""

    dataframe = pd.DataFrame(
        {
            "transaction_amount": [1200],
            "income": [100_000],
            "loan_amount": [50_000],
            "existing_debt": [10_000],
            "repayment_history_score": [80],
            "transaction_frequency": [12],
        }
    )

    result = detect_anomalies(dataframe)

    assert result["rule_version"].tolist() == [RULESET_VERSION]


def test_missing_row_evidence_is_not_median_imputed_into_rule_results() -> None:
    """Each rule identifies rows it could not evaluate instead of inventing evidence."""

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

    result = detect_anomalies(dataframe)

    assert result.loc[1, "rule_unusually_high_amount_status"] == RuleStatus.NOT_EVALUATED
    assert result.loc[1, "rule_spending_spike_status"] == RuleStatus.NOT_EVALUATED
    assert result.loc[1, "rule_loan_to_income_status"] == RuleStatus.NOT_EVALUATED
    assert result.loc[1, "rule_repayment_pattern_status"] == RuleStatus.CLEAR
    assert result.loc[1, "rules_not_evaluated_count"] == 3
    assert "unusually_high_amount" in result.loc[1, "not_evaluated_rule_ids"]
    assert "loan_to_income" in result.loc[1, "not_evaluated_rule_ids"]


def test_rule_coverage_reports_evaluated_not_evaluated_and_triggered_counts() -> None:
    dataframe = pd.DataFrame(
        {
            "transaction_id": ["TX-1", "TX-2"],
            "transaction_amount": [1200, None],
            "income": [100_000, 100_000],
            "loan_amount": [50_000, None],
            "existing_debt": [10_000, 10_000],
            "repayment_history_score": [80, 20],
            "transaction_frequency": [12, 12],
        }
    )

    coverage = rule_coverage(detect_anomalies(dataframe)).set_index("rule_id")

    assert coverage.loc["unusually_high_amount", "evaluated_records"] == 1
    assert coverage.loc["unusually_high_amount", "not_evaluated_records"] == 1
    assert coverage.loc["unusually_high_amount", "coverage_percent"] == 50.0
    assert coverage.loc["repayment_pattern", "triggered_records"] == 1
    assert coverage.loc["repayment_pattern", "coverage_percent"] == 100.0
