"""Default-deny workspace authorization service."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from .contracts import (
    AuthenticatedActor,
    AuthorizationDecision,
    AuthorizationPolicy,
    AuthorizationRequest,
    Permission,
    Role,
)
from .ports import MembershipReader, SessionStatusReader

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ADMIN: frozenset(
        {
            Permission.WORKSPACE_VIEW,
            Permission.WORKSPACE_MANAGE,
            Permission.MEMBERSHIP_VIEW,
            Permission.MEMBERSHIP_MANAGE,
            Permission.AUDIT_VIEW,
        }
    ),
    Role.DATA_STEWARD: frozenset(
        {
            Permission.WORKSPACE_VIEW,
            Permission.DATASET_VIEW,
            Permission.DATASET_UPLOAD,
            Permission.DATASET_MANAGE,
            Permission.QUALITY_OVERRIDE,
        }
    ),
    Role.ANALYST: frozenset(
        {
            Permission.WORKSPACE_VIEW,
            Permission.DATASET_VIEW,
            Permission.PORTFOLIO_ANALYZE,
            Permission.MODEL_TRAIN,
            Permission.REPORT_VIEW,
            Permission.REPORT_GENERATE,
            Permission.ASSISTANT_QUERY,
        }
    ),
    Role.RISK_REVIEWER: frozenset(
        {
            Permission.WORKSPACE_VIEW,
            Permission.DATASET_VIEW,
            Permission.PORTFOLIO_ANALYZE,
            Permission.RISK_REVIEW,
            Permission.REPORT_VIEW,
            Permission.REPORT_GENERATE,
            Permission.ASSISTANT_QUERY,
        }
    ),
    Role.APPROVER: frozenset(
        {
            Permission.WORKSPACE_VIEW,
            Permission.DATASET_VIEW,
            Permission.MODEL_APPROVE,
            Permission.DECISION_APPROVE,
            Permission.REPORT_VIEW,
            Permission.REPORT_DELIVER,
            Permission.AUDIT_VIEW,
        }
    ),
    Role.AUDITOR: frozenset(
        {
            Permission.WORKSPACE_VIEW,
            Permission.REPORT_VIEW,
            Permission.AUDIT_VIEW,
        }
    ),
    Role.READ_ONLY: frozenset(
        {
            Permission.WORKSPACE_VIEW,
            Permission.REPORT_VIEW,
        }
    ),
}


class AuthorizationService:
    """Authorize only current exact-scope memberships and explicit permissions."""

    def __init__(
        self,
        memberships: MembershipReader,
        sessions: SessionStatusReader,
        *,
        clock: Callable[[], datetime],
        policy: AuthorizationPolicy | None = None,
    ) -> None:
        self._memberships = memberships
        self._sessions = sessions
        self._clock = clock
        self._policy = policy or AuthorizationPolicy()

    def authorize(self, request: AuthorizationRequest) -> AuthorizationDecision:
        if not self.session_is_active(request.actor):
            return AuthorizationDecision(allowed=False, reason_code="session_inactive")

        membership = self._memberships.find_active(
            actor_id=request.actor.actor_id,
            organization_id=request.scope.organization_id,
            workspace_id=request.scope.workspace_id,
        )
        if membership is None:
            return AuthorizationDecision(allowed=False, reason_code="membership_required")
        if membership.role in self._policy.mfa_required_roles and "mfa" not in request.actor.authentication_methods:
            return AuthorizationDecision(allowed=False, reason_code="mfa_required")
        if request.permission not in ROLE_PERMISSIONS[membership.role]:
            return AuthorizationDecision(allowed=False, reason_code="permission_required")
        return AuthorizationDecision(allowed=True, reason_code="authorized")

    def session_is_active(self, actor: AuthenticatedActor) -> bool:
        """Require both signed actor evidence and current authoritative session state."""

        now = self._clock()
        if not actor.is_active_at(now):
            return False
        return (
            self._sessions.find_active_session(
                session_id=actor.session_id,
                actor_id=actor.actor_id,
                active_at=now,
            )
            is not None
        )
