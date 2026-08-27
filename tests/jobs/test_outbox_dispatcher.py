from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import MappingProxyType

import pytest

from pulseiq.jobs import (
    ClaimedOutboxEvent,
    MessagePublishError,
    OutboxDispatcher,
    OutboxEvent,
)

NOW = datetime(2026, 8, 25, 19, tzinfo=UTC)


def _claim(*, sequence: int = 1, attempts: int = 1) -> ClaimedOutboxEvent:
    return ClaimedOutboxEvent(
        event=OutboxEvent(
            sequence=sequence,
            topic="job.queued",
            aggregate_id="33333333-eeee-4eee-8eee-333333333333",
            payload=MappingProxyType(
                {
                    "job_id": "33333333-eeee-4eee-8eee-333333333333",
                    "dataset_version_id": "33333333-cccc-4ccc-8ccc-333333333333",
                }
            ),
            attempts=attempts,
            created_at=NOW - timedelta(seconds=10),
        ),
        lease_token="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        leased_until=NOW + timedelta(seconds=30),
    )


class FakeOutboxRepository:
    def __init__(self, claims: tuple[ClaimedOutboxEvent, ...]) -> None:
        self.claims = claims
        self.claim_call: tuple[int, datetime, timedelta] | None = None
        self.published: list[tuple[int, str, datetime]] = []
        self.failures: list[tuple[int, str, datetime, str, datetime | None, bool]] = []

    def claim_batch(
        self,
        *,
        limit: int,
        claimed_at: datetime,
        lease_for: timedelta,
    ) -> tuple[ClaimedOutboxEvent, ...]:
        self.claim_call = (limit, claimed_at, lease_for)
        return self.claims

    def mark_published(self, *, sequence: int, lease_token: str, published_at: datetime) -> None:
        self.published.append((sequence, lease_token, published_at))

    def record_failure(
        self,
        *,
        sequence: int,
        lease_token: str,
        failed_at: datetime,
        error_code: str,
        retry_at: datetime | None,
        dead_letter: bool,
    ) -> None:
        self.failures.append((sequence, lease_token, failed_at, error_code, retry_at, dead_letter))


class FakePublisher:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.events: list[OutboxEvent] = []

    def publish(self, event: OutboxEvent) -> None:
        self.events.append(event)
        if self.error is not None:
            raise self.error


def test_dispatcher_publishes_claimed_reference_message_and_acknowledges_lease() -> None:
    repository = FakeOutboxRepository((_claim(),))
    publisher = FakePublisher()
    dispatcher = OutboxDispatcher(repository, publisher, clock=lambda: NOW)

    report = dispatcher.dispatch_once(limit=10)

    assert repository.claim_call == (10, NOW, timedelta(seconds=30))
    assert publisher.events == [_claim().event]
    assert repository.published == [(1, "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", NOW)]
    assert repository.failures == []
    assert report.claimed == 1
    assert report.published == 1
    assert report.retry_scheduled == 0
    assert report.dead_lettered == 0


def test_transient_publication_failure_uses_bounded_exponential_backoff() -> None:
    repository = FakeOutboxRepository((_claim(attempts=3),))
    publisher = FakePublisher(MessagePublishError("broker_unavailable", retryable=True))
    dispatcher = OutboxDispatcher(repository, publisher, clock=lambda: NOW)

    report = dispatcher.dispatch_once()

    assert repository.published == []
    assert repository.failures == [
        (
            1,
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            NOW,
            "broker_unavailable",
            NOW + timedelta(seconds=20),
            False,
        )
    ]
    assert report.retry_scheduled == 1
    assert report.dead_lettered == 0


@pytest.mark.parametrize(
    ("error", "attempts", "expected_code"),
    [
        (MessagePublishError("invalid_topic", retryable=False), 1, "invalid_topic"),
        (MessagePublishError("broker_unavailable", retryable=True), 5, "broker_unavailable"),
    ],
)
def test_permanent_or_exhausted_failure_is_dead_lettered(
    error: MessagePublishError,
    attempts: int,
    expected_code: str,
) -> None:
    repository = FakeOutboxRepository((_claim(attempts=attempts),))
    dispatcher = OutboxDispatcher(repository, FakePublisher(error), clock=lambda: NOW)

    report = dispatcher.dispatch_once()

    assert repository.failures == [
        (
            1,
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            NOW,
            expected_code,
            None,
            True,
        )
    ]
    assert report.retry_scheduled == 0
    assert report.dead_lettered == 1


def test_unknown_publisher_failure_propagates_and_leaves_lease_for_recovery() -> None:
    repository = FakeOutboxRepository((_claim(),))
    dispatcher = OutboxDispatcher(repository, FakePublisher(RuntimeError("programming defect")), clock=lambda: NOW)

    with pytest.raises(RuntimeError, match="programming defect"):
        dispatcher.dispatch_once()

    assert repository.published == []
    assert repository.failures == []


def test_empty_claim_is_a_noop() -> None:
    repository = FakeOutboxRepository(())
    publisher = FakePublisher()

    report = OutboxDispatcher(repository, publisher, clock=lambda: NOW).dispatch_once()

    assert publisher.events == []
    assert report.claimed == 0
    assert report.published == 0
