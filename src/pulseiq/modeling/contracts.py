"""Immutable contracts for governed demonstration-model exploration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class EligibilityStatus(StrEnum):
    ELIGIBLE = "eligible"
    BLOCKED = "blocked"


class EligibilitySeverity(StrEnum):
    BLOCK = "block"
    WARN = "warn"


@dataclass(frozen=True, slots=True)
class ModelEligibilityPolicy:
    """Explicit prototype stability limits; not a production approval policy."""

    min_rows: int = 200
    min_class_rows: int = 30
    max_feature_missing_rate: float = 0.40
    max_category_cardinality: int = 100

    def __post_init__(self) -> None:
        if self.min_rows < 2 or self.min_class_rows < 1:
            raise ValueError("Model row and class limits must be positive and support two classes.")
        if not 0 <= self.max_feature_missing_rate < 1:
            raise ValueError("Maximum feature missing rate must be in [0, 1).")
        if self.max_category_cardinality < 2:
            raise ValueError("Maximum category cardinality must be at least two.")


@dataclass(frozen=True, slots=True)
class ModelEligibilityIssue:
    code: str
    severity: EligibilitySeverity
    message: str
    recovery: str
    column: str | None = None
    count: int | None = None


@dataclass(frozen=True, slots=True)
class FeatureProfile:
    column: str
    kind: str
    valid_count: int
    missing_count: int
    invalid_count: int
    unique_count: int


@dataclass(frozen=True, slots=True)
class ModelEligibility:
    status: EligibilityStatus
    total_rows: int
    eligible_rows: int
    excluded_target_rows: int
    class_counts: tuple[tuple[int, int], ...]
    target_column: str | None
    target_definition: str | None
    profiles: tuple[FeatureProfile, ...]
    issues: tuple[ModelEligibilityIssue, ...]
    definition_version: str = "model-eligibility/1.0.0"

    @property
    def blocking_issue_codes(self) -> tuple[str, ...]:
        return tuple(issue.code for issue in self.issues if issue.severity is EligibilitySeverity.BLOCK)

    @property
    def warning_issue_codes(self) -> tuple[str, ...]:
        return tuple(issue.code for issue in self.issues if issue.severity is EligibilitySeverity.WARN)

    def profile(self, column: str) -> FeatureProfile:
        for profile in self.profiles:
            if profile.column == column:
                return profile
        raise KeyError(f"No model feature profile exists for {column!r}.")


class ModelEligibilityError(ValueError):
    """Raised when training is attempted on ineligible data."""


class ModelInputError(ValueError):
    """Raised when an inference record lacks required model inputs."""


@dataclass(frozen=True, slots=True)
class ModelRunProvenance:
    run_id: str
    generated_at: datetime
    dataset_reference: str
    target_definition: str
    feature_definition: str
    split_strategy: str
    selection_split: str
    final_evaluation_split: str
    random_state: int
    train_rows: int
    validation_rows: int
    test_rows: int
    group_overlap_count: int
    dependency_versions: tuple[tuple[str, str], ...]
    code_version: str
    selection_metric: str = "f1_score"
    probability_status: str = "uncalibrated_demonstration_score"


@dataclass(slots=True)
class ModelBundle:
    name: str
    pipeline: Any
    metrics: dict[str, float]
    confusion_matrix: list[list[int]]
    leaderboard: list[dict[str, float | str]]
    feature_columns: list[str]
    eligibility: ModelEligibility
    provenance: ModelRunProvenance
    approval_status: str = "demonstration_unapproved"
