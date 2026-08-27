"""Immutable contracts for transactional-outbox publication."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    """One durable reference-only message awaiting broker publication."""

    sequence: int
    topic: str
    aggregate_id: str
    payload: Mapping[str, object]
    attempts: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ClaimedOutboxEvent:
    """An outbox event protected by a bounded ownership lease."""

    event: OutboxEvent
    lease_token: str
    leased_until: datetime


@dataclass(frozen=True, slots=True)
class DispatchReport:
    """Counts from one bounded dispatcher iteration."""

    claimed: int
    published: int
    retry_scheduled: int
    dead_lettered: int


class MessagePublishError(RuntimeError):
    """Safe classified broker publication failure."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__("Message publication failed.")
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class ImportJobClaim:
    """One database-owned import execution lease."""

    job_id: str
    organization_id: str
    workspace_id: str
    dataset_version_id: str
    job_type: str
    input_reference: Mapping[str, object]
    attempts: int
    execution_token: str
    leased_until: datetime


@dataclass(frozen=True, slots=True)
class JobRunReport:
    """Safe outcome of handling one at-least-once broker delivery."""

    job_id: str
    outcome: str


class JobExecutionError(RuntimeError):
    """Classified domain or infrastructure failure from a job handler."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__("Import job execution failed.")
        self.code = code
        self.retryable = retryable
