from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from pulseiq.datasets import IssueSeverity
from pulseiq.datasets.quality_overrides import (
    EffectiveQualityStatus,
    EffectiveValidationQuality,
    GetEffectiveValidationQuality,
    OverrideQualityWarning,
    QualityOverrideResult,
    QualityWarningContext,
    QualityWarningOverride,
    QualityWarningOverrideError,
    QualityWarningOverrideService,
    ValidationQualityQueryService,
)
from pulseiq.identity import (
    AuthenticatedActor,
    AuthorizationService,
    InMemoryMembershipRepository,
    InMemorySessionRepository,
    Membership,
    MembershipStatus,
    Role,
    SessionRecord,
    SessionStatus,
)

NOW = datetime(2026, 8, 25, 16, 0, tzinfo=UTC)


class FakeQualityOverrideRepository:
    def __init__(self, context: QualityWarningContext) -> None:
        self.context = context
        self.existing: QualityWarningOverride | None = None
        self.created: list[tuple[QualityWarningOverride, object]] = []
        self.quality = EffectiveValidationQuality(
            validation_run_id="run-1",
            dataset_version_id="version-1",
            organization_id="org-1",
            workspace_id="workspace-1",
            composite_score=92.5,
            blocking_issue_count=0,
            warning_issue_count=2,
            active_override_count=1,
            effective_warning_count=1,
            informational_issue_count=0,
            status=EffectiveQualityStatus.WARN,
            evaluated_at=NOW,
        )

    def get_warning_context(
        self,
        *,
        validation_run_id: str,
        issue_ordinal: int,
        organization_id: str,
        workspace_id: str,
    ) -> QualityWarningContext | None:
        return self.context

    def find_by_request_id(
        self,
        *,
        organization_id: str,
        workspace_id: str,
        request_id: str,
    ) -> QualityWarningOverride | None:
        return self.existing

    def create_override(self, override: QualityWarningOverride, audit_event: object) -> QualityWarningOverride:
        self.created.append((override, audit_event))
        return override

    def get_effective_quality(
        self,
        *,
        validation_run_id: str,
        organization_id: str,
        workspace_id: str,
        evaluated_at: datetime,
    ) -> EffectiveValidationQuality | None:
        return self.quality


def _actor_and_authorization(role: Role = Role.DATA_STEWARD) -> tuple[AuthenticatedActor, AuthorizationService]:
    actor = AuthenticatedActor(
        actor_id="actor-1",
        session_id="session-1",
        authenticated_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(minutes=10),
        authentication_methods=("federated", "mfa"),
    )
    authorization = AuthorizationService(
        InMemoryMembershipRepository(
            [
                Membership(
                    membership_id="membership-1",
                    actor_id=actor.actor_id,
                    organization_id="org-1",
                    workspace_id="workspace-1",
                    role=role,
                    status=MembershipStatus.ACTIVE,
                )
            ]
        ),
        InMemorySessionRepository(
            [
                SessionRecord(
                    session_id=actor.session_id,
                    actor_id=actor.actor_id,
                    authenticated_at=actor.authenticated_at,
                    expires_at=actor.expires_at,
                    status=SessionStatus.ACTIVE,
                )
            ]
        ),
        clock=lambda: NOW,
    )
    return actor, authorization


def _context() -> QualityWarningContext:
    return QualityWarningContext(
        validation_run_id="run-1",
        organization_id="org-1",
        workspace_id="workspace-1",
        dataset_version_id="version-1",
        issue_ordinal=2,
        rule_id="missing_values",
        rule_version="dataset-quality/1.0.0",
        severity=IssueSeverity.WARN,
        override_allowed=True,
    )


def test_data_steward_overrides_policy_approved_warning_with_expiry_and_audit() -> None:
    actor, authorization = _actor_and_authorization()
    repository = FakeQualityOverrideRepository(_context())
    service = QualityWarningOverrideService(
        repository,
        authorization,
        clock=lambda: NOW,
        override_id_factory=lambda: "override-1",
        audit_event_id_factory=lambda: "audit-override-1",
    )

    result = service.override(
        OverrideQualityWarning(
            actor=actor,
            organization_id="org-1",
            workspace_id="workspace-1",
            validation_run_id="run-1",
            issue_ordinal=2,
            expires_at=NOW + timedelta(days=30),
            request_id="request-override-1",
            reason="The source owner confirmed this bounded missingness is expected for the period.",
        )
    )

    assert isinstance(result, QualityOverrideResult)
    assert result.override.override_id == "override-1"
    assert result.override.overridden_by == actor.actor_id
    assert result.override.expires_at == NOW + timedelta(days=30)
    assert result.audit_event is not None
    assert result.audit_event.action == "quality.warning_overridden"
    assert repository.created == [(result.override, result.audit_event)]


def _command(actor: AuthenticatedActor) -> OverrideQualityWarning:
    return OverrideQualityWarning(
        actor=actor,
        organization_id="org-1",
        workspace_id="workspace-1",
        validation_run_id="run-1",
        issue_ordinal=2,
        expires_at=NOW + timedelta(days=30),
        request_id="request-override-1",
        reason="The source owner confirmed this bounded missingness is expected for the period.",
    )


def _service(
    repository: FakeQualityOverrideRepository,
    authorization: AuthorizationService,
) -> QualityWarningOverrideService:
    return QualityWarningOverrideService(
        repository,
        authorization,
        clock=lambda: NOW,
        override_id_factory=lambda: "override-1",
        audit_event_id_factory=lambda: "audit-override-1",
    )


def test_actor_without_quality_override_permission_is_denied_before_issue_lookup() -> None:
    actor, authorization = _actor_and_authorization(Role.ANALYST)
    repository = FakeQualityOverrideRepository(_context())

    with pytest.raises(QualityWarningOverrideError) as error:
        _service(repository, authorization).override(_command(actor))

    assert error.value.code == "permission_required"
    assert repository.created == []


@pytest.mark.parametrize(
    "context",
    [
        replace(_context(), severity=IssueSeverity.BLOCK),
        replace(_context(), override_allowed=False),
    ],
)
def test_only_policy_approved_warning_issues_can_be_overridden(context: QualityWarningContext) -> None:
    actor, authorization = _actor_and_authorization()
    repository = FakeQualityOverrideRepository(context)

    with pytest.raises(QualityWarningOverrideError) as error:
        _service(repository, authorization).override(_command(actor))

    assert error.value.code == "warning_override_not_allowed"
    assert repository.created == []


@pytest.mark.parametrize(
    "expires_at",
    [NOW + timedelta(minutes=14), NOW + timedelta(days=91)],
)
def test_override_expiry_is_bounded(expires_at: datetime) -> None:
    actor, authorization = _actor_and_authorization()
    repository = FakeQualityOverrideRepository(_context())

    with pytest.raises(QualityWarningOverrideError) as error:
        _service(repository, authorization).override(replace(_command(actor), expires_at=expires_at))

    assert error.value.code == "invalid_override_expiry"


def test_same_request_replays_without_duplicate_audit_but_changed_request_conflicts() -> None:
    actor, authorization = _actor_and_authorization()
    repository = FakeQualityOverrideRepository(_context())
    service = _service(repository, authorization)
    first = service.override(_command(actor))
    repository.existing = first.override
    repository.created.clear()

    replay = service.override(_command(actor))

    assert replay.override == first.override
    assert replay.audit_event is None
    assert repository.created == []

    with pytest.raises(QualityWarningOverrideError) as conflict:
        service.override(replace(_command(actor), reason="A materially different override reason was supplied."))
    assert conflict.value.code == "request_conflict"


def test_repository_context_must_match_the_authorized_tenant_and_issue() -> None:
    actor, authorization = _actor_and_authorization()
    repository = FakeQualityOverrideRepository(replace(_context(), workspace_id="workspace-2"))

    with pytest.raises(QualityWarningOverrideError) as error:
        _service(repository, authorization).override(_command(actor))

    assert error.value.code == "validation_warning_not_found"
    assert repository.created == []


def test_effective_quality_query_keeps_original_counts_and_excludes_active_overrides() -> None:
    actor, authorization = _actor_and_authorization(Role.ANALYST)
    repository = FakeQualityOverrideRepository(_context())
    service = ValidationQualityQueryService(repository, authorization, clock=lambda: NOW)

    quality = service.get(
        GetEffectiveValidationQuality(
            actor=actor,
            organization_id="org-1",
            workspace_id="workspace-1",
            validation_run_id="run-1",
        )
    )

    assert quality.warning_issue_count == 2
    assert quality.active_override_count == 1
    assert quality.effective_warning_count == 1
    assert quality.status is EffectiveQualityStatus.WARN
