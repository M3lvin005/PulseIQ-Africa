"""Spreadsheet-safe CSV serialization for user-controlled tabular values."""

from __future__ import annotations

import pandas as pd

from pulseiq.privacy import PrivacyPolicy, minimize_tabular_data

_FORMULA_PREFIXES = ("=", "+", "-", "@")


def _neutralize_cell(value: object) -> object:
    if not isinstance(value, str):
        return value
    candidate = value.lstrip(" \t\r\n")
    if value.startswith(("\t", "\r")) or candidate.startswith(_FORMULA_PREFIXES):
        return f"'{value}"
    return value


def safe_csv_bytes(dataframe: pd.DataFrame, *, privacy_policy: PrivacyPolicy | None = None) -> bytes:
    """Serialize a minimized copy after neutralizing spreadsheet formulas."""

    sanitized = (
        minimize_tabular_data(dataframe, policy=privacy_policy)[0]
        if privacy_policy is not None
        else dataframe.copy(deep=True)
    )
    for column in sanitized.columns:
        sanitized[column] = sanitized[column].map(_neutralize_cell)
    return sanitized.to_csv(index=False).encode("utf-8-sig")
