from __future__ import annotations

import base64
from typing import Any

import pytest
from botocore.exceptions import ClientError

from pulseiq.datasets.s3_storage import DatasetScanStorageError, S3DatasetScanStorage

CHECKSUM = "6f8db599de986fab7a21625b7916589c94cc3107c10fcb27c01f9564a047f8f1"  # pragma: allowlist secret
CHECKSUM_BASE64 = base64.b64encode(bytes.fromhex(CHECKSUM)).decode("ascii")
SOURCE_KEY = "quarantine/org-1/workspace-1/dataset-1/version-1/original.csv"
DESTINATION_KEY = "originals/org-1/workspace-1/dataset-1/version-1/original.csv"


class FakeBody:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.closed = False

    def read(self, size: int) -> bytes:
        assert size == 4
        return self._chunks.pop(0) if self._chunks else b""

    def close(self) -> None:
        self.closed = True


class FakeScanClient:
    def __init__(self) -> None:
        self.body = FakeBody([b"id,n", b"ame\n"])
        self.get_call: dict[str, Any] | None = None
        self.copy_call: dict[str, Any] | None = None
        self.head_calls: list[dict[str, Any]] = []
        self.head_responses: list[dict[str, Any] | ClientError] = []

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self.get_call = kwargs
        return {"Body": self.body}

    def copy_object(self, **kwargs: Any) -> dict[str, Any]:
        self.copy_call = kwargs
        return {}

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        self.head_calls.append(kwargs)
        response = self.head_responses.pop(0)
        if isinstance(response, ClientError):
            raise response
        return response


def _missing_error() -> ClientError:
    return ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "missing"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
        "HeadObject",
    )


def _storage(client: FakeScanClient) -> S3DatasetScanStorage:
    return S3DatasetScanStorage(
        client,
        quarantine_bucket="pulseiq-quarantine",
        originals_bucket="pulseiq-originals",
        read_chunk_bytes=4,
        expected_bucket_owner="123456789012",
    )


def test_read_chunks_streams_private_object_and_always_closes_body() -> None:
    client = FakeScanClient()

    assert list(_storage(client).read_chunks(SOURCE_KEY)) == [b"id,n", b"ame\n"]

    assert client.get_call == {
        "Bucket": "pulseiq-quarantine",
        "Key": SOURCE_KEY,
        "ChecksumMode": "ENABLED",
        "ExpectedBucketOwner": "123456789012",
    }
    assert client.body.closed is True


def test_promotion_copies_once_then_verifies_destination_checksum() -> None:
    client = FakeScanClient()
    client.head_responses = [_missing_error(), {"ChecksumSHA256": CHECKSUM_BASE64}]

    _storage(client).promote_clean(
        source_key=SOURCE_KEY,
        destination_key=DESTINATION_KEY,
        checksum_sha256=CHECKSUM,
    )

    assert client.copy_call == {
        "Bucket": "pulseiq-originals",
        "Key": DESTINATION_KEY,
        "CopySource": {"Bucket": "pulseiq-quarantine", "Key": SOURCE_KEY},
        "ChecksumAlgorithm": "SHA256",
        "MetadataDirective": "COPY",
        "ServerSideEncryption": "AES256",
        "IfNoneMatch": "*",
        "ExpectedBucketOwner": "123456789012",
        "ExpectedSourceBucketOwner": "123456789012",
    }
    assert client.head_calls == [
        {
            "Bucket": "pulseiq-originals",
            "Key": DESTINATION_KEY,
            "ChecksumMode": "ENABLED",
            "ExpectedBucketOwner": "123456789012",
        },
        {
            "Bucket": "pulseiq-originals",
            "Key": DESTINATION_KEY,
            "ChecksumMode": "ENABLED",
            "ExpectedBucketOwner": "123456789012",
        },
    ]


def test_retry_accepts_already_promoted_matching_object_without_overwrite() -> None:
    client = FakeScanClient()
    client.head_responses = [{"ChecksumSHA256": CHECKSUM_BASE64}]

    _storage(client).promote_clean(
        source_key=SOURCE_KEY,
        destination_key=DESTINATION_KEY,
        checksum_sha256=CHECKSUM,
    )

    assert client.copy_call is None


def test_promotion_refuses_to_overwrite_existing_object_with_different_checksum() -> None:
    client = FakeScanClient()
    client.head_responses = [{"ChecksumSHA256": base64.b64encode(b"x" * 32).decode()}]

    with pytest.raises(DatasetScanStorageError) as error:
        _storage(client).promote_clean(
            source_key=SOURCE_KEY,
            destination_key=DESTINATION_KEY,
            checksum_sha256=CHECKSUM,
        )

    assert error.value.code == "immutable_destination_conflict"
    assert error.value.retryable is False
    assert client.copy_call is None


@pytest.mark.parametrize(
    ("source_key", "destination_key"),
    [
        ("public/caller.csv", DESTINATION_KEY),
        (SOURCE_KEY, "quarantine/org-1/workspace-1/dataset-1/version-1/original.csv"),
        (SOURCE_KEY, "originals/org-1/workspace-1/../version-1/original.csv"),
    ],
)
def test_promotion_rejects_keys_outside_server_owned_shapes(source_key: str, destination_key: str) -> None:
    client = FakeScanClient()

    with pytest.raises(DatasetScanStorageError) as error:
        _storage(client).promote_clean(
            source_key=source_key,
            destination_key=destination_key,
            checksum_sha256=CHECKSUM,
        )

    assert error.value.code == "invalid_scan_storage_reference"
    assert error.value.retryable is False
