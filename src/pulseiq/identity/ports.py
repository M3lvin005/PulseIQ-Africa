"""External ports required by the identity application boundary."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pulseiq.audit import AuditEvent

from .contracts import Membership, Role, SessionRecord, WorkspaceInvitation


class SessionStatusReader(Protocol):
    """Read current session state from the authoritative server-side store."""

    def find_active_session(
        self,
        *,
        session_id: str,
        actor_id: str,
        active_at: datetime,
    ) -> SessionRecord | None: ...


class SessionRepository(SessionStatusReader, Protocol):
    """Persist session revocation and audit evidence atomically."""

    def save_session_revocation(
        self,
        session: SessionRecord,
        audit_event: AuditEvent,
        *,
        expected_revision: int,
    ) -> None: ...


class MembershipReader(Protocol):
    """Read current membership from the authoritative server-side store."""

    def find_active(
        self,
        *,
        actor_id: str,
        organization_id: str,
        workspace_id: str,
    ) -> Membership | None: ...


class MembershipRepository(MembershipReader, Protocol):
    """Persist membership changes and their audit evidence atomically."""

    def get_in_scope(
        self,
        *,
        membership_id: str,
        organization_id: str,
        workspace_id: str,
    ) -> Membership | None: ...

    def save_change(
        self,
        membership: Membership,
        audit_event: AuditEvent,
        *,
        expected_revision: int,
    ) -> None: ...

    def count_active_role(
        self,
        *,
        organization_id: str,
        workspace_id: str,
        role: Role,
    ) -> int: ...


class InvitationRepository(MembershipReader, Protocol):
    """Persist one-time invitations and audit evidence atomically."""

    def has_pending_invitation(
        self,
        *,
        organization_id: str,
        workspace_id: str,
        email_binding: str,
        active_at: datetime,
    ) -> bool: ...

    def save_invitation(self, invitation: WorkspaceInvitation, audit_event: AuditEvent) -> None: ...

    def find_invitation_by_token_digest(self, token_digest: str) -> WorkspaceInvitation | None: ...

    def accept_invitation(
        self,
        invitation: WorkspaceInvitation,
        membership: Membership,
        audit_event: AuditEvent,
        *,
        expected_revision: int,
    ) -> None: ...
