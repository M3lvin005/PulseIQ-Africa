"""Audited workspace membership administration commands."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from pulseiq.audit import AuditEvent

from .authorization import AuthorizationService
from .contracts import (
    AuthorizationRequest,
    ChangeMembershipRole,
    Membership,
    MembershipChangeResult,
    MembershipStatus,
    Permission,
    ResourceScope,
    RevokeMembership,
    Role,
)
from .ports import MembershipRepository


class MembershipAdministrationError(RuntimeError):
    """Safe command failure with a stable non-sensitive code."""

    def __init__(self, code: str) -> None:
        super().__init__("Membership administration could not be completed.")
        self.code = code


def _membership_hash(membership: Membership) -> str:
    payload = json.dumps(
        {
            "activated_at": membership.activated_at.isoformat() if membership.activated_at else None,
            "actor_id": membership.actor_id,
            "membership_id": membership.membership_id,
            "organization_id": membership.organization_id,
            "revision": membership.revision,
            "role": membership.role.value,
            "revoked_at": membership.revoked_at.isoformat() if membership.revoked_at else None,
            "status": membership.status.value,
            "workspace_id": membership.workspace_id,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


class IdentityAdministrationService:
    """Apply authorized membership mutations with atomic audit evidence."""

    def __init__(
        self,
        memberships: MembershipRepository,
        authorization: AuthorizationService,
        *,
        clock: Callable[[], datetime],
        event_id_factory: Callable[[], str],
    ) -> None:
        self._memberships = memberships
        self._authorization = authorization
        self._clock = clock
        self._event_id_factory = event_id_factory

    def change_role(self, command: ChangeMembershipRole) -> MembershipChangeResult:
        scope = ResourceScope(
            organization_id=command.organization_id,
            workspace_id=command.workspace_id,
            resource_type="membership",
            resource_id=command.membership_id,
        )
        decision = self._authorization.authorize(
            AuthorizationRequest(
                actor=command.actor,
                permission=Permission.MEMBERSHIP_MANAGE,
                scope=scope,
            )
        )
        if not decision.allowed:
            raise MembershipAdministrationError(decision.reason_code)

        current = self._memberships.get_in_scope(
            membership_id=command.membership_id,
            organization_id=command.organization_id,
            workspace_id=command.workspace_id,
        )
        if current is None or current.status is MembershipStatus.REVOKED:
            raise MembershipAdministrationError("membership_not_found")
        if current.role is command.new_role:
            raise MembershipAdministrationError("role_unchanged")
        if (
            current.role is Role.ADMIN
            and command.new_role is not Role.ADMIN
            and self._memberships.count_active_role(
                organization_id=command.organization_id,
                workspace_id=command.workspace_id,
                role=Role.ADMIN,
            )
            <= 1
        ):
            raise MembershipAdministrationError("last_admin_required")

        updated = replace(current, role=command.new_role, revision=current.revision + 1)
        event = AuditEvent(
            event_id=self._event_id_factory(),
            occurred_at=self._clock(),
            organization_id=command.organization_id,
            workspace_id=command.workspace_id,
            actor_id=command.actor.actor_id,
            action="membership.role_changed",
            target_type="membership",
            target_id=command.membership_id,
            request_id=command.request_id,
            reason=command.reason,
            before_hash=_membership_hash(current),
            after_hash=_membership_hash(updated),
        )
        self._memberships.save_change(updated, event, expected_revision=current.revision)
        return MembershipChangeResult(membership=updated, audit_event=event)

    def revoke(self, command: RevokeMembership) -> MembershipChangeResult:
        scope = ResourceScope(
            organization_id=command.organization_id,
            workspace_id=command.workspace_id,
            resource_type="membership",
            resource_id=command.membership_id,
        )
        decision = self._authorization.authorize(
            AuthorizationRequest(
                actor=command.actor,
                permission=Permission.MEMBERSHIP_MANAGE,
                scope=scope,
            )
        )
        if not decision.allowed:
            raise MembershipAdministrationError(decision.reason_code)

        current = self._memberships.get_in_scope(
            membership_id=command.membership_id,
            organization_id=command.organization_id,
            workspace_id=command.workspace_id,
        )
        if current is None or current.status is MembershipStatus.REVOKED:
            raise MembershipAdministrationError("membership_not_found")
        if (
            current.role is Role.ADMIN
            and self._memberships.count_active_role(
                organization_id=command.organization_id,
                workspace_id=command.workspace_id,
                role=Role.ADMIN,
            )
            <= 1
        ):
            raise MembershipAdministrationError("last_admin_required")

        occurred_at = self._clock()
        updated = replace(
            current,
            status=MembershipStatus.REVOKED,
            revision=current.revision + 1,
            revoked_at=occurred_at,
        )
        event = AuditEvent(
            event_id=self._event_id_factory(),
            occurred_at=occurred_at,
            organization_id=command.organization_id,
            workspace_id=command.workspace_id,
            actor_id=command.actor.actor_id,
            action="membership.revoked",
            target_type="membership",
            target_id=command.membership_id,
            request_id=command.request_id,
            reason=command.reason,
            before_hash=_membership_hash(current),
            after_hash=_membership_hash(updated),
        )
        self._memberships.save_change(updated, event, expected_revision=current.revision)
        return MembershipChangeResult(membership=updated, audit_event=event)
