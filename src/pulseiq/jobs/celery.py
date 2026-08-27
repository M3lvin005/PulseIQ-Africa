"""Small JSON-only Celery publisher for leased outbox events."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol
from urllib.parse import urlparse

from celery import Celery
from kombu import Queue
from kombu.exceptions import OperationalError

from .contracts import MessagePublishError, OutboxEvent


class CeleryApp(Protocol):
    def send_task(self, name: str, **options: object) -> object: ...


@dataclass(frozen=True, slots=True)
class CeleryRoute:
    """Allowlisted broker task and queue for one outbox topic."""

    task_name: str
    queue: str


DEFAULT_CELERY_ROUTES: Mapping[str, CeleryRoute] = MappingProxyType(
    {
        "audit.recorded": CeleryRoute(
            task_name="pulseiq.audit.checkpoint_event",
            queue="audit-events",
        ),
        "job.queued": CeleryRoute(
            task_name="pulseiq.jobs.execute_import",
            queue="dataset-ingestion",
        ),
    }
)


def create_celery_app(broker_url: str) -> Celery:
    """Create the JSON-only Redis broker application used by isolated workers."""

    parsed = urlparse(broker_url)
    if parsed.scheme not in {"redis", "rediss"} or parsed.hostname is None:
        raise ValueError("Celery broker must be a Redis URL with a hostname.")
    app = Celery("pulseiq", broker=broker_url)
    app.conf.update(
        accept_content=("json",),
        broker_connection_retry_on_startup=True,
        broker_transport_options={
            "health_check_interval": 30,
            "socket_connect_timeout": 5,
            "socket_timeout": 5,
            "visibility_timeout": 600,
        },
        enable_utc=True,
        result_backend=None,
        task_acks_late=True,
        task_create_missing_queues=False,
        task_default_queue="dataset-ingestion",
        task_ignore_result=True,
        task_queues=(Queue("audit-events"), Queue("dataset-ingestion")),
        task_reject_on_worker_lost=True,
        task_serializer="json",
        timezone="UTC",
        worker_prefetch_multiplier=1,
    )
    return app


class CeleryMessagePublisher:
    """Publish allowlisted, size-bounded JSON messages with stable delivery IDs."""

    def __init__(
        self,
        app: CeleryApp,
        *,
        routes: Mapping[str, CeleryRoute] = DEFAULT_CELERY_ROUTES,
        maximum_message_bytes: int = 16 * 1024,
    ) -> None:
        self._app = app
        self._routes = routes
        self._maximum_message_bytes = maximum_message_bytes

    def publish(self, event: OutboxEvent) -> None:
        route = self._routes.get(event.topic)
        if route is None:
            raise MessagePublishError("invalid_topic", retryable=False)
        message = {
            "aggregate_id": event.aggregate_id,
            "outbox_sequence": event.sequence,
            "payload": dict(event.payload),
            "topic": event.topic,
        }
        try:
            encoded = json.dumps(message, separators=(",", ":"), sort_keys=True).encode()
        except (TypeError, ValueError) as exc:
            raise MessagePublishError("invalid_payload", retryable=False) from exc
        if len(encoded) > self._maximum_message_bytes:
            raise MessagePublishError("message_too_large", retryable=False)
        try:
            self._app.send_task(
                route.task_name,
                kwargs={"message": message},
                task_id=f"outbox-{event.sequence}",
                queue=route.queue,
                serializer="json",
                retry=True,
                retry_policy={
                    "max_retries": 2,
                    "interval_start": 0,
                    "interval_step": 0.2,
                    "interval_max": 0.5,
                },
                ignore_result=True,
                expires=300,
            )
        except OperationalError as exc:
            raise MessagePublishError("broker_unavailable", retryable=True) from exc
