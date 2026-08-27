"""Validated Celery message consumer for durable import jobs."""

from __future__ import annotations

from collections.abc import Mapping

from celery import Celery, Task

from .contracts import JobRunReport
from .runner import ImportJobRunner


class InvalidImportMessage(RuntimeError):
    """Safe permanent rejection of a malformed broker envelope."""

    def __init__(self) -> None:
        super().__init__("Import-job message is invalid.")


class ImportJobMessageConsumer:
    """Validate a reference-only envelope and invoke the idempotent runner."""

    def __init__(self, runner: ImportJobRunner) -> None:
        self._runner = runner

    def consume(self, message: Mapping[str, object]) -> JobRunReport:
        if set(message) != {"aggregate_id", "outbox_sequence", "payload", "topic"}:
            raise InvalidImportMessage
        aggregate_id = message["aggregate_id"]
        sequence = message["outbox_sequence"]
        payload = message["payload"]
        if (
            message["topic"] != "job.queued"
            or not isinstance(aggregate_id, str)
            or type(sequence) is not int
            or sequence < 1
            or not isinstance(payload, Mapping)
            or payload.get("job_id") != aggregate_id
        ):
            raise InvalidImportMessage
        return self._runner.run(aggregate_id)


def register_import_job_task(app: Celery, runner: ImportJobRunner) -> Task:
    """Register the only dataset-ingestion task with hard execution bounds."""

    consumer = ImportJobMessageConsumer(runner)

    @app.task(  # type: ignore[untyped-decorator]
        name="pulseiq.jobs.execute_import",
        acks_late=True,
        ignore_result=True,
        soft_time_limit=270,
        time_limit=300,
    )
    def execute_import(message: Mapping[str, object]) -> None:
        consumer.consume(message)

    return execute_import
