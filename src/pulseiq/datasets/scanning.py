"""Stream-verified dataset malware scanning and clean-object promotion."""

from __future__ import annotations

import codecs
import hashlib
import hmac
import re
from collections.abc import Iterable, Iterator, Mapping
from typing import Protocol, cast

from pulseiq.jobs import ImportJobClaim, JobExecutionError

from .malware import MalwareScanError, MalwareScanResult, MalwareScanStatus

_MAXIMUM_UPLOAD_BYTES = 10 * 1024 * 1024
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_COMPONENT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_REFERENCE_KEYS = frozenset({"dataset_version_id", "expected_bytes", "expected_sha256", "object_key"})


class ScanObjectStorage(Protocol):
    """Narrow object-storage boundary required by the scan handler."""

    def read_chunks(self, object_key: str) -> Iterable[bytes]: ...

    def promote_clean(
        self,
        *,
        source_key: str,
        destination_key: str,
        checksum_sha256: str,
    ) -> None: ...


class DatasetScanStorageError(RuntimeError):
    """Safe classified object-storage failure during scanning or promotion."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__("Dataset scan storage is unavailable.")
        self.code = code
        self.retryable = retryable


class MalwareScanner(Protocol):
    """Narrow streaming malware-scanner boundary."""

    def scan(self, chunks: Iterable[bytes]) -> MalwareScanResult: ...


class DatasetScanHandler:
    """Re-verify an uploaded object while scanning, then promote a clean copy."""

    def __init__(self, storage: ScanObjectStorage, scanner: MalwareScanner) -> None:
        self._storage = storage
        self._scanner = scanner

    def execute(self, claim: ImportJobClaim) -> None:
        reference = validate_dataset_scan_reference(claim)
        expected_bytes = int(reference["expected_bytes"])
        expected_checksum = reference["expected_sha256"]
        object_key = reference["object_key"]

        digest = hashlib.sha256()
        decoder = codecs.getincrementaldecoder("utf-8-sig")(errors="strict")
        observed_bytes = 0

        def verified_chunks() -> Iterator[bytes]:
            nonlocal observed_bytes
            for chunk in self._storage.read_chunks(object_key):
                if not isinstance(chunk, bytes) or not chunk:
                    raise JobExecutionError("invalid_object_chunk", retryable=False)
                observed_bytes += len(chunk)
                if observed_bytes > expected_bytes:
                    raise JobExecutionError("object_size_mismatch", retryable=False)
                if b"\x00" in chunk:
                    raise JobExecutionError("binary_content", retryable=False)
                try:
                    decoder.decode(chunk, final=False)
                except UnicodeDecodeError as exc:
                    raise JobExecutionError("invalid_csv_encoding", retryable=False) from exc
                digest.update(chunk)
                yield chunk

        try:
            result = self._scanner.scan(verified_chunks())
        except DatasetScanStorageError as exc:
            raise JobExecutionError(exc.code, retryable=exc.retryable) from exc
        except MalwareScanError as exc:
            raise JobExecutionError(exc.code, retryable=exc.retryable) from exc

        if getattr(result, "status", None) is MalwareScanStatus.MALWARE_DETECTED:
            raise JobExecutionError("malware_detected", retryable=False)
        if getattr(result, "status", None) is not MalwareScanStatus.CLEAN:
            raise JobExecutionError("invalid_scanner_verdict", retryable=True)
        if observed_bytes != expected_bytes:
            raise JobExecutionError("object_size_mismatch", retryable=False)
        try:
            decoder.decode(b"", final=True)
        except UnicodeDecodeError as exc:
            raise JobExecutionError("invalid_csv_encoding", retryable=False) from exc
        if not hmac.compare_digest(digest.hexdigest(), expected_checksum):
            raise JobExecutionError("object_checksum_mismatch", retryable=False)

        try:
            self._storage.promote_clean(
                source_key=object_key,
                destination_key=self._destination_key(object_key),
                checksum_sha256=expected_checksum,
            )
        except DatasetScanStorageError as exc:
            raise JobExecutionError(exc.code, retryable=exc.retryable) from exc

    @staticmethod
    def _destination_key(source_key: str) -> str:
        return f"originals/{source_key.removeprefix('quarantine/')}"


def validate_dataset_scan_reference(claim: ImportJobClaim) -> Mapping[str, str]:
    """Validate and narrow the reference shared by scan pipeline stages."""

    reference = claim.input_reference
    if claim.job_type != "dataset.scan" or set(reference) != _REFERENCE_KEYS:
        raise JobExecutionError("invalid_scan_reference", retryable=False)
    if not all(isinstance(value, str) for value in reference.values()):
        raise JobExecutionError("invalid_scan_reference", retryable=False)

    typed_reference = cast(dict[str, str], dict(reference))
    expected_bytes = typed_reference["expected_bytes"]
    expected_checksum = typed_reference["expected_sha256"]
    object_key = typed_reference["object_key"]
    if (
        typed_reference["dataset_version_id"] != claim.dataset_version_id
        or not expected_bytes.isascii()
        or not expected_bytes.isdecimal()
        or expected_bytes.startswith("0")
        or not 1 <= int(expected_bytes) <= _MAXIMUM_UPLOAD_BYTES
        or _SHA256_PATTERN.fullmatch(expected_checksum) is None
        or not _matches_claimed_key(object_key, claim)
    ):
        raise JobExecutionError("invalid_scan_reference", retryable=False)
    return typed_reference


def _matches_claimed_key(object_key: str, claim: ImportJobClaim) -> bool:
    parts = object_key.split("/")
    return (
        len(parts) == 6
        and parts[0] == "quarantine"
        and parts[1] == claim.organization_id
        and parts[2] == claim.workspace_id
        and parts[4] == claim.dataset_version_id
        and parts[5] == "original.csv"
        and all(_COMPONENT_PATTERN.fullmatch(part) is not None for part in parts[1:5])
    )
