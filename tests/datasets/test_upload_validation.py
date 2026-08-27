from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from pulseiq.datasets import (
    BeginDatasetUpload,
    CompleteDatasetUpload,
    DatasetUploadError,
    DatasetUploadService,
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


def _upload_context(
    *,
    role: Role = Role.DATA_STEWARD,
    upload_ttl: timedelta = timedelta(minutes=10),
    maximum_bytes: int = 10 * 1024 * 1024,
) -> tuple[DatasetUploadService, AuthenticatedActor]:
    actor = AuthenticatedActor(
        actor_id="actor-1",
        session_id="session-1",
        authenticated_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=10),
        authentication_methods=("federated", "mfa"),
    )
    memberships = InMemoryMembershipRepository(
        [
            Membership(
                membership_id="membership-1",
                actor_id=actor.actor_id,
                organization_id="organization-1",
                workspace_id="workspace-1",
                role=role,
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
    service = DatasetUploadService(
        InMemoryDatasetUploadRepository(),
        InMemoryQuarantineUploadSigner(base_url="https://quarantine.invalid"),
        AuthorizationService(memberships, sessions, clock=lambda: NOW),
        filename_binding_key=b"test-filename-binding-key-32-bytes!",
        clock=lambda: NOW,
        dataset_version_id_factory=lambda: "version-1",
        audit_event_id_factory=lambda: "event-1",
        upload_ttl=upload_ttl,
        maximum_bytes=maximum_bytes,
    )
    return service, actor


def _valid_command(actor: AuthenticatedActor) -> BeginDatasetUpload:
    return BeginDatasetUpload(
        actor=actor,
        organization_id="organization-1",
        workspace_id="workspace-1",
        dataset_id="dataset-1",
        source_filename="customers.csv",
        content_type="text/csv",
        content_length=1024,
        checksum_sha256=CHECKSUM,
        request_id="request-1",
    )


@pytest.mark.parametrize(
    ("changes", "expected_code"),
    [
        ({"dataset_id": "../dataset"}, "invalid_identifier"),
        ({"content_type": "application/json"}, "unsupported_content_type"),
        ({"content_length": 10 * 1024 * 1024 + 1}, "file_too_large"),
        ({"checksum_sha256": "not-a-digest"}, "invalid_checksum"),
        ({"source_filename": "customers.xlsx"}, "unsupported_extension"),
    ],
)
def test_upload_reservation_rejects_unsafe_or_out_of_policy_expectations(
    changes: dict[str, object], expected_code: str
) -> None:
    service, actor = _upload_context()

    with pytest.raises(DatasetUploadError) as error:
        service.begin_upload(replace(_valid_command(actor), **changes))

    assert error.value.code == expected_code


def test_upload_reservation_defaults_to_deny_when_role_lacks_permission() -> None:
    service, actor = _upload_context(role=Role.READ_ONLY)

    with pytest.raises(DatasetUploadError) as error:
        service.begin_upload(_valid_command(actor))

    assert error.value.code == "permission_required"


def test_completion_requires_the_reserved_object_to_exist() -> None:
    service, actor = _upload_context()
    service.begin_upload(_valid_command(actor))

    with pytest.raises(DatasetUploadError) as error:
        service.complete_upload(
            CompleteDatasetUpload(
                actor=actor,
                organization_id="organization-1",
                workspace_id="workspace-1",
                dataset_version_id="version-1",
                request_id="complete-1",
            )
        )

    assert error.value.code == "upload_missing"


@pytest.mark.parametrize(
    ("upload_ttl", "maximum_bytes", "message"),
    [
        (timedelta(minutes=4), 1024, "Upload form lifetime"),
        (timedelta(minutes=16), 1024, "Upload form lifetime"),
        (timedelta(minutes=10), 0, "Maximum upload bytes"),
    ],
)
def test_upload_service_rejects_unsafe_policy_configuration(
    upload_ttl: timedelta, maximum_bytes: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _upload_context(upload_ttl=upload_ttl, maximum_bytes=maximum_bytes)
