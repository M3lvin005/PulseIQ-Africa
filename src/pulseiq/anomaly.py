"""Rule-based anomaly detection for financial and SME records."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _numeric(df: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in df.columns:
        return pd.Series(default, index=df.index, dtype="float64")
    series = pd.to_numeric(df[column], errors="coerce")
    if series.notna().any():
        return series.fillna(series.median())
    return pd.Series(default, index=df.index, dtype="float64")


def _append_issue(issues: list[list[str]], mask: pd.Series, label: str) -> None:
    for idx, matched in enumerate(mask.fillna(False).to_numpy()):
        if matched:
            issues[idx].append(label)


def detect_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """Flag suspicious records using transparent rules that portfolio reviewers can inspect."""

    working = df.copy().reset_index(drop=True)
    if working.empty:
        working["is_suspicious"] = []
        working["suspicious_category"] = []
        working["risk_level"] = []
        working["anomaly_score"] = []
        working["anomaly_notes"] = []
        return working

    issues: list[list[str]] = [[] for _ in range(len(working))]
    amount = _numeric(working, "transaction_amount")
    income = _numeric(working, "income", default=max(float(amount.median()), 1.0))
    loan_amount = _numeric(working, "loan_amount")
    existing_debt = _numeric(working, "existing_debt")
    repayment_score = _numeric(working, "repayment_history_score", default=70.0)
    frequency = _numeric(working, "transaction_frequency", default=15.0)

    amount_threshold = max(amount.mean() * 4.5, amount.quantile(0.992))
    _append_issue(issues, amount > amount_threshold, "Unusually high amount")

    if "transaction_id" in working.columns:
        duplicate_mask = working.duplicated(subset=["transaction_id"], keep=False)
    elif {"customer_id", "date", "transaction_amount"}.issubset(working.columns):
        duplicate_mask = working.duplicated(subset=["customer_id", "date", "transaction_amount"], keep=False)
    else:
        duplicate_mask = working.duplicated(keep=False)
    _append_issue(issues, duplicate_mask, "Duplicate customer details")

    if "segment" in working.columns:
        segment_median = working.assign(_amount=amount).groupby("segment")["_amount"].transform("median")
        spending_spike = amount > (segment_median.fillna(amount.median()) * 4.2)
    else:
        spending_spike = amount > (amount.median() * 4.2)
    _append_issue(issues, spending_spike, "Sudden spending spike")

    _append_issue(issues, repayment_score < 36, "High-risk repayment pattern")
    _append_issue(issues, loan_amount > (income * 2.15), "Loan-to-income mismatch")
    _append_issue(issues, frequency > max(frequency.quantile(0.992), frequency.mean() + frequency.std() * 2.4), "Multiple transactions in short time")
    _append_issue(issues, existing_debt > (income * 0.82), "High existing debt")

    issue_count = np.array([len(item) for item in issues])
    amount_rank = amount.rank(pct=True).fillna(0).to_numpy()
    repayment_pressure = np.clip((70 - repayment_score.fillna(70)).to_numpy(), 0, 70) / 70
    debt_pressure = np.clip((existing_debt / np.maximum(income, 1)).fillna(0).to_numpy(), 0, 1)
    anomaly_score = np.clip(issue_count * 24 + amount_rank * 18 + repayment_pressure * 32 + debt_pressure * 20, 0, 100)

    working["anomaly_notes"] = ["; ".join(item) if item else "No rule triggered" for item in issues]
    working["is_suspicious"] = issue_count > 0
    working["suspicious_category"] = [item[0] if item else "Normal" for item in issues]
    working["risk_level"] = np.select(
        [issue_count >= 3, issue_count == 2, issue_count == 1],
        ["High", "Medium", "Low"],
        default="Normal",
    )
    working["anomaly_score"] = anomaly_score.round(1)
    return working


def anomaly_summary(anomaly_df: pd.DataFrame) -> pd.DataFrame:
    """Summarize suspicious records by category and risk level."""

    if anomaly_df.empty or "is_suspicious" not in anomaly_df.columns:
        return pd.DataFrame(columns=["suspicious_category", "risk_level", "records"])

    flagged = anomaly_df[anomaly_df["is_suspicious"]].copy()
    if flagged.empty:
        return pd.DataFrame(columns=["suspicious_category", "risk_level", "records"])

    return (
        flagged.groupby(["suspicious_category", "risk_level"], dropna=False)
        .size()
        .reset_index(name="records")
        .sort_values("records", ascending=False)
    )
