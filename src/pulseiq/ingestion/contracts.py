"""Immutable contracts for bounded, user-safe dataset ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import pandas as pd


class UploadErrorCode(StrEnum):
    """Stable codes suitable for UI recovery and privacy-safe telemetry."""

    EMPTY_FILE = "empty_file"
    UNSUPPORTED_EXTENSION = "unsupported_extension"
    FILE_TOO_LARGE = "file_too_large"
    BINARY_CONTENT = "binary_content"
    INVALID_ENCODING = "invalid_encoding"
    UNSUPPORTED_DELIMITER = "unsupported_delimiter"
    PARSE_FAILED = "parse_failed"
    TOO_MANY_ROWS = "too_many_rows"
    TOO_MANY_COLUMNS = "too_many_columns"
    EMPTY_HEADER = "empty_header"
    HEADER_COLLISION = "header_collision"
    RESTRICTED_DATA = "restricted_data"


@dataclass(frozen=True)
class UploadPolicy:
    """Resource and format limits for the in-process prototype parser."""

    max_bytes: int = 10 * 1024 * 1024
    max_rows: int = 100_000
    max_columns: int = 200
    allowed_delimiters: tuple[str, ...] = (",", ";", "\t", "|")

    def __post_init__(self) -> None:
        if self.max_bytes < 1 or self.max_rows < 1 or self.max_columns < 1:
            raise ValueError("Upload limits must be positive integers.")
        if not self.allowed_delimiters:
            raise ValueError("At least one delimiter must be allowed.")


DEFAULT_UPLOAD_POLICY = UploadPolicy()


@dataclass(frozen=True)
class HeaderMapping:
    """A traceable physical source header to normalized field mapping."""

    source: str
    normalized: str


@dataclass(frozen=True)
class IngestionMetadata:
    """Non-sensitive facts needed to identify and reproduce an ingestion."""

    filename: str
    size_bytes: int
    sha256: str
    encoding: str
    delimiter: str
    rows: int
    columns: int


@dataclass(frozen=True)
class IngestedDataset:
    """Validated tabular data plus immutable ingestion evidence."""

    dataframe: pd.DataFrame
    metadata: IngestionMetadata
    header_mappings: tuple[HeaderMapping, ...]


class UploadRejected(ValueError):
    """A safe upload failure with a stable code and recovery instruction."""

    def __init__(self, code: UploadErrorCode, user_message: str, recovery: str) -> None:
        self.code = code
        self.user_message = user_message
        self.recovery = recovery
        super().__init__(user_message)
