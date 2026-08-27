"""Immutable contracts returned by dataset assessment."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class IssueSeverity(StrEnum):
    """Effect of a validation issue on downstream work."""

    BLOCK = "block"
    WARN = "warn"
    INFO = "info"


class AssessmentStatus(StrEnum):
    """Readiness state for a dataset capability."""

    READY = "ready"
    BLOCKED = "blocked"


class DatasetCapability(StrEnum):
    """User-visible operations whose inputs are assessed independently."""

    QUALITY_REVIEW = "quality_review"
    TRANSACTION_ANALYTICS = "transaction_analytics"
    CUSTOMER_ANALYTICS = "customer_analytics"
    REPAYMENT_ANALYTICS = "repayment_analytics"
    RISK_RULE_EVALUATION = "risk_rule_evaluation"
    MODEL_EXPLORATION = "model_exploration"


class QualityDimension(StrEnum):
    """Governed, separately visible quality dimensions."""

    COMPLETENESS = "completeness"
    VALIDITY = "validity"
    UNIQUENESS = "uniqueness"
    CONSISTENCY = "consistency"
    TIMELINESS = "timeliness"
    FITNESS = "fitness"


class DatasetCapabilityError(ValueError):
    """Raised when a caller tries to run an operation on unfit data."""


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One safe, actionable dataset validation result."""

    code: str
    severity: IssueSeverity
    dimension: QualityDimension
    message: str
    recovery: str
    affected_capabilities: tuple[DatasetCapability, ...]
    column: str | None = None
    count: int | None = None
    masked_examples: tuple[str, ...] = ()
    override_allowed: bool = False

    def __post_init__(self) -> None:
        """Keep issue evidence bounded and prevent unsafe override contracts."""

        if self.count is not None and self.count < 0:
            raise ValueError("Validation issue counts cannot be negative.")
        if len(self.masked_examples) > 3 or any(not value.startswith("sha256:") for value in self.masked_examples):
            raise ValueError("Validation issue examples must be bounded masked hashes.")
        if self.override_allowed and self.severity is not IssueSeverity.WARN:
            raise ValueError("Only warning issues may be policy-approved for override.")


@dataclass(frozen=True, slots=True)
class QualityDimensionScore:
    """A visible score for one quality dimension."""

    dimension: QualityDimension
    score: float

    def __post_init__(self) -> None:
        """Reject invalid scores at the contract boundary."""

        if not 0.0 <= self.score <= 100.0:
            raise ValueError("Quality dimension scores must be between 0 and 100.")


@dataclass(frozen=True, slots=True)
class CapabilityAssessment:
    """Readiness for one downstream dataset capability."""

    capability: DatasetCapability
    status: AssessmentStatus
    blocking_issue_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DatasetAssessment:
    """Complete assessment result consumed by UI and application services."""

    rows: int
    columns: int
    composite_score: float
    dimensions: tuple[QualityDimensionScore, ...]
    issues: tuple[ValidationIssue, ...]
    capabilities: tuple[CapabilityAssessment, ...]
    definition_version: str

    def __post_init__(self) -> None:
        """Validate summary invariants."""

        if self.rows < 0 or self.columns < 0:
            raise ValueError("Dataset shape cannot be negative.")
        if not 0.0 <= self.composite_score <= 100.0:
            raise ValueError("Composite score must be between 0 and 100.")

    @property
    def is_blocked(self) -> bool:
        """Return whether any capability has a blocking validation result."""

        return any(capability.status is AssessmentStatus.BLOCKED for capability in self.capabilities)

    def can(self, capability: DatasetCapability) -> bool:
        """Return whether the named operation has all required dataset inputs."""

        return any(
            item.capability is capability and item.status is AssessmentStatus.READY for item in self.capabilities
        )

    def require(self, capability: DatasetCapability) -> None:
        """Raise an actionable error unless the named operation is ready."""

        if self.can(capability):
            return
        reasons = [
            issue.message
            for issue in self.issues
            if issue.severity is IssueSeverity.BLOCK and capability in issue.affected_capabilities
        ]
        label = capability.value.replace("_", " ").capitalize()
        detail = " ".join(reasons) or "Required dataset inputs are unavailable or invalid."
        raise DatasetCapabilityError(f"{label} is blocked: {detail}")

    def score_for(self, dimension: QualityDimension) -> float:
        """Return the score for a named dimension."""

        for item in self.dimensions:
            if item.dimension is dimension:
                return item.score
        raise KeyError(f"No score exists for quality dimension {dimension.value!r}.")
