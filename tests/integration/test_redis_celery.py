from __future__ import annotations

import os
from datetime import UTC, datetime
from types import MappingProxyType
from urllib.parse import urlparse

import pytest
from redis import Redis

from pulseiq.jobs import CeleryMessagePublisher, OutboxEvent, create_celery_app

REDIS_URL = os.environ.get("PULSEIQ_TEST_REDIS_URL")


def test_celery_publishes_reference_only_message_to_named_local_redis_queue() -> None:
    if REDIS_URL is None:
        pytest.skip("Set PULSEIQ_TEST_REDIS_URL to run the Redis broker integration test.")
    parsed = urlparse(REDIS_URL)
    if parsed.scheme != "redis" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.path != "/15":
        pytest.fail("The destructive Redis integration test is restricted to local database 15.")

    redis_client = Redis.from_url(REDIS_URL, socket_connect_timeout=3, socket_timeout=3)
    redis_client.flushdb()
    try:
        publisher = CeleryMessagePublisher(create_celery_app(REDIS_URL))
        publisher.publish(
            OutboxEvent(
                sequence=7,
                topic="job.queued",
                aggregate_id="33333333-eeee-4eee-8eee-333333333333",
                payload=MappingProxyType(
                    {
                        "dataset_version_id": "33333333-cccc-4ccc-8ccc-333333333333",
                        "job_id": "33333333-eeee-4eee-8eee-333333333333",
                    }
                ),
                attempts=1,
                created_at=datetime.now(UTC),
            )
        )

        assert redis_client.llen("dataset-ingestion") == 1
        assert redis_client.llen("audit-events") == 0
    finally:
        redis_client.flushdb()
        redis_client.close()
