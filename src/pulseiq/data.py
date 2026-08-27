"""Data loading, demo data, and data-quality utilities for PulseIQ Africa."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import IO

import numpy as np
import pandas as pd

DEMO_DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "demo_pulseiq_transactions.csv"


@dataclass(frozen=True)
class DataQuality:
    rows: int
    columns: int
    missing_values: int
    duplicate_rows: int
    score: float


def normalize_column_name(name: object) -> str:
    """Convert uploaded CSV headers into predictable snake_case fields."""

    text = str(name).strip().lower()
    text = re.sub(r"[^0-9a-zA-Z]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "unnamed"


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of a dataframe with normalized column names."""

    normalized = df.copy()
    seen: dict[str, int] = {}
    columns: list[str] = []

    for column in normalized.columns:
        base = normalize_column_name(column)
        count = seen.get(base, 0)
        seen[base] = count + 1
        columns.append(base if count == 0 else f"{base}_{count + 1}")

    normalized.columns = columns
    return normalized


def load_demo_data() -> pd.DataFrame:
    """Load the generated demo CSV, creating an in-memory fallback if absent."""

    if DEMO_DATA_PATH.exists():
        return normalize_columns(pd.read_csv(DEMO_DATA_PATH))
    return generate_demo_data()


def load_csv(file_obj: str | Path | IO[str] | IO[bytes]) -> pd.DataFrame:
    """Load a user CSV upload and normalize its column names."""

    return normalize_columns(pd.read_csv(file_obj))


def data_quality(df: pd.DataFrame) -> DataQuality:
    """Return the legacy quality summary backed by governed assessment.

    New code should consume :func:`pulseiq.datasets.assess_dataset` directly so
    it can act on separate dimensions, issues, and capability readiness.
    """

    rows, columns = df.shape
    missing_values = int(df.isna().sum().sum())
    duplicate_rows = int(df.duplicated().sum())
    from .datasets import assess_dataset

    score = assess_dataset(df).composite_score

    return DataQuality(
        rows=int(rows),
        columns=int(columns),
        missing_values=missing_values,
        duplicate_rows=duplicate_rows,
        score=round(score, 1),
    )


def generate_demo_data(rows: int = 5000, seed: int = 42) -> pd.DataFrame:
    """Generate deterministic loan and transaction data for a strong portfolio demo."""

    rng = np.random.default_rng(seed)
    segments = np.array(["Retail", "Market Trader", "SME", "Agriculture", "Services"])
    regions = np.array(["Lagos", "Abuja", "Kano", "Accra", "Kumasi", "Nairobi", "Kigali"])
    employment = np.array(["Salaried", "Self-employed", "Contract", "Informal", "Unemployed"])
    business_types = np.array(["Shop", "Transport", "Food", "Education", "Health", "Fintech Agent"])

    dates = pd.date_range("2025-01-01", "2026-05-31", freq="D")
    customer_ids = rng.integers(10000, 13500, size=rows)
    income = rng.lognormal(mean=12.0, sigma=0.42, size=rows).round(0)
    income = np.clip(income, 65000, 950000)
    existing_debt = (income * rng.uniform(0.02, 0.65, size=rows)).round(0)
    loan_amount = (income * rng.uniform(0.18, 2.4, size=rows)).round(0)
    repayment_history_score = np.clip(rng.normal(72, 18, rows), 5, 100).round(1)
    transaction_frequency = rng.poisson(18, rows) + rng.integers(1, 18, rows)
    account_age_months = rng.integers(2, 96, rows)
    segment = rng.choice(segments, size=rows, p=[0.28, 0.24, 0.19, 0.14, 0.15])
    region = rng.choice(regions, size=rows)
    employment_status = rng.choice(employment, size=rows, p=[0.36, 0.33, 0.13, 0.13, 0.05])
    business_type = rng.choice(business_types, size=rows)
    date_values = rng.choice(dates, size=rows)

    base_transaction = rng.gamma(shape=2.4, scale=18500, size=rows)
    transaction_multiplier = np.where(segment == "SME", 1.45, np.where(segment == "Retail", 1.05, 0.9))
    transaction_amount = (base_transaction * transaction_multiplier).round(0)

    loan_to_income = loan_amount / np.maximum(income, 1)
    debt_to_income = existing_debt / np.maximum(income, 1)
    unemployment_pressure = np.isin(employment_status, ["Informal", "Unemployed"]).astype(float)
    risk_logit = (
        -2.4
        + 1.25 * loan_to_income
        + 1.05 * debt_to_income
        + 0.95 * unemployment_pressure
        - 0.035 * repayment_history_score
        + rng.normal(0, 0.38, size=rows)
    )
    probability_default = 1 / (1 + np.exp(-risk_logit))
    defaulted = rng.binomial(1, probability_default)
    risk_score = np.clip((probability_default * 100).round(1), 1, 99)
    risk_level = pd.cut(
        risk_score,
        bins=[0, 35, 65, 100],
        labels=["Low", "Medium", "High"],
        include_lowest=True,
    ).astype(str)

    df = pd.DataFrame(
        {
            "customer_id": [f"CUST-{value}" for value in customer_ids],
            "transaction_id": [f"TXN-{200000 + idx}" for idx in range(rows)],
            "date": pd.to_datetime(date_values).strftime("%Y-%m-%d"),
            "segment": segment,
            "region": region,
            "business_type": business_type,
            "employment_status": employment_status,
            "income": income.astype(float),
            "loan_amount": loan_amount.astype(float),
            "existing_debt": existing_debt.astype(float),
            "transaction_amount": transaction_amount.astype(float),
            "transaction_frequency": transaction_frequency.astype(int),
            "account_age_months": account_age_months.astype(int),
            "repayment_history_score": repayment_history_score.astype(float),
            "defaulted": defaulted.astype(int),
            "repayment_status": np.where(defaulted == 1, "Defaulted", "Repaid"),
            "risk_score": risk_score.astype(float),
            "risk_level": risk_level,
        }
    )

    high_amount = df["transaction_amount"] > df["transaction_amount"].mean() * 3
    low_repayment = df["repayment_history_score"] < 42
    loan_pressure = df["loan_amount"] > df["income"] * 1.55
    duplicate_candidates = df.index.isin(rng.choice(df.index, size=max(rows // 160, 8), replace=False))

    category = np.full(rows, "Normal", dtype=object)
    category[high_amount.to_numpy()] = "Unusually high amount"
    category[low_repayment.to_numpy()] = "High-risk repayment pattern"
    category[loan_pressure.to_numpy()] = "Loan-to-income mismatch"
    category[duplicate_candidates] = "Duplicate customer details"
    df["suspicious_category"] = category

    missing_income = rng.choice(df.index, size=max(rows // 240, 5), replace=False)
    missing_employment = rng.choice(df.index, size=max(rows // 280, 5), replace=False)
    df.loc[missing_income, "income"] = np.nan
    df.loc[missing_employment, "employment_status"] = np.nan

    duplicate_rows = df.sample(n=max(rows // 500, 4), random_state=seed + 7)
    replacement_index = rng.choice(df.index, size=len(duplicate_rows), replace=False)
    df.loc[replacement_index, :] = duplicate_rows.to_numpy()

    return normalize_columns(df)


def numeric_columns(df: pd.DataFrame) -> list[str]:
    """Return columns that can be treated as numeric after coercion."""

    result: list[str] = []
    for column in df.columns:
        coerced = pd.to_numeric(df[column], errors="coerce")
        if coerced.notna().mean() >= 0.65:
            result.append(column)
    return result


def first_existing(columns: Iterable[str], candidates: Iterable[str]) -> str | None:
    """Return the first candidate column found in a dataframe column list."""

    available = set(columns)
    for candidate in candidates:
        if candidate in available:
            return candidate
    return None
