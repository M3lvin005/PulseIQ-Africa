"""Post-scan normalization stage for governed dataset ingestion."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Protocol

from pulseiq.ingestion import (
    NORMALIZATION_VERSION,
    ParquetNormalizationError,
    UploadRejected,
    normalize_csv_to_parquet,
)
from pulseiq.jobs import ImportJobClaim, JobExecutionError
from pulseiq.jobs.ports import ImportJobHandler

from .scanning import validate_dataset_scan_reference


class DatasetNormalizationStorage(Protocol):
    """Narrow clean-original read and normalized-artifact write boundary."""

    def read_chunks(self, object_key: str) -> Iterable[bytes]: ...

    def store_normalized(
        self,
        *,
        object_key: str,
        payload: bytes,
        checksum_sha256: str,
        metadata: Mapping[str, str],
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class NormalizedArtifactField:
    """One trusted physical field in a normalized artifact schema."""

    position: int
    source_column: str
    normalized_column: str
    physical_type: str
    nullable: bool

    def __post_init__(self) -> None:
        if not 1 <= self.position <= 200:
            raise ValueError("Normalized artifact field position is invalid.")
        if not self.source_column.strip() or not self.normalized_column.strip():
            raise ValueError("Normalized artifact field names must be non-empty.")
        if self.physical_type != "string":
            raise ValueError("Only lexical string artifact fields are currently supported.")


@dataclass(frozen=True, slots=True)
class NormalizedDatasetArtifact:
    """Durable lineage for one verified normalized dataset object."""

    dataset_version_id: str
    organization_id: str
    workspace_id: str
    object_key: str
    source_sha256: str
    artifact_sha256: str
    schema_fingerprint: str
    row_count: int
    column_count: int
    normalization_version: str
    fields: tuple[NormalizedArtifactField, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        identifiers = (
            self.dataset_version_id,
            self.organization_id,
            self.workspace_id,
            self.object_key,
            self.normalization_version,
        )
        if any(not value or value.isspace() for value in identifiers):
            raise ValueError("Normalized artifact identifiers must be non-empty.")
        if any(
            len(checksum) != 64 or any(character not in "0123456789abcdef" for character in checksum)
            for checksum in (self.source_sha256, self.artifact_sha256, self.schema_fingerprint)
        ):
            raise ValueError("Normalized artifact digests must be SHA-256 hex values.")
        if self.row_count < 1 or self.column_count < 1:
            raise ValueError("Normalized artifact dimensions must be positive.")
        if len(self.fields) != self.column_count:
            raise ValueError("Normalized artifact field count must match its column count.")
        if tuple(field.position for field in self.fields) != tuple(range(1, self.column_count + 1)):
            raise ValueError("Normalized artifact field positions must be contiguous.")
        if (
            len({field.source_column for field in self.fields}) != self.column_count
            or len({field.normalized_column for field in self.fields}) != self.column_count
        ):
            raise ValueError("Normalized artifact field names must be unique.")
        if self.created_at.tzinfo is None:
            raise ValueError("Normalized artifact creation time must be timezone-aware.")


class NormalizedArtifactRepository(Protocol):
    def record_artifact(self, artifact: NormalizedDatasetArtifact) -> None: ...


class DatasetNormalizationStorageError(RuntimeError):
    """Safe classified normalized-object storage failure."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__("Dataset normalization storage is unavailable.")
        self.code = code
        self.retryable = retryable


class DatasetNormalizationHandler:
    """Re-verify the promoted original and persist lexical Parquet."""

    def __init__(
        self,
        storage: DatasetNormalizationStorage,
        artifacts: NormalizedArtifactRepository,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._storage = storage
        self._artifacts = artifacts
        self._clock = clock

    def execute(self, claim: ImportJobClaim) -> None:
        reference = validate_dataset_scan_reference(claim)
        expected_bytes = int(reference["expected_bytes"])
        expected_checksum = reference["expected_sha256"]
        original_key = f"originals/{reference['object_key'].removeprefix('quarantine/')}"
        normalized_key = (
            original_key.replace("originals/", "normalized/", 1).removesuffix("original.csv") + "data.parquet"
        )
        payload = bytearray()
        digest = hashlib.sha256()
        try:
            for chunk in self._storage.read_chunks(original_key):
                if not isinstance(chunk, bytes) or not chunk:
                    raise JobExecutionError("invalid_object_chunk", retryable=False)
                if len(payload) + len(chunk) > expected_bytes:
                    raise JobExecutionError("object_size_mismatch", retryable=False)
                payload.extend(chunk)
                digest.update(chunk)
        except DatasetNormalizationStorageError as exc:
            raise JobExecutionError(exc.code, retryable=exc.retryable) from exc
        if len(payload) != expected_bytes:
            raise JobExecutionError("object_size_mismatch", retryable=False)
        if not hmac.compare_digest(digest.hexdigest(), expected_checksum):
            raise JobExecutionError("object_checksum_mismatch", retryable=False)

        try:
            artifact = normalize_csv_to_parquet(bytes(payload))
        except UploadRejected as exc:
            raise JobExecutionError(exc.code.value, retryable=False) from exc
        except ParquetNormalizationError as exc:
            raise JobExecutionError(exc.code, retryable=False) from exc
        metadata = MappingProxyType(
            {
                "columns": str(artifact.columns),
                "normalization-version": NORMALIZATION_VERSION,
                "rows": str(artifact.rows),
                "source-sha256": artifact.source_sha256,
            }
        )
        try:
            self._storage.store_normalized(
                object_key=normalized_key,
                payload=artifact.payload,
                checksum_sha256=artifact.parquet_sha256,
                metadata=metadata,
            )
        except DatasetNormalizationStorageError as exc:
            raise JobExecutionError(exc.code, retryable=exc.retryable) from exc
        self._artifacts.record_artifact(
            NormalizedDatasetArtifact(
                dataset_version_id=claim.dataset_version_id,
                organization_id=claim.organization_id,
                workspace_id=claim.workspace_id,
                object_key=normalized_key,
                source_sha256=artifact.source_sha256,
                artifact_sha256=artifact.parquet_sha256,
                schema_fingerprint=artifact.schema_fingerprint,
                row_count=artifact.rows,
                column_count=artifact.columns,
                normalization_version=NORMALIZATION_VERSION,
                fields=tuple(
                    NormalizedArtifactField(
                        position=position,
                        source_column=mapping.source,
                        normalized_column=mapping.normalized,
                        physical_type="string",
                        nullable=False,
                    )
                    for position, mapping in enumerate(artifact.header_mappings, start=1)
                ),
                created_at=self._clock(),
            )
        )


class DatasetScanPipelineHandler:
    """Run scan/promotion and normalization under one durable job lease."""

    def __init__(self, scanner: ImportJobHandler, normalizer: ImportJobHandler) -> None:
        self._scanner = scanner
        self._normalizer = normalizer

    def execute(self, claim: ImportJobClaim) -> None:
        self._scanner.execute(claim)
        self._normalizer.execute(claim)
