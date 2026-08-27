"""Private S3-compatible quarantine storage adapter."""

from __future__ import annotations

import base64
import binascii
import hmac
import math
import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from datetime import datetime
from types import MappingProxyType
from typing import Protocol, cast

from botocore.exceptions import BotoCoreError, ClientError

from .scanning import DatasetScanStorageError
from .upload_contracts import PresignedUpload, QuarantineUploadRequest, StoredObjectMetadata

_QUARANTINE_KEY_PATTERN = re.compile(
    r"^quarantine/[A-Za-z0-9][A-Za-z0-9_-]{0,127}/[A-Za-z0-9][A-Za-z0-9_-]{0,127}/"
    r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}/[A-Za-z0-9][A-Za-z0-9_-]{0,127}/original\.csv$"
)
_ORIGINAL_KEY_PATTERN = re.compile(
    r"^originals/[A-Za-z0-9][A-Za-z0-9_-]{0,127}/[A-Za-z0-9][A-Za-z0-9_-]{0,127}/"
    r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}/[A-Za-z0-9][A-Za-z0-9_-]{0,127}/original\.csv$"
)


class StreamingBody(Protocol):
    def read(self, amount: int) -> bytes: ...

    def close(self) -> None: ...


class S3Client(Protocol):
    """Narrow Boto3 S3 client surface required by quarantine storage."""

    def generate_presigned_post(
        self,
        *,
        Bucket: str,
        Key: str,
        Fields: dict[str, str],
        Conditions: list[dict[str, str] | list[str | int]],
        ExpiresIn: int,
    ) -> Mapping[str, object]: ...

    def head_object(self, **kwargs: str) -> Mapping[str, object]: ...

    def get_object(self, **kwargs: str) -> Mapping[str, object]: ...

    def copy_object(self, **kwargs: object) -> Mapping[str, object]: ...


class QuarantineObjectStoreError(RuntimeError):
    """Safe infrastructure failure with a stable application code."""

    def __init__(self, code: str) -> None:
        super().__init__("Quarantine object storage is unavailable.")
        self.code = code


class S3DatasetScanStorage:
    """Stream quarantine bytes and idempotently copy verified originals."""

    def __init__(
        self,
        client: S3Client,
        *,
        quarantine_bucket: str,
        originals_bucket: str,
        read_chunk_bytes: int = 64 * 1024,
        expected_bucket_owner: str | None = None,
        server_side_encryption: str = "AES256",
    ) -> None:
        if not quarantine_bucket or quarantine_bucket.isspace():
            raise ValueError("Quarantine bucket must be non-empty.")
        if not originals_bucket or originals_bucket.isspace():
            raise ValueError("Originals bucket must be non-empty.")
        if not 1 <= read_chunk_bytes <= 1024 * 1024:
            raise ValueError("Read chunks must be between 1 byte and 1 MiB.")
        if expected_bucket_owner is not None and (
            len(expected_bucket_owner) != 12 or not expected_bucket_owner.isdigit()
        ):
            raise ValueError("Expected bucket owner must be a 12-digit AWS account ID.")
        if server_side_encryption != "AES256":
            raise ValueError("Only S3-managed AES256 encryption is supported.")
        self._client = client
        self._quarantine_bucket = quarantine_bucket
        self._originals_bucket = originals_bucket
        self._read_chunk_bytes = read_chunk_bytes
        self._expected_bucket_owner = expected_bucket_owner
        self._server_side_encryption = server_side_encryption

    def read_chunks(self, object_key: str) -> Iterable[bytes]:
        self._require_source_key(object_key)
        parameters = {
            "Bucket": self._quarantine_bucket,
            "Key": object_key,
            "ChecksumMode": "ENABLED",
        }
        if self._expected_bucket_owner is not None:
            parameters["ExpectedBucketOwner"] = self._expected_bucket_owner

        def stream() -> Iterator[bytes]:
            try:
                response = self._client.get_object(**parameters)
            except (BotoCoreError, ClientError) as exc:
                raise DatasetScanStorageError("object_read_unavailable", retryable=True) from exc
            body_value = response.get("Body")
            if (
                body_value is None
                or not callable(getattr(body_value, "read", None))
                or not callable(getattr(body_value, "close", None))
            ):
                raise DatasetScanStorageError("invalid_object_stream", retryable=True)
            body = cast(StreamingBody, body_value)
            try:
                while chunk := body.read(self._read_chunk_bytes):
                    if not isinstance(chunk, bytes):
                        raise DatasetScanStorageError("invalid_object_stream", retryable=True)
                    yield chunk
            except (BotoCoreError, ClientError, OSError) as exc:
                raise DatasetScanStorageError("object_read_unavailable", retryable=True) from exc
            finally:
                body.close()

        return stream()

    def promote_clean(
        self,
        *,
        source_key: str,
        destination_key: str,
        checksum_sha256: str,
    ) -> None:
        self._require_promotion_reference(source_key, destination_key, checksum_sha256)
        existing_checksum = self._destination_checksum(destination_key)
        if existing_checksum is not None:
            if hmac.compare_digest(existing_checksum, checksum_sha256):
                return
            raise DatasetScanStorageError("immutable_destination_conflict", retryable=False)

        parameters: dict[str, object] = {
            "Bucket": self._originals_bucket,
            "Key": destination_key,
            "CopySource": {"Bucket": self._quarantine_bucket, "Key": source_key},
            "ChecksumAlgorithm": "SHA256",
            "MetadataDirective": "COPY",
            "ServerSideEncryption": self._server_side_encryption,
            "IfNoneMatch": "*",
        }
        if self._expected_bucket_owner is not None:
            parameters["ExpectedBucketOwner"] = self._expected_bucket_owner
            parameters["ExpectedSourceBucketOwner"] = self._expected_bucket_owner
        try:
            self._client.copy_object(**parameters)
        except (BotoCoreError, ClientError) as exc:
            raise DatasetScanStorageError("object_promotion_unavailable", retryable=True) from exc

        promoted_checksum = self._destination_checksum(destination_key)
        if promoted_checksum is None:
            raise DatasetScanStorageError("promoted_object_missing", retryable=True)
        if not hmac.compare_digest(promoted_checksum, checksum_sha256):
            raise DatasetScanStorageError("promoted_checksum_mismatch", retryable=False)

    def _destination_checksum(self, destination_key: str) -> str | None:
        parameters = {
            "Bucket": self._originals_bucket,
            "Key": destination_key,
            "ChecksumMode": "ENABLED",
        }
        if self._expected_bucket_owner is not None:
            parameters["ExpectedBucketOwner"] = self._expected_bucket_owner
        try:
            response = self._client.head_object(**parameters)
        except ClientError as exc:
            if S3QuarantineObjectStore._is_missing(exc):
                return None
            raise DatasetScanStorageError("promotion_metadata_unavailable", retryable=True) from exc
        except BotoCoreError as exc:
            raise DatasetScanStorageError("promotion_metadata_unavailable", retryable=True) from exc
        checksum = response.get("ChecksumSHA256")
        if not isinstance(checksum, str):
            raise DatasetScanStorageError("invalid_promotion_metadata", retryable=True)
        try:
            checksum_bytes = base64.b64decode(checksum, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise DatasetScanStorageError("invalid_promotion_metadata", retryable=True) from exc
        if len(checksum_bytes) != 32:
            raise DatasetScanStorageError("invalid_promotion_metadata", retryable=True)
        return checksum_bytes.hex()

    @staticmethod
    def _require_source_key(source_key: str) -> None:
        if _QUARANTINE_KEY_PATTERN.fullmatch(source_key) is None:
            raise DatasetScanStorageError("invalid_scan_storage_reference", retryable=False)

    @staticmethod
    def _require_promotion_reference(source_key: str, destination_key: str, checksum: str) -> None:
        expected_destination = f"originals/{source_key.removeprefix('quarantine/')}"
        if (
            _QUARANTINE_KEY_PATTERN.fullmatch(source_key) is None
            or _ORIGINAL_KEY_PATTERN.fullmatch(destination_key) is None
            or destination_key != expected_destination
            or re.fullmatch(r"[0-9a-f]{64}", checksum) is None
        ):
            raise DatasetScanStorageError("invalid_scan_storage_reference", retryable=False)


class S3QuarantineObjectStore:
    """Issue constrained browser POSTs and inspect trusted S3 object metadata."""

    def __init__(
        self,
        client: S3Client,
        *,
        bucket: str,
        clock: Callable[[], datetime],
        expected_bucket_owner: str | None = None,
        server_side_encryption: str | None = "AES256",
    ) -> None:
        if not bucket or bucket.isspace():
            raise ValueError("Quarantine bucket must be non-empty.")
        if expected_bucket_owner is not None and (
            len(expected_bucket_owner) != 12 or not expected_bucket_owner.isdigit()
        ):
            raise ValueError("Expected bucket owner must be a 12-digit AWS account ID.")
        if server_side_encryption not in {None, "AES256"}:
            raise ValueError("Only S3-managed AES256 encryption is supported.")
        self._client = client
        self._bucket = bucket
        self._clock = clock
        self._expected_bucket_owner = expected_bucket_owner
        self._server_side_encryption = server_side_encryption

    def create_upload(self, request: QuarantineUploadRequest) -> PresignedUpload:
        self._require_quarantine_key(request.object_key)
        expires_in = self._expiry_seconds(request.expires_at)
        checksum_base64 = self._checksum_to_base64(request.checksum_sha256)
        fields = {
            "Content-Type": request.content_type,
            "success_action_status": "201",
            "x-amz-checksum-algorithm": "SHA256",
            "x-amz-checksum-sha256": checksum_base64,
        }
        conditions: list[dict[str, str] | list[str | int]] = [
            {"Content-Type": request.content_type},
            {"success_action_status": "201"},
            {"x-amz-checksum-algorithm": "SHA256"},
            {"x-amz-checksum-sha256": checksum_base64},
            ["content-length-range", request.content_length, request.content_length],
        ]
        if self._server_side_encryption is not None:
            fields["x-amz-server-side-encryption"] = self._server_side_encryption
            conditions.insert(4, {"x-amz-server-side-encryption": self._server_side_encryption})
        try:
            response = self._client.generate_presigned_post(
                Bucket=self._bucket,
                Key=request.object_key,
                Fields=fields,
                Conditions=conditions,
                ExpiresIn=expires_in,
            )
        except (BotoCoreError, ClientError) as exc:
            raise QuarantineObjectStoreError("upload_signing_unavailable") from exc
        url = response.get("url")
        response_fields = response.get("fields")
        if not isinstance(url, str) or not isinstance(response_fields, Mapping):
            raise QuarantineObjectStoreError("invalid_upload_policy")
        if not all(isinstance(key, str) and isinstance(value, str) for key, value in response_fields.items()):
            raise QuarantineObjectStoreError("invalid_upload_policy")
        return PresignedUpload(
            url=url,
            fields=MappingProxyType(dict(response_fields)),
            expires_at=request.expires_at,
        )

    def inspect(self, object_key: str) -> StoredObjectMetadata | None:
        self._require_quarantine_key(object_key)
        parameters = {
            "Bucket": self._bucket,
            "Key": object_key,
            "ChecksumMode": "ENABLED",
        }
        if self._expected_bucket_owner is not None:
            parameters["ExpectedBucketOwner"] = self._expected_bucket_owner
        try:
            response = self._client.head_object(**parameters)
        except ClientError as exc:
            if self._is_missing(exc):
                return None
            raise QuarantineObjectStoreError("object_metadata_unavailable") from exc
        except BotoCoreError as exc:
            raise QuarantineObjectStoreError("object_metadata_unavailable") from exc

        content_length = response.get("ContentLength")
        content_type = response.get("ContentType")
        checksum = response.get("ChecksumSHA256")
        if type(content_length) is not int or not isinstance(content_type, str) or not isinstance(checksum, str):
            raise QuarantineObjectStoreError("invalid_object_metadata")
        try:
            checksum_bytes = base64.b64decode(checksum, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise QuarantineObjectStoreError("invalid_object_metadata") from exc
        if len(checksum_bytes) != 32:
            raise QuarantineObjectStoreError("invalid_object_metadata")
        return StoredObjectMetadata(
            object_key=object_key,
            content_type=content_type,
            content_length=content_length,
            checksum_sha256=checksum_bytes.hex(),
        )

    def _expiry_seconds(self, expires_at: datetime) -> int:
        try:
            seconds = math.ceil((expires_at - self._clock()).total_seconds())
        except TypeError as exc:
            raise QuarantineObjectStoreError("invalid_upload_expiry") from exc
        if not 1 <= seconds <= 15 * 60:
            raise QuarantineObjectStoreError("invalid_upload_expiry")
        return seconds

    @staticmethod
    def _checksum_to_base64(checksum: str) -> str:
        try:
            checksum_bytes = bytes.fromhex(checksum)
        except ValueError as exc:
            raise QuarantineObjectStoreError("invalid_upload_checksum") from exc
        if len(checksum_bytes) != 32 or checksum != checksum.casefold():
            raise QuarantineObjectStoreError("invalid_upload_checksum")
        return base64.b64encode(checksum_bytes).decode("ascii")

    @staticmethod
    def _require_quarantine_key(object_key: str) -> None:
        if _QUARANTINE_KEY_PATTERN.fullmatch(object_key) is None:
            raise QuarantineObjectStoreError("invalid_object_key")

    @staticmethod
    def _is_missing(error: ClientError) -> bool:
        response = error.response
        metadata = response.get("ResponseMetadata", {})
        detail = response.get("Error", {})
        status = metadata.get("HTTPStatusCode") if isinstance(metadata, Mapping) else None
        code = detail.get("Code") if isinstance(detail, Mapping) else None
        return status == 404 or code in {"404", "NoSuchKey", "NotFound"}
