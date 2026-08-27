"""Model training, lineage, and inference semantics tests."""

from __future__ import annotations

from pulseiq.data import generate_demo_data
from pulseiq.model import score_customer, train_models


def test_training_records_holdout_metrics_and_reproducible_lineage() -> None:
    bundle = train_models(generate_demo_data(rows=600), random_state=17)

    assert bundle.approval_status == "demonstration_unapproved"
    assert bundle.provenance.dataset_reference.startswith("dataframe:sha256:")
    assert bundle.provenance.target_definition == "defaulted.binary/1.0.0"
    assert bundle.provenance.random_state == 17
    assert bundle.provenance.selection_split == "validation"
    assert bundle.provenance.final_evaluation_split == "holdout"
    assert bundle.provenance.train_rows > bundle.provenance.validation_rows > 0
    assert bundle.provenance.test_rows > 0
    assert bundle.provenance.group_overlap_count == 0
    assert {"pr_auc", "brier_score", "log_loss"}.issubset(bundle.metrics)


def test_scoring_never_returns_an_approval_decision_or_handwritten_model_reason() -> None:
    bundle = train_models(generate_demo_data(rows=600), random_state=23)

    result = score_customer(
        bundle,
        {
            "income": 220_000,
            "loan_amount": 180_000,
            "repayment_history_score": 72,
            "existing_debt": 35_000,
            "transaction_frequency": 24,
            "account_age_months": 28,
            "employment_status": "Salaried",
            "segment": "Retail",
            "business_type": "Shop",
            "region": "Lagos",
        },
    )

    assert 0 <= result["model_score_percent"] <= 100
    assert result["routing"] == "Manual review required"
    assert result["explanation_status"] == "unavailable"
    assert "decision" not in result
    assert "reason" not in result
    assert "approve" not in str(result).lower()
