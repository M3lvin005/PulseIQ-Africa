"""Privacy-boundary tests for demo intake and evidence exports."""

from __future__ import annotations

import pandas as pd
import pytest

from pulseiq.privacy import (
    DEMO_PRIVACY_POLICY,
    PrivacyCategory,
    PrivacyFinding,
    PrivacyPolicy,
    assess_tabular_privacy,
    minimize_tabular_data,
)


def test_privacy_assessment_reports_category_and_count_without_values() -> None:
    dataframe = pd.DataFrame(
        {
            "customer_id": ["CUST-1"],
            "notes": ["Contact analyst@example.com"],
            "phone_number": ["+234 801 234 5678"],
        }
    )

    assessment = assess_tabular_privacy(dataframe)

    assert assessment.restricted
    assert {finding.detection for finding in assessment.findings} == {
        "email_pattern",
        "restricted_column",
    }
    rendered = repr(assessment)
    assert "analyst@example.com" not in rendered
    assert "+234 801 234 5678" not in rendered


def test_privacy_assessment_allows_pseudonymous_operational_identifiers() -> None:
    dataframe = pd.DataFrame(
        {
            "customer_id": ["CUST-1"],
            "transaction_id": ["TXN-1"],
            "transaction_amount": [1250.0],
        }
    )

    assert not assess_tabular_privacy(dataframe).restricted


def test_minimization_drops_identifier_columns_and_redacts_embedded_contact_data() -> None:
    dataframe = pd.DataFrame(
        {
            "customer_id": ["CUST-1"],
            "email_address": ["person@example.com"],
            "notes": ["Call +234 801 234 5678"],
        }
    )

    minimized, assessment = minimize_tabular_data(dataframe, policy=DEMO_PRIVACY_POLICY)

    assert assessment.restricted
    assert list(minimized.columns) == ["customer_id", "notes"]
    assert minimized.loc[0, "notes"] == "[REDACTED]"
    assert dataframe.loc[0, "email_address"] == "person@example.com"
    assert dataframe.loc[0, "notes"] == "Call +234 801 234 5678"


@pytest.mark.parametrize(
    "finding",
    [
        ("", "restricted_column", 1),
        ("column", "", 1),
        ("column", "restricted_column", -1),
    ],
)
def test_privacy_finding_rejects_invalid_safe_metadata(finding: tuple[str, str, int]) -> None:
    with pytest.raises(ValueError):
        PrivacyFinding(PrivacyCategory.CONTACT, *finding)


def test_privacy_policy_requires_positive_bound() -> None:
    with pytest.raises(ValueError, match="positive"):
        PrivacyPolicy(max_inspection_rows=0)


def test_value_inspection_can_be_disabled_for_preclassified_numeric_evidence() -> None:
    policy = PrivacyPolicy(max_inspection_rows=10, inspect_values=False)
    dataframe = pd.DataFrame({"metric": [123, 456], "notes": ["person@example.com", 42]})

    assessment = assess_tabular_privacy(dataframe, policy=policy)
    minimized, minimized_assessment = minimize_tabular_data(dataframe, policy=policy)

    assert not assessment.restricted
    assert not minimized_assessment.restricted
    assert minimized.equals(dataframe)


def test_privacy_patterns_cover_local_phone_and_iban_without_echoing_values() -> None:
    dataframe = pd.DataFrame(
        {
            "notes": ["Call 08012345678", "Transfer to GB82WEST12345698765432"],
            "numeric": [1, 2],
        }
    )

    assessment = assess_tabular_privacy(dataframe)

    assert {finding.detection for finding in assessment.findings} == {
        "nigerian_phone_pattern",
        "iban_pattern",
    }
    assert "08012345678" not in repr(assessment)
