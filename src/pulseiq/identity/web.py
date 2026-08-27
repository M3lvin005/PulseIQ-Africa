"""Secure-cookie session and CSRF boundary for a future authenticated web API."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from .contracts import AuthenticatedActor
from .ports import SessionStatusReader

_COOKIE_NAME = "__Host-pulseiq_session"
_KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_METHOD_PATTERN = re.compile(r"^[a-z0-9:_-]{1,32}$")
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_TICKET_FIELDS = frozenset({"amr", "exp", "iat", "sid", "sub", "v"})


class BrowserAuthenticationError(RuntimeError):
    """Fail-closed browser authentication failure with a safe stable code."""

    def __init__(self, code: str) -> None:
        super().__init__("Browser authentication could not be completed.")
        self.code = code


class RequestIntegrityError(RuntimeError):
    """Safe same-origin/CSRF failure suitable for privacy-safe telemetry."""

    def __init__(self, code: str) -> None:
        super().__init__("Request integrity validation failed.")
        self.code = code


@dataclass(frozen=True, slots=True)
class BrowserSessionKey:
    """One independently rotatable signing/CSRF key pair."""

    key_id: str
    signing_key: bytes = field(repr=False)
    csrf_key: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not _KEY_ID_PATTERN.fullmatch(self.key_id):
            raise ValueError("Browser session key ID has an invalid format.")
        if len(self.signing_key) < 32 or len(self.csrf_key) < 32:
            raise ValueError("Browser session keys must contain at least 256 bits.")
        if hmac.compare_digest(self.signing_key, self.csrf_key):
            raise ValueError("Session signing and CSRF keys must be independent.")


@dataclass(frozen=True, slots=True)
class BrowserSessionPolicy:
    """Conservative browser-session and request-integrity policy."""

    allowed_origins: frozenset[str]
    maximum_session_age: timedelta = timedelta(minutes=30)
    clock_skew: timedelta = timedelta(seconds=30)
    cookie_name: str = _COOKIE_NAME

    def __post_init__(self) -> None:
        if not self.allowed_origins:
            raise ValueError("At least one exact browser origin must be configured.")
        normalized = frozenset(_normalize_origin(origin) for origin in self.allowed_origins)
        if normalized != self.allowed_origins:
            raise ValueError("Allowed browser origins must be canonical origins without paths.")
        if not timedelta(minutes=5) <= self.maximum_session_age <= timedelta(hours=1):
            raise ValueError("Maximum browser session age must be between 5 and 60 minutes.")
        if not timedelta(0) <= self.clock_skew <= timedelta(minutes=2):
            raise ValueError("Browser session clock skew must be between 0 and 2 minutes.")
        if self.cookie_name != _COOKIE_NAME:
            raise ValueError("Production browser sessions must use the __Host- cookie name.")


@dataclass(frozen=True, slots=True)
class BrowserSessionEnvelope:
    """One secure cookie plus a synchronizer token returned outside the cookie."""

    set_cookie: str
    csrf_token: str
    expires_at: datetime


class BrowserSessionCodec:
    """Issue and verify bounded HMAC-authenticated browser session tickets."""

    def __init__(
        self,
        active_key: BrowserSessionKey,
        *,
        verification_keys: tuple[BrowserSessionKey, ...] = (),
        policy: BrowserSessionPolicy,
    ) -> None:
        keys = (active_key, *verification_keys)
        self._keys = {key.key_id: key for key in keys}
        if len(self._keys) != len(keys):
            raise ValueError("Browser session key IDs must be unique.")
        self._active_key = active_key
        self._policy = policy

    def issue(self, actor: AuthenticatedActor, *, now: datetime) -> BrowserSessionEnvelope:
        """Create a short-lived secure ticket only for an active server session."""

        _require_aware(now, "Current time")
        self._validate_actor(actor, now=now)
        payload = {
            "amr": list(actor.authentication_methods),
            "exp": int(actor.expires_at.timestamp()),
            "iat": int(actor.authenticated_at.timestamp()),
            "sid": actor.session_id,
            "sub": actor.actor_id,
            "v": 1,
        }
        encoded_payload = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
        signing_input = f"v1.{self._active_key.key_id}.{encoded_payload}"
        signature = _mac(self._active_key.signing_key, signing_input)
        ticket = f"{signing_input}.{signature}"
        csrf_token = self._csrf_token(actor, self._active_key)
        max_age = max(0, int((actor.expires_at - now).total_seconds()))
        expires = format_datetime(actor.expires_at.astimezone(UTC), usegmt=True)
        set_cookie = (
            f"{self._policy.cookie_name}={ticket}; Path=/; Max-Age={max_age}; Expires={expires}; "
            "Secure; HttpOnly; SameSite=Strict; Priority=High"
        )
        return BrowserSessionEnvelope(set_cookie=set_cookie, csrf_token=csrf_token, expires_at=actor.expires_at)

    def authenticate(self, cookie_header: str | None, *, now: datetime) -> AuthenticatedActor:
        """Verify the cookie and return its signed actor/session evidence."""

        _require_aware(now, "Current time")
        ticket = _extract_cookie(cookie_header, self._policy.cookie_name)
        actor = self.decode(ticket, now=now)
        return actor

    def decode(self, ticket: str, *, now: datetime) -> AuthenticatedActor:
        """Verify one ticket without performing authorization or membership lookup."""

        _require_aware(now, "Current time")
        if len(ticket) > 4096:
            raise BrowserAuthenticationError("invalid_session")
        parts = ticket.split(".")
        if len(parts) != 4 or parts[0] != "v1":
            raise BrowserAuthenticationError("invalid_session")
        _, key_id, encoded_payload, supplied_signature = parts
        key = self._keys.get(key_id)
        if key is None:
            raise BrowserAuthenticationError("invalid_session")
        signing_input = f"v1.{key_id}.{encoded_payload}"
        expected_signature = _mac(key.signing_key, signing_input)
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise BrowserAuthenticationError("invalid_session")
        payload = _decode_payload(encoded_payload)
        actor = _actor_from_payload(payload)
        self._validate_actor(actor, now=now)
        return actor

    def validate_request(
        self,
        actor: AuthenticatedActor,
        *,
        method: str,
        origin: str | None,
        csrf_token: str | None,
        sec_fetch_site: str | None = None,
    ) -> None:
        """Require exact same-origin and synchronizer-token proof for mutations."""

        normalized_method = method.upper().strip()
        if normalized_method in _SAFE_METHODS:
            return
        if normalized_method not in {"POST", "PUT", "PATCH", "DELETE"}:
            raise RequestIntegrityError("method_not_allowed")
        if origin is None:
            raise RequestIntegrityError("origin_required")
        try:
            normalized_origin = _normalize_origin(origin)
        except ValueError as exc:
            raise RequestIntegrityError("origin_denied") from exc
        if normalized_origin not in self._policy.allowed_origins:
            raise RequestIntegrityError("origin_denied")
        if sec_fetch_site is not None and sec_fetch_site.lower() != "same-origin":
            raise RequestIntegrityError("cross_site_request")
        if csrf_token is None:
            raise RequestIntegrityError("csrf_required")
        expected = tuple(self._csrf_token(actor, key) for key in self._keys.values())
        if not any(hmac.compare_digest(csrf_token, candidate) for candidate in expected):
            raise RequestIntegrityError("csrf_invalid")

    def clear_cookie(self) -> str:
        """Expire the host-only session credential during logout."""

        return (
            f"{self._policy.cookie_name}=; Path=/; Max-Age=0; "
            "Expires=Thu, 01 Jan 1970 00:00:00 GMT; Secure; HttpOnly; SameSite=Strict; Priority=High"
        )

    def _validate_actor(self, actor: AuthenticatedActor, *, now: datetime) -> None:
        try:
            UUID(actor.actor_id)
            UUID(actor.session_id)
        except ValueError as exc:
            raise BrowserAuthenticationError("invalid_session") from exc
        if not actor.authentication_methods or len(actor.authentication_methods) > 8:
            raise BrowserAuthenticationError("invalid_session")
        if any(not _METHOD_PATTERN.fullmatch(method) for method in actor.authentication_methods):
            raise BrowserAuthenticationError("invalid_session")
        if actor.expires_at - actor.authenticated_at > self._policy.maximum_session_age:
            raise BrowserAuthenticationError("invalid_session")
        if now + self._policy.clock_skew < actor.authenticated_at:
            raise BrowserAuthenticationError("session_not_yet_valid")
        if now - self._policy.clock_skew >= actor.expires_at:
            raise BrowserAuthenticationError("session_expired")

    @staticmethod
    def _csrf_token(actor: AuthenticatedActor, key: BrowserSessionKey) -> str:
        message = f"v1\n{actor.actor_id}\n{actor.session_id}\n{int(actor.expires_at.timestamp())}"
        return f"v1.{key.key_id}.{_mac(key.csrf_key, message)}"


class BrowserRequestAuthenticator:
    """Compose verified tickets with the authoritative revocable session registry."""

    def __init__(self, codec: BrowserSessionCodec, sessions: SessionStatusReader) -> None:
        self._codec = codec
        self._sessions = sessions

    def authenticate(self, cookie_header: str | None, *, now: datetime) -> AuthenticatedActor:
        actor = self._codec.authenticate(cookie_header, now=now)
        current = self._sessions.find_active_session(
            session_id=actor.session_id,
            actor_id=actor.actor_id,
            active_at=now,
        )
        if current is None:
            raise BrowserAuthenticationError("session_inactive")
        return actor


def _extract_cookie(cookie_header: str | None, cookie_name: str) -> str:
    if cookie_header is None or len(cookie_header) > 8192:
        raise BrowserAuthenticationError("authentication_required")
    matches: list[str] = []
    for fragment in cookie_header.split(";"):
        name, separator, value = fragment.strip().partition("=")
        if separator and name == cookie_name:
            matches.append(value)
    if len(matches) != 1 or not matches[0]:
        raise BrowserAuthenticationError("authentication_required")
    return matches[0]


def _decode_payload(encoded: str) -> dict[str, Any]:
    try:
        raw = _b64decode(encoded)
        if len(raw) > 2048:
            raise ValueError("oversized payload")
        payload = json.loads(raw)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise BrowserAuthenticationError("invalid_session") from exc
    if not isinstance(payload, dict) or frozenset(payload) != _TICKET_FIELDS:
        raise BrowserAuthenticationError("invalid_session")
    return payload


def _actor_from_payload(payload: dict[str, Any]) -> AuthenticatedActor:
    if payload.get("v") != 1:
        raise BrowserAuthenticationError("invalid_session")
    subject = payload.get("sub")
    session_id = payload.get("sid")
    issued_at = payload.get("iat")
    expires_at = payload.get("exp")
    methods = payload.get("amr")
    if (
        not isinstance(subject, str)
        or not isinstance(session_id, str)
        or not isinstance(issued_at, int)
        or isinstance(issued_at, bool)
        or not isinstance(expires_at, int)
        or isinstance(expires_at, bool)
        or not isinstance(methods, list)
        or any(not isinstance(method, str) for method in methods)
    ):
        raise BrowserAuthenticationError("invalid_session")
    try:
        return AuthenticatedActor(
            actor_id=subject,
            session_id=session_id,
            authenticated_at=datetime.fromtimestamp(issued_at, tz=UTC),
            expires_at=datetime.fromtimestamp(expires_at, tz=UTC),
            authentication_methods=tuple(methods),
        )
    except (OSError, OverflowError, ValueError) as exc:
        raise BrowserAuthenticationError("invalid_session") from exc


def _normalize_origin(origin: str) -> str:
    parsed = urlsplit(origin)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ValueError("Origin must use HTTP(S) and include a host.")
    if parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("Origin must not include credentials, paths, queries, or fragments.")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("Non-local browser origins must use HTTPS.")
    default_port = 443 if parsed.scheme == "https" else 80
    port = parsed.port
    host = parsed.hostname.lower()
    return f"{parsed.scheme}://{host}" if port in {None, default_port} else f"{parsed.scheme}://{host}:{port}"


def _mac(key: bytes, value: str) -> str:
    return _b64encode(hmac.new(key, value.encode(), hashlib.sha256).digest())


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    if not value or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Invalid base64url value.")
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)


def _require_aware(moment: datetime, label: str) -> None:
    if moment.tzinfo is None:
        raise ValueError(f"{label} must be timezone-aware.")
