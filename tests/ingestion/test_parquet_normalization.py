from __future__ import annotations

import hashlib
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pulseiq.ingestion import ParquetNormalizationError, normalize_csv_to_parquet


def test_normalization_preserves_lexical_values_and_embeds_reproducibility_metadata() -> None:
    payload = b"Customer ID,Amount,Optional\n00123,0100,\n00456,3.50,N/A\n"

    artifact = normalize_csv_to_parquet(payload)

    table = pq.read_table(pa.BufferReader(artifact.payload), page_checksum_verification=True)
    assert table.column_names == ["customer_id", "amount", "optional"]
    assert table.to_pylist() == [
        {"customer_id": "00123", "amount": "0100", "optional": ""},
        {"customer_id": "00456", "amount": "3.50", "optional": "N/A"},
    ]
    assert artifact.source_sha256 == hashlib.sha256(payload).hexdigest()
    assert artifact.parquet_sha256 == hashlib.sha256(artifact.payload).hexdigest()
    assert artifact.rows == 2
    assert artifact.columns == 3
    metadata = table.schema.metadata
    assert metadata is not None
    assert metadata[b"pulseiq.normalization_version"] == b"1"
    assert metadata[b"pulseiq.schema_fingerprint"] == artifact.schema_fingerprint.encode()
    assert metadata[b"pulseiq.source_sha256"] == artifact.source_sha256.encode()
    assert json.loads(metadata[b"pulseiq.header_mappings"]) == [
        {"normalized": "customer_id", "source": "Customer ID"},
        {"normalized": "amount", "source": "Amount"},
        {"normalized": "optional", "source": "Optional"},
    ]


def test_normalization_is_reproducible_for_the_same_source_bytes() -> None:
    payload = b"id,value\n001,10\n"

    first = normalize_csv_to_parquet(payload)
    second = normalize_csv_to_parquet(payload)

    assert first.payload == second.payload
    assert first.parquet_sha256 == second.parquet_sha256
    assert first.schema_fingerprint == second.schema_fingerprint


def test_normalization_enforces_configured_output_limit() -> None:
    with pytest.raises(ParquetNormalizationError) as error:
        normalize_csv_to_parquet(b"id,value\n001,10\n", maximum_parquet_bytes=1)
    assert error.value.code == "normalized_output_too_large"
    assert str(error.value) == "The normalized dataset could not be created."


@pytest.mark.parametrize("limit", [0, 101 * 1024 * 1024])
def test_normalization_rejects_invalid_output_limit(limit: int) -> None:
    with pytest.raises(ValueError, match="Parquet output limit"):
        normalize_csv_to_parquet(b"id,value\n001,10\n", maximum_parquet_bytes=limit)
