from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pulseiq.datasets import (
    BeginDatasetUpload,
    CompleteDatasetUpload,
    DatasetUploadError,
    DatasetUploadService,
    DatasetVersionStatus,
    ImportJobStatus,
    InMemoryDatasetUploadRepository,
    InMemoryQuarantineUploadSigner,
)
from pulseiq.identity import (
    AuthenticatedActor,
    AuthorizationService,
    InMemoryMembershipRepository,
    InMemorySessionRepository,
    Membership,
    MembershipStatus,
    Role,
    SessionRecord,
    SessionStatus,
)

NOW = datetime(2026, 8, 25, 17, tzinfo=UTC)
CHECKSUM = "6f8db599de986fab7a21625b7916589c94cc3107c10fcb27c01f9564a047f8f1"  # pragma: allowlist secret


def test_data_steward_reserves_tenant_bound_quarantine_upload_without_raw_filename() -> None:
    actor = AuthenticatedActor(
        actor_id="actor-steward",
        session_id="session-steward",
        authenticated_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(minutes=10),
        authentication_methods=("federated", "mfa"),
    )
    memberships = InMemoryMembershipRepository(
        [
            Membership(
                membership_id="membership-steward",
                actor_id=actor.actor_id,
                organization_id="organization-1",
                workspace_id="workspace-1",
                role=Role.DATA_STEWARD,
                status=MembershipStatus.ACTIVE,
            )
        ]
    )
    sessions = InMemorySessionRepository(
        [
            SessionRecord(
                session_id=actor.session_id,
                actor_id=actor.actor_id,
                authenticated_at=actor.authenticated_at,
                expires_at=actor.expires_at,
                status=SessionStatus.ACTIVE,
            )
        ]
    )
    repository = InMemoryDatasetUploadRepository()
    signer = InMemoryQuarantineUploadSigner(base_url="https://quarantine.invalid")
    service = DatasetUploadService(
        repository,
        signer,
        AuthorizationService(memberships, sessions, clock=lambda: NOW),
        filename_binding_key=b"test-filename-binding-key-32-bytes!",
        clock=lambda: NOW,
        dataset_version_id_factory=lambda: "version-1",
        audit_event_id_factory=lambda: "event-1",
    )

    result = service.begin_upload(
        BeginDatasetUpload(
            actor=actor,
            organization_id="organization-1",
            workspace_id="workspace-1",
            dataset_id="dataset-1",
            source_filename="Customer Names August.csv",
            content_type="text/csv",
            content_length=1_024,
            checksum_sha256=CHECKSUM,
            request_id="request-upload-1",
        )
    )

    assert result.version.status is DatasetVersionStatus.UPLOAD_PENDING
    assert result.version.object_key == ("quarantine/organization-1/workspace-1/dataset-1/version-1/original.csv")
    assert result.version.filename_binding.startswith("hmac-sha256:")
    assert "Customer Names" not in repr(result.version)
    assert result.upload.expires_at == NOW + timedelta(minutes=10)
    assert result.upload.fields["key"] == result.version.object_key
    assert result.upload.fields["Content-Type"] == "text/csv"
    assert result.upload.fields["x-pulseiq-content-length"] == "1024"
    assert result.upload.fields["x-pulseiq-checksum-sha256"] == CHECKSUM
    assert result.audit_event.action == "dataset.upload_reserved"


def test_matching_uploaded_object_queues_reference_only_scan_job() -> None:
    actor = AuthenticatedActor(
        actor_id="actor-steward",
        session_id="session-steward",
        authenticated_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(minutes=10),
        authentication_methods=("federated", "mfa"),
    )
    memberships = InMemoryMembershipRepository(
        [
            Membership(
                membership_id="membership-steward",
                actor_id=actor.actor_id,
                organization_id="organization-1",
                workspace_id="workspace-1",
                role=Role.DATA_STEWARD,
                status=MembershipStatus.ACTIVE,
            )
        ]
    )
    sessions = InMemorySessionRepository(
        [
            SessionRecord(
                session_id=actor.session_id,
                actor_id=actor.actor_id,
                authenticated_at=actor.authenticated_at,
                expires_at=actor.expires_at,
                status=SessionStatus.ACTIVE,
            )
        ]
    )
    repository = InMemoryDatasetUploadRepository()
    storage = InMemoryQuarantineUploadSigner(base_url="https://quarantine.invalid")
    service = DatasetUploadService(
        repository,
        storage,
        AuthorizationService(memberships, sessions, clock=lambda: NOW),
        filename_binding_key=b"test-filename-binding-key-32-bytes!",
        clock=lambda: NOW,
        dataset_version_id_factory=lambda: "version-1",
        audit_event_id_factory=iter(("event-reserved", "event-completed")).__next__,
        job_id_factory=lambda: "job-1",
    )
    reservation = service.begin_upload(
        BeginDatasetUpload(
            actor=actor,
            organization_id="organization-1",
            workspace_id="workspace-1",
            dataset_id="dataset-1",
            source_filename="customers.csv",
            content_type="text/csv",
            content_length=1_024,
            checksum_sha256=CHECKSUM,
            request_id="request-upload-1",
        )
    )
    storage.record_uploaded_object(
        object_key=reservation.version.object_key,
        content_type="text/csv",
        content_length=1_024,
        checksum_sha256=CHECKSUM,
    )

    result = service.complete_upload(
        CompleteDatasetUpload(
            actor=actor,
            organization_id="organization-1",
            workspace_id="workspace-1",
            dataset_version_id="version-1",
            request_id="request-complete-1",
        )
    )

    assert result.version.status is DatasetVersionStatus.UPLOADED
    assert result.version.revision == 2
    assert result.job.status is ImportJobStatus.QUEUED
    assert result.job.job_type == "dataset.scan"
    assert result.job.input_reference == {
        "dataset_version_id": "version-1",
        "expected_bytes": "1024",
        "object_key": reservation.version.object_key,
        "expected_sha256": CHECKSUM,
    }
    assert result.job.idempotency_key == f"dataset.scan:version-1:{CHECKSUM}"
    assert result.audit_event.action == "dataset.upload_completed"

    replay = service.complete_upload(
        CompleteDatasetUpload(
            actor=actor,
            organization_id="organization-1",
            workspace_id="workspace-1",
            dataset_version_id="version-1",
            request_id="request-complete-replay",
        )
    )
    assert replay.version == result.version
    assert replay.job == result.job
    assert replay.audit_event is None


def test_mismatched_uploaded_object_is_durably_quarantined_without_job() -> None:
    actor = AuthenticatedActor(
        actor_id="actor-steward",
        session_id="session-steward",
        authenticated_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(minutes=10),
        authentication_methods=("federated", "mfa"),
    )
    memberships = InMemoryMembershipRepository(
        [
            Membership(
                membership_id="membership-steward",
                actor_id=actor.actor_id,
                organization_id="organization-1",
                workspace_id="workspace-1",
                role=Role.DATA_STEWARD,
                status=MembershipStatus.ACTIVE,
            )
        ]
    )
    sessions = InMemorySessionRepository(
        [
            SessionRecord(
                session_id=actor.session_id,
                actor_id=actor.actor_id,
                authenticated_at=actor.authenticated_at,
                expires_at=actor.expires_at,
                status=SessionStatus.ACTIVE,
            )
        ]
    )
    repository = InMemoryDatasetUploadRepository()
    storage = InMemoryQuarantineUploadSigner(base_url="https://quarantine.invalid")
    service = DatasetUploadService(
        repository,
        storage,
        AuthorizationService(memberships, sessions, clock=lambda: NOW),
        filename_binding_key=b"test-filename-binding-key-32-bytes!",
        clock=lambda: NOW,
        dataset_version_id_factory=lambda: "version-1",
        audit_event_id_factory=iter(("event-reserved", "event-quarantined")).__next__,
        job_id_factory=lambda: "job-must-not-be-created",
    )
    reservation = service.begin_upload(
        BeginDatasetUpload(
            actor=actor,
            organization_id="organization-1",
            workspace_id="workspace-1",
            dataset_id="dataset-1",
            source_filename="customers.csv",
            content_type="text/csv",
            content_length=1_024,
            checksum_sha256=CHECKSUM,
            request_id="request-upload-1",
        )
    )
    storage.record_uploaded_object(
        object_key=reservation.version.object_key,
        content_type="text/csv",
        content_length=1_024,
        checksum_sha256="0" * 64,
    )
    command = CompleteDatasetUpload(
        actor=actor,
        organization_id="organization-1",
        workspace_id="workspace-1",
        dataset_version_id="version-1",
        request_id="request-complete-1",
    )

    try:
        service.complete_upload(command)
    except DatasetUploadError as error:
        assert error.code == "upload_metadata_mismatch"
    else:  # pragma: no cover - explicit quarantine assertion
        raise AssertionError("Mismatched object metadata must be rejected.")

    storage.record_uploaded_object(
        object_key=reservation.version.object_key,
        content_type="text/csv",
        content_length=1_024,
        checksum_sha256=CHECKSUM,
    )
    try:
        service.complete_upload(command)
    except DatasetUploadError as error:
        assert error.code == "dataset_version_unavailable"
    else:  # pragma: no cover - explicit durable-quarantine assertion
        raise AssertionError("A quarantined object must not become queueable on retry.")
