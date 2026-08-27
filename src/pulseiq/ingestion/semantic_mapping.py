"""Conservative source-header suggestions for governed business concepts.

Suggestions are evidence for a future mapping UI. They are deliberately never
treated as human confirmation, especially for financial and identity fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .contracts import HeaderMapping


class GovernedConcept(StrEnum):
    CUSTOMER_ID = "customer_id"
    TRANSACTION_ID = "transaction_id"
    DATE = "date"
    TRANSACTION_AMOUNT = "transaction_amount"
    CURRENCY = "currency"
    INCOME = "income"
    LOAN_AMOUNT = "loan_amount"
    EXISTING_DEBT = "existing_debt"
    REPAYMENT_HISTORY_SCORE = "repayment_history_score"
    DEFAULTED = "defaulted"
    REPAYMENT_STATUS = "repayment_status"


class MappingStatus(StrEnum):
    UNMAPPED = "unmapped"
    SUGGESTED = "suggested"


@dataclass(frozen=True)
class SemanticMappingSuggestion:
    source_column: str
    normalized_column: str
    suggested_concept: GovernedConcept | None
    status: MappingStatus
    confidence: float
    confirmation_required: bool


_ALIASES: dict[str, GovernedConcept] = {
    "client_id": GovernedConcept.CUSTOMER_ID,
    "borrower_id": GovernedConcept.CUSTOMER_ID,
    "txn_id": GovernedConcept.TRANSACTION_ID,
    "transaction_date": GovernedConcept.DATE,
    "txn_date": GovernedConcept.DATE,
    "txn_value": GovernedConcept.TRANSACTION_AMOUNT,
    "transaction_value": GovernedConcept.TRANSACTION_AMOUNT,
    "ccy": GovernedConcept.CURRENCY,
    "monthly_income": GovernedConcept.INCOME,
    "principal": GovernedConcept.LOAN_AMOUNT,
    "debt_balance": GovernedConcept.EXISTING_DEBT,
    "repayment_score": GovernedConcept.REPAYMENT_HISTORY_SCORE,
    "is_default": GovernedConcept.DEFAULTED,
    "loan_status": GovernedConcept.REPAYMENT_STATUS,
}

_CRITICAL_CONCEPTS = frozenset(GovernedConcept)


def suggest_semantic_mappings(
    header_mappings: tuple[HeaderMapping, ...],
) -> tuple[SemanticMappingSuggestion, ...]:
    """Return exact or allowlisted suggestions without auto-confirming meaning."""

    suggestions: list[SemanticMappingSuggestion] = []
    for header in header_mappings:
        concept: GovernedConcept | None
        confidence: float
        try:
            concept = GovernedConcept(header.normalized)
            confidence = 1.0
        except ValueError:
            concept = _ALIASES.get(header.normalized)
            confidence = 0.85 if concept is not None else 0.0

        suggestions.append(
            SemanticMappingSuggestion(
                source_column=header.source,
                normalized_column=header.normalized,
                suggested_concept=concept,
                status=MappingStatus.SUGGESTED if concept is not None else MappingStatus.UNMAPPED,
                confidence=confidence,
                confirmation_required=concept in _CRITICAL_CONCEPTS if concept is not None else False,
            )
        )
    return tuple(suggestions)
