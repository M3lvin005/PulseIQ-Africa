"""Immutable cross-domain audit event contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """PII-minimized evidence emitted with a governed state change."""

    event_id: str
    occurred_at: datetime
    organization_id: str
    workspace_id: str
    actor_id: str
    action: str
    target_type: str
    target_id: str
    request_id: str
    reason: str
    before_hash: str
    after_hash: str

    def __post_init__(self) -> None:
        values = (
            self.event_id,
            self.organization_id,
            self.workspace_id,
            self.actor_id,
            self.action,
            self.target_type,
            self.target_id,
            self.request_id,
            self.reason,
            self.before_hash,
            self.after_hash,
        )
        if any(not value or value.isspace() for value in values):
            raise ValueError("Audit event fields must be non-empty.")
        if self.occurred_at.tzinfo is None:
            raise ValueError("Audit event time must be timezone-aware.")
