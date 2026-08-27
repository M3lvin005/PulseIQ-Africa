"""Acceptance tests for the public dataset assessment seam."""

from __future__ import annotations

import pandas as pd

from pulseiq.datasets import DatasetCapability, IssueSeverity, QualityDimension, assess_dataset


def test_empty_dataset_is_blocked_with_zero_quality() -> None:
    """REQ-QUAL-005: empty data cannot appear healthy or usable."""

    assessment = assess_dataset(pd.DataFrame())

    assert assessment.composite_score == 0.0
    assert assessment.is_blocked
    assert not assessment.can(DatasetCapability.QUALITY_REVIEW)
    assert any(issue.code == "empty_dataset" and issue.severity is IssueSeverity.BLOCK for issue in assessment.issues)


def test_missing_transaction_amount_blocks_only_dependent_analytics() -> None:
    """REQ-DATA-006: a missing critical field blocks dependent analysis."""

    dataframe = pd.DataFrame(
        {
            "customer_id": ["CUST-1", "CUST-2"],
            "date": ["2026-01-01", "2026-01-02"],
            "defaulted": [0, 1],
        }
    )

    assessment = assess_dataset(dataframe)

    assert assessment.can(DatasetCapability.QUALITY_REVIEW)
    assert assessment.can(DatasetCapability.CUSTOMER_ANALYTICS)
    assert assessment.can(DatasetCapability.REPAYMENT_ANALYTICS)
    assert not assessment.can(DatasetCapability.TRANSACTION_ANALYTICS)
    assert any(
        issue.code == "missing_transaction_amount"
        and issue.affected_capabilities == (DatasetCapability.TRANSACTION_ANALYTICS,)
        for issue in assessment.issues
    )


def test_unparseable_transaction_amount_is_not_treated_as_zero() -> None:
    """REQ-DATA-006: invalid critical values cannot be silently substituted."""

    dataframe = pd.DataFrame(
        {
            "customer_id": ["CUST-1", "CUST-2"],
            "date": ["2026-01-01", "2026-01-02"],
            "transaction_amount": ["unknown", "not-a-number"],
            "defaulted": [0, 1],
        }
    )

    assessment = assess_dataset(dataframe)

    assert not assessment.can(DatasetCapability.TRANSACTION_ANALYTICS)
    assert any(
        issue.code == "unparseable_transaction_amount" and issue.severity is IssueSeverity.BLOCK and issue.count == 2
        for issue in assessment.issues
    )


def test_partially_invalid_amounts_warn_and_lower_validity() -> None:
    """Invalid rows stay visible instead of being median-imputed into health."""

    dataframe = pd.DataFrame(
        {
            "customer_id": ["CUST-1", "CUST-2"],
            "date": ["2026-01-01", "2026-01-02"],
            "transaction_amount": [1200, "unknown"],
            "defaulted": [0, 1],
        }
    )

    assessment = assess_dataset(dataframe)

    assert assessment.can(DatasetCapability.TRANSACTION_ANALYTICS)
    assert assessment.score_for(QualityDimension.VALIDITY) < 100.0
    assert assessment.composite_score < 100.0
    assert any(
        issue.code == "invalid_transaction_amount" and issue.severity is IssueSeverity.WARN and issue.count == 1
        for issue in assessment.issues
    )


def test_missing_event_date_blocks_transaction_analytics() -> None:
    """Time-based transaction analysis requires explicit event-time semantics."""

    dataframe = pd.DataFrame(
        {
            "customer_id": ["CUST-1"],
            "transaction_amount": [1200],
            "defaulted": [0],
        }
    )

    assessment = assess_dataset(dataframe)

    assert not assessment.can(DatasetCapability.TRANSACTION_ANALYTICS)
    assert any(
        issue.code == "missing_event_date" and issue.affected_capabilities == (DatasetCapability.TRANSACTION_ANALYTICS,)
        for issue in assessment.issues
    )


def test_missing_customer_identifier_blocks_customer_analytics() -> None:
    """Distinct-customer metrics require an explicit business identifier."""

    dataframe = pd.DataFrame(
        {
            "date": ["2026-01-01"],
            "transaction_amount": [1200],
            "defaulted": [0],
        }
    )

    assessment = assess_dataset(dataframe)

    assert assessment.can(DatasetCapability.TRANSACTION_ANALYTICS)
    assert not assessment.can(DatasetCapability.CUSTOMER_ANALYTICS)
    assert any(issue.code == "missing_customer_id" for issue in assessment.issues)


def test_missing_repayment_outcome_blocks_repayment_analytics() -> None:
    """Repayment results cannot be inferred from unrelated columns."""

    dataframe = pd.DataFrame(
        {
            "customer_id": ["CUST-1"],
            "date": ["2026-01-01"],
            "transaction_amount": [1200],
        }
    )

    assessment = assess_dataset(dataframe)

    assert not assessment.can(DatasetCapability.REPAYMENT_ANALYTICS)
    assert any(issue.code == "missing_repayment_outcome" for issue in assessment.issues)


def test_missing_model_features_blocks_model_exploration() -> None:
    """Model inputs cannot be replaced by generic healthy-person defaults."""

    dataframe = pd.DataFrame(
        {
            "customer_id": ["CUST-1"],
            "date": ["2026-01-01"],
            "transaction_amount": [1200],
            "defaulted": [0],
        }
    )

    assessment = assess_dataset(dataframe)

    assert not assessment.can(DatasetCapability.MODEL_EXPLORATION)
    assert any(
        issue.code == "missing_model_inputs" and issue.affected_capabilities == (DatasetCapability.MODEL_EXPLORATION,)
        for issue in assessment.issues
    )


def test_missing_values_are_visible_and_lower_completeness() -> None:
    """REQ-QUAL-001: completeness has its own score and actionable issue."""

    dataframe = pd.DataFrame(
        {
            "customer_id": ["CUST-1", "CUST-2"],
            "date": ["2026-01-01", "2026-01-02"],
            "transaction_amount": [1200, 800],
            "defaulted": [0, 1],
            "income": [150_000, None],
            "loan_amount": [50_000, 90_000],
            "repayment_history_score": [80, 45],
            "existing_debt": [10_000, 30_000],
            "transaction_frequency": [12, 9],
            "account_age_months": [24, 8],
            "employment_status": ["Salaried", "Self-employed"],
            "segment": ["Retail", "SME"],
            "business_type": ["Shop", "Transport"],
            "region": ["Lagos", "Abuja"],
        }
    )

    assessment = assess_dataset(dataframe)

    assert assessment.score_for(QualityDimension.COMPLETENESS) < 100.0
    assert any(
        issue.code == "missing_values" and issue.severity is IssueSeverity.WARN and issue.count == 1
        for issue in assessment.issues
    )


def test_duplicate_rows_are_visible_and_lower_uniqueness() -> None:
    """REQ-QUAL-001: duplicate rows have a separate uniqueness result."""

    dataframe = pd.DataFrame(
        {
            "customer_id": ["CUST-1", "CUST-1"],
            "date": ["2026-01-01", "2026-01-01"],
            "transaction_amount": [1200, 1200],
            "defaulted": [0, 0],
        }
    )

    assessment = assess_dataset(dataframe)

    assert assessment.score_for(QualityDimension.UNIQUENESS) == 50.0
    assert any(
        issue.code == "duplicate_rows" and issue.severity is IssueSeverity.WARN and issue.count == 1
        for issue in assessment.issues
    )


def test_missing_risk_rule_inputs_blocks_rule_evaluation() -> None:
    """Rule evaluation cannot median-impute missing evidence into normality."""

    dataframe = pd.DataFrame(
        {
            "customer_id": ["CUST-1"],
            "date": ["2026-01-01"],
            "transaction_amount": [1200],
            "defaulted": [0],
        }
    )

    assessment = assess_dataset(dataframe)

    assert not assessment.can(DatasetCapability.RISK_RULE_EVALUATION)
    assert any(
        issue.code == "missing_risk_rule_inputs"
        and issue.affected_capabilities == (DatasetCapability.RISK_RULE_EVALUATION,)
        for issue in assessment.issues
    )
