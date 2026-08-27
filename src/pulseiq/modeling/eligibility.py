"""Dataset fitness checks and strict outcome mapping for model exploration."""

from __future__ import annotations

import pandas as pd

from .contracts import (
    EligibilitySeverity,
    EligibilityStatus,
    FeatureProfile,
    ModelEligibility,
    ModelEligibilityIssue,
    ModelEligibilityPolicy,
)

NUMERIC_FEATURES = (
    "income",
    "loan_amount",
    "repayment_history_score",
    "existing_debt",
    "transaction_frequency",
    "account_age_months",
)
CATEGORICAL_FEATURES = ("employment_status", "segment", "business_type", "region")
FEATURE_COLUMNS = NUMERIC_FEATURES + CATEGORICAL_FEATURES
DEFAULT_MODEL_ELIGIBILITY_POLICY = ModelEligibilityPolicy()
_REPAYMENT_STATUS_MAP = {
    "repaid": 0,
    "paid": 0,
    "current": 0,
    "non-default": 0,
    "non default": 0,
    "defaulted": 1,
    "default": 1,
    "charged off": 1,
    "written off": 1,
}


def map_model_target(dataframe: pd.DataFrame) -> tuple[pd.Series, str | None, str | None]:
    """Map only explicit allowlisted outcomes; unknown values remain missing."""

    if "defaulted" in dataframe.columns:
        numeric = pd.to_numeric(dataframe["defaulted"], errors="coerce")
        target = numeric.where(numeric.isin([0, 1])).astype("Int64")
        if target.notna().any():
            return target, "defaulted", "defaulted.binary/1.0.0"
    if "repayment_status" in dataframe.columns:
        normalized = dataframe["repayment_status"].astype("string").str.strip().str.lower()
        target = normalized.map(_REPAYMENT_STATUS_MAP).astype("Int64")
        if target.notna().any():
            return target, "repayment_status", "repayment_status.binary/1.0.0"
    return pd.Series(pd.NA, index=dataframe.index, dtype="Int64"), None, None


def assess_model_eligibility(
    dataframe: pd.DataFrame,
    *,
    policy: ModelEligibilityPolicy = DEFAULT_MODEL_ELIGIBILITY_POLICY,
) -> ModelEligibility:
    """Return target, feature, sample, class, and resource eligibility evidence."""

    issues: list[ModelEligibilityIssue] = []
    missing_features = [column for column in FEATURE_COLUMNS if column not in dataframe.columns]
    if missing_features:
        issues.append(
            ModelEligibilityIssue(
                code="missing_features",
                severity=EligibilitySeverity.BLOCK,
                message=f"Required model features are missing: {', '.join(missing_features)}.",
                recovery="Map every required feature and confirm its meaning before training.",
                count=len(missing_features),
            )
        )

    target, target_column, target_definition = map_model_target(dataframe)
    if target_definition is None:
        issues.append(
            ModelEligibilityIssue(
                code="missing_target",
                severity=EligibilitySeverity.BLOCK,
                message="No explicit allowlisted binary outcome is available.",
                recovery="Map an authoritative defaulted or repayment_status outcome; derived targets are prohibited.",
            )
        )

    eligible_mask = target.notna()
    eligible_rows = int(eligible_mask.sum())
    excluded_target_rows = len(dataframe) - eligible_rows
    if excluded_target_rows and target_definition is not None:
        issues.append(
            ModelEligibilityIssue(
                code="unmapped_target_values",
                severity=EligibilitySeverity.WARN,
                message="Some outcome values are missing or outside the approved target mapping.",
                recovery="Correct or explicitly map those outcomes; excluded rows are not used for training.",
                column=target_column,
                count=excluded_target_rows,
            )
        )

    class_counts = tuple(
        (label, int(target.loc[eligible_mask].eq(label).sum()))
        for label in (0, 1)
        if target.loc[eligible_mask].eq(label).any()
    )
    if eligible_rows and len(class_counts) < 2:
        issues.append(
            ModelEligibilityIssue(
                code="single_target_class",
                severity=EligibilitySeverity.BLOCK,
                message="The eligible target contains only one outcome class.",
                recovery=(
                    "Provide authoritative examples from both outcome classes; a synthetic target will not be created."
                ),
            )
        )
    if eligible_rows < policy.min_rows:
        issues.append(
            ModelEligibilityIssue(
                code="insufficient_rows",
                severity=EligibilitySeverity.BLOCK,
                message=(
                    f"Only {eligible_rows:,} eligible rows are available; this prototype requires {policy.min_rows:,}."
                ),
                recovery=(
                    "Provide a larger representative dataset and independently justify the production sample threshold."
                ),
                count=eligible_rows,
            )
        )
    if len(class_counts) == 2 and min(count for _, count in class_counts) < policy.min_class_rows:
        issues.append(
            ModelEligibilityIssue(
                code="insufficient_class_rows",
                severity=EligibilitySeverity.BLOCK,
                message=f"The minority class has fewer than {policy.min_class_rows:,} eligible rows.",
                recovery="Collect more authoritative minority outcomes before model exploration.",
            )
        )

    profiles: list[FeatureProfile] = []
    eligible_data = dataframe.loc[eligible_mask]
    for column in FEATURE_COLUMNS:
        if column not in dataframe.columns:
            continue
        source = eligible_data[column]
        missing_count = int(source.isna().sum())
        if column in NUMERIC_FEATURES:
            numeric = pd.to_numeric(source, errors="coerce")
            invalid_count = int((source.notna() & numeric.isna()).sum())
            valid_count = int(numeric.notna().sum())
            unique_count = int(numeric.nunique(dropna=True))
            kind = "numeric"
        else:
            normalized = source.astype("string").str.strip()
            invalid_count = int((source.notna() & normalized.eq("")).sum())
            valid_count = int((normalized.notna() & normalized.ne("")).sum())
            unique_count = int(normalized[normalized.ne("")].nunique(dropna=True))
            kind = "categorical"
        profiles.append(
            FeatureProfile(
                column=column,
                kind=kind,
                valid_count=valid_count,
                missing_count=missing_count,
                invalid_count=invalid_count,
                unique_count=unique_count,
            )
        )
        unavailable_rate = (missing_count + invalid_count) / eligible_rows if eligible_rows else 1.0
        if unavailable_rate > policy.max_feature_missing_rate:
            issues.append(
                ModelEligibilityIssue(
                    code="excessive_feature_missingness",
                    severity=EligibilitySeverity.BLOCK,
                    message=f"{column} has {unavailable_rate:.1%} missing or invalid eligible values.",
                    recovery="Correct the feature or exclude it through a reviewed feature-definition change.",
                    column=column,
                    count=missing_count + invalid_count,
                )
            )
        if column in CATEGORICAL_FEATURES and unique_count > policy.max_category_cardinality:
            issues.append(
                ModelEligibilityIssue(
                    code="excessive_category_cardinality",
                    severity=EligibilitySeverity.BLOCK,
                    message=f"{column} has {unique_count:,} categories, above the prototype safety limit.",
                    recovery="Review semantic mapping and use a governed category treatment before training.",
                    column=column,
                    count=unique_count,
                )
            )

    status = (
        EligibilityStatus.BLOCKED
        if any(issue.severity is EligibilitySeverity.BLOCK for issue in issues)
        else EligibilityStatus.ELIGIBLE
    )
    return ModelEligibility(
        status=status,
        total_rows=len(dataframe),
        eligible_rows=eligible_rows,
        excluded_target_rows=excluded_target_rows,
        class_counts=class_counts,
        target_column=target_column,
        target_definition=target_definition,
        profiles=tuple(profiles),
        issues=tuple(issues),
    )
