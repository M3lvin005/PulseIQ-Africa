from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pulseiq.audit import AuditEvent
from pulseiq.identity import (
    AuthenticatedActor,
    InvitationStatus,
    Membership,
    MembershipStatus,
    Role,
    SessionRecord,
    SessionStatus,
    WorkspaceInvitation,
)

NOW = datetime(2026, 8, 25, 14, tzinfo=UTC)


def test_session_timestamps_must_be_aware_and_ordered() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        AuthenticatedActor("actor-1", "session-1", datetime(2026, 8, 25), datetime(2026, 8, 26), ("pwd",))
    with pytest.raises(ValueError, match="must follow"):
        AuthenticatedActor("actor-1", "session-1", NOW, NOW, ("pwd",))


def test_revoked_membership_requires_aware_revocation_time() -> None:
    with pytest.raises(ValueError, match="must record"):
        Membership("membership-1", "actor-1", "organization-1", "workspace-1", Role.READ_ONLY, MembershipStatus.REVOKED)
    with pytest.raises(ValueError, match="Only a revoked"):
        Membership(
            "membership-1",
            "actor-1",
            "organization-1",
            "workspace-1",
            Role.READ_ONLY,
            MembershipStatus.ACTIVE,
            revoked_at=NOW,
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        Membership(
            "membership-1",
            "actor-1",
            "organization-1",
            "workspace-1",
            Role.READ_ONLY,
            MembershipStatus.REVOKED,
            revoked_at=datetime(2026, 8, 25),
        )


def test_revoked_session_cannot_predate_authentication() -> None:
    with pytest.raises(ValueError, match="cannot predate"):
        SessionRecord(
            session_id="session-1",
            actor_id="actor-1",
            authenticated_at=NOW,
            expires_at=NOW + timedelta(minutes=15),
            status=SessionStatus.REVOKED,
            revoked_at=NOW - timedelta(seconds=1),
        )


def test_invitation_acceptance_must_be_within_validity_window() -> None:
    with pytest.raises(ValueError, match="validity window"):
        WorkspaceInvitation(
            invitation_id="invitation-1",
            organization_id="organization-1",
            workspace_id="workspace-1",
            email_binding="hmac-sha256:binding",
            role=Role.READ_ONLY,
            status=InvitationStatus.ACCEPTED,
            token_digest="sha256:token",
            issued_by="actor-admin",
            issued_at=NOW,
            expires_at=NOW + timedelta(hours=1),
            accepted_by="actor-1",
            accepted_at=NOW + timedelta(hours=1),
        )


def test_audit_event_rejects_empty_fields_and_naive_time() -> None:
    values = {
        "event_id": "event-1",
        "occurred_at": NOW,
        "organization_id": "organization-1",
        "workspace_id": "workspace-1",
        "actor_id": "actor-1",
        "action": "membership.revoked",
        "target_type": "membership",
        "target_id": "membership-1",
        "request_id": "request-1",
        "reason": "Access is no longer required.",
        "before_hash": "sha256:before",
        "after_hash": "sha256:after",
    }
    with pytest.raises(ValueError, match="non-empty"):
        AuditEvent(**{**values, "reason": ""})
    with pytest.raises(ValueError, match="timezone-aware"):
        AuditEvent(**{**values, "occurred_at": datetime(2026, 8, 25)})
