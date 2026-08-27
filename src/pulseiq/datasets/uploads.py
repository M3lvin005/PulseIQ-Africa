"""Authorized dataset upload reservation service."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import PurePath
from types import MappingProxyType
from uuid import uuid4

from pulseiq.audit import AuditEvent
from pulseiq.identity import AuthorizationRequest, AuthorizationService, Permission, ResourceScope

from .upload_contracts import (
    BeginDatasetUpload,
    CompleteDatasetUpload,
    CompleteUploadResult,
    DatasetVersion,
    DatasetVersionStatus,
    ImportJob,
    ImportJobStatus,
    QuarantineUploadRequest,
    UploadReservation,
)
from .upload_ports import DatasetUploadRepository, QuarantineObjectStore

_ABSENT_HASH = f"sha256:{hashlib.sha256(b'absent').hexdigest()}"
_CHECKSUM_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_PATH_COMPONENT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_ALLOWED_CONTENT_TYPES = frozenset({"text/csv", "application/csv", "application/vnd.ms-excel"})


class DatasetUploadError(RuntimeError):
    """Safe upload reservation failure with a stable code."""

    def __init__(self, code: str) -> None:
        super().__init__("Dataset upload could not be reserved.")
        self.code = code


def _version_hash(version: DatasetVersion) -> str:
    payload = json.dumps(
        {
            "content_type": version.content_type,
            "created_at": version.created_at.isoformat(),
            "created_by": version.created_by,
            "dataset_id": version.dataset_id,
            "dataset_version_id": version.dataset_version_id,
            "expected_bytes": version.expected_bytes,
            "expected_sha256": version.expected_sha256,
            "failure_code": version.failure_code,
            "filename_binding": version.filename_binding,
            "object_key": version.object_key,
            "organization_id": version.organization_id,
            "revision": version.revision,
            "status": version.status.value,
            "uploaded_at": version.uploaded_at.isoformat() if version.uploaded_at else None,
            "workspace_id": version.workspace_id,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


class DatasetUploadService:
    """Reserve bounded direct uploads into tenant-specific quarantine keys."""

    def __init__(
        self,
        repository: DatasetUploadRepository,
        signer: QuarantineObjectStore,
        authorization: AuthorizationService,
        *,
        filename_binding_key: bytes,
        clock: Callable[[], datetime],
        dataset_version_id_factory: Callable[[], str],
        audit_event_id_factory: Callable[[], str],
        job_id_factory: Callable[[], str] | None = None,
        upload_ttl: timedelta = timedelta(minutes=10),
        maximum_bytes: int = 10 * 1024 * 1024,
    ) -> None:
        if len(filename_binding_key) < 32:
            raise ValueError("Filename binding key must contain at least 32 bytes.")
        if not timedelta(minutes=5) <= upload_ttl <= timedelta(minutes=15):
            raise ValueError("Upload form lifetime must be between 5 and 15 minutes.")
        if maximum_bytes < 1:
            raise ValueError("Maximum upload bytes must be positive.")
        self._repository = repository
        self._signer = signer
        self._authorization = authorization
        self._filename_binding_key = filename_binding_key
        self._clock = clock
        self._dataset_version_id_factory = dataset_version_id_factory
        self._audit_event_id_factory = audit_event_id_factory
        self._job_id_factory = job_id_factory or (lambda: str(uuid4()))
        self._upload_ttl = upload_ttl
        self._maximum_bytes = maximum_bytes

    def begin_upload(self, command: BeginDatasetUpload) -> UploadReservation:
        version_id = self._dataset_version_id_factory()
        decision = self._authorization.authorize(
            AuthorizationRequest(
                actor=command.actor,
                permission=Permission.DATASET_UPLOAD,
                scope=ResourceScope(
                    organization_id=command.organization_id,
                    workspace_id=command.workspace_id,
                    resource_type="dataset_version",
                    resource_id=version_id,
                ),
            )
        )
        if not decision.allowed:
            raise DatasetUploadError(decision.reason_code)

        components = (
            command.organization_id,
            command.workspace_id,
            command.dataset_id,
            version_id,
        )
        if any(_PATH_COMPONENT_PATTERN.fullmatch(component) is None for component in components):
            raise DatasetUploadError("invalid_identifier")
        if command.content_type.casefold() not in _ALLOWED_CONTENT_TYPES:
            raise DatasetUploadError("unsupported_content_type")
        if command.content_length > self._maximum_bytes:
            raise DatasetUploadError("file_too_large")
        checksum = command.checksum_sha256.casefold()
        if _CHECKSUM_PATTERN.fullmatch(checksum) is None:
            raise DatasetUploadError("invalid_checksum")
        if PurePath(command.source_filename).suffix.casefold() != ".csv":
            raise DatasetUploadError("unsupported_extension")

        created_at = self._clock()
        object_key = "/".join(
            (
                "quarantine",
                command.organization_id,
                command.workspace_id,
                command.dataset_id,
                version_id,
                "original.csv",
            )
        )
        filename_binding = (
            "hmac-sha256:"
            + hmac.new(
                self._filename_binding_key,
                command.source_filename.strip().casefold().encode(),
                hashlib.sha256,
            ).hexdigest()
        )
        version = DatasetVersion(
            dataset_version_id=version_id,
            dataset_id=command.dataset_id,
            organization_id=command.organization_id,
            workspace_id=command.workspace_id,
            status=DatasetVersionStatus.UPLOAD_PENDING,
            object_key=object_key,
            filename_binding=filename_binding,
            content_type=command.content_type.casefold(),
            expected_bytes=command.content_length,
            expected_sha256=checksum,
            created_by=command.actor.actor_id,
            created_at=created_at,
        )
        upload = self._signer.create_upload(
            QuarantineUploadRequest(
                object_key=object_key,
                content_type=version.content_type,
                content_length=version.expected_bytes,
                checksum_sha256=version.expected_sha256,
                expires_at=created_at + self._upload_ttl,
            )
        )
        event = AuditEvent(
            event_id=self._audit_event_id_factory(),
            occurred_at=created_at,
            organization_id=command.organization_id,
            workspace_id=command.workspace_id,
            actor_id=command.actor.actor_id,
            action="dataset.upload_reserved",
            target_type="dataset_version",
            target_id=version_id,
            request_id=command.request_id,
            reason="Authorized direct upload reserved in quarantine storage.",
            before_hash=_ABSENT_HASH,
            after_hash=_version_hash(version),
        )
        self._repository.create_pending(version, event)
        return UploadReservation(version=version, upload=upload, audit_event=event)

    def complete_upload(self, command: CompleteDatasetUpload) -> CompleteUploadResult:
        decision = self._authorization.authorize(
            AuthorizationRequest(
                actor=command.actor,
                permission=Permission.DATASET_UPLOAD,
                scope=ResourceScope(
                    organization_id=command.organization_id,
                    workspace_id=command.workspace_id,
                    resource_type="dataset_version",
                    resource_id=command.dataset_version_id,
                ),
            )
        )
        if not decision.allowed:
            raise DatasetUploadError(decision.reason_code)

        current = self._repository.get_in_scope(
            dataset_version_id=command.dataset_version_id,
            organization_id=command.organization_id,
            workspace_id=command.workspace_id,
        )
        if current is None:
            raise DatasetUploadError("dataset_version_unavailable")
        if current.status is DatasetVersionStatus.UPLOADED:
            existing_job = self._repository.find_job_for_version(current.dataset_version_id)
            if existing_job is None:
                raise RuntimeError("Uploaded dataset version has no scan job.")
            return CompleteUploadResult(version=current, job=existing_job, audit_event=None)
        if current.status is not DatasetVersionStatus.UPLOAD_PENDING:
            raise DatasetUploadError("dataset_version_unavailable")
        metadata = self._signer.inspect(current.object_key)
        if metadata is None:
            raise DatasetUploadError("upload_missing")
        if (
            metadata.object_key != current.object_key
            or metadata.content_length != current.expected_bytes
            or metadata.content_type.casefold() != current.content_type
            or not hmac.compare_digest(metadata.checksum_sha256.casefold(), current.expected_sha256)
        ):
            occurred_at = self._clock()
            quarantined = replace(
                current,
                status=DatasetVersionStatus.QUARANTINED,
                revision=current.revision + 1,
                failure_code="upload_metadata_mismatch",
            )
            event = AuditEvent(
                event_id=self._audit_event_id_factory(),
                occurred_at=occurred_at,
                organization_id=current.organization_id,
                workspace_id=current.workspace_id,
                actor_id=command.actor.actor_id,
                action="dataset.upload_quarantined",
                target_type="dataset_version",
                target_id=current.dataset_version_id,
                request_id=command.request_id,
                reason="Uploaded object metadata did not match its reservation.",
                before_hash=_version_hash(current),
                after_hash=_version_hash(quarantined),
            )
            self._repository.quarantine(
                quarantined,
                event,
                expected_revision=current.revision,
            )
            raise DatasetUploadError("upload_metadata_mismatch")

        occurred_at = self._clock()
        completed = replace(
            current,
            status=DatasetVersionStatus.UPLOADED,
            revision=current.revision + 1,
            uploaded_at=occurred_at,
        )
        job = ImportJob(
            job_id=self._job_id_factory(),
            organization_id=current.organization_id,
            workspace_id=current.workspace_id,
            job_type="dataset.scan",
            status=ImportJobStatus.QUEUED,
            input_reference=MappingProxyType(
                {
                    "dataset_version_id": current.dataset_version_id,
                    "expected_bytes": str(current.expected_bytes),
                    "object_key": current.object_key,
                    "expected_sha256": current.expected_sha256,
                }
            ),
            idempotency_key=(f"dataset.scan:{current.dataset_version_id}:{current.expected_sha256}"),
            created_at=occurred_at,
        )
        event = AuditEvent(
            event_id=self._audit_event_id_factory(),
            occurred_at=occurred_at,
            organization_id=current.organization_id,
            workspace_id=current.workspace_id,
            actor_id=command.actor.actor_id,
            action="dataset.upload_completed",
            target_type="dataset_version",
            target_id=current.dataset_version_id,
            request_id=command.request_id,
            reason="Quarantine object metadata matched the upload reservation.",
            before_hash=_version_hash(current),
            after_hash=_version_hash(completed),
        )
        self._repository.complete_and_enqueue(
            completed,
            job,
            event,
            expected_revision=current.revision,
        )
        return CompleteUploadResult(version=completed, job=job, audit_event=event)
