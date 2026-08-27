from __future__ import annotations

import struct

import pytest

from pulseiq.datasets import ClamdInstreamScanner, MalwareScanError, MalwareScanStatus


class FakeSocket:
    def __init__(self, response: bytes = b"stream: OK\x00", error: OSError | None = None) -> None:
        self.response = response
        self.error = error
        self.sent = bytearray()
        self.timeout: float | None = None
        self.closed = False

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def sendall(self, data: bytes) -> None:
        if self.error is not None:
            raise self.error
        self.sent.extend(data)

    def recv(self, size: int) -> bytes:
        chunk, self.response = self.response[:size], self.response[size:]
        return chunk

    def close(self) -> None:
        self.closed = True


def test_clamd_instream_protocol_scans_bounded_chunks_and_returns_clean() -> None:
    connection = FakeSocket()
    scanner = ClamdInstreamScanner(lambda: connection, maximum_bytes=32, timeout_seconds=5)

    result = scanner.scan((b"id,name\n", b"1,Ada\n"))

    expected = bytearray(b"zINSTREAM\x00")
    expected.extend(struct.pack("!I", 8))
    expected.extend(b"id,name\n")
    expected.extend(struct.pack("!I", 6))
    expected.extend(b"1,Ada\n")
    expected.extend(struct.pack("!I", 0))
    assert connection.sent == expected
    assert connection.timeout == 5
    assert connection.closed is True
    assert result.status is MalwareScanStatus.CLEAN


def test_clamd_signature_is_reduced_to_safe_malware_status() -> None:
    connection = FakeSocket(b"stream: Example-Signature FOUND\x00")

    result = ClamdInstreamScanner(lambda: connection, maximum_bytes=32).scan((b"unsafe",))

    assert result.status is MalwareScanStatus.MALWARE_DETECTED
    assert "Example-Signature" not in repr(result)


def test_scanner_rejects_stream_larger_than_reserved_limit() -> None:
    connection = FakeSocket()

    with pytest.raises(MalwareScanError) as error:
        ClamdInstreamScanner(lambda: connection, maximum_bytes=5).scan((b"123", b"456"))

    assert error.value.code == "scan_size_exceeded"
    assert error.value.retryable is False
    assert connection.closed is True


@pytest.mark.parametrize(
    ("response", "code", "retryable"),
    [
        (b"stream: scan limit exceeded ERROR\x00", "scanner_rejected", True),
        (b"unexpected\x00", "invalid_scanner_response", True),
        (b"", "invalid_scanner_response", True),
    ],
)
def test_scanner_rejects_daemon_errors_or_malformed_responses(
    response: bytes,
    code: str,
    retryable: bool,
) -> None:
    with pytest.raises(MalwareScanError) as error:
        ClamdInstreamScanner(lambda: FakeSocket(response), maximum_bytes=32).scan((b"data",))

    assert error.value.code == code
    assert error.value.retryable is retryable


def test_scanner_wraps_socket_failure_without_exposing_network_details() -> None:
    connection = FakeSocket(error=OSError("clamd host and port"))

    with pytest.raises(MalwareScanError) as error:
        ClamdInstreamScanner(lambda: connection, maximum_bytes=32).scan((b"data",))

    assert error.value.code == "scanner_unavailable"
    assert error.value.retryable is True
    assert "clamd host" not in str(error.value)
