"""Immutable contracts for tenant-bound dataset upload reservations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from pulseiq.audit import AuditEvent
from pulseiq.identity import AuthenticatedActor


def _require_identifier(value: str, label: str) -> None:
    if not value or value.isspace():
        raise ValueError(f"{label} must be non-empty.")


class DatasetVersionStatus(StrEnum):
    """Governed lifecycle for one immutable dataset version."""

    UPLOAD_PENDING = "upload_pending"
    UPLOADED = "uploaded"
    SCANNING = "scanning"
    MAPPING_REQUIRED = "mapping_required"
    VALIDATING = "validating"
    READY = "ready"
    ACTIVE = "active"
    QUARANTINED = "quarantined"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class BeginDatasetUpload:
    """Authorized request to reserve a direct quarantine upload."""

    actor: AuthenticatedActor
    organization_id: str
    workspace_id: str
    dataset_id: str
    source_filename: str
    content_type: str
    content_length: int
    checksum_sha256: str
    request_id: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.organization_id, "Organization ID"),
            (self.workspace_id, "Workspace ID"),
            (self.dataset_id, "Dataset ID"),
            (self.source_filename, "Source filename"),
            (self.content_type, "Content type"),
            (self.checksum_sha256, "Checksum"),
            (self.request_id, "Request ID"),
        ):
            _require_identifier(value, label)
        if self.content_length < 1:
            raise ValueError("Content length must be positive.")


@dataclass(frozen=True, slots=True)
class DatasetVersion:
    """Immutable upload expectation and current governed lifecycle state."""

    dataset_version_id: str
    dataset_id: str
    organization_id: str
    workspace_id: str
    status: DatasetVersionStatus
    object_key: str
    filename_binding: str
    content_type: str
    expected_bytes: int
    expected_sha256: str
    created_by: str
    created_at: datetime
    revision: int = 1
    uploaded_at: datetime | None = None
    failure_code: str | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.dataset_version_id, "Dataset version ID"),
            (self.dataset_id, "Dataset ID"),
            (self.organization_id, "Organization ID"),
            (self.workspace_id, "Workspace ID"),
            (self.object_key, "Object key"),
            (self.filename_binding, "Filename binding"),
            (self.content_type, "Content type"),
            (self.expected_sha256, "Expected checksum"),
            (self.created_by, "Creating actor ID"),
        ):
            _require_identifier(value, label)
        if self.expected_bytes < 1:
            raise ValueError("Expected byte count must be positive.")
        if self.created_at.tzinfo is None:
            raise ValueError("Dataset version creation time must be timezone-aware.")
        if self.revision < 1:
            raise ValueError("Dataset version revision must be positive.")
        if self.uploaded_at is not None and self.uploaded_at.tzinfo is None:
            raise ValueError("Dataset version upload time must be timezone-aware.")
        if self.status is DatasetVersionStatus.UPLOAD_PENDING and self.uploaded_at is not None:
            raise ValueError("A pending dataset version cannot record upload completion.")
        if self.status is DatasetVersionStatus.UPLOADED and self.uploaded_at is None:
            raise ValueError("An uploaded dataset version must record upload completion.")
        if self.status is DatasetVersionStatus.QUARANTINED and self.failure_code is None:
            raise ValueError("A quarantined dataset version must record a failure code.")
        if self.status is not DatasetVersionStatus.QUARANTINED and self.failure_code is not None:
            raise ValueError("Only a quarantined dataset version can record a failure code.")


@dataclass(frozen=True, slots=True)
class QuarantineUploadRequest:
    """Exact object-store conditions required for a direct upload."""

    object_key: str
    content_type: str
    content_length: int
    checksum_sha256: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class PresignedUpload:
    """Short-lived form returned to an authorized browser once."""

    url: str
    fields: Mapping[str, str]
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class UploadReservation:
    """Pending version, direct upload form, and committed audit evidence."""

    version: DatasetVersion
    upload: PresignedUpload
    audit_event: AuditEvent


@dataclass(frozen=True, slots=True)
class StoredObjectMetadata:
    """Trusted object-store HEAD metadata used before queueing work."""

    object_key: str
    content_type: str
    content_length: int
    checksum_sha256: str


@dataclass(frozen=True, slots=True)
class CompleteDatasetUpload:
    """Authorized request to verify a direct upload and queue scanning."""

    actor: AuthenticatedActor
    organization_id: str
    workspace_id: str
    dataset_version_id: str
    request_id: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.organization_id, "Organization ID"),
            (self.workspace_id, "Workspace ID"),
            (self.dataset_version_id, "Dataset version ID"),
            (self.request_id, "Request ID"),
        ):
            _require_identifier(value, label)


class ImportJobStatus(StrEnum):
    """Durable import-job state independent of the queue provider."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRY_QUEUED = "retry_queued"
    PERMANENTLY_FAILED = "permanently_failed"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ImportJob:
    """Reference-only, idempotent job persisted before queue delivery."""

    job_id: str
    organization_id: str
    workspace_id: str
    job_type: str
    status: ImportJobStatus
    input_reference: Mapping[str, str]
    idempotency_key: str
    created_at: datetime
    attempts: int = 0


@dataclass(frozen=True, slots=True)
class CompleteUploadResult:
    """Verified version, queued scan job, and committed audit evidence."""

    version: DatasetVersion
    job: ImportJob
    audit_event: AuditEvent | None
