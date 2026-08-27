"""Model dataset eligibility contract tests."""

from __future__ import annotations

import pandas as pd

from pulseiq.modeling import EligibilityStatus, ModelEligibilityPolicy, assess_model_eligibility

FEATURES = {
    "income": [100_000, 120_000, 140_000, 160_000],
    "loan_amount": [20_000, 30_000, 40_000, 50_000],
    "repayment_history_score": [80, 70, 60, 50],
    "existing_debt": [10_000, 20_000, 30_000, 40_000],
    "transaction_frequency": [10, 12, 14, 16],
    "account_age_months": [12, 24, 36, 48],
    "employment_status": ["Salaried", "Salaried", "Informal", "Contract"],
    "segment": ["Retail", "SME", "Retail", "SME"],
    "business_type": ["Shop", "Food", "Health", "Transport"],
    "region": ["Lagos", "Abuja", "Kano", "Lagos"],
}


def _frame(**extra: object) -> pd.DataFrame:
    return pd.DataFrame({**FEATURES, **extra})


def test_model_eligibility_never_derives_a_target() -> None:
    result = assess_model_eligibility(_frame(), policy=ModelEligibilityPolicy(min_rows=2, min_class_rows=1))

    assert result.status is EligibilityStatus.BLOCKED
    assert "missing_target" in result.blocking_issue_codes
    assert result.target_definition is None


def test_invalid_target_rows_are_excluded_and_single_class_blocks_training() -> None:
    dataframe = _frame(defaulted=[0, 0, "unknown", None])

    result = assess_model_eligibility(
        dataframe,
        policy=ModelEligibilityPolicy(min_rows=2, min_class_rows=1, max_feature_missing_rate=0.75),
    )

    assert result.status is EligibilityStatus.BLOCKED
    assert result.eligible_rows == 2
    assert result.excluded_target_rows == 2
    assert result.class_counts == ((0, 2),)
    assert "single_target_class" in result.blocking_issue_codes


def test_explicit_repayment_status_uses_a_versioned_allowlist() -> None:
    dataframe = _frame(repayment_status=["Repaid", "Defaulted", "late", "mystery"])

    result = assess_model_eligibility(dataframe, policy=ModelEligibilityPolicy(min_rows=2, min_class_rows=1))

    assert result.status is EligibilityStatus.ELIGIBLE
    assert result.eligible_rows == 2
    assert result.excluded_target_rows == 2
    assert result.target_definition == "repayment_status.binary/1.0.0"
    assert "unmapped_target_values" in result.warning_issue_codes


def test_feature_profiles_expose_missing_invalid_and_cardinality_evidence() -> None:
    dataframe = _frame(defaulted=[0, 1, 0, 1])
    dataframe["income"] = dataframe["income"].astype(object)
    dataframe.loc[1, "income"] = None
    dataframe.loc[2, "income"] = "invalid"

    result = assess_model_eligibility(
        dataframe,
        policy=ModelEligibilityPolicy(min_rows=2, min_class_rows=1, max_feature_missing_rate=0.75),
    )
    income = result.profile("income")

    assert result.status is EligibilityStatus.ELIGIBLE
    assert income.missing_count == 1
    assert income.invalid_count == 1
    assert income.valid_count == 2
