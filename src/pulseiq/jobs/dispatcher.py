"""Bounded at-least-once transactional-outbox dispatcher."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from .contracts import DispatchReport, MessagePublishError
from .ports import MessagePublisher, OutboxRepository


class OutboxDispatcher:
    """Publish leased events and durably classify their outcomes."""

    def __init__(
        self,
        repository: OutboxRepository,
        publisher: MessagePublisher,
        *,
        clock: Callable[[], datetime],
        lease_for: timedelta = timedelta(seconds=30),
        maximum_attempts: int = 5,
        retry_base: timedelta = timedelta(seconds=5),
        retry_maximum: timedelta = timedelta(minutes=5),
    ) -> None:
        self._repository = repository
        self._publisher = publisher
        self._clock = clock
        self._lease_for = lease_for
        self._maximum_attempts = maximum_attempts
        self._retry_base = retry_base
        self._retry_maximum = retry_maximum

    def dispatch_once(self, *, limit: int = 50) -> DispatchReport:
        now = self._clock()
        claims = self._repository.claim_batch(limit=limit, claimed_at=now, lease_for=self._lease_for)
        published = 0
        retry_scheduled = 0
        dead_lettered = 0
        for claim in claims:
            try:
                self._publisher.publish(claim.event)
            except MessagePublishError as error:
                dead_letter = not error.retryable or claim.event.attempts >= self._maximum_attempts
                retry_at = None if dead_letter else now + self._backoff(claim.event.attempts)
                self._repository.record_failure(
                    sequence=claim.event.sequence,
                    lease_token=claim.lease_token,
                    failed_at=now,
                    error_code=error.code,
                    retry_at=retry_at,
                    dead_letter=dead_letter,
                )
                if dead_letter:
                    dead_lettered += 1
                else:
                    retry_scheduled += 1
            else:
                self._repository.mark_published(
                    sequence=claim.event.sequence,
                    lease_token=claim.lease_token,
                    published_at=now,
                )
                published += 1
        return DispatchReport(
            claimed=len(claims),
            published=published,
            retry_scheduled=retry_scheduled,
            dead_lettered=dead_lettered,
        )

    def _backoff(self, attempts: int) -> timedelta:
        seconds = self._retry_base.total_seconds() * 2 ** max(0, attempts - 1)
        return timedelta(seconds=min(seconds, self._retry_maximum.total_seconds()))
