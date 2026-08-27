"""Deterministic upload adapters for tests and local composition."""

from __future__ import annotations

from types import MappingProxyType

from pulseiq.audit import AuditEvent

from .upload_contracts import (
    DatasetVersion,
    ImportJob,
    PresignedUpload,
    QuarantineUploadRequest,
    StoredObjectMetadata,
)


class InMemoryDatasetUploadRepository:
    """Store isolated pending dataset versions in memory."""

    def __init__(self) -> None:
        self._versions: dict[str, DatasetVersion] = {}
        self._jobs: dict[str, ImportJob] = {}
        self._version_jobs: dict[str, str] = {}
        self._job_idempotency_keys: set[str] = set()
        self._audit_events: list[AuditEvent] = []

    def create_pending(self, version: DatasetVersion, audit_event: AuditEvent) -> None:
        if version.dataset_version_id in self._versions:
            raise RuntimeError("Dataset version ID already exists.")
        if audit_event.target_id != version.dataset_version_id:
            raise ValueError("Audit target must match the dataset version.")
        self._versions[version.dataset_version_id] = version
        self._audit_events.append(audit_event)

    def get_in_scope(
        self,
        *,
        dataset_version_id: str,
        organization_id: str,
        workspace_id: str,
    ) -> DatasetVersion | None:
        version = self._versions.get(dataset_version_id)
        if version is None or version.organization_id != organization_id or version.workspace_id != workspace_id:
            return None
        return version

    def complete_and_enqueue(
        self,
        version: DatasetVersion,
        job: ImportJob,
        audit_event: AuditEvent,
        *,
        expected_revision: int,
    ) -> None:
        current = self._versions.get(version.dataset_version_id)
        if current is None or current.revision != expected_revision:
            raise RuntimeError("Dataset version changed concurrently.")
        if job.job_id in self._jobs or job.idempotency_key in self._job_idempotency_keys:
            raise RuntimeError("Import job already exists.")
        if audit_event.target_id != version.dataset_version_id:
            raise ValueError("Audit target must match the dataset version.")
        self._versions[version.dataset_version_id] = version
        self._jobs[job.job_id] = job
        self._version_jobs[version.dataset_version_id] = job.job_id
        self._job_idempotency_keys.add(job.idempotency_key)
        self._audit_events.append(audit_event)

    def find_job_for_version(self, dataset_version_id: str) -> ImportJob | None:
        job_id = self._version_jobs.get(dataset_version_id)
        return self._jobs.get(job_id) if job_id is not None else None

    def quarantine(
        self,
        version: DatasetVersion,
        audit_event: AuditEvent,
        *,
        expected_revision: int,
    ) -> None:
        current = self._versions.get(version.dataset_version_id)
        if current is None or current.revision != expected_revision:
            raise RuntimeError("Dataset version changed concurrently.")
        if audit_event.target_id != version.dataset_version_id:
            raise ValueError("Audit target must match the dataset version.")
        self._versions[version.dataset_version_id] = version
        self._audit_events.append(audit_event)


class InMemoryQuarantineUploadSigner:
    """Expose deterministic policy fields without contacting an object store."""

    def __init__(self, *, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._objects: dict[str, StoredObjectMetadata] = {}

    def create_upload(self, request: QuarantineUploadRequest) -> PresignedUpload:
        return PresignedUpload(
            url=self._base_url,
            fields=MappingProxyType(
                {
                    "key": request.object_key,
                    "Content-Type": request.content_type,
                    "x-pulseiq-content-length": str(request.content_length),
                    "x-pulseiq-checksum-sha256": request.checksum_sha256,
                }
            ),
            expires_at=request.expires_at,
        )

    def record_uploaded_object(
        self,
        *,
        object_key: str,
        content_type: str,
        content_length: int,
        checksum_sha256: str,
    ) -> None:
        self._objects[object_key] = StoredObjectMetadata(
            object_key=object_key,
            content_type=content_type,
            content_length=content_length,
            checksum_sha256=checksum_sha256,
        )

    def inspect(self, object_key: str) -> StoredObjectMetadata | None:
        return self._objects.get(object_key)
