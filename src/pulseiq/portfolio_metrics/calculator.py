"""Governed portfolio metric calculation service."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pandas as pd

from pulseiq.datasets import DatasetAssessment, DatasetCapability, IssueSeverity, assess_dataset

from .contracts import (
    MetricId,
    MetricQualityStatus,
    MetricStatus,
    MetricValue,
    PortfolioMetrics,
    ReportingPeriod,
)


def calculate_portfolio_metrics(
    dataframe: pd.DataFrame,
    *,
    currency: str | None = None,
    anomaly_dataframe: pd.DataFrame | None = None,
    risk_rule_version: str | None = None,
    generated_at: datetime | None = None,
) -> PortfolioMetrics:
    """Calculate a governed metric snapshot for a dataframe."""

    assessment = assess_dataset(dataframe)
    dataset_reference = _dataset_reference(dataframe)
    period = _reporting_period(dataframe)
    resolved_currency = currency.strip().upper() if currency and currency.strip() else None
    if resolved_currency is None and "currency" in dataframe.columns:
        currencies = dataframe["currency"].dropna().astype("string").str.strip().str.upper()
        unique_currencies = tuple(value for value in currencies.unique().tolist() if value)
        if len(unique_currencies) == 1:
            resolved_currency = str(unique_currencies[0])

    if "transaction_amount" not in dataframe.columns:
        metric = MetricValue(
            metric_id=MetricId.TRANSACTION_VALUE,
            label="Total transaction value",
            status=MetricStatus.UNAVAILABLE,
            value=None,
            unit="currency",
            currency=resolved_currency,
            definition_version="portfolio.transaction-value/1.0.0",
            source_reference=dataset_reference,
            source_fields=("transaction_amount",),
            quality_status=MetricQualityStatus.BLOCKED,
            unavailable_reason="The dataset has no mapped transaction amount.",
            recovery="Map a numeric amount column to transaction_amount and confirm its currency.",
        )
    elif not assessment.can(DatasetCapability.TRANSACTION_ANALYTICS):
        blocking_issue = next(
            issue
            for issue in assessment.issues
            if issue.severity is IssueSeverity.BLOCK
            and DatasetCapability.TRANSACTION_ANALYTICS in issue.affected_capabilities
        )
        metric = MetricValue(
            metric_id=MetricId.TRANSACTION_VALUE,
            label="Total transaction value",
            status=MetricStatus.UNAVAILABLE,
            value=None,
            unit="currency",
            currency=resolved_currency,
            definition_version="portfolio.transaction-value/1.0.0",
            source_reference=dataset_reference,
            source_fields=("transaction_amount", "date"),
            quality_status=MetricQualityStatus.BLOCKED,
            unavailable_reason=blocking_issue.message,
            recovery=blocking_issue.recovery,
        )
    elif resolved_currency is None:
        metric = MetricValue(
            metric_id=MetricId.TRANSACTION_VALUE,
            label="Total transaction value",
            status=MetricStatus.UNAVAILABLE,
            value=None,
            unit="currency",
            definition_version="portfolio.transaction-value/1.0.0",
            source_reference=dataset_reference,
            source_fields=("transaction_amount", "currency"),
            quality_status=MetricQualityStatus.BLOCKED,
            unavailable_reason="Transaction currency is missing or ambiguous.",
            recovery="Confirm one dataset currency or separate values by their mapped currency.",
        )
    else:
        transaction_value = float(pd.to_numeric(dataframe["transaction_amount"], errors="coerce").sum())
        has_warnings = any(
            issue.severity is IssueSeverity.WARN
            and DatasetCapability.TRANSACTION_ANALYTICS in issue.affected_capabilities
            for issue in assessment.issues
        )
        metric = MetricValue(
            metric_id=MetricId.TRANSACTION_VALUE,
            label="Total transaction value",
            status=MetricStatus.AVAILABLE,
            value=transaction_value,
            unit="currency",
            currency=resolved_currency,
            definition_version="portfolio.transaction-value/1.0.0",
            source_reference=dataset_reference,
            source_fields=("transaction_amount", "date"),
            quality_status=MetricQualityStatus.WARN if has_warnings else MetricQualityStatus.HEALTHY,
            period=period,
        )
    customer_metric = _unique_customer_metric(assessment, dataframe, dataset_reference, period)
    average_transaction_metric = _average_transaction_metric(
        assessment,
        dataframe,
        metric,
        dataset_reference,
        period,
    )
    non_default_metric = _non_default_outcome_metric(assessment, dataframe, dataset_reference, period)
    risk_metrics = _risk_metrics(
        assessment,
        anomaly_dataframe,
        risk_rule_version,
        dataset_reference,
        period,
    )
    observation_metrics = _dataset_observation_metrics(assessment, dataframe, dataset_reference, period)
    return PortfolioMetrics(
        dataset_reference=dataset_reference,
        generated_at=generated_at or datetime.now(UTC),
        metrics=(
            *observation_metrics,
            metric,
            average_transaction_metric,
            customer_metric,
            non_default_metric,
            *risk_metrics,
        ),
    )


def _risk_metrics(
    assessment: DatasetAssessment,
    anomaly_dataframe: pd.DataFrame | None,
    risk_rule_version: str | None,
    dataset_reference: str,
    period: ReportingPeriod | None,
) -> tuple[MetricValue, MetricValue]:
    """Return explicitly versioned rule-run counts or unavailable results."""

    reason: str | None = None
    recovery: str | None = None
    if anomaly_dataframe is None or not risk_rule_version:
        reason = "No versioned risk-rule evaluation is attached to this metric snapshot."
        recovery = "Run the approved rule set and provide its version before displaying rule-derived counts."
    elif not assessment.can(DatasetCapability.RISK_RULE_EVALUATION):
        blocking_issue = next(
            issue
            for issue in assessment.issues
            if issue.severity is IssueSeverity.BLOCK
            and DatasetCapability.RISK_RULE_EVALUATION in issue.affected_capabilities
        )
        reason = blocking_issue.message
        recovery = blocking_issue.recovery
    elif not {"is_suspicious", "risk_level"}.issubset(anomaly_dataframe.columns):
        reason = "The risk-rule result is missing required output fields."
        recovery = "Re-run the versioned rule evaluation and preserve is_suspicious and risk_level outputs."

    if reason is not None:
        return (
            _rule_count_metric(
                metric_id=MetricId.SUSPICIOUS_RECORDS,
                label="Suspicious records (rules)",
                definition_version="portfolio.suspicious-rule-records/1.0.0",
                source_fields=("is_suspicious",),
                value=None,
                source_reference=dataset_reference,
                period=period,
                quality_status=MetricQualityStatus.BLOCKED,
                risk_rule_version=risk_rule_version,
                unavailable_reason=reason,
                recovery=recovery,
            ),
            _rule_count_metric(
                metric_id=MetricId.HIGH_RISK_RECORDS,
                label="High-priority rule records",
                definition_version="portfolio.high-priority-rule-records/1.0.0",
                source_fields=("is_suspicious", "risk_level"),
                value=None,
                source_reference=dataset_reference,
                period=period,
                quality_status=MetricQualityStatus.BLOCKED,
                risk_rule_version=risk_rule_version,
                unavailable_reason=reason,
                recovery=recovery,
            ),
        )

    if anomaly_dataframe is None:
        raise RuntimeError("A versioned rule result was expected after rule-metric validation.")
    suspicious = anomaly_dataframe["is_suspicious"].fillna(False).astype(bool)
    quality_status = _quality_status(assessment, DatasetCapability.RISK_RULE_EVALUATION)
    return (
        _rule_count_metric(
            metric_id=MetricId.SUSPICIOUS_RECORDS,
            label="Suspicious records (rules)",
            value=int(suspicious.sum()),
            definition_version="portfolio.suspicious-rule-records/1.0.0",
            source_fields=("is_suspicious",),
            source_reference=dataset_reference,
            period=period,
            quality_status=quality_status,
            risk_rule_version=risk_rule_version,
        ),
        _rule_count_metric(
            metric_id=MetricId.HIGH_RISK_RECORDS,
            label="High-priority rule records",
            value=int((suspicious & anomaly_dataframe["risk_level"].eq("High")).sum()),
            definition_version="portfolio.high-priority-rule-records/1.0.0",
            source_fields=("is_suspicious", "risk_level"),
            source_reference=dataset_reference,
            period=period,
            quality_status=quality_status,
            risk_rule_version=risk_rule_version,
        ),
    )


def _rule_count_metric(
    *,
    metric_id: MetricId,
    label: str,
    definition_version: str,
    source_fields: tuple[str, ...],
    value: int | None,
    source_reference: str,
    period: ReportingPeriod | None,
    quality_status: MetricQualityStatus,
    risk_rule_version: str | None,
    unavailable_reason: str | None = None,
    recovery: str | None = None,
) -> MetricValue:
    """Build one rule count without erasing contract types through kwargs dictionaries."""

    return MetricValue(
        metric_id=metric_id,
        label=label,
        status=MetricStatus.AVAILABLE if value is not None else MetricStatus.UNAVAILABLE,
        value=value,
        unit="records",
        definition_version=definition_version,
        source_reference=source_reference,
        source_fields=source_fields,
        quality_status=quality_status,
        period=period,
        unavailable_reason=unavailable_reason,
        recovery=recovery,
        logic_version=risk_rule_version,
    )


def _non_default_outcome_metric(
    assessment: DatasetAssessment,
    dataframe: pd.DataFrame,
    dataset_reference: str,
    period: ReportingPeriod | None,
) -> MetricValue:
    """Return row-level non-default outcome share without claiming repayment."""

    if "defaulted" not in dataframe.columns:
        return MetricValue(
            metric_id=MetricId.NON_DEFAULT_OUTCOME_SHARE,
            label="Non-default outcome share",
            status=MetricStatus.UNAVAILABLE,
            value=None,
            unit="percent",
            definition_version="portfolio.non-default-outcome-share/1.0.0",
            source_reference=dataset_reference,
            source_fields=("defaulted",),
            quality_status=MetricQualityStatus.BLOCKED,
            period=period,
            unavailable_reason="A canonical defaulted outcome is not mapped.",
            recovery="Map an authoritative binary defaulted outcome; do not infer scheduled repayment from row status.",
        )

    outcomes = pd.to_numeric(dataframe["defaulted"], errors="coerce")
    valid = outcomes.isin([0, 1])
    if not valid.any():
        return MetricValue(
            metric_id=MetricId.NON_DEFAULT_OUTCOME_SHARE,
            label="Non-default outcome share",
            status=MetricStatus.UNAVAILABLE,
            value=None,
            unit="percent",
            definition_version="portfolio.non-default-outcome-share/1.0.0",
            source_reference=dataset_reference,
            source_fields=("defaulted",),
            quality_status=MetricQualityStatus.BLOCKED,
            period=period,
            unavailable_reason="The defaulted outcome contains no valid binary values.",
            recovery="Correct defaulted values to the approved 0/1 outcome definition.",
        )

    denominator = int(valid.sum())
    numerator = int((outcomes[valid] == 0).sum())
    quality_status = _quality_status(assessment, DatasetCapability.REPAYMENT_ANALYTICS)
    if not valid.all():
        quality_status = MetricQualityStatus.WARN
    return MetricValue(
        metric_id=MetricId.NON_DEFAULT_OUTCOME_SHARE,
        label="Non-default outcome share",
        status=MetricStatus.AVAILABLE,
        value=round(numerator / denominator * 100.0, 1),
        unit="percent",
        definition_version="portfolio.non-default-outcome-share/1.0.0",
        source_reference=dataset_reference,
        source_fields=("defaulted",),
        quality_status=quality_status,
        period=period,
        numerator=numerator,
        denominator=denominator,
    )


def _average_transaction_metric(
    assessment: DatasetAssessment,
    dataframe: pd.DataFrame,
    transaction_metric: MetricValue,
    dataset_reference: str,
    period: ReportingPeriod | None,
) -> MetricValue:
    """Return the mean of parseable values under transaction-metric semantics."""

    if transaction_metric.status is MetricStatus.UNAVAILABLE:
        return MetricValue(
            metric_id=MetricId.AVERAGE_TRANSACTION_VALUE,
            label="Average transaction value",
            status=MetricStatus.UNAVAILABLE,
            value=None,
            unit="currency",
            currency=transaction_metric.currency,
            definition_version="portfolio.average-transaction-value/1.0.0",
            source_reference=dataset_reference,
            source_fields=("transaction_amount", "date"),
            quality_status=MetricQualityStatus.BLOCKED,
            period=period,
            unavailable_reason=transaction_metric.unavailable_reason,
            recovery=transaction_metric.recovery,
        )

    values = pd.to_numeric(dataframe["transaction_amount"], errors="coerce").dropna()
    return MetricValue(
        metric_id=MetricId.AVERAGE_TRANSACTION_VALUE,
        label="Average transaction value",
        status=MetricStatus.AVAILABLE,
        value=float(values.mean()),
        unit="currency",
        currency=transaction_metric.currency,
        definition_version="portfolio.average-transaction-value/1.0.0",
        source_reference=dataset_reference,
        source_fields=("transaction_amount", "date"),
        quality_status=_quality_status(assessment, DatasetCapability.TRANSACTION_ANALYTICS),
        period=period,
    )


def _dataset_observation_metrics(
    assessment: DatasetAssessment,
    dataframe: pd.DataFrame,
    dataset_reference: str,
    period: ReportingPeriod | None,
) -> tuple[MetricValue, ...]:
    """Return dataset facts whose numeric zero remains meaningful."""

    quality_status = MetricQualityStatus.BLOCKED if assessment.is_blocked else MetricQualityStatus.HEALTHY
    if not assessment.is_blocked and assessment.issues:
        quality_status = MetricQualityStatus.WARN
    return (
        _observation_metric(
            metric_id=MetricId.RECORDS_PROCESSED,
            label="Records processed",
            value=len(dataframe),
            unit="records",
            definition_version="portfolio.records-processed/1.0.0",
            source_reference=dataset_reference,
            quality_status=quality_status,
            period=period,
        ),
        _observation_metric(
            metric_id=MetricId.DATA_QUALITY_SCORE,
            label="Composite data quality",
            value=assessment.composite_score,
            unit="percent",
            definition_version=assessment.definition_version,
            source_reference=dataset_reference,
            quality_status=quality_status,
            period=period,
        ),
        _observation_metric(
            metric_id=MetricId.MISSING_VALUES,
            label="Missing values",
            value=int(dataframe.isna().sum().sum()),
            unit="cells",
            definition_version="portfolio.missing-values/1.0.0",
            source_reference=dataset_reference,
            quality_status=quality_status,
            period=period,
        ),
        _observation_metric(
            metric_id=MetricId.DUPLICATE_ROWS,
            label="Duplicate rows",
            value=int(dataframe.duplicated().sum()),
            unit="rows",
            definition_version="portfolio.duplicate-rows/1.0.0",
            source_reference=dataset_reference,
            quality_status=quality_status,
            period=period,
        ),
    )


def _observation_metric(
    *,
    metric_id: MetricId,
    label: str,
    value: float | int,
    unit: str,
    definition_version: str,
    source_reference: str,
    quality_status: MetricQualityStatus,
    period: ReportingPeriod | None,
) -> MetricValue:
    """Build an always-observable dataset fact with explicit quality state."""

    return MetricValue(
        metric_id=metric_id,
        label=label,
        status=MetricStatus.AVAILABLE,
        value=value,
        unit=unit,
        definition_version=definition_version,
        source_reference=source_reference,
        source_fields=("*",),
        quality_status=quality_status,
        period=period,
    )


def _unique_customer_metric(
    assessment: DatasetAssessment,
    dataframe: pd.DataFrame,
    dataset_reference: str,
    period: ReportingPeriod | None,
) -> MetricValue:
    """Return an explicit unique-customer count or an unavailable result."""

    if not assessment.can(DatasetCapability.CUSTOMER_ANALYTICS):
        blocking_issue = next(
            issue
            for issue in assessment.issues
            if issue.severity is IssueSeverity.BLOCK
            and DatasetCapability.CUSTOMER_ANALYTICS in issue.affected_capabilities
        )
        return MetricValue(
            metric_id=MetricId.UNIQUE_CUSTOMERS,
            label="Unique customers",
            status=MetricStatus.UNAVAILABLE,
            value=None,
            unit="customers",
            definition_version="portfolio.unique-customers/1.0.0",
            source_reference=dataset_reference,
            source_fields=("customer_id",),
            quality_status=MetricQualityStatus.BLOCKED,
            period=period,
            unavailable_reason=blocking_issue.message,
            recovery=blocking_issue.recovery,
        )

    customer_ids = dataframe["customer_id"].astype("string").str.strip()
    customer_ids = customer_ids[customer_ids.notna() & customer_ids.ne("")]
    return MetricValue(
        metric_id=MetricId.UNIQUE_CUSTOMERS,
        label="Unique customers",
        status=MetricStatus.AVAILABLE,
        value=int(customer_ids.nunique()),
        unit="customers",
        definition_version="portfolio.unique-customers/1.0.0",
        source_reference=dataset_reference,
        source_fields=("customer_id",),
        quality_status=_quality_status(assessment, DatasetCapability.CUSTOMER_ANALYTICS),
        period=period,
    )


def _quality_status(
    assessment: DatasetAssessment,
    capability: DatasetCapability,
) -> MetricQualityStatus:
    """Map warnings for a capability already proven ready."""

    if any(
        issue.severity is IssueSeverity.WARN and capability in issue.affected_capabilities
        for issue in assessment.issues
    ):
        return MetricQualityStatus.WARN
    return MetricQualityStatus.HEALTHY


def _dataset_reference(dataframe: pd.DataFrame) -> str:
    """Create a deterministic content reference for an in-memory dataframe."""

    digest = hashlib.sha256()
    digest.update("\x1f".join(str(column) for column in dataframe.columns).encode("utf-8"))
    digest.update("\x1f".join(str(dtype) for dtype in dataframe.dtypes).encode("utf-8"))
    normalized = dataframe.astype("string")
    hashes = pd.util.hash_pandas_object(normalized, index=True)
    digest.update(hashes.to_numpy(dtype="uint64").tobytes())
    return f"dataframe:sha256:{digest.hexdigest()}"


def _reporting_period(dataframe: pd.DataFrame) -> ReportingPeriod | None:
    """Return the valid inclusive event-date range, if present."""

    if "date" not in dataframe.columns:
        return None
    dates = pd.to_datetime(dataframe["date"], errors="coerce", format="mixed").dropna()
    if dates.empty:
        return None
    return ReportingPeriod(start=dates.min().date(), end=dates.max().date())
