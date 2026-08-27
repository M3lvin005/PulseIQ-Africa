"""Secure one-time workspace invitation issuance."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from uuid import uuid4

from pulseiq.audit import AuditEvent

from .authorization import AuthorizationService
from .contracts import (
    AcceptWorkspaceInvitation,
    AuthorizationPolicy,
    AuthorizationRequest,
    InvitationAcceptanceResult,
    InvitationIssueResult,
    InvitationStatus,
    InviteWorkspaceMember,
    Membership,
    MembershipStatus,
    Permission,
    ResourceScope,
    WorkspaceInvitation,
)
from .ports import InvitationRepository

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ABSENT_HASH = f"sha256:{hashlib.sha256(b'absent').hexdigest()}"


class InvitationError(RuntimeError):
    """Safe invitation failure with a stable non-sensitive code."""

    def __init__(self, code: str) -> None:
        super().__init__("Workspace invitation could not be completed.")
        self.code = code


def _normalize_email(email: str) -> str:
    normalized = email.strip().casefold()
    if not _EMAIL_PATTERN.fullmatch(normalized):
        raise InvitationError("invalid_email")
    return normalized


def _invitation_hash(invitation: WorkspaceInvitation) -> str:
    payload = json.dumps(
        {
            "email_binding": invitation.email_binding,
            "accepted_at": invitation.accepted_at.isoformat() if invitation.accepted_at else None,
            "accepted_by": invitation.accepted_by,
            "expires_at": invitation.expires_at.isoformat(),
            "invitation_id": invitation.invitation_id,
            "issued_at": invitation.issued_at.isoformat(),
            "issued_by": invitation.issued_by,
            "organization_id": invitation.organization_id,
            "revision": invitation.revision,
            "role": invitation.role.value,
            "status": invitation.status.value,
            "token_digest": invitation.token_digest,
            "workspace_id": invitation.workspace_id,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _acceptance_hash(invitation: WorkspaceInvitation, membership: Membership | None) -> str:
    membership_state = None
    if membership is not None:
        membership_state = {
            "activated_at": membership.activated_at.isoformat() if membership.activated_at else None,
            "actor_id": membership.actor_id,
            "membership_id": membership.membership_id,
            "organization_id": membership.organization_id,
            "revision": membership.revision,
            "role": membership.role.value,
            "status": membership.status.value,
            "workspace_id": membership.workspace_id,
        }
    payload = json.dumps(
        {
            "invitation_hash": _invitation_hash(invitation),
            "membership": membership_state,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


class IdentityInvitationService:
    """Issue workspace invitations without persisting raw recipient data or tokens."""

    def __init__(
        self,
        invitations: InvitationRepository,
        authorization: AuthorizationService,
        *,
        email_binding_key: bytes,
        clock: Callable[[], datetime],
        invitation_id_factory: Callable[[], str],
        membership_id_factory: Callable[[], str] | None = None,
        event_id_factory: Callable[[], str] | None = None,
        token_factory: Callable[[], str] | None = None,
        policy: AuthorizationPolicy | None = None,
    ) -> None:
        if len(email_binding_key) < 32:
            raise ValueError("Email binding key must contain at least 32 bytes.")
        self._invitations = invitations
        self._authorization = authorization
        self._email_binding_key = email_binding_key
        self._clock = clock
        self._invitation_id_factory = invitation_id_factory
        self._membership_id_factory = membership_id_factory or (lambda: secrets.token_urlsafe(18))
        self._event_id_factory = event_id_factory or (lambda: str(uuid4()))
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._policy = policy or AuthorizationPolicy()

    def issue(self, command: InviteWorkspaceMember) -> InvitationIssueResult:
        invitation_id = self._invitation_id_factory()
        decision = self._authorization.authorize(
            AuthorizationRequest(
                actor=command.actor,
                permission=Permission.MEMBERSHIP_MANAGE,
                scope=ResourceScope(
                    organization_id=command.organization_id,
                    workspace_id=command.workspace_id,
                    resource_type="invitation",
                    resource_id=invitation_id,
                ),
            )
        )
        if not decision.allowed:
            raise InvitationError(decision.reason_code)

        normalized_email = _normalize_email(command.invitee_email)
        email_binding = (
            "hmac-sha256:"
            + hmac.new(
                self._email_binding_key,
                normalized_email.encode(),
                hashlib.sha256,
            ).hexdigest()
        )
        if self._invitations.has_pending_invitation(
            organization_id=command.organization_id,
            workspace_id=command.workspace_id,
            email_binding=email_binding,
            active_at=self._clock(),
        ):
            raise InvitationError("pending_invitation_exists")

        token = self._token_factory()
        if len(token) < 32:
            raise RuntimeError("Invitation token factory returned an unsafe token.")
        issued_at = self._clock()
        invitation = WorkspaceInvitation(
            invitation_id=invitation_id,
            organization_id=command.organization_id,
            workspace_id=command.workspace_id,
            email_binding=email_binding,
            role=command.role,
            status=InvitationStatus.PENDING,
            token_digest=f"sha256:{hashlib.sha256(token.encode()).hexdigest()}",
            issued_by=command.actor.actor_id,
            issued_at=issued_at,
            expires_at=issued_at + command.expires_in,
        )
        event = AuditEvent(
            event_id=self._event_id_factory(),
            occurred_at=issued_at,
            organization_id=command.organization_id,
            workspace_id=command.workspace_id,
            actor_id=command.actor.actor_id,
            action="membership.invitation_issued",
            target_type="invitation",
            target_id=invitation_id,
            request_id=command.request_id,
            reason=command.reason,
            before_hash=_ABSENT_HASH,
            after_hash=_invitation_hash(invitation),
        )
        self._invitations.save_invitation(invitation, event)
        return InvitationIssueResult(invitation=invitation, token=token, audit_event=event)

    def accept(self, command: AcceptWorkspaceInvitation) -> InvitationAcceptanceResult:
        now = self._clock()
        if not self._authorization.session_is_active(command.actor):
            raise InvitationError("session_inactive")

        token_digest = f"sha256:{hashlib.sha256(command.token.encode()).hexdigest()}"
        current = self._invitations.find_invitation_by_token_digest(token_digest)
        if current is None or current.status is not InvitationStatus.PENDING:
            raise InvitationError("invitation_unavailable")
        if now >= current.expires_at:
            raise InvitationError("invitation_expired")

        normalized_email = _normalize_email(command.verified_email)
        supplied_binding = (
            "hmac-sha256:"
            + hmac.new(
                self._email_binding_key,
                normalized_email.encode(),
                hashlib.sha256,
            ).hexdigest()
        )
        if not hmac.compare_digest(current.email_binding, supplied_binding):
            raise InvitationError("invitation_unavailable")
        if current.role in self._policy.mfa_required_roles and "mfa" not in command.actor.authentication_methods:
            raise InvitationError("mfa_required")
        if (
            self._invitations.find_active(
                actor_id=command.actor.actor_id,
                organization_id=current.organization_id,
                workspace_id=current.workspace_id,
            )
            is not None
        ):
            raise InvitationError("membership_exists")

        accepted = replace(
            current,
            status=InvitationStatus.ACCEPTED,
            revision=current.revision + 1,
            accepted_by=command.actor.actor_id,
            accepted_at=now,
        )
        membership = Membership(
            membership_id=self._membership_id_factory(),
            actor_id=command.actor.actor_id,
            organization_id=current.organization_id,
            workspace_id=current.workspace_id,
            role=current.role,
            status=MembershipStatus.ACTIVE,
            activated_at=now,
        )
        event = AuditEvent(
            event_id=self._event_id_factory(),
            occurred_at=now,
            organization_id=current.organization_id,
            workspace_id=current.workspace_id,
            actor_id=command.actor.actor_id,
            action="membership.invitation_accepted",
            target_type="invitation",
            target_id=current.invitation_id,
            request_id=command.request_id,
            reason="Invitation accepted by its verified recipient.",
            before_hash=_acceptance_hash(current, None),
            after_hash=_acceptance_hash(accepted, membership),
        )
        self._invitations.accept_invitation(
            accepted,
            membership,
            event,
            expected_revision=current.revision,
        )
        return InvitationAcceptanceResult(invitation=accepted, membership=membership, audit_event=event)
