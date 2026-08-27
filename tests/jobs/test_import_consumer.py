from __future__ import annotations

from typing import Any

import pytest

from pulseiq.jobs import (
    ImportJobMessageConsumer,
    InvalidImportMessage,
    JobRunReport,
    create_celery_app,
    register_import_job_task,
)


class FakeRunner:
    def __init__(self) -> None:
        self.job_ids: list[str] = []

    def run(self, job_id: str) -> JobRunReport:
        self.job_ids.append(job_id)
        return JobRunReport(job_id=job_id, outcome="not_claimed")


def _message() -> dict[str, object]:
    return {
        "aggregate_id": "33333333-eeee-4eee-8eee-333333333333",
        "outbox_sequence": 7,
        "payload": {"job_id": "33333333-eeee-4eee-8eee-333333333333"},
        "topic": "job.queued",
    }


def test_consumer_validates_reference_envelope_before_running_job() -> None:
    runner = FakeRunner()

    report = ImportJobMessageConsumer(runner).consume(_message())  # type: ignore[arg-type]

    assert runner.job_ids == ["33333333-eeee-4eee-8eee-333333333333"]
    assert report.outcome == "not_claimed"


@pytest.mark.parametrize(
    "changes",
    [
        {"topic": "audit.recorded"},
        {"outbox_sequence": 0},
        {"payload": {}},
        {"extra": "unexpected"},
    ],
)
def test_consumer_permanently_rejects_malformed_or_misdirected_message(changes: dict[str, Any]) -> None:
    runner = FakeRunner()
    message = _message()
    message.update(changes)

    with pytest.raises(InvalidImportMessage, match="message is invalid"):
        ImportJobMessageConsumer(runner).consume(message)  # type: ignore[arg-type]

    assert runner.job_ids == []


def test_registered_celery_task_has_hard_bounds_and_invokes_consumer() -> None:
    runner = FakeRunner()
    task = register_import_job_task(create_celery_app("redis://localhost:6379/15"), runner)  # type: ignore[arg-type]

    task.run(message=_message())

    assert task.name == "pulseiq.jobs.execute_import"
    assert task.acks_late is True
    assert task.ignore_result is True
    assert task.soft_time_limit == 270
    assert task.time_limit == 300
    assert runner.job_ids == ["33333333-eeee-4eee-8eee-333333333333"]
