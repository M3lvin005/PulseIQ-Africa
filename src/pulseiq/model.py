"""Compatibility facade for the governed model-exploration package."""

from .modeling import (
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    ModelBundle,
    ModelEligibilityError,
    ModelInputError,
    assess_model_eligibility,
    score_customer,
    train_models,
)

__all__ = [
    "CATEGORICAL_FEATURES",
    "NUMERIC_FEATURES",
    "ModelBundle",
    "ModelEligibilityError",
    "ModelInputError",
    "assess_model_eligibility",
    "score_customer",
    "train_models",
]
