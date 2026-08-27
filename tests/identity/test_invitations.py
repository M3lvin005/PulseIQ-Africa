from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pulseiq.identity import (
    AcceptWorkspaceInvitation,
    AuthenticatedActor,
    AuthorizationRequest,
    AuthorizationService,
    IdentityInvitationService,
    InMemoryMembershipRepository,
    InMemorySessionRepository,
    InvitationError,
    InvitationStatus,
    InviteWorkspaceMember,
    Membership,
    MembershipStatus,
    Permission,
    ResourceScope,
    Role,
    SessionRecord,
    SessionStatus,
)

NOW = datetime(2026, 8, 25, 15, tzinfo=UTC)
RAW_TOKEN = "fixed-one-time-invitation-token-000001"


def _admin() -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id="actor-admin",
        session_id="session-admin",
        authenticated_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(minutes=10),
        authentication_methods=("pwd", "mfa"),
    )


def _sessions(*identities: tuple[str, str]) -> InMemorySessionRepository:
    return InMemorySessionRepository(
        SessionRecord(
            session_id=session_id,
            actor_id=actor_id,
            authenticated_at=NOW - timedelta(hours=1),
            expires_at=NOW + timedelta(hours=2),
            status=SessionStatus.ACTIVE,
        )
        for actor_id, session_id in identities
    )


def test_admin_issues_bounded_invitation_without_persisting_raw_email_or_token() -> None:
    repository = InMemoryMembershipRepository(
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
    service = IdentityInvitationService(
        repository,
        AuthorizationService(repository, _sessions(("actor-admin", "session-admin")), clock=lambda: NOW),
        email_binding_key=b"test-email-binding-key-32-bytes!",
        clock=lambda: NOW,
        invitation_id_factory=lambda: "invitation-1",
        token_factory=lambda: RAW_TOKEN,
    )

    result = service.issue(
        InviteWorkspaceMember(
            actor=_admin(),
            organization_id="organization-1",
            workspace_id="workspace-1",
            invitee_email="New.Reviewer@example.com ",
            role=Role.RISK_REVIEWER,
            expires_in=timedelta(hours=72),
            reason="Add the assigned risk reviewer.",
            request_id="request-invite-1",
        )
    )

    assert result.token == RAW_TOKEN
    assert result.invitation.status is InvitationStatus.PENDING
    assert result.invitation.expires_at == NOW + timedelta(hours=72)
    assert result.invitation.token_digest.startswith("sha256:")
    assert result.invitation.email_binding.startswith("hmac-sha256:")
    assert RAW_TOKEN not in repr(result.invitation)
    assert "new.reviewer@example.com" not in repr(result.invitation).lower()
    assert result.audit_event.action == "membership.invitation_issued"
    assert result.audit_event.target_id == "invitation-1"


def test_verified_recipient_accepts_once_and_receives_immediate_workspace_access() -> None:
    repository = InMemoryMembershipRepository(
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
    authorization = AuthorizationService(
        repository,
        _sessions(("actor-admin", "session-admin"), ("actor-new", "session-new")),
        clock=lambda: NOW,
    )
    service = IdentityInvitationService(
        repository,
        authorization,
        email_binding_key=b"test-email-binding-key-32-bytes!",
        clock=lambda: NOW,
        invitation_id_factory=lambda: "invitation-1",
        membership_id_factory=lambda: "membership-new",
        token_factory=lambda: RAW_TOKEN,
    )
    service.issue(
        InviteWorkspaceMember(
            actor=_admin(),
            organization_id="organization-1",
            workspace_id="workspace-1",
            invitee_email="new.reviewer@example.com",
            role=Role.RISK_REVIEWER,
            expires_in=timedelta(hours=72),
            reason="Add the assigned risk reviewer.",
            request_id="request-invite-1",
        )
    )
    recipient = AuthenticatedActor(
        actor_id="actor-new",
        session_id="session-new",
        authenticated_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=14),
        authentication_methods=("federated", "mfa"),
    )

    result = service.accept(
        AcceptWorkspaceInvitation(
            actor=recipient,
            verified_email="NEW.REVIEWER@example.com",
            token=RAW_TOKEN,
            request_id="request-accept-1",
        )
    )

    assert result.invitation.status is InvitationStatus.ACCEPTED
    assert result.invitation.accepted_by == "actor-new"
    assert result.membership.status is MembershipStatus.ACTIVE
    assert result.membership.role is Role.RISK_REVIEWER
    assert result.membership.actor_id == "actor-new"
    assert result.audit_event.action == "membership.invitation_accepted"
    assert authorization.authorize(
        AuthorizationRequest(
            actor=recipient,
            permission=Permission.RISK_REVIEW,
            scope=ResourceScope(
                organization_id="organization-1",
                workspace_id="workspace-1",
                resource_type="case",
                resource_id="case-1",
            ),
        )
    ).allowed

    try:
        service.accept(
            AcceptWorkspaceInvitation(
                actor=recipient,
                verified_email="new.reviewer@example.com",
                token=RAW_TOKEN,
                request_id="request-replay",
            )
        )
    except InvitationError as error:
        assert error.code == "invitation_unavailable"
    else:  # pragma: no cover - explicit replay-safety assertion
        raise AssertionError("An accepted invitation token must not be reusable.")


def test_expired_invitation_is_rejected_and_does_not_block_reissue() -> None:
    current_time = [NOW]
    invitation_ids = iter(("invitation-old", "invitation-fresh"))
    tokens = iter((RAW_TOKEN, "fresh-one-time-invitation-token-000002"))
    repository = InMemoryMembershipRepository(
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
    service = IdentityInvitationService(
        repository,
        AuthorizationService(
            repository,
            _sessions(
                ("actor-admin", "session-admin"),
                ("actor-admin", "session-admin-fresh"),
                ("actor-new", "session-new"),
            ),
            clock=lambda: current_time[0],
        ),
        email_binding_key=b"test-email-binding-key-32-bytes!",
        clock=lambda: current_time[0],
        invitation_id_factory=lambda: next(invitation_ids),
        token_factory=lambda: next(tokens),
    )
    command = InviteWorkspaceMember(
        actor=_admin(),
        organization_id="organization-1",
        workspace_id="workspace-1",
        invitee_email="new.reviewer@example.com",
        role=Role.RISK_REVIEWER,
        expires_in=timedelta(minutes=15),
        reason="Add the assigned risk reviewer.",
        request_id="request-invite-old",
    )
    service.issue(command)
    current_time[0] = NOW + timedelta(minutes=16)
    recipient = AuthenticatedActor(
        actor_id="actor-new",
        session_id="session-new",
        authenticated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        authentication_methods=("federated", "mfa"),
    )

    with pytest.raises(InvitationError) as expired:
        service.accept(
            AcceptWorkspaceInvitation(
                actor=recipient,
                verified_email="new.reviewer@example.com",
                token=RAW_TOKEN,
                request_id="request-accept-expired",
            )
        )

    assert expired.value.code == "invitation_expired"
    replacement = service.issue(
        InviteWorkspaceMember(
            actor=AuthenticatedActor(
                actor_id="actor-admin",
                session_id="session-admin-fresh",
                authenticated_at=current_time[0] - timedelta(minutes=1),
                expires_at=current_time[0] + timedelta(minutes=14),
                authentication_methods=("pwd", "mfa"),
            ),
            organization_id=command.organization_id,
            workspace_id=command.workspace_id,
            invitee_email=command.invitee_email,
            role=command.role,
            expires_in=command.expires_in,
            reason=command.reason,
            request_id="request-invite-fresh",
        )
    )
    assert replacement.invitation.invitation_id == "invitation-fresh"


def test_wrong_verified_email_does_not_consume_invitation() -> None:
    repository = InMemoryMembershipRepository(
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
    service = IdentityInvitationService(
        repository,
        AuthorizationService(
            repository,
            _sessions(("actor-admin", "session-admin"), ("actor-new", "session-new")),
            clock=lambda: NOW,
        ),
        email_binding_key=b"test-email-binding-key-32-bytes!",
        clock=lambda: NOW,
        invitation_id_factory=lambda: "invitation-1",
        membership_id_factory=lambda: "membership-new",
        token_factory=lambda: RAW_TOKEN,
    )
    service.issue(
        InviteWorkspaceMember(
            actor=_admin(),
            organization_id="organization-1",
            workspace_id="workspace-1",
            invitee_email="recipient@example.com",
            role=Role.READ_ONLY,
            expires_in=timedelta(hours=1),
            reason="Grant report access.",
            request_id="request-issue",
        )
    )
    recipient = AuthenticatedActor(
        actor_id="actor-new",
        session_id="session-new",
        authenticated_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=14),
        authentication_methods=("federated",),
    )

    with pytest.raises(InvitationError) as wrong_recipient:
        service.accept(
            AcceptWorkspaceInvitation(
                actor=recipient,
                verified_email="attacker@example.com",
                token=RAW_TOKEN,
                request_id="request-wrong-recipient",
            )
        )
    assert wrong_recipient.value.code == "invitation_unavailable"

    accepted = service.accept(
        AcceptWorkspaceInvitation(
            actor=recipient,
            verified_email="recipient@example.com",
            token=RAW_TOKEN,
            request_id="request-correct-recipient",
        )
    )
    assert accepted.invitation.status is InvitationStatus.ACCEPTED


def test_privileged_invitation_acceptance_requires_mfa() -> None:
    repository = InMemoryMembershipRepository(
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
    service = IdentityInvitationService(
        repository,
        AuthorizationService(
            repository,
            _sessions(("actor-admin", "session-admin"), ("actor-new", "session-new")),
            clock=lambda: NOW,
        ),
        email_binding_key=b"test-email-binding-key-32-bytes!",
        clock=lambda: NOW,
        invitation_id_factory=lambda: "invitation-1",
        token_factory=lambda: RAW_TOKEN,
    )
    service.issue(
        InviteWorkspaceMember(
            actor=_admin(),
            organization_id="organization-1",
            workspace_id="workspace-1",
            invitee_email="analyst@example.com",
            role=Role.ANALYST,
            expires_in=timedelta(hours=1),
            reason="Add an analyst.",
            request_id="request-issue",
        )
    )

    with pytest.raises(InvitationError) as weak_authentication:
        service.accept(
            AcceptWorkspaceInvitation(
                actor=AuthenticatedActor(
                    actor_id="actor-new",
                    session_id="session-new",
                    authenticated_at=NOW - timedelta(minutes=1),
                    expires_at=NOW + timedelta(minutes=14),
                    authentication_methods=("federated",),
                ),
                verified_email="analyst@example.com",
                token=RAW_TOKEN,
                request_id="request-accept",
            )
        )
    assert weak_authentication.value.code == "mfa_required"


def test_invitation_issuance_is_admin_only_and_deduplicated() -> None:
    repository = InMemoryMembershipRepository(
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
                membership_id="membership-viewer",
                actor_id="actor-viewer",
                organization_id="organization-1",
                workspace_id="workspace-1",
                role=Role.READ_ONLY,
                status=MembershipStatus.ACTIVE,
            ),
        ]
    )
    service = IdentityInvitationService(
        repository,
        AuthorizationService(
            repository,
            _sessions(("actor-admin", "session-admin"), ("actor-viewer", "session-viewer")),
            clock=lambda: NOW,
        ),
        email_binding_key=b"test-email-binding-key-32-bytes!",
        clock=lambda: NOW,
        invitation_id_factory=lambda: "invitation-1",
        token_factory=lambda: RAW_TOKEN,
    )
    command = InviteWorkspaceMember(
        actor=_admin(),
        organization_id="organization-1",
        workspace_id="workspace-1",
        invitee_email="recipient@example.com",
        role=Role.READ_ONLY,
        expires_in=timedelta(hours=1),
        reason="Grant report access.",
        request_id="request-issue",
    )
    service.issue(command)

    with pytest.raises(InvitationError) as duplicate:
        service.issue(command)
    assert duplicate.value.code == "pending_invitation_exists"

    with pytest.raises(InvitationError) as unauthorized:
        service.issue(
            InviteWorkspaceMember(
                actor=AuthenticatedActor(
                    actor_id="actor-viewer",
                    session_id="session-viewer",
                    authenticated_at=NOW - timedelta(minutes=1),
                    expires_at=NOW + timedelta(minutes=14),
                    authentication_methods=("pwd",),
                ),
                organization_id="organization-1",
                workspace_id="workspace-1",
                invitee_email="second@example.com",
                role=Role.READ_ONLY,
                expires_in=timedelta(hours=1),
                reason="Grant report access.",
                request_id="request-unauthorized",
            )
        )
    assert unauthorized.value.code == "permission_required"
