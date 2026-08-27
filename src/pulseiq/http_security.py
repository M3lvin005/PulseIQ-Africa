"""Exact-origin CORS and hardened HTTP response-header policy."""

from __future__ import annotations

import base64
import re
import secrets
from dataclasses import dataclass
from urllib.parse import urlsplit

_NONCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{22,128}$")
_ALLOWED_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"})
_ALLOWED_REQUEST_HEADERS = ("Content-Type", "X-CSRF-Token", "X-Request-ID")


class CorsDenied(RuntimeError):
    """Stable denial for origins outside the configured browser boundary."""

    def __init__(self) -> None:
        super().__init__("Cross-origin request is not permitted.")
        self.code = "cors_origin_denied"


@dataclass(frozen=True, slots=True)
class HttpSecurityPolicy:
    """Security-header and exact-origin CORS configuration."""

    app_origin: str
    allowed_cors_origins: frozenset[str]
    hsts_max_age_seconds: int = 63_072_000

    def __post_init__(self) -> None:
        canonical_app = canonical_origin(self.app_origin)
        if canonical_app != self.app_origin:
            raise ValueError("Application origin must be canonical and contain no path.")
        canonical_cors = frozenset(canonical_origin(origin) for origin in self.allowed_cors_origins)
        if canonical_cors != self.allowed_cors_origins:
            raise ValueError("CORS origins must be canonical and contain no path.")
        if self.app_origin not in self.allowed_cors_origins:
            raise ValueError("The application origin must be an allowed CORS origin.")
        if not 31_536_000 <= self.hsts_max_age_seconds <= 126_144_000:
            raise ValueError("HSTS maximum age must be between one and four years.")


def create_csp_nonce() -> str:
    """Return at least 128 bits of base64url entropy for one response."""

    return base64.urlsafe_b64encode(secrets.token_bytes(18)).rstrip(b"=").decode("ascii")


def security_headers(
    policy: HttpSecurityPolicy,
    *,
    csp_nonce: str,
    authenticated: bool = True,
) -> dict[str, str]:
    """Build a strict nonce-based CSP and browser hardening headers."""

    if not _NONCE_PATTERN.fullmatch(csp_nonce):
        raise ValueError("CSP nonce must be a bounded base64url value with at least 128 bits.")
    csp = "; ".join(
        (
            "default-src 'none'",
            "base-uri 'none'",
            "connect-src 'self'",
            "font-src 'self'",
            "form-action 'self'",
            "frame-ancestors 'none'",
            "img-src 'self' data:",
            "manifest-src 'self'",
            "object-src 'none'",
            f"script-src 'self' 'nonce-{csp_nonce}'",
            f"style-src 'self' 'nonce-{csp_nonce}'",
            "worker-src 'self' blob:",
            "upgrade-insecure-requests",
        )
    )
    headers = {
        "Content-Security-Policy": csp,
        "Cross-Origin-Opener-Policy": "same-origin",
        "Cross-Origin-Resource-Policy": "same-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        "Referrer-Policy": "no-referrer",
        "Strict-Transport-Security": (f"max-age={policy.hsts_max_age_seconds}; includeSubDomains; preload"),
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
    }
    if authenticated:
        headers["Cache-Control"] = "no-store, private"
        headers["Pragma"] = "no-cache"
    return headers


def cors_headers(
    policy: HttpSecurityPolicy,
    *,
    origin: str,
    requested_method: str | None = None,
) -> dict[str, str]:
    """Return credentialed CORS headers only for an exact configured origin."""

    try:
        canonical = canonical_origin(origin)
    except ValueError as exc:
        raise CorsDenied() from exc
    if canonical not in policy.allowed_cors_origins:
        raise CorsDenied()
    if requested_method is not None and requested_method.upper() not in _ALLOWED_METHODS:
        raise CorsDenied()
    headers = {
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Origin": canonical,
        "Vary": "Origin",
    }
    if requested_method is not None:
        headers.update(
            {
                "Access-Control-Allow-Headers": ", ".join(_ALLOWED_REQUEST_HEADERS),
                "Access-Control-Allow-Methods": ", ".join(sorted(_ALLOWED_METHODS)),
                "Access-Control-Max-Age": "600",
            }
        )
    return headers


def canonical_origin(origin: str) -> str:
    """Normalize one HTTP origin while rejecting paths, userinfo, and public HTTP."""

    if not origin or origin.isspace() or len(origin) > 512:
        raise ValueError("Origin must be a bounded value.")
    parsed = urlsplit(origin)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ValueError("Origin must use HTTP(S) and contain a host.")
    if parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("Origin must not contain credentials, paths, queries, or fragments.")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("Public application origins must use HTTPS.")
    default_port = 443 if parsed.scheme == "https" else 80
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Origin port is invalid.") from exc
    host = parsed.hostname.lower()
    return f"{parsed.scheme}://{host}" if port in {None, default_port} else f"{parsed.scheme}://{host}:{port}"
