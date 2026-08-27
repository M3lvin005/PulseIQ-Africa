"""Reproducible execution of a confirmed dataset mapping and quality policy."""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, cast
from uuid import UUID

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pyarrow.lib import ArrowException

from pulseiq.ingestion import GovernedConcept
from pulseiq.jobs import ImportJobClaim, JobExecutionError

from .assessment import assess_dataset
from .contracts import (
    AssessmentStatus,
    CapabilityAssessment,
    DatasetAssessment,
    DatasetCapability,
    IssueSeverity,
    QualityDimension,
    ValidationIssue,
)
from .mapping import SchemaMappingVersion, TargetType
from .upload_contracts import DatasetVersionStatus

VALIDATION_POLICY_VERSION = "dataset-validation/1.0.0"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_REFERENCE_KEYS = frozenset({"dataset_version_id", "mapping_version_id", "schema_fingerprint"})
_CONCEPT_CAPABILITIES: dict[GovernedConcept, tuple[DatasetCapability, ...]] = {
    GovernedConcept.CUSTOMER_ID: (DatasetCapability.CUSTOMER_ANALYTICS,),
    GovernedConcept.TRANSACTION_ID: (DatasetCapability.TRANSACTION_ANALYTICS,),
    GovernedConcept.DATE: (DatasetCapability.TRANSACTION_ANALYTICS,),
    GovernedConcept.TRANSACTION_AMOUNT: (
        DatasetCapability.TRANSACTION_ANALYTICS,
        DatasetCapability.RISK_RULE_EVALUATION,
    ),
    GovernedConcept.CURRENCY: (DatasetCapability.TRANSACTION_ANALYTICS,),
    GovernedConcept.INCOME: (DatasetCapability.RISK_RULE_EVALUATION, DatasetCapability.MODEL_EXPLORATION),
    GovernedConcept.LOAN_AMOUNT: (DatasetCapability.RISK_RULE_EVALUATION, DatasetCapability.MODEL_EXPLORATION),
    GovernedConcept.EXISTING_DEBT: (DatasetCapability.RISK_RULE_EVALUATION, DatasetCapability.MODEL_EXPLORATION),
    GovernedConcept.REPAYMENT_HISTORY_SCORE: (
        DatasetCapability.RISK_RULE_EVALUATION,
        DatasetCapability.MODEL_EXPLORATION,
    ),
    GovernedConcept.DEFAULTED: (DatasetCapability.REPAYMENT_ANALYTICS, DatasetCapability.MODEL_EXPLORATION),
    GovernedConcept.REPAYMENT_STATUS: (
        DatasetCapability.REPAYMENT_ANALYTICS,
        DatasetCapability.MODEL_EXPLORATION,
    ),
}


class ValidationVerdict(StrEnum):
    """Terminal result of a completed validation execution."""

    PASSED = "passed"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class ValidationContext:
    """Trusted lineage needed to validate one immutable artifact."""

    dataset_version_id: str
    organization_id: str
    workspace_id: str
    dataset_revision: int
    status: DatasetVersionStatus
    artifact_object_key: str
    artifact_sha256: str
    schema_fingerprint: str
    artifact_row_count: int
    artifact_column_count: int
    mapping: SchemaMappingVersion
    existing_validation_run_id: str | None = None

    def __post_init__(self) -> None:
        if self.dataset_revision < 1:
            raise ValueError("Dataset validation revision must be positive.")
        if self.artifact_row_count < 1 or self.artifact_column_count < 1:
            raise ValueError("Validation artifact dimensions must be positive.")
        if any(_SHA256_PATTERN.fullmatch(value) is None for value in (self.artifact_sha256, self.schema_fingerprint)):
            raise ValueError("Validation lineage digests must be SHA-256 hex values.")
        if (
            self.mapping.dataset_version_id != self.dataset_version_id
            or self.mapping.organization_id != self.organization_id
            or self.mapping.workspace_id != self.workspace_id
            or self.mapping.schema_fingerprint != self.schema_fingerprint
        ):
            raise ValueError("Validation mapping does not match its trusted artifact context.")


@dataclass(frozen=True, slots=True)
class ValidationRun:
    """Immutable completed validation evidence for one mapping and policy."""

    validation_run_id: str
    organization_id: str
    workspace_id: str
    dataset_version_id: str
    mapping_version_id: str
    validation_policy_version: str
    artifact_sha256: str
    schema_fingerprint: str
    verdict: ValidationVerdict
    dataset_status: DatasetVersionStatus
    assessment: DatasetAssessment
    completed_at: datetime

    def __post_init__(self) -> None:
        if self.completed_at.tzinfo is None:
            raise ValueError("Validation completion time must be timezone-aware.")
        expected = (
            DatasetVersionStatus.READY if self.verdict is ValidationVerdict.PASSED else DatasetVersionStatus.FAILED
        )
        if self.dataset_status is not expected:
            raise ValueError("Validation verdict and dataset status do not agree.")

    @property
    def readiness_capability(self) -> DatasetCapability:
        return DatasetCapability.QUALITY_REVIEW


class DatasetValidationStorage(Protocol):
    def read_normalized(self, *, object_key: str, expected_sha256: str) -> bytes: ...


class DatasetValidationRepository(Protocol):
    def get_context(
        self,
        *,
        dataset_version_id: str,
        mapping_version_id: str,
        organization_id: str,
        workspace_id: str,
    ) -> ValidationContext | None: ...

    def complete_validation(self, run: ValidationRun, *, expected_revision: int) -> None: ...


class DatasetValidationStorageError(RuntimeError):
    """Safe classified normalized-artifact read failure."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__("The normalized dataset could not be read for validation.")
        self.code = code
        self.retryable = retryable


class DatasetValidationHandler:
    """Validate exact artifact bytes under confirmed semantics, without imputation."""

    def __init__(
        self,
        storage: DatasetValidationStorage,
        repository: DatasetValidationRepository,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._storage = storage
        self._repository = repository
        self._clock = clock

    def execute(self, claim: ImportJobClaim) -> None:
        reference = self._validate_reference(claim)
        context = self._repository.get_context(
            dataset_version_id=claim.dataset_version_id,
            mapping_version_id=reference["mapping_version_id"],
            organization_id=claim.organization_id,
            workspace_id=claim.workspace_id,
        )
        if (
            context is None
            or (
                context.status is not DatasetVersionStatus.VALIDATING
                and context.existing_validation_run_id != claim.job_id
            )
            or context.schema_fingerprint != reference["schema_fingerprint"]
            or context.mapping.mapping_version_id != reference["mapping_version_id"]
        ):
            raise JobExecutionError("validation_context_not_current", retryable=False)
        try:
            payload = self._storage.read_normalized(
                object_key=context.artifact_object_key,
                expected_sha256=context.artifact_sha256,
            )
        except DatasetValidationStorageError as exc:
            raise JobExecutionError(exc.code, retryable=exc.retryable) from exc
        if not hmac.compare_digest(hashlib.sha256(payload).hexdigest(), context.artifact_sha256):
            raise JobExecutionError("normalized_checksum_mismatch", retryable=False)
        dataframe = self._read_artifact(payload, context)
        assessment = self._assess_mapping(dataframe, context.mapping)
        verdict = (
            ValidationVerdict.PASSED if assessment.can(DatasetCapability.QUALITY_REVIEW) else ValidationVerdict.BLOCKED
        )
        run = ValidationRun(
            validation_run_id=claim.job_id,
            organization_id=claim.organization_id,
            workspace_id=claim.workspace_id,
            dataset_version_id=claim.dataset_version_id,
            mapping_version_id=context.mapping.mapping_version_id,
            validation_policy_version=VALIDATION_POLICY_VERSION,
            artifact_sha256=context.artifact_sha256,
            schema_fingerprint=context.schema_fingerprint,
            verdict=verdict,
            dataset_status=(
                DatasetVersionStatus.READY if verdict == ValidationVerdict.PASSED else DatasetVersionStatus.FAILED
            ),
            assessment=assessment,
            completed_at=self._clock(),
        )
        self._repository.complete_validation(run, expected_revision=context.dataset_revision)

    @staticmethod
    def _validate_reference(claim: ImportJobClaim) -> dict[str, str]:
        if claim.job_type != "dataset.validate" or set(claim.input_reference) != _REFERENCE_KEYS:
            raise JobExecutionError("invalid_validation_reference", retryable=False)
        reference = {key: value for key, value in claim.input_reference.items() if isinstance(value, str)}
        if (
            len(reference) != len(_REFERENCE_KEYS)
            or reference["dataset_version_id"] != claim.dataset_version_id
            or _SHA256_PATTERN.fullmatch(reference["schema_fingerprint"]) is None
            or not reference["mapping_version_id"]
        ):
            raise JobExecutionError("invalid_validation_reference", retryable=False)
        try:
            UUID(reference["dataset_version_id"])
            UUID(reference["mapping_version_id"])
        except ValueError as exc:
            raise JobExecutionError("invalid_validation_reference", retryable=False) from exc
        return reference

    @staticmethod
    def _read_artifact(payload: bytes, context: ValidationContext) -> pd.DataFrame:
        try:
            table = pq.read_table(pa.BufferReader(payload), page_checksum_verification=True)
        except (ArrowException, OSError, ValueError) as exc:
            raise JobExecutionError("invalid_normalized_parquet", retryable=False) from exc
        metadata = table.schema.metadata or {}
        if metadata.get(b"pulseiq.schema_fingerprint", b"").decode("ascii", errors="ignore") != (
            context.schema_fingerprint
        ):
            raise JobExecutionError("normalized_schema_mismatch", retryable=False)
        mapped_columns = {field.normalized_column for field in context.mapping.fields}
        if (
            table.num_rows != context.artifact_row_count
            or table.num_columns != context.artifact_column_count
            or not mapped_columns.issubset(table.column_names)
        ):
            raise JobExecutionError("normalized_schema_mismatch", retryable=False)
        return cast(pd.DataFrame, table.select(sorted(mapped_columns)).to_pandas())

    @classmethod
    def _assess_mapping(cls, dataframe: pd.DataFrame, mapping: SchemaMappingVersion) -> DatasetAssessment:
        canonical: dict[str, pd.Series[Any]] = {}
        mapping_issues: list[ValidationIssue] = []
        for field in mapping.fields:
            values = dataframe[field.normalized_column].astype("string").str.strip()
            values = values.mask(values.eq(""), pd.NA)
            valid = cls._valid_values(values, field.target_type)
            present = values.notna()
            missing_count = int((~present).sum())
            invalid = present & ~valid
            invalid_count = int(invalid.sum())
            affected = (DatasetCapability.QUALITY_REVIEW, *_CONCEPT_CAPABILITIES.get(field.concept, ()))
            if missing_count and not field.nullable:
                mapping_issues.append(
                    ValidationIssue(
                        code="missing_required_field",
                        severity=IssueSeverity.BLOCK,
                        dimension=QualityDimension.COMPLETENESS,
                        column=field.concept.value,
                        count=missing_count,
                        message=f"Required mapped field {field.concept.value} contains missing values.",
                        recovery="Populate the required source values or confirm a mapping with correct nullability.",
                        affected_capabilities=affected,
                    )
                )
            if invalid_count:
                required = not field.nullable
                mapping_issues.append(
                    ValidationIssue(
                        code="unparseable_required_field" if required else "unparseable_optional_field",
                        severity=IssueSeverity.BLOCK if required else IssueSeverity.WARN,
                        dimension=QualityDimension.VALIDITY,
                        column=field.concept.value,
                        count=invalid_count,
                        masked_examples=cls._masked_examples(values[invalid]),
                        override_allowed=not required,
                        message=(
                            f"Mapped field {field.concept.value} contains values incompatible with its target type."
                        ),
                        recovery="Correct the source format or confirm the field against the correct governed type.",
                        affected_capabilities=affected,
                    )
                )
            canonical[field.concept.value] = cls._canonical_values(values, field.target_type)

        assessment = assess_dataset(pd.DataFrame(canonical))
        issues = tuple(mapping_issues) + assessment.issues
        capabilities = tuple(
            CapabilityAssessment(
                capability=capability.capability,
                status=(
                    AssessmentStatus.BLOCKED
                    if any(
                        issue.severity is IssueSeverity.BLOCK and capability.capability in issue.affected_capabilities
                        for issue in issues
                    )
                    else AssessmentStatus.READY
                ),
                blocking_issue_codes=tuple(
                    issue.code
                    for issue in issues
                    if issue.severity is IssueSeverity.BLOCK and capability.capability in issue.affected_capabilities
                ),
            )
            for capability in assessment.capabilities
        )
        return replace(assessment, issues=issues, capabilities=capabilities)

    @staticmethod
    def _valid_values(values: pd.Series[Any], target_type: TargetType) -> pd.Series[bool]:
        if target_type is TargetType.STRING:
            return values.notna()
        if target_type is TargetType.DECIMAL:
            return pd.to_numeric(values, errors="coerce").notna()
        if target_type is TargetType.INTEGER:
            parsed = pd.to_numeric(values, errors="coerce")
            return parsed.notna() & parsed.mod(1).eq(0)
        if target_type is TargetType.BOOLEAN:
            return values.astype("string").str.lower().isin(("0", "1", "false", "true"))
        return pd.to_datetime(values, errors="coerce", format="mixed").notna()

    @staticmethod
    def _canonical_values(values: pd.Series[Any], target_type: TargetType) -> pd.Series[Any]:
        if target_type is TargetType.BOOLEAN:
            normalized = values.astype("string").str.lower().map({"0": 0, "1": 1, "false": 0, "true": 1})
            return normalized.astype("Int64")
        return values

    @staticmethod
    def _masked_examples(values: pd.Series[Any]) -> tuple[str, ...]:
        unique = sorted({str(value) for value in values.dropna().tolist()})[:3]
        return tuple(f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]}" for value in unique)
