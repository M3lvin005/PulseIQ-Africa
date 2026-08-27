from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import MappingProxyType

import pytest

from pulseiq.jobs import ImportJobClaim, ImportJobRunner, JobExecutionError

NOW = datetime(2026, 8, 25, 20, tzinfo=UTC)


def _claim(*, attempts: int = 1) -> ImportJobClaim:
    return ImportJobClaim(
        job_id="33333333-eeee-4eee-8eee-333333333333",
        organization_id="11111111-1111-4111-8111-111111111111",
        workspace_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        dataset_version_id="33333333-cccc-4ccc-8ccc-333333333333",
        job_type="dataset.scan",
        input_reference=MappingProxyType({"object_key": "quarantine/org/workspace/dataset/version/original.csv"}),
        attempts=attempts,
        execution_token="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        leased_until=NOW + timedelta(minutes=5),
    )


class FakeImportJobRepository:
    def __init__(self, claim: ImportJobClaim | None) -> None:
        self.claim = claim
        self.claim_call: tuple[str, datetime, timedelta] | None = None
        self.succeeded: list[tuple[str, str, datetime]] = []
        self.failures: list[tuple[str, str, datetime, str, datetime | None, bool]] = []

    def claim_job(self, *, job_id: str, claimed_at: datetime, lease_for: timedelta) -> ImportJobClaim | None:
        self.claim_call = (job_id, claimed_at, lease_for)
        return self.claim

    def mark_succeeded(self, *, job_id: str, execution_token: str, completed_at: datetime) -> None:
        self.succeeded.append((job_id, execution_token, completed_at))

    def record_failure(
        self,
        *,
        job_id: str,
        execution_token: str,
        failed_at: datetime,
        error_code: str,
        retry_at: datetime | None,
        permanent: bool,
    ) -> None:
        self.failures.append((job_id, execution_token, failed_at, error_code, retry_at, permanent))


class FakeImportHandler:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.claims: list[ImportJobClaim] = []

    def execute(self, claim: ImportJobClaim) -> None:
        self.claims.append(claim)
        if self.error is not None:
            raise self.error


def test_import_runner_claims_executes_and_marks_success() -> None:
    repository = FakeImportJobRepository(_claim())
    handler = FakeImportHandler()
    runner = ImportJobRunner(repository, handler, clock=lambda: NOW)

    report = runner.run("33333333-eeee-4eee-8eee-333333333333")

    assert repository.claim_call == (
        "33333333-eeee-4eee-8eee-333333333333",
        NOW,
        timedelta(minutes=5),
    )
    assert handler.claims == [_claim()]
    assert repository.succeeded == [
        (
            "33333333-eeee-4eee-8eee-333333333333",
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            NOW,
        )
    ]
    assert report.outcome == "succeeded"


def test_duplicate_or_terminal_job_delivery_is_a_noop() -> None:
    repository = FakeImportJobRepository(None)
    handler = FakeImportHandler()

    report = ImportJobRunner(repository, handler, clock=lambda: NOW).run("33333333-eeee-4eee-8eee-333333333333")

    assert handler.claims == []
    assert repository.succeeded == []
    assert report.outcome == "not_claimed"


def test_transient_job_failure_schedules_database_retry() -> None:
    repository = FakeImportJobRepository(_claim(attempts=2))
    handler = FakeImportHandler(JobExecutionError("scanner_unavailable", retryable=True))

    report = ImportJobRunner(repository, handler, clock=lambda: NOW).run("33333333-eeee-4eee-8eee-333333333333")

    assert repository.failures == [
        (
            "33333333-eeee-4eee-8eee-333333333333",
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            NOW,
            "scanner_unavailable",
            NOW + timedelta(seconds=10),
            False,
        )
    ]
    assert report.outcome == "retry_scheduled"


@pytest.mark.parametrize(
    ("error", "attempts"),
    [
        (JobExecutionError("malware_detected", retryable=False), 1),
        (JobExecutionError("scanner_unavailable", retryable=True), 5),
    ],
)
def test_permanent_or_exhausted_job_failure_is_terminal(error: JobExecutionError, attempts: int) -> None:
    repository = FakeImportJobRepository(_claim(attempts=attempts))

    report = ImportJobRunner(repository, FakeImportHandler(error), clock=lambda: NOW).run(
        "33333333-eeee-4eee-8eee-333333333333"
    )

    assert repository.failures[0][4] is None
    assert repository.failures[0][5] is True
    assert report.outcome == "permanently_failed"


def test_unknown_handler_failure_propagates_and_leaves_execution_lease() -> None:
    repository = FakeImportJobRepository(_claim())
    runner = ImportJobRunner(repository, FakeImportHandler(RuntimeError("worker defect")), clock=lambda: NOW)

    with pytest.raises(RuntimeError, match="worker defect"):
        runner.run("33333333-eeee-4eee-8eee-333333333333")

    assert repository.succeeded == []
    assert repository.failures == []
