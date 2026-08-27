"""Bounded CSV parsing at the application trust boundary."""

from __future__ import annotations

import csv
import hashlib
from io import StringIO
from pathlib import PurePath
from typing import Never

import pandas as pd

from pulseiq.data import normalize_column_name

from .contracts import (
    DEFAULT_UPLOAD_POLICY,
    HeaderMapping,
    IngestedDataset,
    IngestionMetadata,
    UploadErrorCode,
    UploadPolicy,
    UploadRejected,
)


def _reject(code: UploadErrorCode, message: str, recovery: str) -> Never:
    raise UploadRejected(code, message, recovery)


def _safe_filename(filename: str) -> str:
    return PurePath(filename.replace("\\", "/")).name


def _decode(payload: bytes) -> tuple[str, str]:
    if b"\x00" in payload:
        _reject(
            UploadErrorCode.BINARY_CONTENT,
            "This file contains binary content and cannot be read as CSV.",
            "Export the source as a plain UTF-8 CSV and upload it again.",
        )
    try:
        if payload.startswith(b"\xef\xbb\xbf"):
            return payload.decode("utf-8-sig"), "utf-8-sig"
        return payload.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        _reject(
            UploadErrorCode.INVALID_ENCODING,
            "This file is not valid UTF-8 text.",
            "Re-export the file using UTF-8 encoding and upload it again.",
        )


def _detect_delimiter(text: str, policy: UploadPolicy) -> str:
    sample = text[:65_536]
    try:
        detected = csv.Sniffer().sniff(sample).delimiter
    except csv.Error:
        first_line = sample.splitlines()[0] if sample.splitlines() else ""
        detected = next((item for item in policy.allowed_delimiters if item in first_line), ",")
    if detected not in policy.allowed_delimiters:
        _reject(
            UploadErrorCode.UNSUPPORTED_DELIMITER,
            "The CSV delimiter is not supported.",
            "Export the file using comma, semicolon, tab, or pipe delimiters.",
        )
    return detected


def _read_headers(text: str, delimiter: str, policy: UploadPolicy) -> tuple[HeaderMapping, ...]:
    try:
        reader = csv.reader(StringIO(text), delimiter=delimiter, strict=True)
        headers = next(reader)
    except (csv.Error, StopIteration):
        _reject(
            UploadErrorCode.PARSE_FAILED,
            "The CSV structure could not be parsed safely.",
            "Check quoting and delimiters, then export a new CSV and try again.",
        )

    if len(headers) > policy.max_columns:
        _reject(
            UploadErrorCode.TOO_MANY_COLUMNS,
            f"This file exceeds the {policy.max_columns:,}-column limit.",
            "Remove unused columns or split the dataset before uploading.",
        )

    if any(not header.strip() for header in headers):
        _reject(
            UploadErrorCode.EMPTY_HEADER,
            "Every CSV column must have a non-empty header.",
            "Name each source column uniquely and upload the file again.",
        )

    mappings = tuple(HeaderMapping(header, normalize_column_name(header)) for header in headers)
    normalized = [mapping.normalized for mapping in mappings]
    collisions = {name for name in normalized if normalized.count(name) > 1}
    if collisions:
        _reject(
            UploadErrorCode.HEADER_COLLISION,
            "Two or more headers become identical after normalization.",
            "Rename the conflicting source columns so each has a distinct meaning.",
        )
    return mappings


def ingest_csv(
    payload: bytes,
    *,
    filename: str,
    policy: UploadPolicy = DEFAULT_UPLOAD_POLICY,
    preserve_lexical_values: bool = False,
) -> IngestedDataset:
    """Validate and parse one CSV without exposing parser internals to callers."""

    safe_filename = _safe_filename(filename)
    if not payload:
        _reject(
            UploadErrorCode.EMPTY_FILE,
            "This CSV is empty.",
            "Choose a CSV with one header row and at least one data row.",
        )
    if not safe_filename.lower().endswith(".csv"):
        _reject(
            UploadErrorCode.UNSUPPORTED_EXTENSION,
            "Only CSV files are supported.",
            "Export the source with a .csv extension and upload it again.",
        )
    if len(payload) > policy.max_bytes:
        _reject(
            UploadErrorCode.FILE_TOO_LARGE,
            f"This file exceeds the {policy.max_bytes / (1024 * 1024):g} MB prototype limit.",
            "Split the dataset into smaller files or reduce unused columns.",
        )

    text, encoding = _decode(payload)
    delimiter = _detect_delimiter(text, policy)
    mappings = _read_headers(text, delimiter, policy)

    try:
        if preserve_lexical_values:
            dataframe = pd.read_csv(
                StringIO(text),
                sep=delimiter,
                nrows=policy.max_rows + 1,
                on_bad_lines="error",
                dtype="string",
                keep_default_na=False,
                na_filter=False,
            )
        else:
            dataframe = pd.read_csv(
                StringIO(text),
                sep=delimiter,
                nrows=policy.max_rows + 1,
                on_bad_lines="error",
            )
    except (csv.Error, pd.errors.ParserError, UnicodeError, ValueError):
        _reject(
            UploadErrorCode.PARSE_FAILED,
            "The CSV structure could not be parsed safely.",
            "Check quoting, row widths, and delimiters, then export a new CSV and try again.",
        )

    if len(dataframe) > policy.max_rows:
        _reject(
            UploadErrorCode.TOO_MANY_ROWS,
            f"This file exceeds the {policy.max_rows:,}-row prototype limit.",
            "Split the dataset into smaller files before uploading.",
        )
    if dataframe.empty:
        _reject(
            UploadErrorCode.EMPTY_FILE,
            "This CSV has headers but no data rows.",
            "Choose a CSV with at least one data row.",
        )

    dataframe.columns = [mapping.normalized for mapping in mappings]
    metadata = IngestionMetadata(
        filename=safe_filename,
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        encoding=encoding,
        delimiter=delimiter,
        rows=len(dataframe),
        columns=len(dataframe.columns),
    )
    return IngestedDataset(dataframe=dataframe, metadata=metadata, header_mappings=mappings)
