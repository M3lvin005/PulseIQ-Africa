"""S3-compatible storage adapter for clean originals and normalized Parquet."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
from collections.abc import Iterable, Iterator, Mapping
from typing import Protocol, cast

from botocore.exceptions import BotoCoreError, ClientError

from .normalization import DatasetNormalizationStorageError
from .validation import DatasetValidationStorageError

_ORIGINAL_KEY_PATTERN = re.compile(
    r"^originals/[A-Za-z0-9][A-Za-z0-9_-]{0,127}/[A-Za-z0-9][A-Za-z0-9_-]{0,127}/"
    r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}/[A-Za-z0-9][A-Za-z0-9_-]{0,127}/original\.csv$"
)
_NORMALIZED_KEY_PATTERN = re.compile(
    r"^normalized/[A-Za-z0-9][A-Za-z0-9_-]{0,127}/[A-Za-z0-9][A-Za-z0-9_-]{0,127}/"
    r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}/[A-Za-z0-9][A-Za-z0-9_-]{0,127}/data\.parquet$"
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_METADATA_KEYS = frozenset({"columns", "normalization-version", "rows", "source-sha256"})


class StreamingBody(Protocol):
    def read(self, amount: int) -> bytes: ...

    def close(self) -> None: ...


class S3NormalizationClient(Protocol):
    def get_object(self, **kwargs: object) -> Mapping[str, object]: ...

    def head_object(self, **kwargs: object) -> Mapping[str, object]: ...

    def put_object(self, **kwargs: object) -> Mapping[str, object]: ...


class S3DatasetNormalizationStorage:
    """Read immutable originals and conditionally create normalized artifacts."""

    def __init__(
        self,
        client: S3NormalizationClient,
        *,
        originals_bucket: str,
        normalized_bucket: str,
        read_chunk_bytes: int = 64 * 1024,
        maximum_parquet_bytes: int = 25 * 1024 * 1024,
        expected_bucket_owner: str | None = None,
    ) -> None:
        if not originals_bucket or originals_bucket.isspace():
            raise ValueError("Originals bucket must be non-empty.")
        if not normalized_bucket or normalized_bucket.isspace():
            raise ValueError("Normalized bucket must be non-empty.")
        if not 1 <= read_chunk_bytes <= 1024 * 1024:
            raise ValueError("Read chunks must be between 1 byte and 1 MiB.")
        if not 1 <= maximum_parquet_bytes <= 100 * 1024 * 1024:
            raise ValueError("Parquet limit must be between 1 byte and 100 MiB.")
        if expected_bucket_owner is not None and (
            len(expected_bucket_owner) != 12 or not expected_bucket_owner.isdigit()
        ):
            raise ValueError("Expected bucket owner must be a 12-digit AWS account ID.")
        self._client = client
        self._originals_bucket = originals_bucket
        self._normalized_bucket = normalized_bucket
        self._read_chunk_bytes = read_chunk_bytes
        self._maximum_parquet_bytes = maximum_parquet_bytes
        self._expected_bucket_owner = expected_bucket_owner

    def read_chunks(self, object_key: str) -> Iterable[bytes]:
        if _ORIGINAL_KEY_PATTERN.fullmatch(object_key) is None:
            raise DatasetNormalizationStorageError("invalid_normalization_reference", retryable=False)
        parameters: dict[str, object] = {
            "Bucket": self._originals_bucket,
            "Key": object_key,
            "ChecksumMode": "ENABLED",
        }
        self._add_owner(parameters)

        def stream() -> Iterator[bytes]:
            try:
                response = self._client.get_object(**parameters)
            except (BotoCoreError, ClientError) as exc:
                raise DatasetNormalizationStorageError("original_read_unavailable", retryable=True) from exc
            body_value = response.get("Body")
            if (
                body_value is None
                or not callable(getattr(body_value, "read", None))
                or not callable(getattr(body_value, "close", None))
            ):
                raise DatasetNormalizationStorageError("invalid_original_stream", retryable=True)
            body = cast(StreamingBody, body_value)
            try:
                while chunk := body.read(self._read_chunk_bytes):
                    if not isinstance(chunk, bytes):
                        raise DatasetNormalizationStorageError("invalid_original_stream", retryable=True)
                    yield chunk
            except (BotoCoreError, ClientError, OSError) as exc:
                raise DatasetNormalizationStorageError("original_read_unavailable", retryable=True) from exc
            finally:
                body.close()

        return stream()

    def store_normalized(
        self,
        *,
        object_key: str,
        payload: bytes,
        checksum_sha256: str,
        metadata: Mapping[str, str],
    ) -> None:
        self._validate_write(object_key, payload, checksum_sha256, metadata)
        existing = self._checksum(object_key)
        if existing is not None:
            if hmac.compare_digest(existing, checksum_sha256):
                return
            raise DatasetNormalizationStorageError("normalized_destination_conflict", retryable=False)

        checksum_base64 = base64.b64encode(bytes.fromhex(checksum_sha256)).decode("ascii")
        parameters: dict[str, object] = {
            "Bucket": self._normalized_bucket,
            "Key": object_key,
            "Body": payload,
            "ChecksumAlgorithm": "SHA256",
            "ChecksumSHA256": checksum_base64,
            "ContentType": "application/vnd.apache.parquet",
            "IfNoneMatch": "*",
            "Metadata": dict(metadata),
            "ServerSideEncryption": "AES256",
        }
        self._add_owner(parameters)
        try:
            self._client.put_object(**parameters)
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status == 412:
                raced_checksum = self._checksum(object_key)
                if raced_checksum is not None and hmac.compare_digest(raced_checksum, checksum_sha256):
                    return
                raise DatasetNormalizationStorageError("normalized_destination_conflict", retryable=False) from exc
            raise DatasetNormalizationStorageError("normalized_write_unavailable", retryable=True) from exc
        except BotoCoreError as exc:
            raise DatasetNormalizationStorageError("normalized_write_unavailable", retryable=True) from exc

        persisted = self._checksum(object_key)
        if persisted is None:
            raise DatasetNormalizationStorageError("normalized_object_missing", retryable=True)
        if not hmac.compare_digest(persisted, checksum_sha256):
            raise DatasetNormalizationStorageError("normalized_checksum_mismatch", retryable=False)

    def read_normalized(self, *, object_key: str, expected_sha256: str) -> bytes:
        """Read one checksum-bound Parquet object under a strict memory ceiling."""

        if _NORMALIZED_KEY_PATTERN.fullmatch(object_key) is None or _SHA256_PATTERN.fullmatch(expected_sha256) is None:
            raise DatasetValidationStorageError("invalid_validation_artifact_reference", retryable=False)
        parameters: dict[str, object] = {
            "Bucket": self._normalized_bucket,
            "Key": object_key,
            "ChecksumMode": "ENABLED",
        }
        self._add_owner(parameters)
        try:
            response = self._client.get_object(**parameters)
        except (BotoCoreError, ClientError) as exc:
            raise DatasetValidationStorageError("normalized_read_unavailable", retryable=True) from exc
        remote_checksum = self._decode_checksum(response.get("ChecksumSHA256"))
        if remote_checksum is None:
            raise DatasetValidationStorageError("invalid_normalized_metadata", retryable=True)
        if not hmac.compare_digest(remote_checksum, expected_sha256):
            raise DatasetValidationStorageError("normalized_checksum_mismatch", retryable=False)
        body_value = response.get("Body")
        if (
            body_value is None
            or not callable(getattr(body_value, "read", None))
            or not callable(getattr(body_value, "close", None))
        ):
            raise DatasetValidationStorageError("invalid_normalized_stream", retryable=True)
        body = cast(StreamingBody, body_value)
        payload = bytearray()
        digest = hashlib.sha256()
        try:
            while chunk := body.read(self._read_chunk_bytes):
                if not isinstance(chunk, bytes):
                    raise DatasetValidationStorageError("invalid_normalized_stream", retryable=True)
                if len(payload) + len(chunk) > self._maximum_parquet_bytes:
                    raise DatasetValidationStorageError("normalized_artifact_too_large", retryable=False)
                payload.extend(chunk)
                digest.update(chunk)
        except (BotoCoreError, ClientError, OSError) as exc:
            raise DatasetValidationStorageError("normalized_read_unavailable", retryable=True) from exc
        finally:
            body.close()
        if not payload or not hmac.compare_digest(digest.hexdigest(), expected_sha256):
            raise DatasetValidationStorageError("normalized_checksum_mismatch", retryable=False)
        return bytes(payload)

    def _checksum(self, object_key: str) -> str | None:
        parameters: dict[str, object] = {
            "Bucket": self._normalized_bucket,
            "Key": object_key,
            "ChecksumMode": "ENABLED",
        }
        self._add_owner(parameters)
        try:
            response = self._client.head_object(**parameters)
        except ClientError as exc:
            if self._is_missing(exc):
                return None
            raise DatasetNormalizationStorageError("normalized_metadata_unavailable", retryable=True) from exc
        except BotoCoreError as exc:
            raise DatasetNormalizationStorageError("normalized_metadata_unavailable", retryable=True) from exc
        checksum = response.get("ChecksumSHA256")
        if not isinstance(checksum, str):
            raise DatasetNormalizationStorageError("invalid_normalized_metadata", retryable=True)
        decoded = self._decode_checksum(checksum)
        if decoded is None:
            raise DatasetNormalizationStorageError("invalid_normalized_metadata", retryable=True)
        return decoded

    @staticmethod
    def _decode_checksum(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        try:
            checksum_bytes = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError):
            return None
        return checksum_bytes.hex() if len(checksum_bytes) == 32 else None

    def _validate_write(
        self,
        object_key: str,
        payload: bytes,
        checksum: str,
        metadata: Mapping[str, str],
    ) -> None:
        valid_metadata = (
            set(metadata) == _METADATA_KEYS
            and metadata.get("normalization-version") == "1"
            and metadata.get("rows", "").isascii()
            and metadata.get("rows", "").isdecimal()
            and metadata.get("columns", "").isascii()
            and metadata.get("columns", "").isdecimal()
            and _SHA256_PATTERN.fullmatch(metadata.get("source-sha256", "")) is not None
        )
        if (
            _NORMALIZED_KEY_PATTERN.fullmatch(object_key) is None
            or not isinstance(payload, bytes)
            or not 1 <= len(payload) <= self._maximum_parquet_bytes
            or _SHA256_PATTERN.fullmatch(checksum) is None
            or not hmac.compare_digest(hashlib.sha256(payload).hexdigest(), checksum)
            or not valid_metadata
        ):
            raise DatasetNormalizationStorageError("invalid_normalized_artifact", retryable=False)

    def _add_owner(self, parameters: dict[str, object]) -> None:
        if self._expected_bucket_owner is not None:
            parameters["ExpectedBucketOwner"] = self._expected_bucket_owner

    @staticmethod
    def _is_missing(error: ClientError) -> bool:
        response = error.response
        metadata = response.get("ResponseMetadata", {})
        detail = response.get("Error", {})
        status = metadata.get("HTTPStatusCode") if isinstance(metadata, Mapping) else None
        code = detail.get("Code") if isinstance(detail, Mapping) else None
        return status == 404 or code in {"404", "NoSuchKey", "NotFound"}
