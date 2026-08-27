from __future__ import annotations

from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

import pytest
from kombu.exceptions import OperationalError

from pulseiq.jobs import CeleryMessagePublisher, MessagePublishError, OutboxEvent, create_celery_app


class FakeCeleryApp:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def send_task(self, name: str, **options: Any) -> object:
        self.calls.append((name, options))
        if self.error is not None:
            raise self.error
        return object()


def _event(*, topic: str = "job.queued", payload: dict[str, object] | None = None) -> OutboxEvent:
    return OutboxEvent(
        sequence=7,
        topic=topic,
        aggregate_id="33333333-eeee-4eee-8eee-333333333333",
        payload=MappingProxyType(payload or {"job_id": "33333333-eeee-4eee-8eee-333333333333"}),
        attempts=1,
        created_at=datetime(2026, 8, 25, 19, tzinfo=UTC),
    )


def test_celery_publisher_routes_small_json_reference_envelope_with_stable_id() -> None:
    app = FakeCeleryApp()

    CeleryMessagePublisher(app).publish(_event())

    assert app.calls == [
        (
            "pulseiq.jobs.execute_import",
            {
                "kwargs": {
                    "message": {
                        "aggregate_id": "33333333-eeee-4eee-8eee-333333333333",
                        "outbox_sequence": 7,
                        "payload": {"job_id": "33333333-eeee-4eee-8eee-333333333333"},
                        "topic": "job.queued",
                    }
                },
                "task_id": "outbox-7",
                "queue": "dataset-ingestion",
                "serializer": "json",
                "retry": True,
                "retry_policy": {
                    "max_retries": 2,
                    "interval_start": 0,
                    "interval_step": 0.2,
                    "interval_max": 0.5,
                },
                "ignore_result": True,
                "expires": 300,
            },
        )
    ]


def test_unknown_outbox_topic_is_a_permanent_publication_failure() -> None:
    with pytest.raises(MessagePublishError) as error:
        CeleryMessagePublisher(FakeCeleryApp()).publish(_event(topic="unknown.topic"))

    assert error.value.code == "invalid_topic"
    assert error.value.retryable is False


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        ({"value": object()}, "invalid_payload"),
        ({"value": "x" * 17_000}, "message_too_large"),
    ],
)
def test_non_json_or_oversized_payload_is_rejected_before_broker_call(
    payload: dict[str, object],
    expected_code: str,
) -> None:
    app = FakeCeleryApp()

    with pytest.raises(MessagePublishError) as error:
        CeleryMessagePublisher(app).publish(_event(payload=payload))

    assert error.value.code == expected_code
    assert error.value.retryable is False
    assert app.calls == []


def test_broker_operational_error_is_classified_as_transient() -> None:
    app = FakeCeleryApp(OperationalError("redis unavailable"))

    with pytest.raises(MessagePublishError) as error:
        CeleryMessagePublisher(app).publish(_event())

    assert error.value.code == "broker_unavailable"
    assert error.value.retryable is True
    assert "redis unavailable" not in str(error.value)


def test_celery_app_uses_json_only_named_queues_late_ack_and_no_result_backend() -> None:
    app = create_celery_app("redis://localhost:6379/15")

    assert app.conf.broker_url == "redis://localhost:6379/15"
    assert app.conf.accept_content == ("json",)
    assert app.conf.task_serializer == "json"
    assert app.conf.result_backend is None
    assert app.conf.task_ignore_result is True
    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True
    assert app.conf.worker_prefetch_multiplier == 1
    assert app.conf.task_create_missing_queues is False
    assert app.conf.task_default_queue == "dataset-ingestion"
    assert {queue.name for queue in app.conf.task_queues} == {"audit-events", "dataset-ingestion"}
    assert app.conf.broker_transport_options == {
        "health_check_interval": 30,
        "socket_connect_timeout": 5,
        "socket_timeout": 5,
        "visibility_timeout": 600,
    }


@pytest.mark.parametrize("broker_url", ["", "amqp://localhost", "redis:///15"])
def test_celery_app_rejects_missing_or_non_redis_broker(broker_url: str) -> None:
    with pytest.raises(ValueError, match="Redis URL"):
        create_celery_app(broker_url)
