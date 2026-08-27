from __future__ import annotations

import base64
import hashlib
from typing import Any

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from pulseiq.datasets.normalization import DatasetNormalizationStorageError
from pulseiq.datasets.s3_normalization import S3DatasetNormalizationStorage
from pulseiq.datasets.validation import DatasetValidationStorageError

SOURCE = b"id,value\n001,10\n"
PARQUET = b"PAR1-normalized-PAR1"
CHECKSUM = hashlib.sha256(PARQUET).hexdigest()
CHECKSUM_BASE64 = base64.b64encode(bytes.fromhex(CHECKSUM)).decode()
ORIGINAL_KEY = "originals/org-1/workspace-1/dataset-1/version-1/original.csv"
NORMALIZED_KEY = "normalized/org-1/workspace-1/dataset-1/version-1/data.parquet"
METADATA = {
    "columns": "2",
    "normalization-version": "1",
    "rows": "1",
    "source-sha256": hashlib.sha256(SOURCE).hexdigest(),
}


class FakeBody:
    def __init__(self) -> None:
        self.chunks = [SOURCE, b""]
        self.closed = False

    def read(self, size: int) -> bytes:
        assert size == 1024
        return self.chunks.pop(0)

    def close(self) -> None:
        self.closed = True


class FakeClient:
    def __init__(self) -> None:
        self.body = FakeBody()
        self.get_call: dict[str, Any] | None = None
        self.put_call: dict[str, Any] | None = None
        self.head_responses: list[dict[str, Any] | ClientError] = []
        self.get_error: Exception | None = None
        self.get_response: dict[str, Any] | None = None
        self.put_error: Exception | None = None

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self.get_call = kwargs
        if self.get_error is not None:
            raise self.get_error
        return self.get_response if self.get_response is not None else {"Body": self.body}

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.put_call = kwargs
        if self.put_error is not None:
            raise self.put_error
        return {}

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        response = self.head_responses.pop(0)
        if isinstance(response, ClientError):
            raise response
        return response


def _missing() -> ClientError:
    return ClientError(
        {"Error": {"Code": "NoSuchKey"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
        "HeadObject",
    )


def _storage(client: FakeClient) -> S3DatasetNormalizationStorage:
    return S3DatasetNormalizationStorage(
        client,
        originals_bucket="pulseiq-originals",
        normalized_bucket="pulseiq-normalized",
        expected_bucket_owner="123456789012",
        read_chunk_bytes=1024,
    )


def test_reads_clean_original_with_owner_binding_and_closes_stream() -> None:
    client = FakeClient()

    assert list(_storage(client).read_chunks(ORIGINAL_KEY)) == [SOURCE]

    assert client.get_call == {
        "Bucket": "pulseiq-originals",
        "Key": ORIGINAL_KEY,
        "ChecksumMode": "ENABLED",
        "ExpectedBucketOwner": "123456789012",
    }
    assert client.body.closed is True


def test_conditionally_writes_checksum_bound_encrypted_parquet() -> None:
    client = FakeClient()
    client.head_responses = [_missing(), {"ChecksumSHA256": CHECKSUM_BASE64}]

    _storage(client).store_normalized(
        object_key=NORMALIZED_KEY,
        payload=PARQUET,
        checksum_sha256=CHECKSUM,
        metadata=METADATA,
    )

    assert client.put_call == {
        "Bucket": "pulseiq-normalized",
        "Key": NORMALIZED_KEY,
        "Body": PARQUET,
        "ChecksumAlgorithm": "SHA256",
        "ChecksumSHA256": CHECKSUM_BASE64,
        "ContentType": "application/vnd.apache.parquet",
        "ExpectedBucketOwner": "123456789012",
        "IfNoneMatch": "*",
        "Metadata": METADATA,
        "ServerSideEncryption": "AES256",
    }


def test_matching_existing_normalized_object_is_idempotent() -> None:
    client = FakeClient()
    client.head_responses = [{"ChecksumSHA256": CHECKSUM_BASE64}]

    _storage(client).store_normalized(
        object_key=NORMALIZED_KEY,
        payload=PARQUET,
        checksum_sha256=CHECKSUM,
        metadata=METADATA,
    )

    assert client.put_call is None


def test_reads_checksum_bound_normalized_artifact_for_validation() -> None:
    client = FakeClient()
    client.body.chunks = [PARQUET[:5], PARQUET[5:], b""]
    client.get_response = {"Body": client.body, "ChecksumSHA256": CHECKSUM_BASE64}

    payload = _storage(client).read_normalized(object_key=NORMALIZED_KEY, expected_sha256=CHECKSUM)

    assert payload == PARQUET
    assert client.get_call == {
        "Bucket": "pulseiq-normalized",
        "Key": NORMALIZED_KEY,
        "ChecksumMode": "ENABLED",
        "ExpectedBucketOwner": "123456789012",
    }
    assert client.body.closed is True


def test_validation_read_rejects_wrong_remote_or_streamed_checksum() -> None:
    client = FakeClient()
    client.get_response = {
        "Body": client.body,
        "ChecksumSHA256": base64.b64encode(b"x" * 32).decode(),
    }
    with pytest.raises(DatasetValidationStorageError) as remote_error:
        _storage(client).read_normalized(object_key=NORMALIZED_KEY, expected_sha256=CHECKSUM)
    assert remote_error.value.code == "normalized_checksum_mismatch"

    client = FakeClient()
    client.body.chunks = [b"changed", b""]
    client.get_response = {"Body": client.body, "ChecksumSHA256": CHECKSUM_BASE64}
    with pytest.raises(DatasetValidationStorageError) as stream_error:
        _storage(client).read_normalized(object_key=NORMALIZED_KEY, expected_sha256=CHECKSUM)
    assert stream_error.value.code == "normalized_checksum_mismatch"


def test_validation_read_classifies_invalid_reference_provider_and_stream_failures() -> None:
    with pytest.raises(DatasetValidationStorageError) as reference_error:
        _storage(FakeClient()).read_normalized(object_key="public/data.parquet", expected_sha256=CHECKSUM)
    assert reference_error.value.code == "invalid_validation_artifact_reference"

    client = FakeClient()
    client.get_error = EndpointConnectionError(endpoint_url="https://s3.invalid")
    with pytest.raises(DatasetValidationStorageError) as provider_error:
        _storage(client).read_normalized(object_key=NORMALIZED_KEY, expected_sha256=CHECKSUM)
    assert provider_error.value.code == "normalized_read_unavailable"
    assert provider_error.value.retryable is True

    client = FakeClient()
    client.get_response = {"Body": object()}
    with pytest.raises(DatasetValidationStorageError) as metadata_error:
        _storage(client).read_normalized(object_key=NORMALIZED_KEY, expected_sha256=CHECKSUM)
    assert metadata_error.value.code == "invalid_normalized_metadata"

    client = FakeClient()
    client.get_response = {"Body": object(), "ChecksumSHA256": CHECKSUM_BASE64}
    with pytest.raises(DatasetValidationStorageError) as stream_error:
        _storage(client).read_normalized(object_key=NORMALIZED_KEY, expected_sha256=CHECKSUM)
    assert stream_error.value.code == "invalid_normalized_stream"


def test_validation_read_enforces_parquet_memory_ceiling_and_nonempty_payload() -> None:
    client = FakeClient()
    client.body.chunks = [PARQUET, b""]
    client.get_response = {"Body": client.body, "ChecksumSHA256": CHECKSUM_BASE64}
    storage = S3DatasetNormalizationStorage(
        client,
        originals_bucket="pulseiq-originals",
        normalized_bucket="pulseiq-normalized",
        maximum_parquet_bytes=3,
        read_chunk_bytes=1024,
    )
    with pytest.raises(DatasetValidationStorageError) as size_error:
        storage.read_normalized(object_key=NORMALIZED_KEY, expected_sha256=CHECKSUM)
    assert size_error.value.code == "normalized_artifact_too_large"
    assert client.body.closed is True

    empty_checksum = hashlib.sha256(b"").hexdigest()
    client = FakeClient()
    client.body.chunks = [b""]
    client.get_response = {
        "Body": client.body,
        "ChecksumSHA256": base64.b64encode(bytes.fromhex(empty_checksum)).decode(),
    }
    with pytest.raises(DatasetValidationStorageError) as empty_error:
        _storage(client).read_normalized(object_key=NORMALIZED_KEY, expected_sha256=empty_checksum)
    assert empty_error.value.code == "normalized_checksum_mismatch"


def test_existing_normalized_checksum_conflict_is_permanent() -> None:
    client = FakeClient()
    client.head_responses = [{"ChecksumSHA256": base64.b64encode(b"x" * 32).decode()}]

    with pytest.raises(DatasetNormalizationStorageError) as error:
        _storage(client).store_normalized(
            object_key=NORMALIZED_KEY,
            payload=PARQUET,
            checksum_sha256=CHECKSUM,
            metadata=METADATA,
        )

    assert error.value.code == "normalized_destination_conflict"
    assert error.value.retryable is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"originals_bucket": ""},
        {"normalized_bucket": " "},
        {"read_chunk_bytes": 0},
        {"maximum_parquet_bytes": 0},
        {"expected_bucket_owner": "invalid"},
    ],
)
def test_rejects_invalid_storage_configuration(kwargs: dict[str, Any]) -> None:
    settings: dict[str, Any] = {
        "originals_bucket": "pulseiq-originals",
        "normalized_bucket": "pulseiq-normalized",
    }
    settings.update(kwargs)
    with pytest.raises(ValueError):
        S3DatasetNormalizationStorage(FakeClient(), **settings)


def test_rejects_invalid_original_key_before_network_access() -> None:
    with pytest.raises(DatasetNormalizationStorageError) as error:
        _storage(FakeClient()).read_chunks("public/caller.csv")
    assert error.value.code == "invalid_normalization_reference"
    assert error.value.retryable is False


def test_classifies_unavailable_or_invalid_original_stream() -> None:
    client = FakeClient()
    client.get_error = EndpointConnectionError(endpoint_url="https://s3.invalid")
    with pytest.raises(DatasetNormalizationStorageError) as unavailable:
        list(_storage(client).read_chunks(ORIGINAL_KEY))
    assert unavailable.value.code == "original_read_unavailable"

    client = FakeClient()
    client.get_response = {"Body": object()}
    with pytest.raises(DatasetNormalizationStorageError) as invalid:
        list(_storage(client).read_chunks(ORIGINAL_KEY))
    assert invalid.value.code == "invalid_original_stream"

    class InvalidBody(FakeBody):
        def read(self, size: int) -> bytes:
            return "not-bytes"  # type: ignore[return-value]

    client = FakeClient()
    client.body = InvalidBody()
    with pytest.raises(DatasetNormalizationStorageError) as invalid_chunk:
        list(_storage(client).read_chunks(ORIGINAL_KEY))
    assert invalid_chunk.value.code == "invalid_original_stream"


@pytest.mark.parametrize(
    ("object_key", "payload", "checksum", "metadata"),
    [
        ("public/data.parquet", PARQUET, CHECKSUM, METADATA),
        (NORMALIZED_KEY, b"", hashlib.sha256(b"").hexdigest(), METADATA),
        (NORMALIZED_KEY, PARQUET, "0" * 64, METADATA),
        (NORMALIZED_KEY, PARQUET, CHECKSUM, {**METADATA, "rows": "not-a-number"}),
    ],
)
def test_rejects_invalid_normalized_artifact_before_network_access(
    object_key: str,
    payload: bytes,
    checksum: str,
    metadata: dict[str, str],
) -> None:
    with pytest.raises(DatasetNormalizationStorageError) as error:
        _storage(FakeClient()).store_normalized(
            object_key=object_key,
            payload=payload,
            checksum_sha256=checksum,
            metadata=metadata,
        )
    assert error.value.code == "invalid_normalized_artifact"
    assert error.value.retryable is False


def test_classifies_head_and_put_failures_without_provider_details() -> None:
    denied = ClientError(
        {"Error": {"Code": "AccessDenied"}, "ResponseMetadata": {"HTTPStatusCode": 403}},
        "HeadObject",
    )
    client = FakeClient()
    client.head_responses = [denied]
    with pytest.raises(DatasetNormalizationStorageError) as head_error:
        _storage(client).store_normalized(
            object_key=NORMALIZED_KEY,
            payload=PARQUET,
            checksum_sha256=CHECKSUM,
            metadata=METADATA,
        )
    assert head_error.value.code == "normalized_metadata_unavailable"

    client = FakeClient()
    client.head_responses = [_missing()]
    client.put_error = EndpointConnectionError(endpoint_url="https://s3.invalid")
    with pytest.raises(DatasetNormalizationStorageError) as put_error:
        _storage(client).store_normalized(
            object_key=NORMALIZED_KEY,
            payload=PARQUET,
            checksum_sha256=CHECKSUM,
            metadata=METADATA,
        )
    assert put_error.value.code == "normalized_write_unavailable"


def test_conditional_write_race_accepts_same_checksum_and_rejects_conflict() -> None:
    precondition = ClientError(
        {"Error": {"Code": "PreconditionFailed"}, "ResponseMetadata": {"HTTPStatusCode": 412}},
        "PutObject",
    )
    client = FakeClient()
    client.head_responses = [_missing(), {"ChecksumSHA256": CHECKSUM_BASE64}]
    client.put_error = precondition
    _storage(client).store_normalized(
        object_key=NORMALIZED_KEY,
        payload=PARQUET,
        checksum_sha256=CHECKSUM,
        metadata=METADATA,
    )

    client = FakeClient()
    client.head_responses = [_missing(), {"ChecksumSHA256": base64.b64encode(b"x" * 32).decode()}]
    client.put_error = precondition
    with pytest.raises(DatasetNormalizationStorageError) as conflict:
        _storage(client).store_normalized(
            object_key=NORMALIZED_KEY,
            payload=PARQUET,
            checksum_sha256=CHECKSUM,
            metadata=METADATA,
        )
    assert conflict.value.code == "normalized_destination_conflict"


@pytest.mark.parametrize(
    ("post_write_response", "expected_code", "retryable"),
    [
        (_missing(), "normalized_object_missing", True),
        ({"ChecksumSHA256": base64.b64encode(b"x" * 32).decode()}, "normalized_checksum_mismatch", False),
        ({"ChecksumSHA256": "not-base64"}, "invalid_normalized_metadata", True),
    ],
)
def test_rejects_missing_corrupt_or_malformed_post_write_object(
    post_write_response: dict[str, Any] | ClientError,
    expected_code: str,
    retryable: bool,
) -> None:
    client = FakeClient()
    client.head_responses = [_missing(), post_write_response]
    with pytest.raises(DatasetNormalizationStorageError) as error:
        _storage(client).store_normalized(
            object_key=NORMALIZED_KEY,
            payload=PARQUET,
            checksum_sha256=CHECKSUM,
            metadata=METADATA,
        )
    assert error.value.code == expected_code
    assert error.value.retryable is retryable
