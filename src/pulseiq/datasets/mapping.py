"""Authorized, versioned confirmation of dataset schema semantics."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol

from pulseiq.audit import AuditEvent
from pulseiq.identity import (
    AuthenticatedActor,
    AuthorizationRequest,
    AuthorizationService,
    Permission,
    ResourceScope,
)
from pulseiq.ingestion import GovernedConcept

from .normalization import NormalizedArtifactField
from .upload_contracts import DatasetVersionStatus, ImportJob, ImportJobStatus

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")
_ABSENT_HASH = f"sha256:{hashlib.sha256(b'absent').hexdigest()}"


class TargetType(StrEnum):
    STRING = "string"
    DECIMAL = "decimal"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"


class UnitSemantics(StrEnum):
    IDENTIFIER = "identifier"
    MONEY = "money"
    CURRENCY_CODE = "currency_code"
    TEMPORAL = "temporal"
    SCORE = "score"
    CATEGORY = "category"
    OUTCOME = "outcome"


class CurrencyMode(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    FIXED = "fixed"
    COLUMN = "column"


class PeriodSemantics(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    TRANSACTION = "transaction"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


class AmountDirection(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    SIGNED = "signed"
    INFLOW_POSITIVE = "inflow_positive"
    OUTFLOW_POSITIVE = "outflow_positive"


class TimeSemantics(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    EVENT_TIME = "event_time"
    EFFECTIVE_TIME = "effective_time"
    OBSERVATION_TIME = "observation_time"


@dataclass(frozen=True, slots=True)
class ConfirmedFieldMapping:
    source_column: str
    normalized_column: str
    concept: GovernedConcept
    target_type: TargetType
    nullable: bool
    unit: UnitSemantics
    currency_mode: CurrencyMode = CurrencyMode.NOT_APPLICABLE
    currency_code: str | None = None
    period: PeriodSemantics = PeriodSemantics.NOT_APPLICABLE
    amount_direction: AmountDirection = AmountDirection.NOT_APPLICABLE
    time_semantics: TimeSemantics = TimeSemantics.NOT_APPLICABLE

    def __post_init__(self) -> None:
        if not self.source_column.strip() or not self.normalized_column.strip():
            raise ValueError("Mapped field names must be non-empty.")
        if self.currency_mode is CurrencyMode.FIXED:
            if self.currency_code is None or _CURRENCY_PATTERN.fullmatch(self.currency_code) is None:
                raise ValueError("Fixed currency mappings require an uppercase three-letter code.")
        elif self.currency_code is not None:
            raise ValueError("Only fixed currency mappings may carry a currency code.")
        self._validate_concept_semantics()

    def _validate_concept_semantics(self) -> None:
        identifier_concepts = {GovernedConcept.CUSTOMER_ID, GovernedConcept.TRANSACTION_ID}
        money_concepts = {
            GovernedConcept.TRANSACTION_AMOUNT,
            GovernedConcept.INCOME,
            GovernedConcept.LOAN_AMOUNT,
            GovernedConcept.EXISTING_DEBT,
        }
        if self.concept in identifier_concepts and not (
            self.target_type is TargetType.STRING
            and self.unit is UnitSemantics.IDENTIFIER
            and self.currency_mode is CurrencyMode.NOT_APPLICABLE
            and self.period is PeriodSemantics.NOT_APPLICABLE
            and self.amount_direction is AmountDirection.NOT_APPLICABLE
            and self.time_semantics is TimeSemantics.NOT_APPLICABLE
        ):
            raise ValueError("Identifier mappings contain incompatible semantics.")
        if self.concept in money_concepts and not (
            self.target_type is TargetType.DECIMAL
            and self.unit is UnitSemantics.MONEY
            and self.currency_mode is not CurrencyMode.NOT_APPLICABLE
            and self.time_semantics is TimeSemantics.NOT_APPLICABLE
        ):
            raise ValueError("Money mappings require decimal type and explicit currency semantics.")
        if self.concept is GovernedConcept.TRANSACTION_AMOUNT and (
            self.period is not PeriodSemantics.TRANSACTION or self.amount_direction is AmountDirection.NOT_APPLICABLE
        ):
            raise ValueError("Transaction amounts require transaction period and direction semantics.")
        if self.concept is GovernedConcept.CURRENCY and not (
            self.target_type is TargetType.STRING
            and self.unit is UnitSemantics.CURRENCY_CODE
            and self.currency_mode is CurrencyMode.NOT_APPLICABLE
        ):
            raise ValueError("Currency columns must map to lexical currency-code semantics.")
        if self.concept is GovernedConcept.DATE and not (
            self.target_type in {TargetType.DATE, TargetType.DATETIME}
            and self.unit is UnitSemantics.TEMPORAL
            and self.time_semantics is not TimeSemantics.NOT_APPLICABLE
        ):
            raise ValueError("Date mappings require explicit temporal semantics.")

    @classmethod
    def identifier(
        cls,
        *,
        source_column: str,
        normalized_column: str,
        concept: GovernedConcept,
        nullable: bool = False,
    ) -> ConfirmedFieldMapping:
        return cls(
            source_column=source_column,
            normalized_column=normalized_column,
            concept=concept,
            target_type=TargetType.STRING,
            nullable=nullable,
            unit=UnitSemantics.IDENTIFIER,
        )

    @classmethod
    def currency_column(cls, *, source_column: str, normalized_column: str) -> ConfirmedFieldMapping:
        return cls(
            source_column=source_column,
            normalized_column=normalized_column,
            concept=GovernedConcept.CURRENCY,
            target_type=TargetType.STRING,
            nullable=False,
            unit=UnitSemantics.CURRENCY_CODE,
        )


@dataclass(frozen=True, slots=True)
class ArtifactMappingContext:
    dataset_version_id: str
    dataset_id: str
    organization_id: str
    workspace_id: str
    dataset_revision: int
    status: DatasetVersionStatus
    schema_fingerprint: str
    fields: tuple[NormalizedArtifactField, ...]


@dataclass(frozen=True, slots=True)
class ConfirmSchemaMapping:
    actor: AuthenticatedActor
    organization_id: str
    workspace_id: str
    dataset_version_id: str
    schema_fingerprint: str
    fields: tuple[ConfirmedFieldMapping, ...]
    request_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class SchemaMappingVersion:
    mapping_version_id: str
    dataset_version_id: str
    dataset_id: str
    organization_id: str
    workspace_id: str
    schema_fingerprint: str
    fields: tuple[ConfirmedFieldMapping, ...]
    confirmed_by: str
    confirmed_at: datetime
    reason: str


@dataclass(frozen=True, slots=True)
class MappingConfirmationResult:
    mapping: SchemaMappingVersion
    validation_job: ImportJob
    audit_event: AuditEvent
    dataset_status: DatasetVersionStatus


class MappingConfirmationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__("Schema mapping could not be confirmed.")
        self.code = code


class SchemaMappingRepository(Protocol):
    def get_context(
        self,
        *,
        dataset_version_id: str,
        organization_id: str,
        workspace_id: str,
    ) -> ArtifactMappingContext | None: ...

    def confirm_and_enqueue(
        self,
        mapping: SchemaMappingVersion,
        validation_job: ImportJob,
        audit_event: AuditEvent,
        *,
        expected_revision: int,
    ) -> None: ...


class SchemaMappingService:
    def __init__(
        self,
        repository: SchemaMappingRepository,
        authorization: AuthorizationService,
        *,
        clock: Callable[[], datetime],
        mapping_version_id_factory: Callable[[], str],
        validation_job_id_factory: Callable[[], str],
        audit_event_id_factory: Callable[[], str],
    ) -> None:
        self._repository = repository
        self._authorization = authorization
        self._clock = clock
        self._mapping_version_id_factory = mapping_version_id_factory
        self._validation_job_id_factory = validation_job_id_factory
        self._audit_event_id_factory = audit_event_id_factory

    def confirm(self, command: ConfirmSchemaMapping) -> MappingConfirmationResult:
        mapping_version_id = self._mapping_version_id_factory()
        actor = command.actor
        decision = self._authorization.authorize(
            AuthorizationRequest(
                actor=actor,
                permission=Permission.DATASET_MANAGE,
                scope=ResourceScope(
                    organization_id=command.organization_id,
                    workspace_id=command.workspace_id,
                    resource_type="schema_mapping_version",
                    resource_id=mapping_version_id,
                ),
            )
        )
        if not decision.allowed:
            raise MappingConfirmationError(decision.reason_code)
        context = self._repository.get_context(
            dataset_version_id=command.dataset_version_id,
            organization_id=command.organization_id,
            workspace_id=command.workspace_id,
        )
        if context is None or context.status is not DatasetVersionStatus.MAPPING_REQUIRED:
            raise MappingConfirmationError("dataset_not_mapping_required")
        if not re.fullmatch(r"[0-9a-f]{64}", command.schema_fingerprint) or command.schema_fingerprint != (
            context.schema_fingerprint
        ):
            raise MappingConfirmationError("schema_fingerprint_mismatch")
        self._validate_fields(command.fields, context.fields)

        confirmed_at = self._clock()
        mapping = SchemaMappingVersion(
            mapping_version_id=mapping_version_id,
            dataset_version_id=context.dataset_version_id,
            dataset_id=context.dataset_id,
            organization_id=context.organization_id,
            workspace_id=context.workspace_id,
            schema_fingerprint=context.schema_fingerprint,
            fields=command.fields,
            confirmed_by=actor.actor_id,
            confirmed_at=confirmed_at,
            reason=command.reason,
        )
        validation_job = ImportJob(
            job_id=self._validation_job_id_factory(),
            organization_id=context.organization_id,
            workspace_id=context.workspace_id,
            job_type="dataset.validate",
            status=ImportJobStatus.QUEUED,
            input_reference=MappingProxyType(
                {
                    "dataset_version_id": context.dataset_version_id,
                    "mapping_version_id": mapping.mapping_version_id,
                    "schema_fingerprint": mapping.schema_fingerprint,
                }
            ),
            idempotency_key=f"dataset.validate:{context.dataset_version_id}:{mapping.mapping_version_id}",
            created_at=confirmed_at,
        )
        event = AuditEvent(
            event_id=self._audit_event_id_factory(),
            occurred_at=confirmed_at,
            organization_id=context.organization_id,
            workspace_id=context.workspace_id,
            actor_id=mapping.confirmed_by,
            action="dataset.mapping_confirmed",
            target_type="schema_mapping_version",
            target_id=mapping.mapping_version_id,
            request_id=command.request_id,
            reason=command.reason,
            before_hash=_ABSENT_HASH,
            after_hash=self._mapping_hash(mapping),
        )
        self._repository.confirm_and_enqueue(
            mapping,
            validation_job,
            event,
            expected_revision=context.dataset_revision,
        )
        return MappingConfirmationResult(
            mapping=mapping,
            validation_job=validation_job,
            audit_event=event,
            dataset_status=DatasetVersionStatus.VALIDATING,
        )

    @staticmethod
    def _validate_fields(
        fields: tuple[ConfirmedFieldMapping, ...],
        artifact_fields: tuple[NormalizedArtifactField, ...],
    ) -> None:
        if not fields or len(fields) > len(artifact_fields):
            raise MappingConfirmationError("invalid_mapping_field_count")
        trusted = {(field.source_column, field.normalized_column) for field in artifact_fields}
        submitted = {(field.source_column, field.normalized_column) for field in fields}
        if len(submitted) != len(fields) or not submitted.issubset(trusted):
            raise MappingConfirmationError("mapping_column_mismatch")
        concepts = [field.concept for field in fields]
        if len(set(concepts)) != len(concepts):
            raise MappingConfirmationError("duplicate_governed_concept")
        uses_currency_column = any(field.currency_mode is CurrencyMode.COLUMN for field in fields)
        if uses_currency_column and GovernedConcept.CURRENCY not in concepts:
            raise MappingConfirmationError("currency_column_mapping_required")

    @staticmethod
    def _mapping_hash(mapping: SchemaMappingVersion) -> str:
        payload = json.dumps(
            {
                "confirmed_at": mapping.confirmed_at.isoformat(),
                "confirmed_by": mapping.confirmed_by,
                "dataset_id": mapping.dataset_id,
                "dataset_version_id": mapping.dataset_version_id,
                "fields": [
                    {
                        "amount_direction": field.amount_direction.value,
                        "concept": field.concept.value,
                        "currency_code": field.currency_code,
                        "currency_mode": field.currency_mode.value,
                        "normalized_column": field.normalized_column,
                        "nullable": field.nullable,
                        "period": field.period.value,
                        "source_column": field.source_column,
                        "target_type": field.target_type.value,
                        "time_semantics": field.time_semantics.value,
                        "unit": field.unit.value,
                    }
                    for field in mapping.fields
                ],
                "mapping_version_id": mapping.mapping_version_id,
                "organization_id": mapping.organization_id,
                "reason": mapping.reason,
                "schema_fingerprint": mapping.schema_fingerprint,
                "workspace_id": mapping.workspace_id,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return f"sha256:{hashlib.sha256(payload).hexdigest()}"
