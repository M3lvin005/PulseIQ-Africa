"""Dataset assessment application service."""

from __future__ import annotations

import pandas as pd

from .contracts import (
    AssessmentStatus,
    CapabilityAssessment,
    DatasetAssessment,
    DatasetCapability,
    IssueSeverity,
    QualityDimension,
    QualityDimensionScore,
    ValidationIssue,
)

_DEFINITION_VERSION = "dataset-quality/1.0.0"
_DIMENSION_WEIGHTS = {
    QualityDimension.COMPLETENESS: 0.25,
    QualityDimension.VALIDITY: 0.20,
    QualityDimension.UNIQUENESS: 0.15,
    QualityDimension.CONSISTENCY: 0.15,
    QualityDimension.TIMELINESS: 0.10,
    QualityDimension.FITNESS: 0.15,
}
_NUMERIC_COLUMNS = (
    "transaction_amount",
    "income",
    "loan_amount",
    "existing_debt",
    "transaction_frequency",
    "account_age_months",
    "repayment_history_score",
    "defaulted",
    "risk_score",
)
_MODEL_FEATURE_COLUMNS = (
    "income",
    "loan_amount",
    "repayment_history_score",
    "existing_debt",
    "transaction_frequency",
    "account_age_months",
    "employment_status",
    "segment",
    "business_type",
    "region",
)
_RISK_RULE_INPUT_COLUMNS = (
    "transaction_amount",
    "income",
    "loan_amount",
    "existing_debt",
    "repayment_history_score",
    "transaction_frequency",
)


def assess_dataset(dataframe: pd.DataFrame) -> DatasetAssessment:
    """Assess whether a dataframe is fit for each supported operation.

    This initial adapter exposes the new contract over the legacy score. Its
    permissive behavior is intentionally captured by the first red test.
    """

    rows, columns = dataframe.shape
    if dataframe.empty:
        issue = ValidationIssue(
            code="empty_dataset",
            severity=IssueSeverity.BLOCK,
            dimension=QualityDimension.FITNESS,
            message="The dataset contains no data rows.",
            recovery="Upload a CSV with a header row and at least one data row.",
            affected_capabilities=tuple(DatasetCapability),
        )
        return DatasetAssessment(
            rows=int(rows),
            columns=int(columns),
            composite_score=0.0,
            dimensions=tuple(QualityDimensionScore(dimension=dimension, score=0.0) for dimension in QualityDimension),
            issues=(issue,),
            capabilities=tuple(
                CapabilityAssessment(
                    capability=capability,
                    status=AssessmentStatus.BLOCKED,
                    blocking_issue_codes=(issue.code,),
                )
                for capability in DatasetCapability
            ),
            definition_version=_DEFINITION_VERSION,
        )

    issues: list[ValidationIssue] = []
    missing_values = int(dataframe.isna().sum().sum())
    if missing_values:
        issues.append(
            ValidationIssue(
                code="missing_values",
                severity=IssueSeverity.WARN,
                dimension=QualityDimension.COMPLETENESS,
                count=missing_values,
                message="The dataset contains missing values that may reduce downstream coverage.",
                recovery="Review missingness by column and either correct, exclude, or document each treatment.",
                affected_capabilities=tuple(DatasetCapability),
            )
        )
    duplicate_rows = int(dataframe.duplicated().sum())
    if duplicate_rows:
        issues.append(
            ValidationIssue(
                code="duplicate_rows",
                severity=IssueSeverity.WARN,
                dimension=QualityDimension.UNIQUENESS,
                count=duplicate_rows,
                message="The dataset contains exact duplicate rows.",
                recovery="Confirm the authoritative business key and remove unintended duplicates.",
                affected_capabilities=tuple(DatasetCapability),
                override_allowed=True,
            )
        )

    if "transaction_amount" not in dataframe.columns:
        issues.append(
            ValidationIssue(
                code="missing_transaction_amount",
                severity=IssueSeverity.BLOCK,
                dimension=QualityDimension.FITNESS,
                column="transaction_amount",
                message="Transaction analytics requires a mapped transaction amount column.",
                recovery="Map a numeric amount column to transaction_amount and validate its unit and currency.",
                affected_capabilities=(DatasetCapability.TRANSACTION_ANALYTICS,),
            )
        )
    else:
        transaction_amount = pd.to_numeric(dataframe["transaction_amount"], errors="coerce")
        invalid_amounts = dataframe["transaction_amount"].notna() & transaction_amount.isna()
        if not transaction_amount.notna().any():
            issues.append(
                ValidationIssue(
                    code="unparseable_transaction_amount",
                    severity=IssueSeverity.BLOCK,
                    dimension=QualityDimension.VALIDITY,
                    column="transaction_amount",
                    count=int(invalid_amounts.sum()),
                    message="Transaction amount contains no parseable numeric values.",
                    recovery="Remove non-numeric symbols or map a numeric amount column, then validate again.",
                    affected_capabilities=(DatasetCapability.TRANSACTION_ANALYTICS,),
                )
            )
        elif invalid_amounts.any():
            issues.append(
                ValidationIssue(
                    code="invalid_transaction_amount",
                    severity=IssueSeverity.WARN,
                    dimension=QualityDimension.VALIDITY,
                    column="transaction_amount",
                    count=int(invalid_amounts.sum()),
                    message="Some transaction amounts cannot be parsed as numbers and are excluded from aggregates.",
                    recovery="Correct or remove the invalid amount values, then validate again.",
                    affected_capabilities=(DatasetCapability.TRANSACTION_ANALYTICS,),
                )
            )

    if "date" not in dataframe.columns:
        issues.append(
            ValidationIssue(
                code="missing_event_date",
                severity=IssueSeverity.BLOCK,
                dimension=QualityDimension.FITNESS,
                column="date",
                message="Time-based transaction analytics requires a mapped event date.",
                recovery="Map the transaction event date and confirm its timezone and period semantics.",
                affected_capabilities=(DatasetCapability.TRANSACTION_ANALYTICS,),
            )
        )
    else:
        event_dates = pd.to_datetime(dataframe["date"], errors="coerce", format="mixed")
        invalid_dates = dataframe["date"].notna() & event_dates.isna()
        if not event_dates.notna().any():
            issues.append(
                ValidationIssue(
                    code="unparseable_event_date",
                    severity=IssueSeverity.BLOCK,
                    dimension=QualityDimension.VALIDITY,
                    column="date",
                    count=int(invalid_dates.sum()),
                    message="The event date contains no parseable date values.",
                    recovery="Convert event dates to an unambiguous date format, then validate again.",
                    affected_capabilities=(DatasetCapability.TRANSACTION_ANALYTICS,),
                )
            )
        elif invalid_dates.any():
            issues.append(
                ValidationIssue(
                    code="invalid_event_date",
                    severity=IssueSeverity.WARN,
                    dimension=QualityDimension.VALIDITY,
                    column="date",
                    count=int(invalid_dates.sum()),
                    message="Some event dates cannot be parsed and are excluded from time-based analysis.",
                    recovery="Correct or remove invalid event dates, then validate again.",
                    affected_capabilities=(DatasetCapability.TRANSACTION_ANALYTICS,),
                )
            )

    if "customer_id" not in dataframe.columns:
        issues.append(
            ValidationIssue(
                code="missing_customer_id",
                severity=IssueSeverity.BLOCK,
                dimension=QualityDimension.FITNESS,
                column="customer_id",
                message="Customer analytics requires a mapped customer business identifier.",
                recovery="Map a stable customer identifier and confirm its uniqueness semantics.",
                affected_capabilities=(DatasetCapability.CUSTOMER_ANALYTICS,),
            )
        )
    else:
        customer_ids = dataframe["customer_id"].astype("string").str.strip()
        present_customer_ids = customer_ids.notna() & customer_ids.ne("")
        if not present_customer_ids.any():
            issues.append(
                ValidationIssue(
                    code="empty_customer_id",
                    severity=IssueSeverity.BLOCK,
                    dimension=QualityDimension.COMPLETENESS,
                    column="customer_id",
                    count=len(dataframe),
                    message="The customer identifier contains no usable values.",
                    recovery="Populate stable customer identifiers, then validate again.",
                    affected_capabilities=(DatasetCapability.CUSTOMER_ANALYTICS,),
                )
            )
        elif not present_customer_ids.all():
            issues.append(
                ValidationIssue(
                    code="missing_customer_ids",
                    severity=IssueSeverity.WARN,
                    dimension=QualityDimension.COMPLETENESS,
                    column="customer_id",
                    count=int((~present_customer_ids).sum()),
                    message="Some records have no usable customer identifier and are excluded from customer metrics.",
                    recovery="Populate missing customer identifiers or document why those rows are excluded.",
                    affected_capabilities=(DatasetCapability.CUSTOMER_ANALYTICS,),
                )
            )

    has_repayment_outcome = False
    if "defaulted" in dataframe.columns:
        defaulted = pd.to_numeric(dataframe["defaulted"], errors="coerce")
        valid_defaulted = defaulted.isin([0, 1])
        has_repayment_outcome = bool(valid_defaulted.any())
    if "repayment_status" in dataframe.columns:
        repayment_status = dataframe["repayment_status"].astype("string").str.strip()
        has_repayment_outcome = has_repayment_outcome or bool(
            (repayment_status.notna() & repayment_status.ne("")).any()
        )
    if not has_repayment_outcome:
        issues.append(
            ValidationIssue(
                code="missing_repayment_outcome",
                severity=IssueSeverity.BLOCK,
                dimension=QualityDimension.FITNESS,
                message="Repayment analytics requires an explicit repayment outcome field.",
                recovery="Map defaulted or repayment_status to an authoritative outcome definition.",
                affected_capabilities=(DatasetCapability.REPAYMENT_ANALYTICS,),
            )
        )

    missing_model_inputs = tuple(column for column in _MODEL_FEATURE_COLUMNS if column not in dataframe.columns)
    if missing_model_inputs:
        issues.append(
            ValidationIssue(
                code="missing_model_inputs",
                severity=IssueSeverity.BLOCK,
                dimension=QualityDimension.FITNESS,
                count=len(missing_model_inputs),
                message=f"Model exploration is missing required inputs: {', '.join(missing_model_inputs)}.",
                recovery="Map every required model feature and validate its meaning before training.",
                affected_capabilities=(DatasetCapability.MODEL_EXPLORATION,),
            )
        )
    if "defaulted" not in dataframe.columns and "repayment_status" not in dataframe.columns:
        issues.append(
            ValidationIssue(
                code="missing_model_target",
                severity=IssueSeverity.BLOCK,
                dimension=QualityDimension.FITNESS,
                message="Model exploration requires an explicit, authoritative outcome target.",
                recovery=(
                    "Map an approved defaulted or repayment_status outcome; "
                    "derived demonstration targets are not eligible."
                ),
                affected_capabilities=(DatasetCapability.MODEL_EXPLORATION,),
            )
        )

    missing_risk_inputs = tuple(column for column in _RISK_RULE_INPUT_COLUMNS if column not in dataframe.columns)
    if missing_risk_inputs:
        issues.append(
            ValidationIssue(
                code="missing_risk_rule_inputs",
                severity=IssueSeverity.BLOCK,
                dimension=QualityDimension.FITNESS,
                count=len(missing_risk_inputs),
                message=f"Risk-rule evaluation is missing required inputs: {', '.join(missing_risk_inputs)}.",
                recovery="Map every required rule input before evaluating suspicious activity.",
                affected_capabilities=(DatasetCapability.RISK_RULE_EVALUATION,),
            )
        )

    capabilities = tuple(
        CapabilityAssessment(
            capability=capability,
            status=(
                AssessmentStatus.BLOCKED
                if any(
                    issue.severity is IssueSeverity.BLOCK and capability in issue.affected_capabilities
                    for issue in issues
                )
                else AssessmentStatus.READY
            ),
            blocking_issue_codes=tuple(
                issue.code
                for issue in issues
                if issue.severity is IssueSeverity.BLOCK and capability in issue.affected_capabilities
            ),
        )
        for capability in DatasetCapability
    )
    dimensions = _score_dimensions(dataframe, capabilities)
    composite_score = round(
        sum(item.score * _DIMENSION_WEIGHTS[item.dimension] for item in dimensions),
        1,
    )
    return DatasetAssessment(
        rows=int(rows),
        columns=int(columns),
        composite_score=composite_score,
        dimensions=dimensions,
        issues=tuple(issues),
        capabilities=capabilities,
        definition_version=_DEFINITION_VERSION,
    )


def _score_dimensions(
    dataframe: pd.DataFrame,
    capabilities: tuple[CapabilityAssessment, ...],
) -> tuple[QualityDimensionScore, ...]:
    """Calculate separately visible quality dimensions for a non-empty dataframe."""

    rows, columns = dataframe.shape
    total_cells = rows * columns
    completeness = 100.0 if total_cells == 0 else (1.0 - dataframe.isna().sum().sum() / total_cells) * 100.0
    uniqueness = (1.0 - dataframe.duplicated().sum() / rows) * 100.0

    governed_values = 0
    invalid_values = 0
    for column in _NUMERIC_COLUMNS:
        if column not in dataframe.columns:
            continue
        present = dataframe[column].notna()
        parsed = pd.to_numeric(dataframe[column], errors="coerce")
        governed_values += int(present.sum())
        invalid_values += int((present & parsed.isna()).sum())
    if "date" in dataframe.columns:
        present_dates = dataframe["date"].notna()
        parsed_dates = pd.to_datetime(dataframe["date"], errors="coerce", format="mixed")
        governed_values += int(present_dates.sum())
        invalid_values += int((present_dates & parsed_dates.isna()).sum())
        timeliness = float(parsed_dates.notna().mean() * 100.0)
    else:
        timeliness = 0.0
    validity = 100.0 if governed_values == 0 else (1.0 - invalid_values / governed_values) * 100.0

    consistency = 100.0
    if "defaulted" in dataframe.columns:
        defaulted = pd.to_numeric(dataframe["defaulted"], errors="coerce")
        present_defaulted = dataframe["defaulted"].notna()
        if present_defaulted.any():
            consistent = defaulted.isin([0, 1]) & present_defaulted
            consistency = float(consistent.sum() / present_defaulted.sum() * 100.0)

    ready_capabilities = sum(item.status is AssessmentStatus.READY for item in capabilities)
    fitness = ready_capabilities / len(DatasetCapability) * 100.0
    raw_scores = {
        QualityDimension.COMPLETENESS: completeness,
        QualityDimension.VALIDITY: validity,
        QualityDimension.UNIQUENESS: uniqueness,
        QualityDimension.CONSISTENCY: consistency,
        QualityDimension.TIMELINESS: timeliness,
        QualityDimension.FITNESS: fitness,
    }
    return tuple(
        QualityDimensionScore(dimension=dimension, score=round(float(raw_scores[dimension]), 1))
        for dimension in QualityDimension
    )
