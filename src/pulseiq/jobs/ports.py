"""Provider ports for outbox persistence and broker publication."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from .contracts import ClaimedOutboxEvent, ImportJobClaim, OutboxEvent


class OutboxRepository(Protocol):
    def claim_batch(
        self,
        *,
        limit: int,
        claimed_at: datetime,
        lease_for: timedelta,
    ) -> tuple[ClaimedOutboxEvent, ...]: ...

    def mark_published(self, *, sequence: int, lease_token: str, published_at: datetime) -> None: ...

    def record_failure(
        self,
        *,
        sequence: int,
        lease_token: str,
        failed_at: datetime,
        error_code: str,
        retry_at: datetime | None,
        dead_letter: bool,
    ) -> None: ...


class MessagePublisher(Protocol):
    def publish(self, event: OutboxEvent) -> None: ...


class ImportJobRepository(Protocol):
    def claim_job(
        self,
        *,
        job_id: str,
        claimed_at: datetime,
        lease_for: timedelta,
    ) -> ImportJobClaim | None: ...

    def mark_succeeded(self, *, job_id: str, execution_token: str, completed_at: datetime) -> None: ...

    def record_failure(
        self,
        *,
        job_id: str,
        execution_token: str,
        failed_at: datetime,
        error_code: str,
        retry_at: datetime | None,
        permanent: bool,
    ) -> None: ...


class ImportJobHandler(Protocol):
    def execute(self, claim: ImportJobClaim) -> None: ...
