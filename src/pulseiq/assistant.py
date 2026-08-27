"""Rule-based insight assistant for the first production-ready version."""

from __future__ import annotations

import re

import pandas as pd

from .portfolio_metrics import MetricId, MetricStatus, MetricValue, PortfolioMetrics


def answer_question(
    question: str,
    df: pd.DataFrame,
    metrics: PortfolioMetrics,
    anomaly_df: pd.DataFrame,
    model_metrics: dict[str, float] | None = None,
) -> str:
    """Answer a business question with transparent rules instead of a paid AI API."""

    normalized = re.sub(r"[^a-z0-9 ]+", " ", question.lower()).strip()
    if not normalized:
        return (
            "Ask about risk, suspicious records, transaction value, data quality, model performance, or next actions."
        )

    if any(term in normalized for term in ["biggest risk", "main risk", "highest risk"]):
        risk_metric = metrics.metric(MetricId.SUSPICIOUS_RECORDS)
        if risk_metric.status is MetricStatus.UNAVAILABLE:
            return _unavailable_answer(risk_metric)
        flagged = _flagged_rows(anomaly_df)
        if flagged.empty:
            return (
                f"The versioned rule run found no suspicious records. Source: {risk_metric.logic_version}; "
                f"dataset: {metrics.dataset_reference}. Validate the rules against reviewed examples before "
                f"treating this as low risk.{_rule_coverage_caveat(anomaly_df)}"
            )
        top_issue = str(flagged["suspicious_category"].value_counts().idxmax())
        count = int((flagged["suspicious_category"] == top_issue).sum())
        return (
            f"The biggest risk is {top_issue.lower()}, with {count:,} records requiring review."
            f"{_rule_coverage_caveat(anomaly_df)}"
        )

    if any(term in normalized for term in ["what should", "recommend", "next action", "do next"]):
        risk_metric = metrics.metric(MetricId.SUSPICIOUS_RECORDS)
        if risk_metric.status is MetricStatus.UNAVAILABLE:
            return f"Before recommending a risk action, {_unavailable_answer(risk_metric).lower()}"
        if int(risk_metric.value or 0) > 0:
            return (
                "Review high-priority rule records first, verify duplicate or abnormal evidence, and send "
                "loan-to-income pressure cases to an authorized reviewer."
            )
        return "Review the versioned rule coverage and collect authoritative outcomes before changing lending limits."

    if any(term in normalized for term in ["why", "flagged", "suspicious"]):
        risk_metric = metrics.metric(MetricId.SUSPICIOUS_RECORDS)
        if risk_metric.status is MetricStatus.UNAVAILABLE:
            return _unavailable_answer(risk_metric)
        flagged = _flagged_rows(anomaly_df)
        if flagged.empty:
            return (
                "No records are currently flagged by the attached versioned run. Its rules evaluate unusually "
                "high amounts, duplicate identifiers, spending spikes, repayment patterns, and profile mismatches."
                f"{_rule_coverage_caveat(anomaly_df)}"
            )
        example = flagged.sort_values("anomaly_score", ascending=False).iloc[0]
        txn = example.get("transaction_id", "the top flagged record")
        notes = example.get("anomaly_notes", example.get("suspicious_category", "risk rules were triggered"))
        return f"{txn} was flagged because {str(notes).lower()}.{_rule_coverage_caveat(anomaly_df)}"

    if any(term in normalized for term in ["revenue", "money", "transaction value", "sales"]):
        total = metrics.metric(MetricId.TRANSACTION_VALUE)
        average = metrics.metric(MetricId.AVERAGE_TRANSACTION_VALUE)
        if total.status is MetricStatus.UNAVAILABLE:
            return _unavailable_answer(total)
        return (
            f"Total transaction value is {_format_financial_metric(total)}, with an average of "
            f"{_format_financial_metric(average)}. This is transaction value, not recognized revenue. "
            f"Definition: {total.definition_version}; source: {total.source_reference}."
        )

    if any(term in normalized for term in ["quality", "missing", "duplicate", "clean"]):
        quality = metrics.metric(MetricId.DATA_QUALITY_SCORE)
        missing = metrics.metric(MetricId.MISSING_VALUES)
        duplicates = metrics.metric(MetricId.DUPLICATE_ROWS)
        return (
            f"The composite data quality score is {float(_required_value(quality)):.1f}% "
            f"({quality.quality_status.value}). I found {int(_required_value(missing)):,} missing values and "
            f"{int(_required_value(duplicates)):,} duplicate rows. "
            "Review the six quality dimensions because a composite score never overrides a blocking issue."
        )

    if any(term in normalized for term in ["model", "accuracy", "precision", "recall", "f1", "auc"]):
        if not model_metrics:
            return (
                "Train the demonstration model first, then I can summarize accuracy, precision, recall, "
                "F1-score, and ROC-AUC."
            )
        return (
            f"On the final holdout, the demonstration model scored {model_metrics.get('accuracy', float('nan')):.2f} "
            f"accuracy, {model_metrics.get('precision', float('nan')):.2f} precision, "
            f"{model_metrics.get('recall', float('nan')):.2f} recall, "
            f"{model_metrics.get('f1_score', float('nan')):.2f} F1-score, "
            f"{model_metrics.get('roc_auc', float('nan')):.2f} ROC-AUC, and "
            f"{model_metrics.get('pr_auc', float('nan')):.2f} PR-AUC. "
            "Its output is uncalibrated, the model is unapproved, and every score requires human review."
        )

    if any(term in normalized for term in ["customers", "segments", "segment"]):
        customers = metrics.metric(MetricId.UNIQUE_CUSTOMERS)
        if customers.status is MetricStatus.UNAVAILABLE:
            return _unavailable_answer(customers)
        if "segment" in df.columns:
            top_segment = df["segment"].fillna("Unknown").value_counts().idxmax()
            return (
                f"The largest customer segment is {top_segment}, and total unique customers are "
                f"{int(_required_value(customers)):,}."
            )
        return f"The dataset contains {int(_required_value(customers)):,} unique customers."

    return (
        "Review the governed metric definitions, resolve dataset issues, inspect versioned rule evidence, "
        "and use the accessible report for a traceable summary."
    )


def _flagged_rows(anomaly_df: pd.DataFrame) -> pd.DataFrame:
    """Return rule-flagged rows only when a valid rule output is present."""

    if "is_suspicious" not in anomaly_df.columns:
        return pd.DataFrame()
    return anomaly_df[anomaly_df["is_suspicious"].fillna(False).astype(bool)]


def _rule_coverage_caveat(anomaly_df: pd.DataFrame) -> str:
    """State incomplete evidence without treating non-evaluation as a clear result."""

    if "rules_not_evaluated_count" not in anomaly_df.columns:
        return ""
    not_evaluated = int(pd.to_numeric(anomaly_df["rules_not_evaluated_count"], errors="coerce").fillna(0).sum())
    if not_evaluated == 0:
        return ""
    return (
        f" Coverage caveat: {not_evaluated:,} record-rule evaluations were not evaluated because required "
        "evidence was missing or invalid."
    )


def _unavailable_answer(metric: MetricValue) -> str:
    """Explain an unavailable governed metric and its recovery path."""

    return f"{metric.label} is unavailable: {metric.unavailable_reason} Recovery: {metric.recovery}"


def _format_financial_metric(metric: MetricValue) -> str:
    """Format an available financial metric with its declared currency."""

    if metric.status is MetricStatus.UNAVAILABLE or metric.value is None:
        return "Not available"
    return f"{metric.currency} {float(metric.value):,.0f}"


def _required_value(metric: MetricValue) -> float | int:
    """Return an available metric value or raise on a violated contract."""

    if metric.value is None:
        raise ValueError(f"Metric {metric.metric_id.value} must contain a value in this answer path.")
    return metric.value
