"""Business analytics and insight generation for PulseIQ Africa."""

from __future__ import annotations

import pandas as pd

from .data import data_quality


def _numeric(df: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in df.columns:
        return pd.Series(default, index=df.index, dtype="float64")
    values = pd.to_numeric(df[column], errors="coerce")
    if values.notna().any():
        return values.fillna(values.median())
    return pd.Series(default, index=df.index, dtype="float64")


def calculate_kpis(df: pd.DataFrame, anomaly_df: pd.DataFrame | None = None) -> dict[str, float | int | str]:
    """Return the top-level measurements used across dashboard and report pages."""

    quality = data_quality(df)
    amount = _numeric(df, "transaction_amount")
    defaulted = _numeric(df, "defaulted")
    customer_count = int(df["customer_id"].nunique()) if "customer_id" in df.columns else len(df)

    if anomaly_df is not None and "is_suspicious" in anomaly_df.columns:
        suspicious_records = int(anomaly_df["is_suspicious"].sum())
        high_risk = int((anomaly_df.get("risk_level", pd.Series(index=anomaly_df.index)) == "High").sum())
    else:
        suspicious_records = int((df.get("suspicious_category", pd.Series(["Normal"] * len(df))) != "Normal").sum())
        high_risk = int((df.get("risk_level", pd.Series(["Normal"] * len(df))) == "High").sum())

    repayment_rate = float((1 - defaulted.clip(0, 1).mean()) * 100) if len(defaulted) else 0.0

    return {
        "records_processed": len(df),
        "total_revenue": float(amount.sum()),
        "total_customers": customer_count,
        "average_transaction_value": float(amount.mean() if len(amount) else 0.0),
        "loan_repayment_rate": round(repayment_rate, 1),
        "high_risk_customers": high_risk,
        "suspicious_transactions": suspicious_records,
        "data_quality_score": quality.score,
        "missing_values": quality.missing_values,
        "duplicate_rows": quality.duplicate_rows,
    }


def monthly_revenue(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate transaction amount by month."""

    if df.empty:
        return pd.DataFrame(columns=["month", "transaction_amount"])

    working = df.copy()
    if "date" in working.columns:
        working["month"] = pd.to_datetime(working["date"], errors="coerce").dt.to_period("M").astype(str)
    elif "month" not in working.columns:
        working["month"] = "Unknown"
    working["transaction_amount"] = _numeric(working, "transaction_amount")
    return working.groupby("month", dropna=False)["transaction_amount"].sum().reset_index().sort_values("month")


def categorical_counts(df: pd.DataFrame, column: str, value_name: str = "records") -> pd.DataFrame:
    """Count records for a categorical field."""

    if column not in df.columns or df.empty:
        return pd.DataFrame(columns=[column, value_name])
    return df[column].fillna("Unknown").value_counts().rename_axis(column).reset_index(name=value_name)


def default_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    """Return repayment/default status counts."""

    if "repayment_status" in df.columns:
        return categorical_counts(df, "repayment_status")
    defaulted = _numeric(df, "defaulted").clip(0, 1)
    labels = defaulted.map({0: "Repaid", 1: "Defaulted"}).fillna("Unknown")
    return labels.value_counts().rename_axis("repayment_status").reset_index(name="records")


def make_insights(
    df: pd.DataFrame,
    kpis: dict[str, float | int | str],
    anomaly_df: pd.DataFrame | None = None,
    model_metrics: dict[str, float] | None = None,
) -> list[str]:
    """Create rule-based narrative insights from the current dataset."""

    insights: list[str] = []

    if "segment" in df.columns and "transaction_amount" in df.columns:
        segment_revenue = (
            df.assign(transaction_amount=_numeric(df, "transaction_amount"))
            .groupby("segment")["transaction_amount"]
            .sum()
        )
        if not segment_revenue.empty:
            top_segment = str(segment_revenue.idxmax())
            insights.append(f"{top_segment} is the strongest customer segment by total transaction value.")

    suspicious = int(kpis.get("suspicious_transactions", 0))
    records = max(int(kpis.get("records_processed", 0)), 1)
    suspicious_rate = suspicious / records * 100
    if suspicious_rate > 15:
        insights.append("Suspicious activity is high enough to justify manual review before approvals.")
    elif suspicious_rate > 0:
        insights.append("A focused review of flagged records would reduce operational and credit risk.")
    else:
        insights.append("No suspicious records were flagged by the current rule set.")

    repayment_rate = float(kpis.get("loan_repayment_rate", 0))
    if repayment_rate >= 85:
        insights.append("The repayment profile is healthy, with most customers marked as repaid.")
    elif repayment_rate >= 65:
        insights.append("Repayment performance is moderate; risk checks should stay active.")
    else:
        insights.append("Repayment performance is weak and approval rules should be tightened.")

    quality_score = float(kpis.get("data_quality_score", 0))
    if quality_score < 90:
        insights.append("Data quality issues may affect model confidence; clean missing and duplicate records.")
    else:
        insights.append("The dataset quality score is strong enough for dashboard and model exploration.")

    if model_metrics:
        f1 = model_metrics.get("f1_score")
        auc = model_metrics.get("roc_auc")
        if f1 is not None:
            insights.append(f"The selected model reached an F1-score of {f1:.2f} on the test split.")
        if auc is not None:
            insights.append(f"The ROC-AUC score is {auc:.2f}, which helps show measurable model performance.")

    if anomaly_df is not None and "suspicious_category" in anomaly_df.columns:
        flagged = anomaly_df[anomaly_df.get("is_suspicious", False)]
        if not flagged.empty:
            top_issue = str(flagged["suspicious_category"].value_counts().idxmax())
            insights.append(f"The most common suspicious pattern is {top_issue.lower()}.")

    return insights[:7]


def format_currency(value: float | int) -> str:
    """Format values as Nigerian naira without relying on special glyphs."""

    return f"NGN {float(value):,.0f}"
