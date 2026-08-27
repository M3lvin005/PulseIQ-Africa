"""Invariant tests for governed metric contracts."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from pulseiq.portfolio_metrics import (
    MetricId,
    MetricQualityStatus,
    MetricStatus,
    MetricValue,
    PortfolioMetrics,
    ReportingPeriod,
)


def _metric(
    *,
    status: MetricStatus = MetricStatus.AVAILABLE,
    value: float | int | None = 1,
    unavailable_reason: str | None = None,
) -> MetricValue:
    return MetricValue(
        metric_id=MetricId.RECORDS_PROCESSED,
        label="Records processed",
        status=status,
        value=value,
        unit="records",
        definition_version="test/1.0.0",
        source_reference="dataframe:sha256:test",
        source_fields=("*",),
        quality_status=MetricQualityStatus.HEALTHY,
        unavailable_reason=unavailable_reason,
    )


def test_reporting_period_rejects_inverted_dates() -> None:
    with pytest.raises(ValueError, match="cannot precede"):
        ReportingPeriod(start=date(2026, 2, 1), end=date(2026, 1, 1))


@pytest.mark.parametrize(
    ("status", "value", "reason", "message"),
    [
        (MetricStatus.AVAILABLE, None, None, "must contain a value"),
        (MetricStatus.UNAVAILABLE, 0, "missing", "cannot contain a fabricated value"),
        (MetricStatus.UNAVAILABLE, None, None, "must explain why"),
    ],
)
def test_metric_value_rejects_inconsistent_availability(
    status: MetricStatus,
    value: float | int | None,
    reason: str | None,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _metric(status=status, value=value, unavailable_reason=reason)


def test_snapshot_rejects_naive_generation_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        PortfolioMetrics(
            dataset_reference="dataframe:sha256:test",
            generated_at=datetime(2026, 1, 1),
            metrics=(_metric(),),
        )


def test_snapshot_rejects_duplicate_metric_identifiers() -> None:
    with pytest.raises(ValueError, match="duplicate metric"):
        PortfolioMetrics(
            dataset_reference="dataframe:sha256:test",
            generated_at=datetime.now().astimezone(),
            metrics=(_metric(), _metric()),
        )


def test_missing_metric_identifier_is_a_programming_error() -> None:
    snapshot = PortfolioMetrics(
        dataset_reference="dataframe:sha256:test",
        generated_at=datetime.now().astimezone(),
        metrics=(_metric(),),
    )

    with pytest.raises(KeyError, match="transaction_value"):
        snapshot.metric(MetricId.TRANSACTION_VALUE)
