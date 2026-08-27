"""Deterministic local adapters for tests and non-production composition."""

from __future__ import annotations

import hmac
from collections.abc import Iterable
from datetime import datetime

from pulseiq.audit import AuditEvent

from .contracts import (
    InvitationStatus,
    Membership,
    MembershipStatus,
    Role,
    SessionRecord,
    SessionStatus,
    WorkspaceInvitation,
)


class InMemorySessionRepository:
    """Deterministic authoritative session store for tests and local composition."""

    def __init__(self, sessions: Iterable[SessionRecord] = ()) -> None:
        session_items = tuple(sessions)
        self._sessions = {session.session_id: session for session in session_items}
        if len(self._sessions) != len(session_items):
            raise ValueError("Session IDs must be unique.")
        self._audit_events: list[AuditEvent] = []

    def find_active_session(
        self,
        *,
        session_id: str,
        actor_id: str,
        active_at: datetime,
    ) -> SessionRecord | None:
        session = self._sessions.get(session_id)
        if (
            session is None
            or session.actor_id != actor_id
            or session.status is not SessionStatus.ACTIVE
            or not session.authenticated_at <= active_at < session.expires_at
        ):
            return None
        return session

    def save_session_revocation(
        self,
        session: SessionRecord,
        audit_event: AuditEvent,
        *,
        expected_revision: int,
    ) -> None:
        current = self._sessions.get(session.session_id)
        if current is None or current.revision != expected_revision or current.status is not SessionStatus.ACTIVE:
            raise RuntimeError("Session changed concurrently.")
        if audit_event.target_id != session.session_id:
            raise ValueError("Audit target must match the revoked session.")
        self._sessions[session.session_id] = session
        self._audit_events.append(audit_event)


class InMemoryMembershipRepository:
    """Authoritative membership reader backed by an isolated in-memory snapshot."""

    def __init__(self, memberships: Iterable[Membership] = ()) -> None:
        membership_items = tuple(memberships)
        self._memberships = {membership.membership_id: membership for membership in membership_items}
        if len(self._memberships) != len(membership_items):
            raise ValueError("Membership IDs must be unique.")
        self._audit_events: list[AuditEvent] = []
        self._invitations: dict[str, WorkspaceInvitation] = {}
        active_scopes: set[tuple[str, str, str]] = set()
        for membership in self._memberships.values():
            if membership.status is not MembershipStatus.ACTIVE:
                continue
            scope = (membership.actor_id, membership.organization_id, membership.workspace_id)
            if scope in active_scopes:
                raise ValueError("An actor can have only one active membership in a workspace.")
            active_scopes.add(scope)

    def find_active(
        self,
        *,
        actor_id: str,
        organization_id: str,
        workspace_id: str,
    ) -> Membership | None:
        return next(
            (
                membership
                for membership in self._memberships.values()
                if membership.actor_id == actor_id
                and membership.organization_id == organization_id
                and membership.workspace_id == workspace_id
                and membership.status is MembershipStatus.ACTIVE
            ),
            None,
        )

    def get_in_scope(
        self,
        *,
        membership_id: str,
        organization_id: str,
        workspace_id: str,
    ) -> Membership | None:
        membership = self._memberships.get(membership_id)
        if (
            membership is None
            or membership.organization_id != organization_id
            or membership.workspace_id != workspace_id
        ):
            return None
        return membership

    def save_change(
        self,
        membership: Membership,
        audit_event: AuditEvent,
        *,
        expected_revision: int,
    ) -> None:
        current = self._memberships.get(membership.membership_id)
        if current is None or current.revision != expected_revision:
            raise RuntimeError("Membership changed concurrently.")
        if audit_event.target_id != membership.membership_id:
            raise ValueError("Audit target must match the changed membership.")
        self._memberships[membership.membership_id] = membership
        self._audit_events.append(audit_event)

    def count_active_role(
        self,
        *,
        organization_id: str,
        workspace_id: str,
        role: Role,
    ) -> int:
        return sum(
            1
            for membership in self._memberships.values()
            if membership.organization_id == organization_id
            and membership.workspace_id == workspace_id
            and membership.role is role
            and membership.status is MembershipStatus.ACTIVE
        )

    def has_pending_invitation(
        self,
        *,
        organization_id: str,
        workspace_id: str,
        email_binding: str,
        active_at: datetime,
    ) -> bool:
        return any(
            invitation.organization_id == organization_id
            and invitation.workspace_id == workspace_id
            and invitation.email_binding == email_binding
            and invitation.status is InvitationStatus.PENDING
            and active_at < invitation.expires_at
            for invitation in self._invitations.values()
        )

    def save_invitation(self, invitation: WorkspaceInvitation, audit_event: AuditEvent) -> None:
        if invitation.invitation_id in self._invitations:
            raise RuntimeError("Invitation ID already exists.")
        if audit_event.target_id != invitation.invitation_id:
            raise ValueError("Audit target must match the invitation.")
        self._invitations[invitation.invitation_id] = invitation
        self._audit_events.append(audit_event)

    def find_invitation_by_token_digest(self, token_digest: str) -> WorkspaceInvitation | None:
        return next(
            (
                invitation
                for invitation in self._invitations.values()
                if hmac.compare_digest(invitation.token_digest, token_digest)
            ),
            None,
        )

    def accept_invitation(
        self,
        invitation: WorkspaceInvitation,
        membership: Membership,
        audit_event: AuditEvent,
        *,
        expected_revision: int,
    ) -> None:
        current = self._invitations.get(invitation.invitation_id)
        if current is None or current.revision != expected_revision or current.status is not InvitationStatus.PENDING:
            raise RuntimeError("Invitation changed concurrently.")
        if membership.membership_id in self._memberships:
            raise RuntimeError("Membership ID already exists.")
        if (
            self.find_active(
                actor_id=membership.actor_id,
                organization_id=membership.organization_id,
                workspace_id=membership.workspace_id,
            )
            is not None
        ):
            raise RuntimeError("Actor already has an active workspace membership.")
        if audit_event.target_id != invitation.invitation_id:
            raise ValueError("Audit target must match the invitation.")
        self._invitations[invitation.invitation_id] = invitation
        self._memberships[membership.membership_id] = membership
        self._audit_events.append(audit_event)
