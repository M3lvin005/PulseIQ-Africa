from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pulseiq.identity import (
    AuthenticatedActor,
    AuthorizationRequest,
    AuthorizationService,
    ChangeMembershipRole,
    IdentityAdministrationService,
    InMemoryMembershipRepository,
    InMemorySessionRepository,
    Membership,
    MembershipAdministrationError,
    MembershipStatus,
    Permission,
    ResourceScope,
    RevokeMembership,
    Role,
    SessionRecord,
    SessionStatus,
)

NOW = datetime(2026, 8, 25, 13, tzinfo=UTC)


def _actor(actor_id: str) -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id=actor_id,
        session_id=f"session-{actor_id}",
        authenticated_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(minutes=10),
        authentication_methods=("pwd", "mfa"),
    )


def _sessions(*actor_ids: str) -> InMemorySessionRepository:
    actors = (_actor(actor_id) for actor_id in actor_ids)
    return InMemorySessionRepository(
        SessionRecord(
            session_id=actor.session_id,
            actor_id=actor.actor_id,
            authenticated_at=actor.authenticated_at,
            expires_at=actor.expires_at,
            status=SessionStatus.ACTIVE,
        )
        for actor in actors
    )


def test_authorized_role_change_is_immediate_and_returns_audit_evidence() -> None:
    memberships = InMemoryMembershipRepository(
        [
            Membership(
                membership_id="membership-admin",
                actor_id="actor-admin",
                organization_id="organization-1",
                workspace_id="workspace-1",
                role=Role.ADMIN,
                status=MembershipStatus.ACTIVE,
            ),
            Membership(
                membership_id="membership-target",
                actor_id="actor-target",
                organization_id="organization-1",
                workspace_id="workspace-1",
                role=Role.ANALYST,
                status=MembershipStatus.ACTIVE,
            ),
        ]
    )
    authorization = AuthorizationService(memberships, _sessions("actor-admin", "actor-target"), clock=lambda: NOW)
    administration = IdentityAdministrationService(
        memberships,
        authorization,
        clock=lambda: NOW,
        event_id_factory=lambda: "event-1",
    )

    result = administration.change_role(
        ChangeMembershipRole(
            actor=_actor("actor-admin"),
            organization_id="organization-1",
            workspace_id="workspace-1",
            membership_id="membership-target",
            new_role=Role.APPROVER,
            reason="Separate model training from approval.",
            request_id="request-1",
        )
    )

    assert result.membership.role is Role.APPROVER
    assert result.membership.revision == 2
    assert result.audit_event.action == "membership.role_changed"
    assert result.audit_event.actor_id == "actor-admin"
    assert result.audit_event.request_id == "request-1"
    assert result.audit_event.before_hash != result.audit_event.after_hash

    scope = ResourceScope(
        organization_id="organization-1",
        workspace_id="workspace-1",
        resource_type="model",
        resource_id="model-1",
    )
    can_approve = authorization.authorize(
        AuthorizationRequest(
            actor=_actor("actor-target"),
            permission=Permission.MODEL_APPROVE,
            scope=scope,
        )
    )
    can_train = authorization.authorize(
        AuthorizationRequest(
            actor=_actor("actor-target"),
            permission=Permission.MODEL_TRAIN,
            scope=scope,
        )
    )

    assert can_approve.allowed is True
    assert can_train.allowed is False


def test_last_active_admin_cannot_remove_its_own_admin_role() -> None:
    memberships = InMemoryMembershipRepository(
        [
            Membership(
                membership_id="membership-admin",
                actor_id="actor-admin",
                organization_id="organization-1",
                workspace_id="workspace-1",
                role=Role.ADMIN,
                status=MembershipStatus.ACTIVE,
            )
        ]
    )
    authorization = AuthorizationService(memberships, _sessions("actor-admin"), clock=lambda: NOW)
    administration = IdentityAdministrationService(
        memberships,
        authorization,
        clock=lambda: NOW,
        event_id_factory=lambda: "event-1",
    )

    with pytest.raises(MembershipAdministrationError) as error:
        administration.change_role(
            ChangeMembershipRole(
                actor=_actor("actor-admin"),
                organization_id="organization-1",
                workspace_id="workspace-1",
                membership_id="membership-admin",
                new_role=Role.READ_ONLY,
                reason="Remove administrator access.",
                request_id="request-1",
            )
        )

    assert error.value.code == "last_admin_required"


def test_revocation_is_immediate_and_returns_audit_evidence() -> None:
    memberships = InMemoryMembershipRepository(
        [
            Membership(
                membership_id="membership-admin",
                actor_id="actor-admin",
                organization_id="organization-1",
                workspace_id="workspace-1",
                role=Role.ADMIN,
                status=MembershipStatus.ACTIVE,
            ),
            Membership(
                membership_id="membership-target",
                actor_id="actor-target",
                organization_id="organization-1",
                workspace_id="workspace-1",
                role=Role.ANALYST,
                status=MembershipStatus.ACTIVE,
            ),
        ]
    )
    authorization = AuthorizationService(memberships, _sessions("actor-admin", "actor-target"), clock=lambda: NOW)
    administration = IdentityAdministrationService(
        memberships,
        authorization,
        clock=lambda: NOW,
        event_id_factory=lambda: "event-2",
    )

    result = administration.revoke(
        RevokeMembership(
            actor=_actor("actor-admin"),
            organization_id="organization-1",
            workspace_id="workspace-1",
            membership_id="membership-target",
            reason="Employment ended.",
            request_id="request-2",
        )
    )

    assert result.membership.status is MembershipStatus.REVOKED
    assert result.membership.revoked_at == NOW
    assert result.membership.revision == 2
    assert result.audit_event.action == "membership.revoked"

    decision = authorization.authorize(
        AuthorizationRequest(
            actor=_actor("actor-target"),
            permission=Permission.DATASET_VIEW,
            scope=ResourceScope(
                organization_id="organization-1",
                workspace_id="workspace-1",
                resource_type="dataset",
                resource_id="dataset-1",
            ),
        )
    )
    assert decision.allowed is False
    assert decision.reason_code == "membership_required"


def test_cross_workspace_membership_change_is_hidden_as_not_found() -> None:
    memberships = InMemoryMembershipRepository(
        [
            Membership(
                membership_id="membership-admin",
                actor_id="actor-admin",
                organization_id="organization-1",
                workspace_id="workspace-1",
                role=Role.ADMIN,
                status=MembershipStatus.ACTIVE,
            ),
            Membership(
                membership_id="membership-other",
                actor_id="actor-other",
                organization_id="organization-2",
                workspace_id="workspace-2",
                role=Role.ANALYST,
                status=MembershipStatus.ACTIVE,
            ),
        ]
    )
    service = IdentityAdministrationService(
        memberships,
        AuthorizationService(memberships, _sessions("actor-admin"), clock=lambda: NOW),
        clock=lambda: NOW,
        event_id_factory=lambda: "event-3",
    )

    with pytest.raises(MembershipAdministrationError) as error:
        service.change_role(
            ChangeMembershipRole(
                actor=_actor("actor-admin"),
                organization_id="organization-1",
                workspace_id="workspace-1",
                membership_id="membership-other",
                new_role=Role.READ_ONLY,
                reason="Attempt an out-of-scope change.",
                request_id="request-3",
            )
        )

    assert error.value.code == "membership_not_found"


def test_role_change_rejects_unchanged_role() -> None:
    memberships = InMemoryMembershipRepository(
        [
            Membership(
                membership_id="membership-admin",
                actor_id="actor-admin",
                organization_id="organization-1",
                workspace_id="workspace-1",
                role=Role.ADMIN,
                status=MembershipStatus.ACTIVE,
            ),
            Membership(
                membership_id="membership-target",
                actor_id="actor-target",
                organization_id="organization-1",
                workspace_id="workspace-1",
                role=Role.ANALYST,
                status=MembershipStatus.ACTIVE,
            ),
        ]
    )
    service = IdentityAdministrationService(
        memberships,
        AuthorizationService(memberships, _sessions("actor-admin"), clock=lambda: NOW),
        clock=lambda: NOW,
        event_id_factory=lambda: "event-4",
    )

    with pytest.raises(MembershipAdministrationError) as error:
        service.change_role(
            ChangeMembershipRole(
                actor=_actor("actor-admin"),
                organization_id="organization-1",
                workspace_id="workspace-1",
                membership_id="membership-target",
                new_role=Role.ANALYST,
                reason="No actual change.",
                request_id="request-4",
            )
        )

    assert error.value.code == "role_unchanged"


def test_non_admin_cannot_revoke_membership() -> None:
    memberships = InMemoryMembershipRepository(
        [
            Membership(
                membership_id="membership-analyst",
                actor_id="actor-analyst",
                organization_id="organization-1",
                workspace_id="workspace-1",
                role=Role.ANALYST,
                status=MembershipStatus.ACTIVE,
            ),
            Membership(
                membership_id="membership-target",
                actor_id="actor-target",
                organization_id="organization-1",
                workspace_id="workspace-1",
                role=Role.READ_ONLY,
                status=MembershipStatus.ACTIVE,
            ),
        ]
    )
    service = IdentityAdministrationService(
        memberships,
        AuthorizationService(memberships, _sessions("actor-analyst"), clock=lambda: NOW),
        clock=lambda: NOW,
        event_id_factory=lambda: "event-5",
    )

    with pytest.raises(MembershipAdministrationError) as error:
        service.revoke(
            RevokeMembership(
                actor=_actor("actor-analyst"),
                organization_id="organization-1",
                workspace_id="workspace-1",
                membership_id="membership-target",
                reason="Unauthorized removal.",
                request_id="request-5",
            )
        )

    assert error.value.code == "permission_required"


def test_last_active_admin_cannot_be_revoked() -> None:
    memberships = InMemoryMembershipRepository(
        [
            Membership(
                membership_id="membership-admin",
                actor_id="actor-admin",
                organization_id="organization-1",
                workspace_id="workspace-1",
                role=Role.ADMIN,
                status=MembershipStatus.ACTIVE,
            )
        ]
    )
    service = IdentityAdministrationService(
        memberships,
        AuthorizationService(memberships, _sessions("actor-admin"), clock=lambda: NOW),
        clock=lambda: NOW,
        event_id_factory=lambda: "event-6",
    )

    with pytest.raises(MembershipAdministrationError) as error:
        service.revoke(
            RevokeMembership(
                actor=_actor("actor-admin"),
                organization_id="organization-1",
                workspace_id="workspace-1",
                membership_id="membership-admin",
                reason="Remove the only administrator.",
                request_id="request-6",
            )
        )

    assert error.value.code == "last_admin_required"
