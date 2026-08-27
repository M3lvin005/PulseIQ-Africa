"""External ports for dataset upload reservation."""

from __future__ import annotations

from typing import Protocol

from pulseiq.audit import AuditEvent

from .upload_contracts import (
    DatasetVersion,
    ImportJob,
    PresignedUpload,
    QuarantineUploadRequest,
    StoredObjectMetadata,
)


class DatasetUploadRepository(Protocol):
    """Persist a pending version and its audit evidence atomically."""

    def create_pending(self, version: DatasetVersion, audit_event: AuditEvent) -> None: ...

    def get_in_scope(
        self,
        *,
        dataset_version_id: str,
        organization_id: str,
        workspace_id: str,
    ) -> DatasetVersion | None: ...

    def complete_and_enqueue(
        self,
        version: DatasetVersion,
        job: ImportJob,
        audit_event: AuditEvent,
        *,
        expected_revision: int,
    ) -> None: ...

    def find_job_for_version(self, dataset_version_id: str) -> ImportJob | None: ...

    def quarantine(
        self,
        version: DatasetVersion,
        audit_event: AuditEvent,
        *,
        expected_revision: int,
    ) -> None: ...


class QuarantineUploadSigner(Protocol):
    """Create a policy-bound direct upload form for quarantine storage."""

    def create_upload(self, request: QuarantineUploadRequest) -> PresignedUpload: ...


class QuarantineObjectInspector(Protocol):
    """Read trusted object metadata without downloading the object."""

    def inspect(self, object_key: str) -> StoredObjectMetadata | None: ...


class QuarantineObjectStore(QuarantineUploadSigner, QuarantineObjectInspector, Protocol):
    """Create bounded upload forms and inspect the resulting object metadata."""
