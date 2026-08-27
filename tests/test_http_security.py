"""HTTP security-header and exact-origin CORS tests."""

from __future__ import annotations

import pytest

from pulseiq.http_security import (
    CorsDenied,
    HttpSecurityPolicy,
    canonical_origin,
    cors_headers,
    create_csp_nonce,
    security_headers,
)


def _policy() -> HttpSecurityPolicy:
    return HttpSecurityPolicy(
        app_origin="https://app.pulseiq.africa",
        allowed_cors_origins=frozenset(
            {
                "https://app.pulseiq.africa",
                "https://admin.pulseiq.africa",
            }
        ),
    )


def test_security_headers_use_nonce_csp_and_no_authenticated_cache() -> None:
    nonce = create_csp_nonce()
    headers = security_headers(_policy(), csp_nonce=nonce)

    csp = headers["Content-Security-Policy"]
    assert f"script-src 'self' 'nonce-{nonce}'" in csp
    assert f"style-src 'self' 'nonce-{nonce}'" in csp
    assert "default-src 'none'" in csp
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "'unsafe-inline'" not in csp
    assert "'unsafe-eval'" not in csp
    assert headers["Strict-Transport-Security"].startswith("max-age=63072000")
    assert headers["Cache-Control"] == "no-store, private"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"


def test_cors_echoes_only_exact_allowlisted_origin_without_wildcard() -> None:
    headers = cors_headers(
        _policy(),
        origin="https://app.pulseiq.africa",
        requested_method="POST",
    )

    assert headers["Access-Control-Allow-Origin"] == "https://app.pulseiq.africa"
    assert headers["Access-Control-Allow-Credentials"] == "true"
    assert headers["Vary"] == "Origin"
    assert "X-CSRF-Token" in headers["Access-Control-Allow-Headers"]
    assert "*" not in " ".join(headers.values())


@pytest.mark.parametrize(
    "origin",
    [
        "https://app.pulseiq.africa.evil.example",
        "https://evil.example",
        "http://app.pulseiq.africa",
        "https://app.pulseiq.africa/path",
        "https://user@app.pulseiq.africa",
    ],
)
def test_cors_rejects_lookalike_or_unsafe_origins(origin: str) -> None:
    with pytest.raises(CorsDenied) as error:
        cors_headers(_policy(), origin=origin, requested_method="POST")

    assert error.value.code == "cors_origin_denied"
    assert origin not in str(error.value)


def test_cors_rejects_unapproved_method() -> None:
    with pytest.raises(CorsDenied):
        cors_headers(_policy(), origin="https://app.pulseiq.africa", requested_method="TRACE")


def test_policy_requires_canonical_https_origin_and_app_allowlist() -> None:
    with pytest.raises(ValueError, match="allowed CORS"):
        HttpSecurityPolicy(
            app_origin="https://app.pulseiq.africa",
            allowed_cors_origins=frozenset({"https://admin.pulseiq.africa"}),
        )
    with pytest.raises(ValueError, match="Public application origins"):
        canonical_origin("http://app.pulseiq.africa")
    assert canonical_origin("http://127.0.0.1:8501/") == "http://127.0.0.1:8501"


def test_nonce_validation_rejects_short_or_non_base64_values() -> None:
    with pytest.raises(ValueError, match="nonce"):
        security_headers(_policy(), csp_nonce="short")
    with pytest.raises(ValueError, match="nonce"):
        security_headers(_policy(), csp_nonce="x" * 22 + "+")


def test_public_response_can_omit_authenticated_no_store_headers() -> None:
    headers = security_headers(_policy(), csp_nonce=create_csp_nonce(), authenticated=False)

    assert "Cache-Control" not in headers
    assert "Pragma" not in headers


def test_simple_cors_response_omits_preflight_only_headers() -> None:
    headers = cors_headers(_policy(), origin="https://admin.pulseiq.africa")

    assert headers["Access-Control-Allow-Origin"] == "https://admin.pulseiq.africa"
    assert "Access-Control-Allow-Methods" not in headers
    assert "Access-Control-Max-Age" not in headers


def test_policy_rejects_noncanonical_origins_and_hsts_bounds() -> None:
    with pytest.raises(ValueError, match="canonical"):
        HttpSecurityPolicy(
            app_origin="https://APP.pulseiq.africa",
            allowed_cors_origins=frozenset({"https://APP.pulseiq.africa"}),
        )
    with pytest.raises(ValueError, match="CORS origins"):
        HttpSecurityPolicy(
            app_origin="https://app.pulseiq.africa",
            allowed_cors_origins=frozenset({"https://app.pulseiq.africa", "https://ADMIN.pulseiq.africa"}),
        )
    with pytest.raises(ValueError, match="HSTS"):
        HttpSecurityPolicy(
            app_origin="https://app.pulseiq.africa",
            allowed_cors_origins=frozenset({"https://app.pulseiq.africa"}),
            hsts_max_age_seconds=60,
        )


@pytest.mark.parametrize("origin", ["", "   ", "ftp://app.pulseiq.africa", "https://app.pulseiq.africa:bad"])
def test_canonical_origin_rejects_empty_wrong_scheme_or_bad_port(origin: str) -> None:
    with pytest.raises(ValueError):
        canonical_origin(origin)
