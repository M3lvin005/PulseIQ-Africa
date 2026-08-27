from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import UTC, datetime
from types import MappingProxyType

import pytest

from pulseiq.datasets import (
    DatasetScanStorageError,
    MalwareScanError,
    MalwareScanResult,
    MalwareScanStatus,
)
from pulseiq.datasets.scanning import DatasetScanHandler
from pulseiq.jobs import ImportJobClaim, JobExecutionError

PAYLOAD = b"id,name\n1,Ada\n"
CHECKSUM = hashlib.sha256(PAYLOAD).hexdigest()
DATASET_VERSION_ID = "33333333-cccc-4ccc-8ccc-333333333333"
OBJECT_KEY = f"quarantine/org-1/workspace-1/dataset-1/{DATASET_VERSION_ID}/original.csv"


def _claim(*, overrides: dict[str, object] | None = None) -> ImportJobClaim:
    reference: dict[str, object] = {
        "dataset_version_id": DATASET_VERSION_ID,
        "expected_bytes": str(len(PAYLOAD)),
        "expected_sha256": CHECKSUM,
        "object_key": OBJECT_KEY,
    }
    if overrides:
        reference.update(overrides)
    return ImportJobClaim(
        job_id="33333333-eeee-4eee-8eee-333333333333",
        organization_id="org-1",
        workspace_id="workspace-1",
        dataset_version_id=DATASET_VERSION_ID,
        job_type="dataset.scan",
        input_reference=MappingProxyType(reference),
        attempts=1,
        execution_token="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        leased_until=datetime.now(UTC),
    )


class FakeScanStorage:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self.chunks = chunks
        self.promotions: list[tuple[str, str, str]] = []

    def read_chunks(self, object_key: str) -> Iterable[bytes]:
        assert object_key == OBJECT_KEY
        return iter(self.chunks)

    def promote_clean(self, *, source_key: str, destination_key: str, checksum_sha256: str) -> None:
        self.promotions.append((source_key, destination_key, checksum_sha256))


class FakeScanner:
    def __init__(self, status: MalwareScanStatus) -> None:
        self.status = status
        self.received = bytearray()

    def scan(self, chunks: Iterable[bytes]) -> MalwareScanResult:
        for chunk in chunks:
            self.received.extend(chunk)
        return MalwareScanResult(status=self.status)


def test_clean_exact_csv_is_stream_verified_and_promoted_to_immutable_prefix() -> None:
    storage = FakeScanStorage((PAYLOAD[:5], PAYLOAD[5:]))
    scanner = FakeScanner(MalwareScanStatus.CLEAN)

    DatasetScanHandler(storage, scanner).execute(_claim())

    assert scanner.received == PAYLOAD
    assert storage.promotions == [
        (
            OBJECT_KEY,
            f"originals/org-1/workspace-1/dataset-1/{DATASET_VERSION_ID}/original.csv",
            CHECKSUM,
        )
    ]


def test_malware_verdict_is_permanent_and_never_promoted() -> None:
    storage = FakeScanStorage((PAYLOAD,))

    with pytest.raises(JobExecutionError) as error:
        DatasetScanHandler(storage, FakeScanner(MalwareScanStatus.MALWARE_DETECTED)).execute(_claim())

    assert error.value.code == "malware_detected"
    assert error.value.retryable is False
    assert storage.promotions == []


@pytest.mark.parametrize(
    ("chunks", "overrides", "expected_code"),
    [
        ((PAYLOAD + b"x",), None, "object_size_mismatch"),
        ((PAYLOAD,), {"expected_sha256": "0" * 64}, "object_checksum_mismatch"),
        ((b"id,name\n1,\xff\n",), {"expected_bytes": "12"}, "invalid_csv_encoding"),
        ((b"id,name\n1,\x00\n",), {"expected_bytes": "12"}, "binary_content"),
    ],
)
def test_scan_rejects_changed_size_checksum_or_non_csv_content(
    chunks: tuple[bytes, ...],
    overrides: dict[str, object] | None,
    expected_code: str,
) -> None:
    storage = FakeScanStorage(chunks)

    with pytest.raises(JobExecutionError) as error:
        DatasetScanHandler(storage, FakeScanner(MalwareScanStatus.CLEAN)).execute(_claim(overrides=overrides))

    assert error.value.code == expected_code
    assert error.value.retryable is False
    assert storage.promotions == []


def test_scan_rejects_tampered_job_reference_before_reading_storage() -> None:
    storage = FakeScanStorage((PAYLOAD,))

    with pytest.raises(JobExecutionError) as error:
        DatasetScanHandler(storage, FakeScanner(MalwareScanStatus.CLEAN)).execute(
            _claim(overrides={"object_key": "public/caller.csv"})
        )

    assert error.value.code == "invalid_scan_reference"
    assert storage.promotions == []


def test_scan_rejects_truncated_or_incomplete_utf8_object() -> None:
    for payload, code in ((PAYLOAD[:-1], "object_size_mismatch"), (b"id\n\xe2", "invalid_csv_encoding")):
        storage = FakeScanStorage((payload,))
        overrides = None
        if code == "invalid_csv_encoding":
            overrides = {
                "expected_bytes": str(len(payload)),
                "expected_sha256": hashlib.sha256(payload).hexdigest(),
            }
        with pytest.raises(JobExecutionError) as error:
            DatasetScanHandler(storage, FakeScanner(MalwareScanStatus.CLEAN)).execute(_claim(overrides=overrides))
        assert error.value.code == code


def test_scan_maps_classified_scanner_and_promotion_failures() -> None:
    class BrokenScanner:
        def scan(self, chunks: Iterable[bytes]) -> MalwareScanResult:
            raise MalwareScanError("scanner_unavailable", retryable=True)

    with pytest.raises(JobExecutionError) as scanner_error:
        DatasetScanHandler(FakeScanStorage((PAYLOAD,)), BrokenScanner()).execute(_claim())
    assert scanner_error.value.code == "scanner_unavailable"
    assert scanner_error.value.retryable is True

    class BrokenPromotionStorage(FakeScanStorage):
        def promote_clean(self, *, source_key: str, destination_key: str, checksum_sha256: str) -> None:
            raise DatasetScanStorageError("object_promotion_unavailable", retryable=True)

    with pytest.raises(JobExecutionError) as storage_error:
        DatasetScanHandler(BrokenPromotionStorage((PAYLOAD,)), FakeScanner(MalwareScanStatus.CLEAN)).execute(_claim())
    assert storage_error.value.code == "object_promotion_unavailable"
    assert storage_error.value.retryable is True


def test_scan_rejects_unknown_scanner_verdict() -> None:
    class InvalidScanner:
        def scan(self, chunks: Iterable[bytes]) -> MalwareScanResult:
            list(chunks)
            return MalwareScanResult(status=MalwareScanStatus.CLEAN).__class__(status="unknown")  # type: ignore[arg-type]

    with pytest.raises(JobExecutionError) as error:
        DatasetScanHandler(FakeScanStorage((PAYLOAD,)), InvalidScanner()).execute(_claim())
    assert error.value.code == "invalid_scanner_verdict"
    assert error.value.retryable is True
