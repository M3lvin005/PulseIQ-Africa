from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from botocore.exceptions import ClientError

from pulseiq.datasets import QuarantineUploadRequest
from pulseiq.datasets.s3_storage import QuarantineObjectStoreError, S3QuarantineObjectStore

NOW = datetime(2026, 8, 25, 18, tzinfo=UTC)
CHECKSUM = "6f8db599de986fab7a21625b7916589c94cc3107c10fcb27c01f9564a047f8f1"  # pragma: allowlist secret
OBJECT_KEY = "quarantine/org-1/workspace-1/dataset-1/version-1/original.csv"


class FakeS3Client:
    def __init__(self) -> None:
        self.post_call: dict[str, Any] | None = None
        self.head_call: dict[str, Any] | None = None
        self.head_response: dict[str, Any] = {}
        self.head_error: ClientError | None = None
        self.post_error: ClientError | None = None

    def generate_presigned_post(self, **kwargs: Any) -> dict[str, Any]:
        self.post_call = kwargs
        if self.post_error is not None:
            raise self.post_error
        fields = dict(kwargs["Fields"])
        fields.update(
            {
                "key": kwargs["Key"],
                "policy": "signed-policy",
                "x-amz-signature": "signed-value",
            }
        )
        return {"url": "https://quarantine.example.invalid", "fields": fields}

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        self.head_call = kwargs
        if self.head_error is not None:
            raise self.head_error
        return self.head_response


def _request(*, expires_at: datetime = NOW + timedelta(minutes=10)) -> QuarantineUploadRequest:
    return QuarantineUploadRequest(
        object_key=OBJECT_KEY,
        content_type="text/csv",
        content_length=1024,
        checksum_sha256=CHECKSUM,
        expires_at=expires_at,
    )


def test_presigned_post_binds_exact_key_type_size_checksum_and_encryption() -> None:
    client = FakeS3Client()
    store = S3QuarantineObjectStore(
        client,
        bucket="pulseiq-quarantine",
        expected_bucket_owner="123456789012",
        clock=lambda: NOW,
    )

    upload = store.create_upload(_request())

    checksum_base64 = base64.b64encode(bytes.fromhex(CHECKSUM)).decode("ascii")
    assert client.post_call == {
        "Bucket": "pulseiq-quarantine",
        "Key": OBJECT_KEY,
        "Fields": {
            "Content-Type": "text/csv",
            "success_action_status": "201",
            "x-amz-checksum-algorithm": "SHA256",
            "x-amz-checksum-sha256": checksum_base64,
            "x-amz-server-side-encryption": "AES256",
        },
        "Conditions": [
            {"Content-Type": "text/csv"},
            {"success_action_status": "201"},
            {"x-amz-checksum-algorithm": "SHA256"},
            {"x-amz-checksum-sha256": checksum_base64},
            {"x-amz-server-side-encryption": "AES256"},
            ["content-length-range", 1024, 1024],
        ],
        "ExpiresIn": 600,
    }
    assert upload.url == "https://quarantine.example.invalid"
    assert upload.fields["key"] == OBJECT_KEY
    assert upload.fields["x-amz-checksum-sha256"] == checksum_base64
    assert upload.expires_at == NOW + timedelta(minutes=10)


def test_head_inspection_requests_checksum_and_normalizes_sha256_to_hex() -> None:
    client = FakeS3Client()
    client.head_response = {
        "ContentLength": 1024,
        "ContentType": "text/csv",
        "ChecksumSHA256": base64.b64encode(bytes.fromhex(CHECKSUM)).decode("ascii"),
        "ETag": '"must-not-be-used-as-a-checksum"',
    }
    store = S3QuarantineObjectStore(
        client,
        bucket="pulseiq-quarantine",
        expected_bucket_owner="123456789012",
        clock=lambda: NOW,
    )

    metadata = store.inspect(OBJECT_KEY)

    assert client.head_call == {
        "Bucket": "pulseiq-quarantine",
        "Key": OBJECT_KEY,
        "ChecksumMode": "ENABLED",
        "ExpectedBucketOwner": "123456789012",
    }
    assert metadata is not None
    assert metadata.object_key == OBJECT_KEY
    assert metadata.content_length == 1024
    assert metadata.content_type == "text/csv"
    assert metadata.checksum_sha256 == CHECKSUM


def test_missing_object_returns_none_without_hiding_access_failures() -> None:
    client = FakeS3Client()
    client.head_error = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "missing"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
        "HeadObject",
    )
    store = S3QuarantineObjectStore(client, bucket="pulseiq-quarantine", clock=lambda: NOW)

    assert store.inspect(OBJECT_KEY) is None

    client.head_error = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "denied"}, "ResponseMetadata": {"HTTPStatusCode": 403}},
        "HeadObject",
    )
    with pytest.raises(QuarantineObjectStoreError) as error:
        store.inspect(OBJECT_KEY)
    assert error.value.code == "object_metadata_unavailable"


@pytest.mark.parametrize(
    "head_response",
    [
        {"ContentLength": 1024, "ContentType": "text/csv"},
        {"ContentLength": 1024, "ContentType": "text/csv", "ChecksumSHA256": "not-base64"},
        {"ContentLength": "1024", "ContentType": "text/csv", "ChecksumSHA256": base64.b64encode(b"x" * 32).decode()},
    ],
)
def test_head_inspection_rejects_incomplete_or_malformed_trusted_metadata(head_response: dict[str, Any]) -> None:
    client = FakeS3Client()
    client.head_response = head_response
    store = S3QuarantineObjectStore(client, bucket="pulseiq-quarantine", clock=lambda: NOW)

    with pytest.raises(QuarantineObjectStoreError) as error:
        store.inspect(OBJECT_KEY)

    assert error.value.code == "invalid_object_metadata"


@pytest.mark.parametrize(
    "expires_at",
    [NOW - timedelta(seconds=1), NOW + timedelta(minutes=16)],
)
def test_presigned_post_rejects_expired_or_overlong_policy(expires_at: datetime) -> None:
    store = S3QuarantineObjectStore(FakeS3Client(), bucket="pulseiq-quarantine", clock=lambda: NOW)

    with pytest.raises(QuarantineObjectStoreError) as error:
        store.create_upload(_request(expires_at=expires_at))

    assert error.value.code == "invalid_upload_expiry"


def test_signing_failure_is_wrapped_without_provider_details() -> None:
    client = FakeS3Client()
    client.post_error = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "credential details"}},
        "CreatePresignedPost",
    )
    store = S3QuarantineObjectStore(client, bucket="pulseiq-quarantine", clock=lambda: NOW)

    with pytest.raises(QuarantineObjectStoreError) as error:
        store.create_upload(_request())

    assert error.value.code == "upload_signing_unavailable"
    assert str(error.value) == "Quarantine object storage is unavailable."


@pytest.mark.parametrize(
    "object_key",
    [
        "public/org-1/workspace-1/dataset-1/version-1/original.csv",
        "quarantine/org-1/workspace-1/../version-1/original.csv",
        "quarantine/org-1/workspace-1/dataset-1/version-1/caller-name.csv",
    ],
)
def test_adapter_rejects_keys_outside_the_server_owned_quarantine_shape(object_key: str) -> None:
    store = S3QuarantineObjectStore(FakeS3Client(), bucket="pulseiq-quarantine", clock=lambda: NOW)

    with pytest.raises(QuarantineObjectStoreError) as error:
        store.inspect(object_key)

    assert error.value.code == "invalid_object_key"
