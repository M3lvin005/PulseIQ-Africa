"""Immutable identity and workspace authorization contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from pulseiq.audit import AuditEvent


def _require_identifier(value: str, label: str) -> None:
    if not value or value.isspace():
        raise ValueError(f"{label} must be a non-empty identifier.")


class Role(StrEnum):
    """Named least-privilege workspace responsibilities."""

    ADMIN = "admin"
    DATA_STEWARD = "data_steward"
    ANALYST = "analyst"
    RISK_REVIEWER = "risk_reviewer"
    APPROVER = "approver"
    AUDITOR = "auditor"
    READ_ONLY = "read_only"


class Permission(StrEnum):
    """Atomic actions authorized within a workspace."""

    WORKSPACE_VIEW = "workspace.view"
    WORKSPACE_MANAGE = "workspace.manage"
    MEMBERSHIP_VIEW = "membership.view"
    MEMBERSHIP_MANAGE = "membership.manage"
    DATASET_VIEW = "dataset.view"
    DATASET_UPLOAD = "dataset.upload"
    DATASET_MANAGE = "dataset.manage"
    QUALITY_OVERRIDE = "quality.override"
    PORTFOLIO_ANALYZE = "portfolio.analyze"
    RISK_REVIEW = "risk.review"
    MODEL_TRAIN = "model.train"
    MODEL_APPROVE = "model.approve"
    DECISION_APPROVE = "decision.approve"
    REPORT_VIEW = "report.view"
    REPORT_GENERATE = "report.generate"
    REPORT_DELIVER = "report.deliver"
    AUDIT_VIEW = "audit.view"
    ASSISTANT_QUERY = "assistant.query"


class MembershipStatus(StrEnum):
    """Lifecycle state of an actor's workspace membership."""

    INVITED = "invited"
    ACTIVE = "active"
    REVOKED = "revoked"


class InvitationStatus(StrEnum):
    """Lifecycle state of a one-time workspace invitation."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    REVOKED = "revoked"


class SessionStatus(StrEnum):
    """Authoritative server-side session lifecycle."""

    ACTIVE = "active"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class AuthenticatedActor:
    """Provider-verified identity and short-lived server-session evidence."""

    actor_id: str
    session_id: str
    authenticated_at: datetime
    expires_at: datetime
    authentication_methods: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_identifier(self.actor_id, "Actor ID")
        _require_identifier(self.session_id, "Session ID")
        if self.authenticated_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("Authentication timestamps must be timezone-aware.")
        if self.expires_at <= self.authenticated_at:
            raise ValueError("Session expiry must follow authentication time.")

    def is_active_at(self, moment: datetime) -> bool:
        return self.authenticated_at <= moment < self.expires_at


@dataclass(frozen=True, slots=True)
class SessionRecord:
    """Server-side session state used to invalidate credentials immediately."""

    session_id: str
    actor_id: str
    authenticated_at: datetime
    expires_at: datetime
    status: SessionStatus
    revision: int = 1
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.session_id, "Session ID")
        _require_identifier(self.actor_id, "Actor ID")
        if self.authenticated_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("Session timestamps must be timezone-aware.")
        if self.expires_at <= self.authenticated_at:
            raise ValueError("Session expiry must follow authentication time.")
        if self.revision < 1:
            raise ValueError("Session revision must be positive.")
        if self.status is SessionStatus.REVOKED and self.revoked_at is None:
            raise ValueError("A revoked session must record its revocation time.")
        if self.status is not SessionStatus.REVOKED and self.revoked_at is not None:
            raise ValueError("Only a revoked session can record a revocation time.")
        if self.revoked_at is not None and self.revoked_at.tzinfo is None:
            raise ValueError("Session revocation time must be timezone-aware.")
        if self.revoked_at is not None and self.revoked_at < self.authenticated_at:
            raise ValueError("Session revocation cannot predate authentication.")


@dataclass(frozen=True, slots=True)
class Membership:
    """Server-side assignment of one actor and role to one workspace."""

    membership_id: str
    actor_id: str
    organization_id: str
    workspace_id: str
    role: Role
    status: MembershipStatus
    revision: int = 1
    activated_at: datetime | None = None
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.membership_id, "Membership ID")
        _require_identifier(self.actor_id, "Actor ID")
        _require_identifier(self.organization_id, "Organization ID")
        _require_identifier(self.workspace_id, "Workspace ID")
        if self.revision < 1:
            raise ValueError("Membership revision must be positive.")
        if self.activated_at is not None and self.activated_at.tzinfo is None:
            raise ValueError("Membership activation time must be timezone-aware.")
        if self.status is MembershipStatus.REVOKED and self.revoked_at is None:
            raise ValueError("A revoked membership must record its revocation time.")
        if self.status is not MembershipStatus.REVOKED and self.revoked_at is not None:
            raise ValueError("Only a revoked membership can record a revocation time.")
        if self.revoked_at is not None and self.revoked_at.tzinfo is None:
            raise ValueError("Membership revocation time must be timezone-aware.")


@dataclass(frozen=True, slots=True)
class ResourceScope:
    """Tenant ownership coordinates for an authorization target."""

    organization_id: str
    workspace_id: str
    resource_type: str
    resource_id: str

    def __post_init__(self) -> None:
        _require_identifier(self.organization_id, "Organization ID")
        _require_identifier(self.workspace_id, "Workspace ID")
        _require_identifier(self.resource_type, "Resource type")
        _require_identifier(self.resource_id, "Resource ID")


@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    """One actor action against one server-resolved tenant resource."""

    actor: AuthenticatedActor
    permission: Permission
    scope: ResourceScope


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    """Fail-closed authorization result with a stable safe reason code."""

    allowed: bool
    reason_code: str


@dataclass(frozen=True, slots=True)
class AuthorizationPolicy:
    """Server-resolved workspace authentication assurance policy."""

    mfa_required_roles: frozenset[Role] = field(
        default_factory=lambda: frozenset(
            {
                Role.ADMIN,
                Role.DATA_STEWARD,
                Role.ANALYST,
                Role.RISK_REVIEWER,
                Role.APPROVER,
            }
        )
    )


@dataclass(frozen=True, slots=True)
class ChangeMembershipRole:
    """Authorized command to replace one membership role."""

    actor: AuthenticatedActor
    organization_id: str
    workspace_id: str
    membership_id: str
    new_role: Role
    reason: str
    request_id: str

    def __post_init__(self) -> None:
        _require_identifier(self.organization_id, "Organization ID")
        _require_identifier(self.workspace_id, "Workspace ID")
        _require_identifier(self.membership_id, "Membership ID")
        _require_identifier(self.reason, "Role-change reason")
        _require_identifier(self.request_id, "Request ID")


@dataclass(frozen=True, slots=True)
class MembershipChangeResult:
    """New membership state and the audit evidence committed with it."""

    membership: Membership
    audit_event: AuditEvent


@dataclass(frozen=True, slots=True)
class RevokeMembership:
    """Authorized command to remove an actor's current workspace access."""

    actor: AuthenticatedActor
    organization_id: str
    workspace_id: str
    membership_id: str
    reason: str
    request_id: str

    def __post_init__(self) -> None:
        _require_identifier(self.organization_id, "Organization ID")
        _require_identifier(self.workspace_id, "Workspace ID")
        _require_identifier(self.membership_id, "Membership ID")
        _require_identifier(self.reason, "Revocation reason")
        _require_identifier(self.request_id, "Request ID")


@dataclass(frozen=True, slots=True)
class InviteWorkspaceMember:
    """Authorized command to issue one email-bound workspace invitation."""

    actor: AuthenticatedActor
    organization_id: str
    workspace_id: str
    invitee_email: str
    role: Role
    expires_in: timedelta
    reason: str
    request_id: str

    def __post_init__(self) -> None:
        _require_identifier(self.organization_id, "Organization ID")
        _require_identifier(self.workspace_id, "Workspace ID")
        _require_identifier(self.invitee_email, "Invitee email")
        _require_identifier(self.reason, "Invitation reason")
        _require_identifier(self.request_id, "Request ID")
        if not timedelta(minutes=15) <= self.expires_in <= timedelta(days=7):
            raise ValueError("Invitation lifetime must be between 15 minutes and 7 days.")


@dataclass(frozen=True, slots=True)
class WorkspaceInvitation:
    """Stored invitation metadata without raw email or bearer token."""

    invitation_id: str
    organization_id: str
    workspace_id: str
    email_binding: str
    role: Role
    status: InvitationStatus
    token_digest: str
    issued_by: str
    issued_at: datetime
    expires_at: datetime
    revision: int = 1
    accepted_by: str | None = None
    accepted_at: datetime | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.invitation_id, "Invitation ID"),
            (self.organization_id, "Organization ID"),
            (self.workspace_id, "Workspace ID"),
            (self.email_binding, "Email binding"),
            (self.token_digest, "Token digest"),
            (self.issued_by, "Issuing actor ID"),
        ):
            _require_identifier(value, label)
        if self.issued_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("Invitation timestamps must be timezone-aware.")
        if self.expires_at <= self.issued_at:
            raise ValueError("Invitation expiry must follow issue time.")
        if self.revision < 1:
            raise ValueError("Invitation revision must be positive.")
        if self.status is InvitationStatus.ACCEPTED and (self.accepted_by is None or self.accepted_at is None):
            raise ValueError("An accepted invitation must record its actor and acceptance time.")
        if self.status is not InvitationStatus.ACCEPTED and (
            self.accepted_by is not None or self.accepted_at is not None
        ):
            raise ValueError("Only an accepted invitation can record acceptance metadata.")
        if self.accepted_at is not None and self.accepted_at.tzinfo is None:
            raise ValueError("Invitation acceptance time must be timezone-aware.")
        if self.accepted_at is not None and not self.issued_at <= self.accepted_at < self.expires_at:
            raise ValueError("Invitation acceptance must occur during its validity window.")


@dataclass(frozen=True, slots=True)
class InvitationIssueResult:
    """One-time bearer token plus persisted invitation and audit evidence."""

    invitation: WorkspaceInvitation
    token: str
    audit_event: AuditEvent


@dataclass(frozen=True, slots=True)
class AcceptWorkspaceInvitation:
    """Command from a provider-verified recipient to consume an invitation."""

    actor: AuthenticatedActor
    verified_email: str
    token: str
    request_id: str

    def __post_init__(self) -> None:
        _require_identifier(self.verified_email, "Verified email")
        _require_identifier(self.token, "Invitation token")
        _require_identifier(self.request_id, "Request ID")


@dataclass(frozen=True, slots=True)
class InvitationAcceptanceResult:
    """Accepted invitation, active membership, and committed audit evidence."""

    invitation: WorkspaceInvitation
    membership: Membership
    audit_event: AuditEvent


@dataclass(frozen=True, slots=True)
class RevokeSession:
    """Command for an actor to revoke its current server-side session."""

    actor: AuthenticatedActor
    organization_id: str
    workspace_id: str
    reason: str
    request_id: str

    def __post_init__(self) -> None:
        _require_identifier(self.organization_id, "Organization ID")
        _require_identifier(self.workspace_id, "Workspace ID")
        _require_identifier(self.reason, "Session revocation reason")
        _require_identifier(self.request_id, "Request ID")


@dataclass(frozen=True, slots=True)
class SessionRevocationResult:
    """Revoked session and the audit evidence committed with it."""

    session: SessionRecord
    audit_event: AuditEvent
