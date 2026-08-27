"""Tests for conservative semantic mapping suggestions."""

from __future__ import annotations

from pulseiq.ingestion import (
    GovernedConcept,
    HeaderMapping,
    MappingStatus,
    suggest_semantic_mappings,
)


def test_critical_exact_field_is_suggested_but_never_auto_confirmed() -> None:
    mappings = suggest_semantic_mappings((HeaderMapping("Customer ID", "customer_id"),))

    assert len(mappings) == 1
    mapping = mappings[0]
    assert mapping.suggested_concept is GovernedConcept.CUSTOMER_ID
    assert mapping.status is MappingStatus.SUGGESTED
    assert mapping.confidence == 1.0
    assert mapping.confirmation_required is True


def test_known_alias_is_a_lower_confidence_suggestion() -> None:
    mapping = suggest_semantic_mappings((HeaderMapping("Txn Value", "txn_value"),))[0]

    assert mapping.suggested_concept is GovernedConcept.TRANSACTION_AMOUNT
    assert mapping.confidence == 0.85
    assert mapping.confirmation_required is True


def test_ambiguous_amount_field_remains_unmapped() -> None:
    mapping = suggest_semantic_mappings((HeaderMapping("Amount", "amount"),))[0]

    assert mapping.suggested_concept is None
    assert mapping.status is MappingStatus.UNMAPPED
    assert mapping.confidence == 0.0
    assert mapping.confirmation_required is False
