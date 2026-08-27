"""Provider-neutral identity, membership, and workspace authorization seam."""

from pulseiq.postgres import DatabaseScope

from .adapters import InMemoryMembershipRepository, InMemorySessionRepository
from .administration import IdentityAdministrationService, MembershipAdministrationError
from .authorization import AuthorizationService
from .contracts import (
    AcceptWorkspaceInvitation,
    AuthenticatedActor,
    AuthorizationDecision,
    AuthorizationPolicy,
    AuthorizationRequest,
    ChangeMembershipRole,
    InvitationAcceptanceResult,
    InvitationIssueResult,
    InvitationStatus,
    InviteWorkspaceMember,
    Membership,
    MembershipChangeResult,
    MembershipStatus,
    Permission,
    ResourceScope,
    RevokeMembership,
    RevokeSession,
    Role,
    SessionRecord,
    SessionRevocationResult,
    SessionStatus,
    WorkspaceInvitation,
)
from .invitations import IdentityInvitationService, InvitationError
from .postgres import PostgresIdentityRepository
from .sessions import SessionAdministrationError, SessionAdministrationService

__all__ = [
    "AcceptWorkspaceInvitation",
    "AuthenticatedActor",
    "AuthorizationDecision",
    "AuthorizationPolicy",
    "AuthorizationRequest",
    "AuthorizationService",
    "ChangeMembershipRole",
    "DatabaseScope",
    "IdentityAdministrationService",
    "IdentityInvitationService",
    "InMemoryMembershipRepository",
    "InMemorySessionRepository",
    "InvitationAcceptanceResult",
    "InvitationError",
    "InvitationIssueResult",
    "InvitationStatus",
    "InviteWorkspaceMember",
    "Membership",
    "MembershipAdministrationError",
    "MembershipChangeResult",
    "MembershipStatus",
    "Permission",
    "PostgresIdentityRepository",
    "ResourceScope",
    "RevokeMembership",
    "RevokeSession",
    "Role",
    "SessionAdministrationError",
    "SessionAdministrationService",
    "SessionRecord",
    "SessionRevocationResult",
    "SessionStatus",
    "WorkspaceInvitation",
]
