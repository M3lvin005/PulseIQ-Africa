"""Authorized, expiring acknowledgements of policy-approved quality warnings."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from pulseiq.audit import AuditEvent
from pulseiq.identity import (
    AuthenticatedActor,
    AuthorizationRequest,
    AuthorizationService,
    Permission,
    ResourceScope,
)

from .contracts import IssueSeverity

_MINIMUM_OVERRIDE_LIFETIME = timedelta(minutes=15)
_MAXIMUM_OVERRIDE_LIFETIME = timedelta(days=90)


def _require_text(value: str, label: str, *, minimum: int = 1, maximum: int = 1000) -> None:
    if value != value.strip() or "\x00" in value or not minimum <= len(value) <= maximum:
        raise ValueError(f"{label} is invalid.")


@dataclass(frozen=True, slots=True)
class QualityWarningContext:
    """Trusted validation issue facts required for an override decision."""

    validation_run_id: str
    organization_id: str
    workspace_id: str
    dataset_version_id: str
    issue_ordinal: int
    rule_id: str
    rule_version: str
    severity: IssueSeverity
    override_allowed: bool

    def __post_init__(self) -> None:
        for value, label in (
            (self.validation_run_id, "Validation run ID"),
            (self.organization_id, "Organization ID"),
            (self.workspace_id, "Workspace ID"),
            (self.dataset_version_id, "Dataset version ID"),
            (self.rule_id, "Rule ID"),
            (self.rule_version, "Rule version"),
        ):
            _require_text(value, label, maximum=120)
        if not 1 <= self.issue_ordinal <= 1000:
            raise ValueError("Validation issue ordinal is invalid.")


@dataclass(frozen=True, slots=True)
class OverrideQualityWarning:
    """Actor command to acknowledge one bounded quality warning."""

    actor: AuthenticatedActor
    organization_id: str
    workspace_id: str
    validation_run_id: str
    issue_ordinal: int
    expires_at: datetime
    request_id: str
    reason: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.organization_id, "Organization ID"),
            (self.workspace_id, "Workspace ID"),
            (self.validation_run_id, "Validation run ID"),
            (self.request_id, "Request ID"),
        ):
            _require_text(value, label, maximum=120)
        _require_text(self.reason, "Override reason", minimum=10)
        if not 1 <= self.issue_ordinal <= 1000:
            raise ValueError("Validation issue ordinal is invalid.")
        if self.expires_at.tzinfo is None:
            raise ValueError("Override expiry must be timezone-aware.")


@dataclass(frozen=True, slots=True)
class QualityWarningOverride:
    """Immutable warning acknowledgement and its governance evidence."""

    override_id: str
    organization_id: str
    workspace_id: str
    dataset_version_id: str
    validation_run_id: str
    issue_ordinal: int
    rule_id: str
    rule_version: str
    overridden_by: str
    overridden_at: datetime
    expires_at: datetime
    request_id: str
    reason: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.override_id, "Override ID"),
            (self.organization_id, "Organization ID"),
            (self.workspace_id, "Workspace ID"),
            (self.dataset_version_id, "Dataset version ID"),
            (self.validation_run_id, "Validation run ID"),
            (self.rule_id, "Rule ID"),
            (self.rule_version, "Rule version"),
            (self.overridden_by, "Overriding actor ID"),
            (self.request_id, "Request ID"),
        ):
            _require_text(value, label, maximum=120)
        _require_text(self.reason, "Override reason", minimum=10)
        if self.overridden_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("Override timestamps must be timezone-aware.")
        if self.expires_at <= self.overridden_at:
            raise ValueError("Override expiry must follow its creation time.")

    def is_active_at(self, moment: datetime) -> bool:
        return self.overridden_at <= moment < self.expires_at


@dataclass(frozen=True, slots=True)
class QualityOverrideResult:
    override: QualityWarningOverride
    audit_event: AuditEvent | None


class EffectiveQualityStatus(StrEnum):
    """Derived validation quality after time-bounded warning acknowledgements."""

    BLOCKED = "blocked"
    WARN = "warn"
    HEALTHY = "healthy"


@dataclass(frozen=True, slots=True)
class GetEffectiveValidationQuality:
    actor: AuthenticatedActor
    organization_id: str
    workspace_id: str
    validation_run_id: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.organization_id, "Organization ID"),
            (self.workspace_id, "Workspace ID"),
            (self.validation_run_id, "Validation run ID"),
        ):
            _require_text(value, label, maximum=120)


@dataclass(frozen=True, slots=True)
class EffectiveValidationQuality:
    validation_run_id: str
    dataset_version_id: str
    organization_id: str
    workspace_id: str
    composite_score: float
    blocking_issue_count: int
    warning_issue_count: int
    active_override_count: int
    effective_warning_count: int
    informational_issue_count: int
    status: EffectiveQualityStatus
    evaluated_at: datetime

    def __post_init__(self) -> None:
        if not 0 <= self.composite_score <= 100:
            raise ValueError("Effective quality score must be between 0 and 100.")
        counts = (
            self.blocking_issue_count,
            self.warning_issue_count,
            self.active_override_count,
            self.effective_warning_count,
            self.informational_issue_count,
        )
        if any(count < 0 for count in counts):
            raise ValueError("Effective quality counts cannot be negative.")
        if self.active_override_count > self.warning_issue_count or self.effective_warning_count != (
            self.warning_issue_count - self.active_override_count
        ):
            raise ValueError("Effective warning counts are inconsistent.")
        expected = (
            EffectiveQualityStatus.BLOCKED
            if self.blocking_issue_count
            else EffectiveQualityStatus.WARN
            if self.effective_warning_count
            else EffectiveQualityStatus.HEALTHY
        )
        if self.status is not expected:
            raise ValueError("Effective quality status is inconsistent with issue counts.")
        if self.evaluated_at.tzinfo is None:
            raise ValueError("Effective quality evaluation time must be timezone-aware.")


class QualityWarningOverrideError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__("Quality warning could not be overridden.")
        self.code = code


class QualityWarningOverrideRepository(Protocol):
    def get_warning_context(
        self,
        *,
        validation_run_id: str,
        issue_ordinal: int,
        organization_id: str,
        workspace_id: str,
    ) -> QualityWarningContext | None: ...

    def find_by_request_id(
        self,
        *,
        organization_id: str,
        workspace_id: str,
        request_id: str,
    ) -> QualityWarningOverride | None: ...

    def create_override(
        self,
        override: QualityWarningOverride,
        audit_event: AuditEvent,
    ) -> QualityWarningOverride: ...


class ValidationQualityRepository(Protocol):
    def get_effective_quality(
        self,
        *,
        validation_run_id: str,
        organization_id: str,
        workspace_id: str,
        evaluated_at: datetime,
    ) -> EffectiveValidationQuality | None: ...


class ValidationQualityQueryError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__("Validation quality could not be read.")
        self.code = code


class ValidationQualityQueryService:
    """Return an authorized time-aware quality summary without rewriting evidence."""

    def __init__(
        self,
        repository: ValidationQualityRepository,
        authorization: AuthorizationService,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._repository = repository
        self._authorization = authorization
        self._clock = clock

    def get(self, query: GetEffectiveValidationQuality) -> EffectiveValidationQuality:
        decision = self._authorization.authorize(
            AuthorizationRequest(
                actor=query.actor,
                permission=Permission.DATASET_VIEW,
                scope=ResourceScope(
                    organization_id=query.organization_id,
                    workspace_id=query.workspace_id,
                    resource_type="validation_run",
                    resource_id=query.validation_run_id,
                ),
            )
        )
        if not decision.allowed:
            raise ValidationQualityQueryError(decision.reason_code)
        evaluated_at = self._clock()
        quality = self._repository.get_effective_quality(
            validation_run_id=query.validation_run_id,
            organization_id=query.organization_id,
            workspace_id=query.workspace_id,
            evaluated_at=evaluated_at,
        )
        if (
            quality is None
            or quality.organization_id != query.organization_id
            or quality.workspace_id != query.workspace_id
            or quality.validation_run_id != query.validation_run_id
            or quality.evaluated_at != evaluated_at
        ):
            raise ValidationQualityQueryError("validation_run_not_found")
        return quality


class QualityWarningOverrideService:
    """Authorize, validate, audit, and persist one warning override."""

    def __init__(
        self,
        repository: QualityWarningOverrideRepository,
        authorization: AuthorizationService,
        *,
        clock: Callable[[], datetime],
        override_id_factory: Callable[[], str],
        audit_event_id_factory: Callable[[], str],
    ) -> None:
        self._repository = repository
        self._authorization = authorization
        self._clock = clock
        self._override_id_factory = override_id_factory
        self._audit_event_id_factory = audit_event_id_factory

    def override(self, command: OverrideQualityWarning) -> QualityOverrideResult:
        decision = self._authorization.authorize(
            AuthorizationRequest(
                actor=command.actor,
                permission=Permission.QUALITY_OVERRIDE,
                scope=ResourceScope(
                    organization_id=command.organization_id,
                    workspace_id=command.workspace_id,
                    resource_type="validation_issue",
                    resource_id=f"{command.validation_run_id}:{command.issue_ordinal}",
                ),
            )
        )
        if not decision.allowed:
            raise QualityWarningOverrideError(decision.reason_code)
        existing = self._repository.find_by_request_id(
            organization_id=command.organization_id,
            workspace_id=command.workspace_id,
            request_id=command.request_id,
        )
        if existing is not None:
            if self._matches_replay(existing, command):
                return QualityOverrideResult(override=existing, audit_event=None)
            raise QualityWarningOverrideError("request_conflict")
        context = self._repository.get_warning_context(
            validation_run_id=command.validation_run_id,
            issue_ordinal=command.issue_ordinal,
            organization_id=command.organization_id,
            workspace_id=command.workspace_id,
        )
        if context is None:
            raise QualityWarningOverrideError("validation_warning_not_found")
        if (
            context.organization_id != command.organization_id
            or context.workspace_id != command.workspace_id
            or context.validation_run_id != command.validation_run_id
            or context.issue_ordinal != command.issue_ordinal
        ):
            raise QualityWarningOverrideError("validation_warning_not_found")
        if context.severity is not IssueSeverity.WARN or not context.override_allowed:
            raise QualityWarningOverrideError("warning_override_not_allowed")
        now = self._clock()
        lifetime = command.expires_at - now
        if not _MINIMUM_OVERRIDE_LIFETIME <= lifetime <= _MAXIMUM_OVERRIDE_LIFETIME:
            raise QualityWarningOverrideError("invalid_override_expiry")
        override = QualityWarningOverride(
            override_id=self._override_id_factory(),
            organization_id=context.organization_id,
            workspace_id=context.workspace_id,
            dataset_version_id=context.dataset_version_id,
            validation_run_id=context.validation_run_id,
            issue_ordinal=context.issue_ordinal,
            rule_id=context.rule_id,
            rule_version=context.rule_version,
            overridden_by=command.actor.actor_id,
            overridden_at=now,
            expires_at=command.expires_at,
            request_id=command.request_id,
            reason=command.reason,
        )
        audit_event = AuditEvent(
            event_id=self._audit_event_id_factory(),
            occurred_at=now,
            organization_id=context.organization_id,
            workspace_id=context.workspace_id,
            actor_id=command.actor.actor_id,
            action="quality.warning_overridden",
            target_type="validation_issue_override",
            target_id=override.override_id,
            request_id=command.request_id,
            reason=command.reason,
            before_hash=self._hash(self._context_payload(context)),
            after_hash=self._hash(self._override_payload(override)),
        )
        persisted = self._repository.create_override(override, audit_event)
        if persisted != override:
            if self._matches_replay(persisted, command):
                return QualityOverrideResult(override=persisted, audit_event=None)
            raise QualityWarningOverrideError("request_conflict")
        return QualityOverrideResult(override=persisted, audit_event=audit_event)

    @staticmethod
    def _matches_replay(existing: QualityWarningOverride, command: OverrideQualityWarning) -> bool:
        return (
            existing.organization_id == command.organization_id
            and existing.workspace_id == command.workspace_id
            and existing.validation_run_id == command.validation_run_id
            and existing.issue_ordinal == command.issue_ordinal
            and existing.overridden_by == command.actor.actor_id
            and existing.expires_at == command.expires_at
            and existing.reason == command.reason
        )

    @staticmethod
    def _hash(payload: dict[str, object]) -> str:
        serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        return f"sha256:{hashlib.sha256(serialized).hexdigest()}"

    @staticmethod
    def _context_payload(context: QualityWarningContext) -> dict[str, object]:
        return {
            "issue_ordinal": context.issue_ordinal,
            "override_allowed": context.override_allowed,
            "rule_id": context.rule_id,
            "rule_version": context.rule_version,
            "severity": context.severity.value,
            "validation_run_id": context.validation_run_id,
        }

    @staticmethod
    def _override_payload(override: QualityWarningOverride) -> dict[str, object]:
        return {
            "expires_at": override.expires_at.isoformat(),
            "issue_ordinal": override.issue_ordinal,
            "override_id": override.override_id,
            "overridden_at": override.overridden_at.isoformat(),
            "overridden_by": override.overridden_by,
            "reason": override.reason,
            "rule_id": override.rule_id,
            "rule_version": override.rule_version,
            "validation_run_id": override.validation_run_id,
        }
