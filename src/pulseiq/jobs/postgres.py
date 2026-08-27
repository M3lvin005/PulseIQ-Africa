"""Worker-role PostgreSQL transactional-outbox repository."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timedelta
from types import MappingProxyType
from uuid import UUID

from psycopg import Connection
from psycopg.rows import TupleRow
from psycopg_pool import ConnectionPool

from .contracts import ClaimedOutboxEvent, ImportJobClaim, OutboxEvent

_ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,119}$")
_QUARANTINE_SCAN_ERRORS = frozenset(
    {
        "binary_content",
        "immutable_destination_conflict",
        "malware_detected",
        "object_checksum_mismatch",
        "object_size_mismatch",
        "promoted_checksum_mismatch",
    }
)


class PostgresOutboxRepository:
    """Lease and settle outbox events through an isolated cross-tenant worker role."""

    def __init__(
        self,
        pool: ConnectionPool[Connection[TupleRow]],
        *,
        lease_token_factory: Callable[[], str],
    ) -> None:
        self._pool = pool
        self._lease_token_factory = lease_token_factory

    def claim_batch(
        self,
        *,
        limit: int,
        claimed_at: datetime,
        lease_for: timedelta,
    ) -> tuple[ClaimedOutboxEvent, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("Outbox claim limit must be between 1 and 100.")
        if not timedelta(seconds=5) <= lease_for <= timedelta(minutes=5):
            raise ValueError("Outbox lease must be between 5 seconds and 5 minutes.")
        lease_token = self._lease_token_factory()
        UUID(lease_token)
        leased_until = claimed_at + lease_for
        with self._pool.connection() as connection, connection.transaction():
            rows = connection.execute(
                """
                WITH candidates AS (
                    SELECT outbox_sequence
                    FROM pulseiq.outbox_events
                    WHERE published_at IS NULL
                      AND dead_lettered_at IS NULL
                      AND available_at <= %s
                      AND (leased_until IS NULL OR leased_until <= %s)
                      AND attempts < 5
                    ORDER BY available_at, outbox_sequence
                    FOR UPDATE SKIP LOCKED
                    LIMIT %s
                ), claimed AS (
                    UPDATE pulseiq.outbox_events AS event
                    SET lease_token = %s,
                        leased_until = %s,
                        last_attempt_at = %s
                    FROM candidates
                    WHERE event.outbox_sequence = candidates.outbox_sequence
                    RETURNING event.outbox_sequence, event.topic,
                              event.aggregate_id::text, event.payload,
                              event.attempts + 1 AS delivery_attempt,
                              event.created_at, event.lease_token::text,
                              event.leased_until
                )
                SELECT * FROM claimed ORDER BY outbox_sequence
                """,
                (claimed_at, claimed_at, limit, lease_token, leased_until, claimed_at),
                prepare=True,
            ).fetchall()
        return tuple(self._claimed(row) for row in rows)

    def mark_published(self, *, sequence: int, lease_token: str, published_at: datetime) -> None:
        UUID(lease_token)
        with self._pool.connection() as connection, connection.transaction():
            changed = connection.execute(
                """
                UPDATE pulseiq.outbox_events
                SET attempts = attempts + 1,
                    published_at = %s,
                    lease_token = NULL,
                    leased_until = NULL
                WHERE outbox_sequence = %s
                  AND lease_token = %s
                  AND published_at IS NULL
                  AND dead_lettered_at IS NULL
                  AND attempts < 5
                RETURNING outbox_sequence
                """,
                (published_at, sequence, lease_token),
                prepare=True,
            ).fetchone()
            if changed is None:
                raise RuntimeError("Outbox lease is no longer current.")

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
        UUID(lease_token)
        if _ERROR_CODE_PATTERN.fullmatch(error_code) is None:
            raise ValueError("Outbox failure code is invalid.")
        if dead_letter == (retry_at is not None):
            raise ValueError("Exactly one retry or dead-letter outcome is required.")
        if retry_at is not None and retry_at <= failed_at:
            raise ValueError("Outbox retry must be scheduled after the failure time.")
        with self._pool.connection() as connection, connection.transaction():
            if dead_letter:
                changed = connection.execute(
                    """
                    UPDATE pulseiq.outbox_events
                    SET attempts = attempts + 1,
                        last_error_code = %s,
                        dead_lettered_at = %s,
                        lease_token = NULL,
                        leased_until = NULL
                    WHERE outbox_sequence = %s
                      AND lease_token = %s
                      AND published_at IS NULL
                      AND dead_lettered_at IS NULL
                      AND attempts < 5
                    RETURNING outbox_sequence
                    """,
                    (error_code, failed_at, sequence, lease_token),
                    prepare=True,
                ).fetchone()
            else:
                changed = connection.execute(
                    """
                    UPDATE pulseiq.outbox_events
                    SET attempts = attempts + 1,
                        last_error_code = %s,
                        available_at = %s,
                        lease_token = NULL,
                        leased_until = NULL
                    WHERE outbox_sequence = %s
                      AND lease_token = %s
                      AND published_at IS NULL
                      AND dead_lettered_at IS NULL
                      AND attempts < 5
                    RETURNING outbox_sequence
                    """,
                    (error_code, retry_at, sequence, lease_token),
                    prepare=True,
                ).fetchone()
            if changed is None:
                raise RuntimeError("Outbox lease is no longer current.")

    @staticmethod
    def _claimed(row: TupleRow) -> ClaimedOutboxEvent:
        return ClaimedOutboxEvent(
            event=OutboxEvent(
                sequence=int(row[0]),
                topic=str(row[1]),
                aggregate_id=str(row[2]),
                payload=MappingProxyType(dict(row[3])),
                attempts=int(row[4]),
                created_at=row[5],
            ),
            lease_token=str(row[6]),
            leased_until=row[7],
        )


class PostgresImportJobRepository:
    """Claim and settle import jobs through token-bound execution leases."""

    def __init__(
        self,
        pool: ConnectionPool[Connection[TupleRow]],
        *,
        execution_token_factory: Callable[[], str],
    ) -> None:
        self._pool = pool
        self._execution_token_factory = execution_token_factory

    def claim_job(
        self,
        *,
        job_id: str,
        claimed_at: datetime,
        lease_for: timedelta,
    ) -> ImportJobClaim | None:
        UUID(job_id)
        if not timedelta(seconds=30) <= lease_for <= timedelta(minutes=10):
            raise ValueError("Import-job lease must be between 30 seconds and 10 minutes.")
        token = self._execution_token_factory()
        UUID(token)
        leased_until = claimed_at + lease_for
        with self._pool.connection() as connection, connection.transaction():
            row = connection.execute(
                """
                WITH exhausted AS (
                    UPDATE pulseiq.import_jobs
                    SET status = 'permanently_failed',
                        completed_at = %s,
                        error_code = 'worker_lease_exhausted',
                        execution_token = NULL,
                        leased_until = NULL,
                        revision = revision + 1
                    WHERE job_id = %s
                      AND status = 'running'
                      AND leased_until <= %s
                      AND attempts >= 5
                    RETURNING job_id
                )
                UPDATE pulseiq.import_jobs
                SET status = 'running',
                    attempts = attempts + 1,
                    execution_token = %s,
                    leased_until = %s,
                    started_at = %s,
                    heartbeat_at = %s,
                    completed_at = NULL,
                    error_code = NULL,
                    revision = revision + 1
                WHERE job_id = %s
                  AND attempts < 5
                  AND available_at <= %s
                  AND (
                      job_type <> 'dataset.scan'
                      OR EXISTS (
                          SELECT 1
                          FROM pulseiq.dataset_versions AS version
                          WHERE version.dataset_version_id = import_jobs.dataset_version_id
                            AND version.organization_id = import_jobs.organization_id
                            AND version.workspace_id = import_jobs.workspace_id
                            AND version.status IN ('uploaded', 'scanning')
                      )
                  )
                  AND (
                      job_type <> 'dataset.validate'
                      OR EXISTS (
                          SELECT 1
                          FROM pulseiq.dataset_versions AS version
                          WHERE version.dataset_version_id = import_jobs.dataset_version_id
                            AND version.organization_id = import_jobs.organization_id
                            AND version.workspace_id = import_jobs.workspace_id
                            AND (
                                version.status = 'validating'
                                OR (
                                    version.status IN ('ready', 'failed')
                                    AND EXISTS (
                                        SELECT 1 FROM pulseiq.validation_runs AS run
                                        WHERE run.validation_run_id = import_jobs.job_id
                                          AND run.dataset_version_id = version.dataset_version_id
                                          AND run.organization_id = version.organization_id
                                          AND run.workspace_id = version.workspace_id
                                    )
                                )
                            )
                      )
                  )
                  AND (
                      status IN ('queued', 'retry_queued')
                      OR (status = 'running' AND leased_until <= %s)
                  )
                  AND NOT EXISTS (SELECT 1 FROM exhausted)
                RETURNING job_id::text, organization_id::text, workspace_id::text,
                          dataset_version_id::text, job_type, input_reference,
                          attempts, execution_token::text, leased_until
                """,
                (
                    claimed_at,
                    job_id,
                    claimed_at,
                    token,
                    leased_until,
                    claimed_at,
                    claimed_at,
                    job_id,
                    claimed_at,
                    claimed_at,
                ),
                prepare=True,
            ).fetchone()
            connection.execute(
                """
                UPDATE pulseiq.dataset_versions AS version
                SET status = 'failed',
                    failure_code = NULL,
                    revision = version.revision + 1
                FROM pulseiq.import_jobs AS job
                WHERE job.job_id = %s
                  AND job.dataset_version_id = version.dataset_version_id
                  AND job.organization_id = version.organization_id
                  AND job.workspace_id = version.workspace_id
                  AND job.job_type = 'dataset.scan'
                  AND job.status = 'permanently_failed'
                  AND job.error_code = 'worker_lease_exhausted'
                  AND version.status = 'scanning'
                """,
                (job_id,),
                prepare=True,
            )
            connection.execute(
                """
                UPDATE pulseiq.dataset_versions AS version
                SET status = 'failed',
                    failure_code = NULL,
                    revision = version.revision + 1
                FROM pulseiq.import_jobs AS job
                WHERE job.job_id = %s
                  AND job.dataset_version_id = version.dataset_version_id
                  AND job.organization_id = version.organization_id
                  AND job.workspace_id = version.workspace_id
                  AND job.job_type = 'dataset.validate'
                  AND job.status = 'permanently_failed'
                  AND job.error_code = 'worker_lease_exhausted'
                  AND version.status = 'validating'
                """,
                (job_id,),
                prepare=True,
            )
            if row is not None and str(row[4]) == "dataset.scan":
                version = connection.execute(
                    """
                    UPDATE pulseiq.dataset_versions
                    SET status = 'scanning',
                        failure_code = NULL,
                        revision = revision + 1
                    WHERE dataset_version_id = %s
                      AND organization_id = %s
                      AND workspace_id = %s
                      AND status = 'uploaded'
                    RETURNING dataset_version_id
                    """,
                    (row[3], row[1], row[2]),
                    prepare=True,
                ).fetchone()
                if version is None:
                    version = connection.execute(
                        """
                        SELECT dataset_version_id
                        FROM pulseiq.dataset_versions
                        WHERE dataset_version_id = %s
                          AND organization_id = %s
                          AND workspace_id = %s
                          AND status = 'scanning'
                        """,
                        (row[3], row[1], row[2]),
                        prepare=True,
                    ).fetchone()
                if version is None:
                    raise RuntimeError("Dataset version is not claimable for scanning.")
        return self._job_claim(row) if row is not None else None

    def heartbeat(
        self,
        *,
        job_id: str,
        execution_token: str,
        heartbeat_at: datetime,
        lease_for: timedelta,
        progress_percent: int,
    ) -> None:
        UUID(job_id)
        UUID(execution_token)
        if not 0 <= progress_percent <= 100:
            raise ValueError("Job progress must be between 0 and 100.")
        with self._pool.connection() as connection, connection.transaction():
            changed = connection.execute(
                """
                UPDATE pulseiq.import_jobs
                SET heartbeat_at = %s,
                    leased_until = %s,
                    progress_percent = %s,
                    revision = revision + 1
                WHERE job_id = %s AND execution_token = %s AND status = 'running'
                RETURNING job_id
                """,
                (heartbeat_at, heartbeat_at + lease_for, progress_percent, job_id, execution_token),
                prepare=True,
            ).fetchone()
            self._require_current_job(changed)

    @staticmethod
    def _settle_scan_version(
        connection: Connection[TupleRow],
        *,
        dataset_version_id: str,
        organization_id: str,
        workspace_id: str,
        job_status: str,
        error_code: str | None,
    ) -> None:
        if job_status == "retry_queued":
            return
        if job_status == "succeeded":
            version_status = "mapping_required"
            failure_code = None
        elif error_code in _QUARANTINE_SCAN_ERRORS:
            version_status = "quarantined"
            failure_code = error_code
        else:
            version_status = "failed"
            failure_code = None
        changed = connection.execute(
            """
            UPDATE pulseiq.dataset_versions
            SET status = %s,
                failure_code = %s,
                revision = revision + 1
            WHERE dataset_version_id = %s
              AND organization_id = %s
              AND workspace_id = %s
              AND status = 'scanning'
            RETURNING dataset_version_id
            """,
            (
                version_status,
                failure_code,
                dataset_version_id,
                organization_id,
                workspace_id,
            ),
            prepare=True,
        ).fetchone()
        if changed is None:
            raise RuntimeError("Dataset scan lifecycle is no longer current.")

    def mark_succeeded(self, *, job_id: str, execution_token: str, completed_at: datetime) -> None:
        self._settle(
            job_id=job_id,
            execution_token=execution_token,
            status="succeeded",
            occurred_at=completed_at,
            error_code=None,
            retry_at=None,
        )

    @staticmethod
    def _settle_validation_version(
        connection: Connection[TupleRow],
        *,
        job_id: str,
        dataset_version_id: str,
        organization_id: str,
        workspace_id: str,
        job_status: str,
    ) -> None:
        if job_status == "retry_queued":
            return
        if job_status == "succeeded":
            completed = connection.execute(
                """
                SELECT version.dataset_version_id
                FROM pulseiq.dataset_versions AS version
                JOIN pulseiq.validation_runs AS run
                  ON run.validation_run_id = %s
                 AND run.dataset_version_id = version.dataset_version_id
                 AND run.organization_id = version.organization_id
                 AND run.workspace_id = version.workspace_id
                WHERE version.dataset_version_id = %s
                  AND version.organization_id = %s
                  AND version.workspace_id = %s
                  AND version.status = CASE run.verdict
                      WHEN 'passed' THEN 'ready'
                      WHEN 'blocked' THEN 'failed'
                  END
                """,
                (job_id, dataset_version_id, organization_id, workspace_id),
                prepare=True,
            ).fetchone()
            if completed is None:
                raise RuntimeError("Dataset validation evidence is not complete.")
            return
        changed = connection.execute(
            """
            UPDATE pulseiq.dataset_versions
            SET status = 'failed', failure_code = NULL, revision = revision + 1
            WHERE dataset_version_id = %s
              AND organization_id = %s
              AND workspace_id = %s
              AND status = 'validating'
            RETURNING dataset_version_id
            """,
            (dataset_version_id, organization_id, workspace_id),
            prepare=True,
        ).fetchone()
        if changed is None:
            raise RuntimeError("Dataset validation lifecycle is no longer current.")

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
        if _ERROR_CODE_PATTERN.fullmatch(error_code) is None:
            raise ValueError("Import-job failure code is invalid.")
        if permanent == (retry_at is not None):
            raise ValueError("Exactly one retry or permanent outcome is required.")
        if retry_at is not None and retry_at <= failed_at:
            raise ValueError("Import-job retry must be scheduled after failure.")
        self._settle(
            job_id=job_id,
            execution_token=execution_token,
            status="permanently_failed" if permanent else "retry_queued",
            occurred_at=failed_at,
            error_code=error_code,
            retry_at=retry_at,
        )

    def _settle(
        self,
        *,
        job_id: str,
        execution_token: str,
        status: str,
        occurred_at: datetime,
        error_code: str | None,
        retry_at: datetime | None,
    ) -> None:
        UUID(job_id)
        UUID(execution_token)
        completed_at = occurred_at if status in {"succeeded", "permanently_failed"} else None
        available_at = retry_at if retry_at is not None else occurred_at
        progress = 100 if status == "succeeded" else 0
        with self._pool.connection() as connection, connection.transaction():
            changed = connection.execute(
                """
                UPDATE pulseiq.import_jobs
                SET status = %s,
                    available_at = %s,
                    heartbeat_at = %s,
                    completed_at = %s,
                    error_code = %s,
                    execution_token = NULL,
                    leased_until = NULL,
                    progress_percent = %s,
                    revision = revision + 1
                WHERE job_id = %s AND execution_token = %s AND status = 'running'
                RETURNING job_id, dataset_version_id, organization_id, workspace_id, job_type
                """,
                (
                    status,
                    available_at,
                    occurred_at,
                    completed_at,
                    error_code,
                    progress,
                    job_id,
                    execution_token,
                ),
                prepare=True,
            ).fetchone()
            if changed is None:
                raise RuntimeError("Import-job execution lease is no longer current.")
            if str(changed[4]) == "dataset.scan":
                self._settle_scan_version(
                    connection,
                    dataset_version_id=str(changed[1]),
                    organization_id=str(changed[2]),
                    workspace_id=str(changed[3]),
                    job_status=status,
                    error_code=error_code,
                )
            elif str(changed[4]) == "dataset.validate":
                self._settle_validation_version(
                    connection,
                    job_id=str(changed[0]),
                    dataset_version_id=str(changed[1]),
                    organization_id=str(changed[2]),
                    workspace_id=str(changed[3]),
                    job_status=status,
                )

    @staticmethod
    def _require_current_job(changed: TupleRow | None) -> None:
        if changed is None:
            raise RuntimeError("Import-job execution lease is no longer current.")

    @staticmethod
    def _job_claim(row: TupleRow) -> ImportJobClaim:
        return ImportJobClaim(
            job_id=str(row[0]),
            organization_id=str(row[1]),
            workspace_id=str(row[2]),
            dataset_version_id=str(row[3]),
            job_type=str(row[4]),
            input_reference=MappingProxyType(dict(row[5])),
            attempts=int(row[6]),
            execution_token=str(row[7]),
            leased_until=row[8],
        )
