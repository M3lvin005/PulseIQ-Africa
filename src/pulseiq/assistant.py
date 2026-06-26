"""Rule-based insight assistant for the first production-ready version."""

from __future__ import annotations

import re

import pandas as pd

from .analytics import format_currency


def answer_question(
    question: str,
    df: pd.DataFrame,
    kpis: dict[str, float | int | str],
    anomaly_df: pd.DataFrame,
    model_metrics: dict[str, float] | None = None,
) -> str:
    """Answer a business question with transparent rules instead of a paid AI API."""

    normalized = re.sub(r"[^a-z0-9 ]+", " ", question.lower()).strip()
    if not normalized:
        return "Ask about risk, suspicious records, revenue, data quality, model performance, or next actions."

    if any(term in normalized for term in ["biggest risk", "main risk", "highest risk"]):
        flagged = anomaly_df[anomaly_df.get("is_suspicious", False)]
        if flagged.empty:
            return "The biggest risk is low visibility: no suspicious records were flagged, so the next step is to validate the rules against real business examples."
        top_issue = flagged["suspicious_category"].value_counts().idxmax()
        count = int((flagged["suspicious_category"] == top_issue).sum())
        return f"The biggest risk is {top_issue.lower()}, with {count:,} records requiring review."

    if any(term in normalized for term in ["what should", "recommend", "next action", "do next"]):
        if int(kpis.get("suspicious_transactions", 0)) > 0:
            return "Review high-risk customers first, verify duplicate or abnormal records, and tighten approvals for cases with high loan-to-income pressure."
        return "Keep the dashboard live, monitor repayment movement each month, and collect richer customer history before increasing lending limits."

    if any(term in normalized for term in ["why", "flagged", "suspicious"]):
        flagged = anomaly_df[anomaly_df.get("is_suspicious", False)]
        if flagged.empty:
            return "No records are currently flagged. The rules look for unusually high amounts, duplicate transaction IDs, sudden spending spikes, weak repayment patterns, and profile mismatches."
        example = flagged.sort_values("anomaly_score", ascending=False).iloc[0]
        txn = example.get("transaction_id", "the top flagged record")
        notes = example.get("anomaly_notes", example.get("suspicious_category", "risk rules were triggered"))
        return f"{txn} was flagged because {str(notes).lower()}."

    if any(term in normalized for term in ["revenue", "money", "transaction value", "sales"]):
        return (
            f"Total transaction value is {format_currency(float(kpis.get('total_revenue', 0)))}, "
            f"with an average transaction value of {format_currency(float(kpis.get('average_transaction_value', 0)))}."
        )

    if any(term in normalized for term in ["quality", "missing", "duplicate", "clean"]):
        return (
            f"The data quality score is {float(kpis.get('data_quality_score', 0)):.1f}%. "
            f"I found {int(kpis.get('missing_values', 0)):,} missing values and "
            f"{int(kpis.get('duplicate_rows', 0)):,} duplicate rows."
        )

    if any(term in normalized for term in ["model", "accuracy", "precision", "recall", "f1", "auc"]):
        if not model_metrics:
            return "Train the prediction model first, then I can summarize accuracy, precision, recall, F1-score, and ROC-AUC."
        return (
            f"The model scored {model_metrics.get('accuracy', 0):.2f} accuracy, "
            f"{model_metrics.get('precision', 0):.2f} precision, {model_metrics.get('recall', 0):.2f} recall, "
            f"{model_metrics.get('f1_score', 0):.2f} F1-score, and {model_metrics.get('roc_auc', 0):.2f} ROC-AUC."
        )

    if any(term in normalized for term in ["customers", "segments", "segment"]):
        if "segment" in df.columns:
            top_segment = df["segment"].fillna("Unknown").value_counts().idxmax()
            return f"The largest customer segment is {top_segment}, and total unique customers are {int(kpis.get('total_customers', 0)):,}."
        return f"The dataset contains {int(kpis.get('total_customers', 0)):,} unique customers."

    return "The strongest summary is: analyze the uploaded records, review flagged risk patterns, and use the report page to turn the findings into a portfolio-ready PDF."

