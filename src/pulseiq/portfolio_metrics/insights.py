"""Narrative insights derived only from governed metric results."""

from __future__ import annotations

from .contracts import MetricId, MetricStatus, MetricValue, PortfolioMetrics


def build_metric_insights(metrics: PortfolioMetrics) -> tuple[str, ...]:
    """Return concise review notes without bypassing metric availability."""

    quality = metrics.metric(MetricId.DATA_QUALITY_SCORE)
    if quality.value is None:
        raise ValueError("The governed data-quality observation must always contain a value.")
    insights = [
        f"Composite data quality is {float(quality.value):.1f}% ({quality.quality_status.value}); "
        "review the six dimensions and blocking issues before relying on it."
    ]
    for metric_id in (
        MetricId.TRANSACTION_VALUE,
        MetricId.UNIQUE_CUSTOMERS,
        MetricId.NON_DEFAULT_OUTCOME_SHARE,
        MetricId.SUSPICIOUS_RECORDS,
    ):
        metric = metrics.metric(metric_id)
        insights.append(_metric_insight(metric))
    return tuple(insights)


def _metric_insight(metric: MetricValue) -> str:
    """Create one availability-preserving metric sentence."""

    if metric.status is MetricStatus.UNAVAILABLE:
        return f"{metric.label} is unavailable: {metric.unavailable_reason} Recovery: {metric.recovery}"
    if metric.value is None:
        raise ValueError("An available governed metric must contain a value.")
    if metric.unit == "currency":
        value = f"{metric.currency} {float(metric.value):,.0f}"
    elif metric.unit == "percent":
        value = f"{float(metric.value):.1f}%"
    elif isinstance(metric.value, int):
        value = f"{metric.value:,}"
    else:
        value = str(metric.value)
    qualification = " This is not recognized revenue." if metric.metric_id is MetricId.TRANSACTION_VALUE else ""
    return (
        f"{metric.label} is {value} ({metric.quality_status.value}).{qualification} "
        f"Definition: {metric.definition_version}."
    )
