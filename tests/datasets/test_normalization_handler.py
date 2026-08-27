from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from types import MappingProxyType

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pulseiq.datasets.normalization import (
    DatasetNormalizationHandler,
    DatasetNormalizationStorageError,
    DatasetScanPipelineHandler,
    NormalizedArtifactField,
    NormalizedDatasetArtifact,
)
from pulseiq.jobs import ImportJobClaim, JobExecutionError

PAYLOAD = b"Customer ID,Amount\n00123,0100\n"
CHECKSUM = hashlib.sha256(PAYLOAD).hexdigest()
VERSION_ID = "33333333-cccc-4ccc-8ccc-333333333333"
QUARANTINE_KEY = f"quarantine/org-1/workspace-1/dataset-1/{VERSION_ID}/original.csv"
ORIGINAL_KEY = f"originals/org-1/workspace-1/dataset-1/{VERSION_ID}/original.csv"
NORMALIZED_KEY = f"normalized/org-1/workspace-1/dataset-1/{VERSION_ID}/data.parquet"


def _claim() -> ImportJobClaim:
    return ImportJobClaim(
        job_id="33333333-eeee-4eee-8eee-333333333333",
        organization_id="org-1",
        workspace_id="workspace-1",
        dataset_version_id=VERSION_ID,
        job_type="dataset.scan",
        input_reference=MappingProxyType(
            {
                "dataset_version_id": VERSION_ID,
                "expected_bytes": str(len(PAYLOAD)),
                "expected_sha256": CHECKSUM,
                "object_key": QUARANTINE_KEY,
            }
        ),
        attempts=1,
        execution_token="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        leased_until=datetime.now(UTC),
    )


class FakeNormalizationStorage:
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self.chunks = chunks
        self.writes: list[tuple[str, bytes, str, Mapping[str, str]]] = []

    def read_chunks(self, object_key: str) -> Iterable[bytes]:
        assert object_key == ORIGINAL_KEY
        return iter(self.chunks)

    def store_normalized(
        self,
        *,
        object_key: str,
        payload: bytes,
        checksum_sha256: str,
        metadata: Mapping[str, str],
    ) -> None:
        self.writes.append((object_key, payload, checksum_sha256, metadata))


class FakeArtifactRepository:
    def __init__(self) -> None:
        self.artifacts: list[NormalizedDatasetArtifact] = []

    def record_artifact(self, artifact: NormalizedDatasetArtifact) -> None:
        self.artifacts.append(artifact)


def _handler(
    storage: FakeNormalizationStorage,
    repository: FakeArtifactRepository | None = None,
) -> DatasetNormalizationHandler:
    return DatasetNormalizationHandler(storage, repository or FakeArtifactRepository(), clock=lambda: datetime.now(UTC))


def test_normalization_handler_reverifies_original_and_writes_lexical_parquet() -> None:
    storage = FakeNormalizationStorage((PAYLOAD[:7], PAYLOAD[7:]))
    repository = FakeArtifactRepository()

    _handler(storage, repository).execute(_claim())

    assert len(storage.writes) == 1
    object_key, parquet_bytes, checksum, metadata = storage.writes[0]
    assert object_key == NORMALIZED_KEY
    assert checksum == hashlib.sha256(parquet_bytes).hexdigest()
    assert metadata == {
        "columns": "2",
        "normalization-version": "1",
        "rows": "1",
        "source-sha256": CHECKSUM,
    }
    table = pq.read_table(pa.BufferReader(parquet_bytes), page_checksum_verification=True)
    assert table.to_pylist() == [{"customer_id": "00123", "amount": "0100"}]
    assert len(repository.artifacts) == 1
    artifact = repository.artifacts[0]
    assert artifact.dataset_version_id == VERSION_ID
    assert artifact.object_key == NORMALIZED_KEY
    assert artifact.artifact_sha256 == checksum
    assert artifact.source_sha256 == CHECKSUM
    assert artifact.row_count == 1
    assert artifact.column_count == 2
    assert artifact.schema_fingerprint
    assert artifact.fields == (
        NormalizedArtifactField(1, "Customer ID", "customer_id", "string", False),
        NormalizedArtifactField(2, "Amount", "amount", "string", False),
    )


def test_normalization_handler_rejects_changed_clean_original_before_write() -> None:
    storage = FakeNormalizationStorage((PAYLOAD + b"x",))

    with pytest.raises(JobExecutionError) as error:
        _handler(storage).execute(_claim())

    assert error.value.code == "object_size_mismatch"
    assert storage.writes == []


@pytest.mark.parametrize(
    ("chunks", "expected_code"),
    [
        ((PAYLOAD[:-1],), "object_size_mismatch"),
        ((PAYLOAD[:5], b""), "invalid_object_chunk"),
        ((b"Customer ID,Amount\n00123,0101\n",), "object_checksum_mismatch"),
        ((b"Customer ID,customer_id\n00123,0100\n",), "header_collision"),
    ],
)
def test_normalization_handler_rejects_truncated_invalid_or_unparseable_original(
    chunks: tuple[bytes, ...], expected_code: str
) -> None:
    storage = FakeNormalizationStorage(chunks)
    claim = _claim()
    if expected_code == "header_collision":
        payload = chunks[0]
        claim = ImportJobClaim(
            job_id=claim.job_id,
            organization_id=claim.organization_id,
            workspace_id=claim.workspace_id,
            dataset_version_id=claim.dataset_version_id,
            job_type=claim.job_type,
            input_reference=MappingProxyType(
                {
                    **claim.input_reference,
                    "expected_bytes": str(len(payload)),
                    "expected_sha256": hashlib.sha256(payload).hexdigest(),
                }
            ),
            attempts=claim.attempts,
            execution_token=claim.execution_token,
            leased_until=claim.leased_until,
        )
    with pytest.raises(JobExecutionError) as error:
        _handler(storage).execute(claim)
    assert error.value.code == expected_code
    assert storage.writes == []


def test_normalization_handler_maps_read_and_write_storage_failures() -> None:
    class BrokenReadStorage(FakeNormalizationStorage):
        def read_chunks(self, object_key: str) -> Iterable[bytes]:
            raise DatasetNormalizationStorageError("original_read_unavailable", retryable=True)

    with pytest.raises(JobExecutionError) as read_error:
        _handler(BrokenReadStorage((PAYLOAD,))).execute(_claim())
    assert read_error.value.code == "original_read_unavailable"
    assert read_error.value.retryable is True

    class BrokenWriteStorage(FakeNormalizationStorage):
        def store_normalized(
            self,
            *,
            object_key: str,
            payload: bytes,
            checksum_sha256: str,
            metadata: Mapping[str, str],
        ) -> None:
            raise DatasetNormalizationStorageError("normalized_write_unavailable", retryable=True)

    with pytest.raises(JobExecutionError) as write_error:
        _handler(BrokenWriteStorage((PAYLOAD,))).execute(_claim())
    assert write_error.value.code == "normalized_write_unavailable"
    assert write_error.value.retryable is True


class RecordingHandler:
    def __init__(self, name: str, calls: list[str], error: JobExecutionError | None = None) -> None:
        self.name = name
        self.calls = calls
        self.error = error

    def execute(self, claim: ImportJobClaim) -> None:
        self.calls.append(self.name)
        if self.error is not None:
            raise self.error


def test_scan_pipeline_only_normalizes_after_successful_promotion() -> None:
    calls: list[str] = []
    pipeline = DatasetScanPipelineHandler(RecordingHandler("scan", calls), RecordingHandler("normalize", calls))

    pipeline.execute(_claim())

    assert calls == ["scan", "normalize"]


def test_scan_pipeline_stops_before_normalization_when_scan_fails() -> None:
    calls: list[str] = []
    pipeline = DatasetScanPipelineHandler(
        RecordingHandler("scan", calls, JobExecutionError("malware_detected", retryable=False)),
        RecordingHandler("normalize", calls),
    )

    with pytest.raises(JobExecutionError):
        pipeline.execute(_claim())

    assert calls == ["scan"]
