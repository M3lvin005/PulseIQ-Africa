"""Public seam for governed model exploration."""

from .contracts import (
    EligibilitySeverity,
    EligibilityStatus,
    FeatureProfile,
    ModelBundle,
    ModelEligibility,
    ModelEligibilityError,
    ModelEligibilityIssue,
    ModelEligibilityPolicy,
    ModelInputError,
    ModelRunProvenance,
)
from .eligibility import (
    CATEGORICAL_FEATURES,
    DEFAULT_MODEL_ELIGIBILITY_POLICY,
    FEATURE_COLUMNS,
    NUMERIC_FEATURES,
    assess_model_eligibility,
    map_model_target,
)
from .training import score_customer, train_models

__all__ = [
    "CATEGORICAL_FEATURES",
    "DEFAULT_MODEL_ELIGIBILITY_POLICY",
    "FEATURE_COLUMNS",
    "NUMERIC_FEATURES",
    "EligibilitySeverity",
    "EligibilityStatus",
    "FeatureProfile",
    "ModelBundle",
    "ModelEligibility",
    "ModelEligibilityError",
    "ModelEligibilityIssue",
    "ModelEligibilityPolicy",
    "ModelInputError",
    "ModelRunProvenance",
    "assess_model_eligibility",
    "map_model_target",
    "score_customer",
    "train_models",
]
