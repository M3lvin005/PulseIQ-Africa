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
    RevokeSession,
    Role,
    SessionAdministrationError,
    SessionAdministrationService,
    SessionRecord,
    SessionStatus,
)

NOW = datetime(2026, 8, 25, 16, tzinfo=UTC)


def test_logout_revokes_authoritative_session_before_browser_expiry() -> None:
    actor = AuthenticatedActor(
        actor_id="actor-1",
        session_id="session-1",
        authenticated_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(minutes=10),
        authentication_methods=("pwd", "mfa"),
    )
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
    sessions = InMemorySessionRepository(
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
    authorization = AuthorizationService(memberships, sessions, clock=lambda: NOW)
    request = AuthorizationRequest(
        actor=actor,
        permission=Permission.WORKSPACE_VIEW,
        scope=ResourceScope(
            organization_id="organization-1",
            workspace_id="workspace-1",
            resource_type="workspace",
            resource_id="workspace-1",
        ),
    )
    assert authorization.authorize(request).allowed

    administration = SessionAdministrationService(
        sessions,
        clock=lambda: NOW,
        event_id_factory=lambda: "event-session-revoked",
    )
    command = RevokeSession(
        actor=actor,
        organization_id="organization-1",
        workspace_id="workspace-1",
        reason="User signed out.",
        request_id="request-logout",
    )
    result = administration.logout(command)

    assert result.session.status is SessionStatus.REVOKED
    assert result.session.revoked_at == NOW
    assert result.audit_event.action == "session.revoked"
    denied = authorization.authorize(request)
    assert denied.allowed is False
    assert denied.reason_code == "session_inactive"

    with pytest.raises(SessionAdministrationError) as replay:
        administration.logout(command)
    assert replay.value.code == "session_inactive"


def test_unregistered_or_actor_mismatched_session_fails_closed() -> None:
    actor = AuthenticatedActor(
        actor_id="actor-1",
        session_id="session-1",
        authenticated_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(minutes=10),
        authentication_methods=("pwd",),
    )
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
    scope = ResourceScope(
        organization_id="organization-1",
        workspace_id="workspace-1",
        resource_type="workspace",
        resource_id="workspace-1",
    )
    request = AuthorizationRequest(actor=actor, permission=Permission.WORKSPACE_VIEW, scope=scope)

    missing = AuthorizationService(
        memberships,
        InMemorySessionRepository(),
        clock=lambda: NOW,
    ).authorize(request)
    mismatched = AuthorizationService(
        memberships,
        InMemorySessionRepository(
            [
                SessionRecord(
                    session_id="session-1",
                    actor_id="different-actor",
                    authenticated_at=actor.authenticated_at,
                    expires_at=actor.expires_at,
                    status=SessionStatus.ACTIVE,
                )
            ]
        ),
        clock=lambda: NOW,
    ).authorize(request)

    assert missing.reason_code == "session_inactive"
    assert mismatched.reason_code == "session_inactive"
