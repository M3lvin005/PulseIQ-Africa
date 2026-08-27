"""Immutable governed metric contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


class MetricId(StrEnum):
    """Stable identifiers for prototype portfolio metrics."""

    RECORDS_PROCESSED = "records_processed"
    TRANSACTION_VALUE = "transaction_value"
    UNIQUE_CUSTOMERS = "unique_customers"
    AVERAGE_TRANSACTION_VALUE = "average_transaction_value"
    NON_DEFAULT_OUTCOME_SHARE = "non_default_outcome_share"
    HIGH_RISK_RECORDS = "high_risk_records"
    SUSPICIOUS_RECORDS = "suspicious_records"
    DATA_QUALITY_SCORE = "data_quality_score"
    MISSING_VALUES = "missing_values"
    DUPLICATE_ROWS = "duplicate_rows"


class MetricStatus(StrEnum):
    """Whether a metric has enough governed input to be calculated."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class MetricQualityStatus(StrEnum):
    """Quality state attached to an individual metric result."""

    HEALTHY = "pass"
    WARN = "warn"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class ReportingPeriod:
    """Inclusive event-time range represented by a metric."""

    start: date
    end: date

    def __post_init__(self) -> None:
        """Reject an inverted period."""

        if self.end < self.start:
            raise ValueError("Reporting period end cannot precede its start.")


@dataclass(frozen=True, slots=True)
class MetricValue:
    """One value with the metadata needed to interpret it safely."""

    metric_id: MetricId
    label: str
    status: MetricStatus
    value: float | int | None
    unit: str
    definition_version: str
    source_reference: str
    source_fields: tuple[str, ...]
    quality_status: MetricQualityStatus
    currency: str | None = None
    period: ReportingPeriod | None = None
    unavailable_reason: str | None = None
    recovery: str | None = None
    numerator: float | int | None = None
    denominator: float | int | None = None
    logic_version: str | None = None

    def __post_init__(self) -> None:
        """Keep available values and unavailable explanations internally consistent."""

        if self.status is MetricStatus.AVAILABLE and self.value is None:
            raise ValueError("An available metric must contain a value.")
        if self.status is MetricStatus.UNAVAILABLE and self.value is not None:
            raise ValueError("An unavailable metric cannot contain a fabricated value.")
        if self.status is MetricStatus.UNAVAILABLE and not self.unavailable_reason:
            raise ValueError("An unavailable metric must explain why it cannot be calculated.")


@dataclass(frozen=True, slots=True)
class PortfolioMetrics:
    """Versioned metric snapshot for one in-memory dataset."""

    dataset_reference: str
    generated_at: datetime
    metrics: tuple[MetricValue, ...]

    def __post_init__(self) -> None:
        """Require an aware generation timestamp and unique metric identifiers."""

        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("Metric generation time must be timezone-aware.")
        metric_ids = [metric.metric_id for metric in self.metrics]
        if len(metric_ids) != len(set(metric_ids)):
            raise ValueError("A metric snapshot cannot contain duplicate metric identifiers.")

    def metric(self, metric_id: MetricId) -> MetricValue:
        """Return one named metric or raise for a programming error."""

        for metric in self.metrics:
            if metric.metric_id is metric_id:
                return metric
        raise KeyError(f"Metric {metric_id.value!r} is not present in this snapshot.")
