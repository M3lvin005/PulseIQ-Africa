from __future__ import annotations

import hashlib
import os
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import uuid4

import boto3
import pytest
from botocore.config import Config

from pulseiq.datasets import QuarantineUploadRequest, S3QuarantineObjectStore

S3_ENDPOINT = os.environ.get("PULSEIQ_TEST_S3_ENDPOINT")
S3_ACCESS_KEY = os.environ.get("PULSEIQ_TEST_S3_ACCESS_KEY")
S3_SECRET_KEY = os.environ.get("PULSEIQ_TEST_S3_SECRET_KEY")


def _post_form(url: str, fields: dict[str, str], payload: bytes) -> int:
    boundary = f"----pulseiq-{uuid4().hex}"
    body = bytearray()
    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(value.encode())
        body.extend(b"\r\n")
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(b'Content-Disposition: form-data; name="file"; filename="original.csv"\r\n')
    body.extend(b"Content-Type: text/csv\r\n\r\n")
    body.extend(payload)
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    request = urllib.request.Request(
        url,
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status


def test_s3_compatible_post_policy_and_checksum_head_round_trip() -> None:
    if S3_ENDPOINT is None or S3_ACCESS_KEY is None or S3_SECRET_KEY is None:
        pytest.skip("Set the PULSEIQ_TEST_S3_* variables to run the S3-compatible integration test.")
    endpoint = urlparse(S3_ENDPOINT)
    if endpoint.scheme != "http" or endpoint.hostname not in {"127.0.0.1", "localhost"}:
        pytest.fail("The destructive S3 integration test is restricted to a local HTTP endpoint.")

    client = boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        region_name="us-east-1",
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    bucket = f"pulseiq-quarantine-{uuid4().hex}"
    object_key = "quarantine/org-1/workspace-1/dataset-1/version-1/original.csv"
    payload = b"id,name\n1,Ada\n"
    checksum = hashlib.sha256(payload).hexdigest()
    now = datetime.now(UTC)
    client.create_bucket(Bucket=bucket)
    try:
        store = S3QuarantineObjectStore(
            client,
            bucket=bucket,
            clock=lambda: now,
            server_side_encryption=None,  # Local MinIO has no KMS; production defaults to SSE-S3.
        )
        upload = store.create_upload(
            QuarantineUploadRequest(
                object_key=object_key,
                content_type="text/csv",
                content_length=len(payload),
                checksum_sha256=checksum,
                expires_at=now + timedelta(minutes=10),
            )
        )

        with pytest.raises(urllib.error.HTTPError) as rejected:
            _post_form(upload.url, dict(upload.fields), b"x" * len(payload))
        assert rejected.value.code in {400, 403}, rejected.value.read().decode()

        assert _post_form(upload.url, dict(upload.fields), payload) == 201
        metadata = store.inspect(object_key)
        assert metadata is not None
        assert metadata.content_length == len(payload)
        assert metadata.content_type == "text/csv"
        assert metadata.checksum_sha256 == checksum
    finally:
        client.delete_object(Bucket=bucket, Key=object_key)
        client.delete_bucket(Bucket=bucket)
