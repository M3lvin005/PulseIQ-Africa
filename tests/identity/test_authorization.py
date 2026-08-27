from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pulseiq.identity import (
    AuthenticatedActor,
    AuthorizationRequest,
    AuthorizationService,
    InMemoryMembershipRepository,
    InMemorySessionRepository,
    Membership,
    MembershipStatus,
    Permission,
    ResourceScope,
    Role,
    SessionRecord,
    SessionStatus,
)

NOW = datetime(2026, 8, 25, 12, tzinfo=UTC)


ROLE_PERMISSIONS = {
    Role.ADMIN: {
        Permission.WORKSPACE_VIEW,
        Permission.WORKSPACE_MANAGE,
        Permission.MEMBERSHIP_VIEW,
        Permission.MEMBERSHIP_MANAGE,
        Permission.AUDIT_VIEW,
    },
    Role.DATA_STEWARD: {
        Permission.WORKSPACE_VIEW,
        Permission.DATASET_VIEW,
        Permission.DATASET_UPLOAD,
        Permission.DATASET_MANAGE,
        Permission.QUALITY_OVERRIDE,
    },
    Role.ANALYST: {
        Permission.WORKSPACE_VIEW,
        Permission.DATASET_VIEW,
        Permission.PORTFOLIO_ANALYZE,
        Permission.MODEL_TRAIN,
        Permission.REPORT_VIEW,
        Permission.REPORT_GENERATE,
        Permission.ASSISTANT_QUERY,
    },
    Role.RISK_REVIEWER: {
        Permission.WORKSPACE_VIEW,
        Permission.DATASET_VIEW,
        Permission.PORTFOLIO_ANALYZE,
        Permission.RISK_REVIEW,
        Permission.REPORT_VIEW,
        Permission.REPORT_GENERATE,
        Permission.ASSISTANT_QUERY,
    },
    Role.APPROVER: {
        Permission.WORKSPACE_VIEW,
        Permission.DATASET_VIEW,
        Permission.MODEL_APPROVE,
        Permission.DECISION_APPROVE,
        Permission.REPORT_VIEW,
        Permission.REPORT_DELIVER,
        Permission.AUDIT_VIEW,
    },
    Role.AUDITOR: {
        Permission.WORKSPACE_VIEW,
        Permission.REPORT_VIEW,
        Permission.AUDIT_VIEW,
    },
    Role.READ_ONLY: {
        Permission.WORKSPACE_VIEW,
        Permission.REPORT_VIEW,
    },
}


def _sessions(actor: AuthenticatedActor) -> InMemorySessionRepository:
    return InMemorySessionRepository(
        [
            SessionRecord(
                session_id=actor.session_id,
                actor_id=actor.actor_id,
                authenticated_at=actor.authenticated_at,
                expires_at=actor.expires_at,
                status=SessionStatus.ACTIVE,
            )
        ]
    )


def test_membership_in_one_workspace_cannot_authorize_another_workspace() -> None:
    memberships = InMemoryMembershipRepository(
        [
            Membership(
                membership_id="membership-a",
                actor_id="actor-1",
                organization_id="organization-1",
                workspace_id="workspace-a",
                role=Role.ANALYST,
                status=MembershipStatus.ACTIVE,
            )
        ]
    )
    actor = AuthenticatedActor(
        actor_id="actor-1",
        session_id="session-1",
        authenticated_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(minutes=10),
        authentication_methods=("pwd",),
    )
    service = AuthorizationService(memberships, _sessions(actor), clock=lambda: NOW)
    request = AuthorizationRequest(
        actor=actor,
        permission=Permission.DATASET_VIEW,
        scope=ResourceScope(
            organization_id="organization-1",
            workspace_id="workspace-b",
            resource_type="dataset",
            resource_id="dataset-1",
        ),
    )

    decision = service.authorize(request)

    assert decision.allowed is False
    assert decision.reason_code == "membership_required"


def test_each_role_receives_exactly_its_least_privilege_permissions() -> None:
    all_permissions = set(Permission)
    for role, expected_permissions in ROLE_PERMISSIONS.items():
        memberships = InMemoryMembershipRepository(
            [
                Membership(
                    membership_id=f"membership-{role.value}",
                    actor_id="actor-1",
                    organization_id="organization-1",
                    workspace_id="workspace-1",
                    role=role,
                    status=MembershipStatus.ACTIVE,
                )
            ]
        )
        actor = AuthenticatedActor(
            actor_id="actor-1",
            session_id="session-1",
            authenticated_at=NOW - timedelta(minutes=5),
            expires_at=NOW + timedelta(minutes=10),
            authentication_methods=("pwd", "mfa"),
        )
        service = AuthorizationService(memberships, _sessions(actor), clock=lambda: NOW)
        scope = ResourceScope(
            organization_id="organization-1",
            workspace_id="workspace-1",
            resource_type="workspace",
            resource_id="workspace-1",
        )

        actual_permissions = {
            permission
            for permission in all_permissions
            if service.authorize(AuthorizationRequest(actor=actor, permission=permission, scope=scope)).allowed
        }

        assert actual_permissions == expected_permissions


def test_privileged_role_requires_mfa_before_authorization() -> None:
    memberships = InMemoryMembershipRepository(
        [
            Membership(
                membership_id="membership-admin",
                actor_id="actor-1",
                organization_id="organization-1",
                workspace_id="workspace-1",
                role=Role.ADMIN,
                status=MembershipStatus.ACTIVE,
            )
        ]
    )
    actor = AuthenticatedActor(
        actor_id="actor-1",
        session_id="session-1",
        authenticated_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(minutes=10),
        authentication_methods=("pwd",),
    )
    service = AuthorizationService(memberships, _sessions(actor), clock=lambda: NOW)
    request = AuthorizationRequest(
        actor=actor,
        permission=Permission.MEMBERSHIP_MANAGE,
        scope=ResourceScope(
            organization_id="organization-1",
            workspace_id="workspace-1",
            resource_type="workspace",
            resource_id="workspace-1",
        ),
    )

    decision = service.authorize(request)

    assert decision.allowed is False
    assert decision.reason_code == "mfa_required"


def test_repository_rejects_multiple_active_roles_for_one_actor_workspace() -> None:
    duplicate_scope = [
        Membership(
            membership_id="membership-analyst",
            actor_id="actor-1",
            organization_id="organization-1",
            workspace_id="workspace-1",
            role=Role.ANALYST,
            status=MembershipStatus.ACTIVE,
        ),
        Membership(
            membership_id="membership-approver",
            actor_id="actor-1",
            organization_id="organization-1",
            workspace_id="workspace-1",
            role=Role.APPROVER,
            status=MembershipStatus.ACTIVE,
        ),
    ]

    with pytest.raises(ValueError, match="one active membership"):
        InMemoryMembershipRepository(duplicate_scope)


def test_expired_server_session_is_rejected_before_membership_use() -> None:
    memberships = InMemoryMembershipRepository(
        [
            Membership(
                membership_id="membership-1",
                actor_id="actor-1",
                organization_id="organization-1",
                workspace_id="workspace-1",
                role=Role.READ_ONLY,
                status=MembershipStatus.ACTIVE,
            )
        ]
    )
    actor = AuthenticatedActor(
        actor_id="actor-1",
        session_id="expired-session",
        authenticated_at=NOW - timedelta(hours=1),
        expires_at=NOW - timedelta(seconds=1),
        authentication_methods=("pwd",),
    )
    decision = AuthorizationService(memberships, _sessions(actor), clock=lambda: NOW).authorize(
        AuthorizationRequest(
            actor=actor,
            permission=Permission.WORKSPACE_VIEW,
            scope=ResourceScope(
                organization_id="organization-1",
                workspace_id="workspace-1",
                resource_type="workspace",
                resource_id="workspace-1",
            ),
        )
    )

    assert decision.allowed is False
    assert decision.reason_code == "session_inactive"


def test_duplicate_membership_identifiers_are_rejected() -> None:
    membership = Membership(
        membership_id="membership-1",
        actor_id="actor-1",
        organization_id="organization-1",
        workspace_id="workspace-1",
        role=Role.READ_ONLY,
        status=MembershipStatus.ACTIVE,
    )

    with pytest.raises(ValueError, match="IDs must be unique"):
        InMemoryMembershipRepository([membership, membership])
