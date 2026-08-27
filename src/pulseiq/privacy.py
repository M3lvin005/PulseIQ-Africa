"""Fail-closed privacy inspection and minimization for tabular evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

import pandas as pd

from .data import normalize_column_name


class PrivacyCategory(StrEnum):
    """Stable non-sensitive classifications for restricted data findings."""

    DIRECT_IDENTIFIER = "direct_identifier"
    CONTACT = "contact"
    GOVERNMENT_IDENTIFIER = "government_identifier"
    FINANCIAL_ACCOUNT = "financial_account"


@dataclass(frozen=True, slots=True)
class PrivacyFinding:
    """One privacy finding that deliberately excludes the matched value."""

    category: PrivacyCategory
    column: str
    detection: str
    affected_rows: int

    def __post_init__(self) -> None:
        if not self.column or self.column.isspace():
            raise ValueError("Privacy finding column must be non-empty.")
        if not self.detection or self.detection.isspace():
            raise ValueError("Privacy finding detection must be non-empty.")
        if self.affected_rows < 0:
            raise ValueError("Privacy finding affected rows cannot be negative.")


@dataclass(frozen=True, slots=True)
class PrivacyAssessment:
    """Bounded privacy inspection result without source values."""

    inspected_rows: int
    findings: tuple[PrivacyFinding, ...]

    @property
    def restricted(self) -> bool:
        return bool(self.findings)


@dataclass(frozen=True, slots=True)
class PrivacyPolicy:
    """Conservative controls for the synthetic/de-identified prototype boundary."""

    max_inspection_rows: int = 100_000
    inspect_values: bool = True

    def __post_init__(self) -> None:
        if self.max_inspection_rows < 1:
            raise ValueError("Privacy inspection row limit must be positive.")


DEMO_PRIVACY_POLICY = PrivacyPolicy()


_SENSITIVE_COLUMNS: dict[str, PrivacyCategory] = {
    "account_number": PrivacyCategory.FINANCIAL_ACCOUNT,
    "bank_account": PrivacyCategory.FINANCIAL_ACCOUNT,
    "bank_account_number": PrivacyCategory.FINANCIAL_ACCOUNT,
    "bvn": PrivacyCategory.GOVERNMENT_IDENTIFIER,
    "card_number": PrivacyCategory.FINANCIAL_ACCOUNT,
    "date_of_birth": PrivacyCategory.DIRECT_IDENTIFIER,
    "dob": PrivacyCategory.DIRECT_IDENTIFIER,
    "drivers_license": PrivacyCategory.GOVERNMENT_IDENTIFIER,
    "email": PrivacyCategory.CONTACT,
    "email_address": PrivacyCategory.CONTACT,
    "first_name": PrivacyCategory.DIRECT_IDENTIFIER,
    "full_name": PrivacyCategory.DIRECT_IDENTIFIER,
    "home_address": PrivacyCategory.CONTACT,
    "last_name": PrivacyCategory.DIRECT_IDENTIFIER,
    "mobile": PrivacyCategory.CONTACT,
    "mobile_number": PrivacyCategory.CONTACT,
    "national_id": PrivacyCategory.GOVERNMENT_IDENTIFIER,
    "nin": PrivacyCategory.GOVERNMENT_IDENTIFIER,
    "pan": PrivacyCategory.FINANCIAL_ACCOUNT,
    "passport_number": PrivacyCategory.GOVERNMENT_IDENTIFIER,
    "phone": PrivacyCategory.CONTACT,
    "phone_number": PrivacyCategory.CONTACT,
    "postal_address": PrivacyCategory.CONTACT,
    "street_address": PrivacyCategory.CONTACT,
    "surname": PrivacyCategory.DIRECT_IDENTIFIER,
}

_EMAIL_PATTERN = re.compile(r"(?i)\b[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+\b")
_INTERNATIONAL_PHONE_PATTERN = re.compile(r"(?<!\w)\+\d[\d\s().-]{7,}\d(?!\w)")
_NIGERIAN_PHONE_PATTERN = re.compile(r"(?<!\d)0(?:70|71|80|81|90|91)\d{8}(?!\d)")
_IBAN_PATTERN = re.compile(r"(?i)\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")

_VALUE_PATTERNS: tuple[tuple[str, PrivacyCategory, re.Pattern[str]], ...] = (
    ("email_pattern", PrivacyCategory.CONTACT, _EMAIL_PATTERN),
    ("international_phone_pattern", PrivacyCategory.CONTACT, _INTERNATIONAL_PHONE_PATTERN),
    ("nigerian_phone_pattern", PrivacyCategory.CONTACT, _NIGERIAN_PHONE_PATTERN),
    ("iban_pattern", PrivacyCategory.FINANCIAL_ACCOUNT, _IBAN_PATTERN),
)


def assess_tabular_privacy(
    dataframe: pd.DataFrame,
    *,
    policy: PrivacyPolicy = DEMO_PRIVACY_POLICY,
) -> PrivacyAssessment:
    """Inspect a bounded sample and report only categories/counts, never values."""

    inspected = dataframe.head(policy.max_inspection_rows)
    findings: list[PrivacyFinding] = []
    header_restricted: set[str] = set()

    for raw_column in dataframe.columns:
        column = str(raw_column)
        normalized = normalize_column_name(column)
        category = _SENSITIVE_COLUMNS.get(normalized)
        if category is None:
            continue
        header_restricted.add(column)
        findings.append(
            PrivacyFinding(
                category=category,
                column=column,
                detection="restricted_column",
                affected_rows=len(inspected),
            )
        )

    if policy.inspect_values:
        for raw_column in inspected.columns:
            column = str(raw_column)
            if column in header_restricted or not _is_textual(inspected[raw_column]):
                continue
            values = inspected[raw_column].dropna().astype(str)
            for detection, category, pattern in _VALUE_PATTERNS:
                affected = int(values.str.contains(pattern, regex=True, na=False).sum())
                if affected:
                    findings.append(
                        PrivacyFinding(
                            category=category,
                            column=column,
                            detection=detection,
                            affected_rows=affected,
                        )
                    )

    return PrivacyAssessment(inspected_rows=len(inspected), findings=tuple(findings))


def minimize_tabular_data(
    dataframe: pd.DataFrame,
    *,
    policy: PrivacyPolicy = DEMO_PRIVACY_POLICY,
) -> tuple[pd.DataFrame, PrivacyAssessment]:
    """Drop direct-identifier columns and redact matching textual cells in a copy."""

    assessment = assess_tabular_privacy(dataframe, policy=policy)
    minimized = dataframe.copy(deep=True)
    restricted_columns = {finding.column for finding in assessment.findings if finding.detection == "restricted_column"}
    if restricted_columns:
        minimized = minimized.drop(
            columns=[column for column in minimized.columns if str(column) in restricted_columns]
        )

    if policy.inspect_values:
        for column in minimized.columns:
            if not _is_textual(minimized[column]):
                continue
            minimized[column] = minimized[column].map(_redact_restricted_value)
    return minimized, assessment


def _is_textual(series: pd.Series) -> bool:
    return bool(pd.api.types.is_object_dtype(series.dtype) or pd.api.types.is_string_dtype(series.dtype))


def _redact_restricted_value(value: object) -> object:
    if not isinstance(value, str):
        return value
    if any(pattern.search(value) for _, _, pattern in _VALUE_PATTERNS):
        return "[REDACTED]"
    return value
