"""Idempotent import-job execution coordinator."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from .contracts import JobExecutionError, JobRunReport
from .ports import ImportJobHandler, ImportJobRepository


class ImportJobRunner:
    """Claim one durable job and settle its classified handler outcome."""

    def __init__(
        self,
        repository: ImportJobRepository,
        handler: ImportJobHandler,
        *,
        clock: Callable[[], datetime],
        lease_for: timedelta = timedelta(minutes=5),
        maximum_attempts: int = 5,
        retry_base: timedelta = timedelta(seconds=5),
        retry_maximum: timedelta = timedelta(minutes=5),
    ) -> None:
        self._repository = repository
        self._handler = handler
        self._clock = clock
        self._lease_for = lease_for
        self._maximum_attempts = maximum_attempts
        self._retry_base = retry_base
        self._retry_maximum = retry_maximum

    def run(self, job_id: str) -> JobRunReport:
        now = self._clock()
        claim = self._repository.claim_job(job_id=job_id, claimed_at=now, lease_for=self._lease_for)
        if claim is None:
            return JobRunReport(job_id=job_id, outcome="not_claimed")
        try:
            self._handler.execute(claim)
        except JobExecutionError as error:
            permanent = not error.retryable or claim.attempts >= self._maximum_attempts
            retry_at = None if permanent else now + self._backoff(claim.attempts)
            self._repository.record_failure(
                job_id=claim.job_id,
                execution_token=claim.execution_token,
                failed_at=now,
                error_code=error.code,
                retry_at=retry_at,
                permanent=permanent,
            )
            outcome = "permanently_failed" if permanent else "retry_scheduled"
            return JobRunReport(job_id=job_id, outcome=outcome)
        self._repository.mark_succeeded(
            job_id=claim.job_id,
            execution_token=claim.execution_token,
            completed_at=now,
        )
        return JobRunReport(job_id=job_id, outcome="succeeded")

    def _backoff(self, attempts: int) -> timedelta:
        seconds = self._retry_base.total_seconds() * 2 ** max(0, attempts - 1)
        return timedelta(seconds=min(seconds, self._retry_maximum.total_seconds()))
