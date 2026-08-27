"""Deterministic lexical CSV normalization into governed Parquet bytes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import pyarrow as pa
import pyarrow.parquet as pq

from .contracts import DEFAULT_UPLOAD_POLICY, HeaderMapping, UploadPolicy
from .csv import ingest_csv

NORMALIZATION_VERSION = "1"
DEFAULT_MAXIMUM_PARQUET_BYTES = 25 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class NormalizedParquet:
    """One bounded normalized artifact plus reproducibility evidence."""

    payload: bytes
    source_sha256: str
    parquet_sha256: str
    schema_fingerprint: str
    rows: int
    columns: int
    header_mappings: tuple[HeaderMapping, ...]


class ParquetNormalizationError(RuntimeError):
    """Safe classified normalization failure."""

    def __init__(self, code: str) -> None:
        super().__init__("The normalized dataset could not be created.")
        self.code = code


def normalize_csv_to_parquet(
    payload: bytes,
    *,
    policy: UploadPolicy = DEFAULT_UPLOAD_POLICY,
    maximum_parquet_bytes: int = DEFAULT_MAXIMUM_PARQUET_BYTES,
) -> NormalizedParquet:
    """Preserve lexical values and emit deterministic compressed Parquet."""

    if not 1 <= maximum_parquet_bytes <= 100 * 1024 * 1024:
        raise ValueError("Parquet output limit must be between 1 byte and 100 MiB.")
    ingested = ingest_csv(
        payload,
        filename="original.csv",
        policy=policy,
        preserve_lexical_values=True,
    )
    header_metadata = [
        {"normalized": mapping.normalized, "source": mapping.source} for mapping in ingested.header_mappings
    ]
    schema_payload = json.dumps(
        {
            "fields": [{**field, "physical_type": "string", "nullable": False} for field in header_metadata],
            "normalization_version": NORMALIZATION_VERSION,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    schema_fingerprint = hashlib.sha256(schema_payload).hexdigest()
    table = pa.Table.from_pandas(ingested.dataframe, preserve_index=False)
    metadata = dict(table.schema.metadata or {})
    metadata.update(
        {
            b"pulseiq.header_mappings": json.dumps(
                header_metadata,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8"),
            b"pulseiq.normalization_version": NORMALIZATION_VERSION.encode("ascii"),
            b"pulseiq.schema_fingerprint": schema_fingerprint.encode("ascii"),
            b"pulseiq.source_sha256": ingested.metadata.sha256.encode("ascii"),
        }
    )
    table = table.replace_schema_metadata(metadata)
    sink = pa.BufferOutputStream()
    pq.write_table(
        table,
        sink,
        compression="zstd",
        data_page_version="2.0",
        row_group_size=64 * 1024,
        use_dictionary=True,
        version="2.6",
        write_page_checksum=True,
        write_statistics=True,
    )
    normalized = sink.getvalue().to_pybytes()
    if len(normalized) > maximum_parquet_bytes:
        raise ParquetNormalizationError("normalized_output_too_large")
    return NormalizedParquet(
        payload=normalized,
        source_sha256=ingested.metadata.sha256,
        parquet_sha256=hashlib.sha256(normalized).hexdigest(),
        schema_fingerprint=schema_fingerprint,
        rows=ingested.metadata.rows,
        columns=ingested.metadata.columns,
        header_mappings=ingested.header_mappings,
    )
