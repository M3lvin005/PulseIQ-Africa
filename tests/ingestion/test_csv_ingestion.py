"""Contract tests for the bounded CSV ingestion boundary."""

from __future__ import annotations

import hashlib

import pytest

from pulseiq.ingestion import (
    UploadErrorCode,
    UploadPolicy,
    UploadRejected,
    ingest_csv,
)
from pulseiq.privacy import DEMO_PRIVACY_POLICY


def test_ingest_csv_returns_normalized_data_and_reproducible_metadata() -> None:
    payload = b"\xef\xbb\xbfCustomer ID;Transaction Amount\r\nC-1;1200\r\nC-2;3400\r\n"

    result = ingest_csv(payload, filename="portfolio.CSV")

    assert list(result.dataframe.columns) == ["customer_id", "transaction_amount"]
    assert result.dataframe.to_dict("records") == [
        {"customer_id": "C-1", "transaction_amount": 1200},
        {"customer_id": "C-2", "transaction_amount": 3400},
    ]
    assert result.metadata.filename == "portfolio.CSV"
    assert result.metadata.size_bytes == len(payload)
    assert result.metadata.sha256 == hashlib.sha256(payload).hexdigest()
    assert result.metadata.encoding == "utf-8-sig"
    assert result.metadata.delimiter == ";"
    assert result.metadata.rows == 2
    assert result.metadata.columns == 2
    assert [(item.source, item.normalized) for item in result.header_mappings] == [
        ("Customer ID", "customer_id"),
        ("Transaction Amount", "transaction_amount"),
    ]


@pytest.mark.parametrize(
    ("payload", "filename", "policy", "expected_code"),
    [
        (b"", "data.csv", UploadPolicy(), UploadErrorCode.EMPTY_FILE),
        (b"a,b\n1,2\n", "data.txt", UploadPolicy(), UploadErrorCode.UNSUPPORTED_EXTENSION),
        (b"a,b\n1,2\n", "data.csv", UploadPolicy(max_bytes=4), UploadErrorCode.FILE_TOO_LARGE),
        (b"a,b\x00\n1,2\n", "data.csv", UploadPolicy(), UploadErrorCode.BINARY_CONTENT),
        (b"a,b\n\xff,2\n", "data.csv", UploadPolicy(), UploadErrorCode.INVALID_ENCODING),
        (b"a^b\n1^2\n", "data.csv", UploadPolicy(), UploadErrorCode.UNSUPPORTED_DELIMITER),
        (b"a,b\n1,2\n3,4\n", "data.csv", UploadPolicy(max_rows=1), UploadErrorCode.TOO_MANY_ROWS),
        (b"a,b,c\n1,2,3\n", "data.csv", UploadPolicy(max_columns=2), UploadErrorCode.TOO_MANY_COLUMNS),
        (
            b"Loan Amount,loan_amount\n100,200\n",
            "data.csv",
            UploadPolicy(),
            UploadErrorCode.HEADER_COLLISION,
        ),
    ],
)
def test_ingest_csv_rejects_unsafe_or_out_of_policy_input(
    payload: bytes,
    filename: str,
    policy: UploadPolicy,
    expected_code: UploadErrorCode,
) -> None:
    with pytest.raises(UploadRejected) as error:
        ingest_csv(payload, filename=filename, policy=policy)

    assert error.value.code is expected_code
    assert error.value.user_message
    assert error.value.recovery
    assert "Traceback" not in str(error.value)


def test_ingest_csv_rejects_an_empty_header() -> None:
    with pytest.raises(UploadRejected) as error:
        ingest_csv(b",amount\nC-1,100\n", filename="data.csv")

    assert error.value.code is UploadErrorCode.EMPTY_HEADER


def test_ingest_csv_wraps_parser_details_in_a_safe_error() -> None:
    with pytest.raises(UploadRejected) as error:
        ingest_csv(b'a,b\n"unclosed,2\n', filename="data.csv")

    assert error.value.code is UploadErrorCode.PARSE_FAILED
    assert "unclosed" not in error.value.user_message.lower()
    assert "token" not in error.value.user_message.lower()


@pytest.mark.parametrize(
    "payload",
    [
        b"customer_id,email_address\nCUST-1,person@example.com\n",
        b"customer_id,notes\nCUST-1,person@example.com\n",
    ],
)
def test_demo_privacy_policy_rejects_personal_data_without_echoing_it(payload: bytes) -> None:
    with pytest.raises(UploadRejected) as error:
        ingest_csv(payload, filename="data.csv", privacy_policy=DEMO_PRIVACY_POLICY)

    assert error.value.code is UploadErrorCode.RESTRICTED_DATA
    assert "person@example.com" not in error.value.user_message
    assert "de-identify" in error.value.recovery
