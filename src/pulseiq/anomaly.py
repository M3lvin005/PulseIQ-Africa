"""Versioned, row-evidence-aware risk rules for financial and SME records."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from .datasets import DatasetCapability, assess_dataset

RULESET_VERSION = "prototype-risk-rules/2.0.0"


class RuleStatus(StrEnum):
    """Outcome of one rule for one record."""

    TRIGGERED = "triggered"
    CLEAR = "clear"
    NOT_EVALUATED = "not_evaluated"


@dataclass(frozen=True, slots=True)
class RuleDefinition:
    """Stable identity and reviewer-facing meaning for one rule."""

    rule_id: str
    label: str
    description: str

    @property
    def status_column(self) -> str:
        return f"rule_{self.rule_id}_status"


RULE_DEFINITIONS = (
    RuleDefinition("unusually_high_amount", "Unusually high amount", "Amount exceeds the portfolio tail threshold."),
    RuleDefinition("duplicate_record", "Potential duplicate record", "A usable record identity occurs more than once."),
    RuleDefinition("spending_spike", "Sudden spending spike", "Amount materially exceeds its segment baseline."),
    RuleDefinition("repayment_pattern", "High-risk repayment pattern", "Repayment history score is below 36."),
    RuleDefinition("loan_to_income", "Loan-to-income mismatch", "Loan amount exceeds 2.15 times declared income."),
    RuleDefinition(
        "rapid_transactions",
        "Multiple transactions in short time",
        "Transaction frequency exceeds the portfolio tail threshold.",
    ),
    RuleDefinition("debt_to_income", "High existing debt", "Existing debt exceeds 82% of declared income."),
)
_RULE_BY_ID = {rule.rule_id: rule for rule in RULE_DEFINITIONS}


def _numeric(dataframe: pd.DataFrame, column: str) -> pd.Series:
    """Coerce evidence without filling missing or invalid source values."""

    return pd.to_numeric(dataframe[column], errors="coerce")


def _text_is_present(series: pd.Series) -> pd.Series:
    return series.notna() & series.astype("string").str.strip().ne("").fillna(False)


def _evaluate_rule(
    working: pd.DataFrame,
    issues: list[list[str]],
    statuses: dict[str, pd.Series],
    *,
    rule_id: str,
    evaluable: pd.Series,
    triggered: pd.Series,
) -> None:
    definition = _RULE_BY_ID[rule_id]
    evaluable = evaluable.fillna(False).astype(bool)
    triggered = (triggered & evaluable).fillna(False).astype(bool)
    status = pd.Series(RuleStatus.NOT_EVALUATED.value, index=working.index, dtype="string")
    status.loc[evaluable] = RuleStatus.CLEAR.value
    status.loc[triggered] = RuleStatus.TRIGGERED.value
    statuses[rule_id] = status
    working[definition.status_column] = status
    for position, matched in enumerate(triggered.to_numpy()):
        if matched:
            issues[position].append(definition.label)


def _duplicate_evidence(working: pd.DataFrame, amount: pd.Series) -> tuple[pd.Series, pd.Series]:
    if "transaction_id" in working.columns:
        evaluable = _text_is_present(working["transaction_id"])
        triggered = working["transaction_id"].duplicated(keep=False) & evaluable
        return evaluable, triggered

    identity_columns = {"customer_id", "date", "transaction_amount"}
    if identity_columns.issubset(working.columns):
        evaluable = _text_is_present(working["customer_id"]) & _text_is_present(working["date"]) & amount.notna()
        triggered = working.duplicated(subset=["customer_id", "date", "transaction_amount"], keep=False)
        return evaluable, triggered & evaluable

    unavailable = pd.Series(False, index=working.index, dtype=bool)
    return unavailable, unavailable.copy()


def detect_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """Evaluate transparent rules while preserving missing row evidence."""

    assess_dataset(df).require(DatasetCapability.RISK_RULE_EVALUATION)
    working = df.copy().reset_index(drop=True)
    issues: list[list[str]] = [[] for _ in range(len(working))]
    statuses: dict[str, pd.Series] = {}

    amount = _numeric(working, "transaction_amount")
    income = _numeric(working, "income")
    loan_amount = _numeric(working, "loan_amount")
    existing_debt = _numeric(working, "existing_debt")
    repayment_score = _numeric(working, "repayment_history_score")
    frequency = _numeric(working, "transaction_frequency")

    valid_amount = amount.dropna()
    amount_threshold = max(float(valid_amount.mean() * 4.5), float(valid_amount.quantile(0.992)))
    _evaluate_rule(
        working,
        issues,
        statuses,
        rule_id="unusually_high_amount",
        evaluable=amount.notna(),
        triggered=amount > amount_threshold,
    )

    duplicate_evaluable, duplicate_triggered = _duplicate_evidence(working, amount)
    _evaluate_rule(
        working,
        issues,
        statuses,
        rule_id="duplicate_record",
        evaluable=duplicate_evaluable,
        triggered=duplicate_triggered,
    )

    if "segment" in working.columns:
        segment_present = _text_is_present(working["segment"])
        spike_evaluable = amount.notna() & segment_present
        segment_median = working.assign(_amount=amount).groupby("segment")["_amount"].transform("median")
        spending_spike = amount > (segment_median * 4.2)
    else:
        spike_evaluable = amount.notna()
        spending_spike = amount > (float(valid_amount.median()) * 4.2)
    _evaluate_rule(
        working,
        issues,
        statuses,
        rule_id="spending_spike",
        evaluable=spike_evaluable,
        triggered=spending_spike,
    )

    _evaluate_rule(
        working,
        issues,
        statuses,
        rule_id="repayment_pattern",
        evaluable=repayment_score.notna(),
        triggered=repayment_score < 36,
    )
    positive_income = income.notna() & income.gt(0)
    _evaluate_rule(
        working,
        issues,
        statuses,
        rule_id="loan_to_income",
        evaluable=loan_amount.notna() & positive_income,
        triggered=loan_amount > (income * 2.15),
    )

    valid_frequency = frequency.dropna()
    frequency_threshold = max(
        float(valid_frequency.quantile(0.992)),
        float(valid_frequency.mean() + valid_frequency.std(ddof=0) * 2.4),
    )
    _evaluate_rule(
        working,
        issues,
        statuses,
        rule_id="rapid_transactions",
        evaluable=frequency.notna(),
        triggered=frequency > frequency_threshold,
    )
    _evaluate_rule(
        working,
        issues,
        statuses,
        rule_id="debt_to_income",
        evaluable=existing_debt.notna() & positive_income,
        triggered=existing_debt > (income * 0.82),
    )

    issue_count = np.array([len(item) for item in issues])
    evaluated_count = pd.Series(0, index=working.index, dtype="int64")
    for status in statuses.values():
        evaluated_count = evaluated_count.add(status.ne(RuleStatus.NOT_EVALUATED.value).astype(int))
    not_evaluated_count = len(RULE_DEFINITIONS) - evaluated_count

    amount_rank = amount.rank(pct=True).fillna(0).to_numpy()
    repayment_pressure = np.clip((70 - repayment_score).fillna(0).to_numpy(), 0, 70) / 70
    debt_ratio = (existing_debt / income.where(income.gt(0))).fillna(0)
    debt_pressure: NDArray[np.float64] = np.clip(debt_ratio.to_numpy(dtype=float), 0, 1)
    anomaly_score = np.clip(issue_count * 24 + amount_rank * 18 + repayment_pressure * 32 + debt_pressure * 20, 0, 100)
    score_series = pd.Series(anomaly_score.round(1), index=working.index, dtype="Float64")
    score_series.loc[evaluated_count.eq(0)] = pd.NA

    not_evaluated_ids = [
        [rule.rule_id for rule in RULE_DEFINITIONS if statuses[rule.rule_id].iloc[row] == RuleStatus.NOT_EVALUATED]
        for row in range(len(working))
    ]
    notes: list[str] = []
    for triggered_labels, unavailable_ids in zip(issues, not_evaluated_ids, strict=True):
        parts = list(triggered_labels)
        if not parts:
            parts.append("No evaluated rule triggered")
        if unavailable_ids:
            parts.append(f"Not evaluated: {', '.join(unavailable_ids)}")
        notes.append("; ".join(parts))

    working["anomaly_notes"] = notes
    working["rule_version"] = RULESET_VERSION
    working["rules_evaluated_count"] = evaluated_count
    working["rules_not_evaluated_count"] = not_evaluated_count
    working["not_evaluated_rule_ids"] = ["|".join(item) for item in not_evaluated_ids]
    working["rule_coverage_status"] = np.select(
        [evaluated_count.eq(0), not_evaluated_count.gt(0)],
        ["none", "partial"],
        default="full",
    )
    working["is_suspicious"] = issue_count > 0
    working["suspicious_category"] = [item[0] if item else "Normal" for item in issues]
    working["risk_level"] = np.select(
        [issue_count >= 3, issue_count == 2, issue_count == 1],
        ["High", "Medium", "Low"],
        default="Normal",
    )
    working["anomaly_score"] = score_series
    return working


def rule_coverage(anomaly_df: pd.DataFrame) -> pd.DataFrame:
    """Summarize evidence coverage and triggers for every rule definition."""

    rows: list[dict[str, object]] = []
    total = len(anomaly_df)
    for definition in RULE_DEFINITIONS:
        column = definition.status_column
        if column not in anomaly_df.columns:
            status = pd.Series(RuleStatus.NOT_EVALUATED.value, index=anomaly_df.index, dtype="string")
        else:
            status = anomaly_df[column].astype("string")
        not_evaluated = int(status.eq(RuleStatus.NOT_EVALUATED.value).sum())
        evaluated = total - not_evaluated
        rows.append(
            {
                "rule_id": definition.rule_id,
                "rule_label": definition.label,
                "evaluated_records": evaluated,
                "not_evaluated_records": not_evaluated,
                "triggered_records": int(status.eq(RuleStatus.TRIGGERED.value).sum()),
                "coverage_percent": round(evaluated / total * 100, 1) if total else 0.0,
                "rule_version": RULESET_VERSION,
            }
        )
    return pd.DataFrame(rows)


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
