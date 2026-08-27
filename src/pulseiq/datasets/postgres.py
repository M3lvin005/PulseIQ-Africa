"""Request-scoped PostgreSQL repository for governed dataset ingestion."""

from __future__ import annotations

from types import MappingProxyType

from psycopg.rows import TupleRow
from psycopg.types.json import Jsonb

from pulseiq.audit import AuditEvent
from pulseiq.postgres import PostgresRequestRepository

from .upload_contracts import DatasetVersion, DatasetVersionStatus, ImportJob, ImportJobStatus


def _hash_bytes(value: str, prefix: str) -> bytes:
    expected = f"{prefix}:"
    if not value.startswith(expected):
        raise ValueError(f"Expected {prefix} hash encoding.")
    try:
        decoded = bytes.fromhex(value.removeprefix(expected))
    except ValueError as exc:
        raise ValueError(f"Expected {prefix} hash encoding.") from exc
    if len(decoded) != 32:
        raise ValueError(f"Expected 32-byte {prefix} hash.")
    return decoded


def _digest_bytes(value: str) -> bytes:
    try:
        decoded = bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError("Expected SHA-256 hexadecimal encoding.") from exc
    if len(decoded) != 32:
        raise ValueError("Expected 32-byte SHA-256 digest.")
    return decoded


class PostgresDatasetUploadRepository(PostgresRequestRepository):
    """Persist dataset versions, jobs, and audit evidence in one RLS transaction."""

    def create_pending(self, version: DatasetVersion, audit_event: AuditEvent) -> None:
        self._require_scope(version.organization_id, version.workspace_id)
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO pulseiq.dataset_versions (
                    dataset_version_id, dataset_id, organization_id, workspace_id,
                    status, object_key, filename_binding, content_type,
                    expected_bytes, expected_sha256, created_by, created_at,
                    revision, uploaded_at, failure_code
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    version.dataset_version_id,
                    version.dataset_id,
                    version.organization_id,
                    version.workspace_id,
                    version.status.value,
                    version.object_key,
                    _hash_bytes(version.filename_binding, "hmac-sha256"),
                    version.content_type,
                    version.expected_bytes,
                    _digest_bytes(version.expected_sha256),
                    version.created_by,
                    version.created_at,
                    version.revision,
                    version.uploaded_at,
                    version.failure_code,
                ),
                prepare=True,
            )
            self._insert_audit(connection, audit_event)

    def get_in_scope(
        self,
        *,
        dataset_version_id: str,
        organization_id: str,
        workspace_id: str,
    ) -> DatasetVersion | None:
        if not self._is_scope(organization_id, workspace_id):
            return None
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT dataset_version_id::text, dataset_id::text, organization_id::text,
                       workspace_id::text, status, object_key, filename_binding,
                       content_type, expected_bytes, expected_sha256, created_by::text,
                       created_at, revision, uploaded_at, failure_code
                FROM pulseiq.dataset_versions
                WHERE dataset_version_id = %s AND organization_id = %s AND workspace_id = %s
                """,
                (dataset_version_id, organization_id, workspace_id),
                prepare=True,
            ).fetchone()
        return self._version(row) if row is not None else None

    def complete_and_enqueue(
        self,
        version: DatasetVersion,
        job: ImportJob,
        audit_event: AuditEvent,
        *,
        expected_revision: int,
    ) -> None:
        self._require_scope(version.organization_id, version.workspace_id)
        with self._transaction() as connection:
            changed = connection.execute(
                """
                UPDATE pulseiq.dataset_versions
                SET status = %s, revision = %s, uploaded_at = %s, failure_code = %s
                WHERE dataset_version_id = %s AND organization_id = %s AND workspace_id = %s
                  AND revision = %s AND status = 'upload_pending'
                RETURNING dataset_version_id
                """,
                (
                    version.status.value,
                    version.revision,
                    version.uploaded_at,
                    version.failure_code,
                    version.dataset_version_id,
                    version.organization_id,
                    version.workspace_id,
                    expected_revision,
                ),
                prepare=True,
            ).fetchone()
            if changed is None:
                raise RuntimeError("Dataset version changed concurrently.")
            connection.execute(
                """
                INSERT INTO pulseiq.import_jobs (
                    job_id, organization_id, workspace_id, dataset_version_id,
                    job_type, status, input_reference, idempotency_key,
                    attempts, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    job.job_id,
                    job.organization_id,
                    job.workspace_id,
                    version.dataset_version_id,
                    job.job_type,
                    job.status.value,
                    Jsonb(dict(job.input_reference)),
                    job.idempotency_key,
                    job.attempts,
                    job.created_at,
                ),
                prepare=True,
            )
            self._insert_audit(connection, audit_event)

    def find_job_for_version(self, dataset_version_id: str) -> ImportJob | None:
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT job_id::text, organization_id::text, workspace_id::text,
                       job_type, status, input_reference, idempotency_key,
                       created_at, attempts
                FROM pulseiq.import_jobs
                WHERE dataset_version_id = %s AND job_type = 'dataset.scan'
                ORDER BY created_at, job_id
                LIMIT 1
                """,
                (dataset_version_id,),
                prepare=True,
            ).fetchone()
        return self._job(row) if row is not None else None

    def quarantine(
        self,
        version: DatasetVersion,
        audit_event: AuditEvent,
        *,
        expected_revision: int,
    ) -> None:
        self._require_scope(version.organization_id, version.workspace_id)
        with self._transaction() as connection:
            changed = connection.execute(
                """
                UPDATE pulseiq.dataset_versions
                SET status = %s, revision = %s, uploaded_at = %s, failure_code = %s
                WHERE dataset_version_id = %s AND organization_id = %s AND workspace_id = %s
                  AND revision = %s AND status = 'upload_pending'
                RETURNING dataset_version_id
                """,
                (
                    version.status.value,
                    version.revision,
                    version.uploaded_at,
                    version.failure_code,
                    version.dataset_version_id,
                    version.organization_id,
                    version.workspace_id,
                    expected_revision,
                ),
                prepare=True,
            ).fetchone()
            if changed is None:
                raise RuntimeError("Dataset version changed concurrently.")
            self._insert_audit(connection, audit_event)

    @staticmethod
    def _version(row: TupleRow) -> DatasetVersion:
        return DatasetVersion(
            dataset_version_id=str(row[0]),
            dataset_id=str(row[1]),
            organization_id=str(row[2]),
            workspace_id=str(row[3]),
            status=DatasetVersionStatus(str(row[4])),
            object_key=str(row[5]),
            filename_binding=f"hmac-sha256:{bytes(row[6]).hex()}",
            content_type=str(row[7]),
            expected_bytes=int(row[8]),
            expected_sha256=bytes(row[9]).hex(),
            created_by=str(row[10]),
            created_at=row[11],
            revision=int(row[12]),
            uploaded_at=row[13],
            failure_code=str(row[14]) if row[14] is not None else None,
        )

    @staticmethod
    def _job(row: TupleRow) -> ImportJob:
        return ImportJob(
            job_id=str(row[0]),
            organization_id=str(row[1]),
            workspace_id=str(row[2]),
            job_type=str(row[3]),
            status=ImportJobStatus(str(row[4])),
            input_reference=MappingProxyType(dict(row[5])),
            idempotency_key=str(row[6]),
            created_at=row[7],
            attempts=int(row[8]),
        )
