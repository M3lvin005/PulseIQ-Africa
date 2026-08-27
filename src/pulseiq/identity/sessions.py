"""Audited server-side session revocation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from pulseiq.audit import AuditEvent

from .contracts import RevokeSession, SessionRecord, SessionRevocationResult, SessionStatus
from .ports import SessionRepository


class SessionAdministrationError(RuntimeError):
    """Safe session command failure with a stable non-sensitive code."""

    def __init__(self, code: str) -> None:
        super().__init__("Session administration could not be completed.")
        self.code = code


def _session_hash(session: SessionRecord) -> str:
    payload = json.dumps(
        {
            "actor_id": session.actor_id,
            "authenticated_at": session.authenticated_at.isoformat(),
            "expires_at": session.expires_at.isoformat(),
            "revision": session.revision,
            "revoked_at": session.revoked_at.isoformat() if session.revoked_at else None,
            "session_id": session.session_id,
            "status": session.status.value,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


class SessionAdministrationService:
    """Revoke an actor's current session with atomic audit evidence."""

    def __init__(
        self,
        sessions: SessionRepository,
        *,
        clock: Callable[[], datetime],
        event_id_factory: Callable[[], str],
    ) -> None:
        self._sessions = sessions
        self._clock = clock
        self._event_id_factory = event_id_factory

    def logout(self, command: RevokeSession) -> SessionRevocationResult:
        now = self._clock()
        if not command.actor.is_active_at(now):
            raise SessionAdministrationError("session_inactive")
        current = self._sessions.find_active_session(
            session_id=command.actor.session_id,
            actor_id=command.actor.actor_id,
            active_at=now,
        )
        if current is None:
            raise SessionAdministrationError("session_inactive")

        updated = replace(
            current,
            status=SessionStatus.REVOKED,
            revision=current.revision + 1,
            revoked_at=now,
        )
        event = AuditEvent(
            event_id=self._event_id_factory(),
            occurred_at=now,
            organization_id=command.organization_id,
            workspace_id=command.workspace_id,
            actor_id=command.actor.actor_id,
            action="session.revoked",
            target_type="session",
            target_id=current.session_id,
            request_id=command.request_id,
            reason=command.reason,
            before_hash=_session_hash(current),
            after_hash=_session_hash(updated),
        )
        self._sessions.save_session_revocation(updated, event, expected_revision=current.revision)
        return SessionRevocationResult(session=updated, audit_event=event)
