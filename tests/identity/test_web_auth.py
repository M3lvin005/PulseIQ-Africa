"""Secure browser-session and request-integrity boundary tests."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from pulseiq.identity import (
    AuthenticatedActor,
    BrowserAuthenticationError,
    BrowserRequestAuthenticator,
    BrowserSessionCodec,
    BrowserSessionKey,
    BrowserSessionPolicy,
    InMemorySessionRepository,
    RequestIntegrityError,
    SessionRecord,
    SessionStatus,
)

NOW = datetime(2026, 8, 27, 8, tzinfo=UTC)
ACTOR_ID = "5f680135-a9af-4d91-a36e-966e990f082e"
SESSION_ID = "8a6c820a-344d-4a60-8440-251d8e9922ab"


def _actor(*, expires_at: datetime | None = None) -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id=ACTOR_ID,
        session_id=SESSION_ID,
        authenticated_at=NOW,
        expires_at=expires_at or NOW + timedelta(minutes=20),
        authentication_methods=("pwd", "mfa"),
    )


def _key(key_id: str = "2026-08") -> BrowserSessionKey:
    return BrowserSessionKey(key_id, b"s" * 32, b"c" * 32)


def _codec(*, key: BrowserSessionKey | None = None) -> BrowserSessionCodec:
    return BrowserSessionCodec(
        key or _key(),
        policy=BrowserSessionPolicy(allowed_origins=frozenset({"https://app.pulseiq.africa"})),
    )


def _cookie_value(set_cookie: str) -> str:
    return set_cookie.split(";", 1)[0].split("=", 1)[1]


def _signed_ticket(payload: object, key: BrowserSessionKey | None = None) -> str:
    active = key or _key()
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=").decode()
    signing_input = f"v1.{active.key_id}.{encoded}"
    signature = (
        base64.urlsafe_b64encode(hmac.new(active.signing_key, signing_input.encode(), hashlib.sha256).digest())
        .rstrip(b"=")
        .decode()
    )
    return f"{signing_input}.{signature}"


def _valid_payload() -> dict[str, object]:
    return {
        "amr": ["pwd", "mfa"],
        "exp": int((NOW + timedelta(minutes=20)).timestamp()),
        "iat": int(NOW.timestamp()),
        "sid": SESSION_ID,
        "sub": ACTOR_ID,
        "v": 1,
    }


def test_issue_uses_host_only_secure_http_only_strict_cookie_and_csrf_token() -> None:
    envelope = _codec().issue(_actor(), now=NOW + timedelta(minutes=1))

    assert envelope.set_cookie.startswith("__Host-pulseiq_session=")
    for directive in ("Path=/", "Secure", "HttpOnly", "SameSite=Strict", "Priority=High", "Max-Age=1140"):
        assert directive in envelope.set_cookie
    assert envelope.csrf_token.startswith("v1.2026-08.")
    assert "Domain=" not in envelope.set_cookie
    assert "pwd" not in envelope.set_cookie


def test_ticket_round_trip_requires_active_authoritative_session() -> None:
    actor = _actor()
    codec = _codec()
    envelope = codec.issue(actor, now=NOW)
    cookie_header = f"theme=dark; __Host-pulseiq_session={_cookie_value(envelope.set_cookie)}"
    sessions = InMemorySessionRepository(
        [
            SessionRecord(
                session_id=actor.session_id,
                actor_id=actor.actor_id,
                authenticated_at=actor.authenticated_at,
                expires_at=actor.expires_at,
                status=SessionStatus.ACTIVE,
            )
        ]
    )

    authenticated = BrowserRequestAuthenticator(codec, sessions).authenticate(
        cookie_header,
        now=NOW + timedelta(minutes=2),
    )

    assert authenticated == actor
    UUID(authenticated.actor_id)
    UUID(authenticated.session_id)


def test_missing_revoked_or_duplicate_cookie_fails_closed() -> None:
    actor = _actor()
    codec = _codec()
    envelope = codec.issue(actor, now=NOW)
    ticket = _cookie_value(envelope.set_cookie)
    authenticator = BrowserRequestAuthenticator(codec, InMemorySessionRepository())

    with pytest.raises(BrowserAuthenticationError) as missing:
        authenticator.authenticate(None, now=NOW)
    with pytest.raises(BrowserAuthenticationError) as inactive:
        authenticator.authenticate(f"__Host-pulseiq_session={ticket}", now=NOW)
    with pytest.raises(BrowserAuthenticationError) as duplicate:
        authenticator.authenticate(
            f"__Host-pulseiq_session={ticket}; __Host-pulseiq_session={ticket}",
            now=NOW,
        )

    assert missing.value.code == "authentication_required"
    assert inactive.value.code == "session_inactive"
    assert duplicate.value.code == "authentication_required"


def test_tampering_expiry_and_oversized_lifetime_fail_closed() -> None:
    codec = _codec()
    envelope = codec.issue(_actor(), now=NOW)
    ticket = _cookie_value(envelope.set_cookie)
    tampered = f"{ticket[:-1]}{'A' if ticket[-1] != 'A' else 'B'}"

    with pytest.raises(BrowserAuthenticationError) as invalid:
        codec.decode(tampered, now=NOW)
    with pytest.raises(BrowserAuthenticationError) as expired:
        codec.decode(ticket, now=NOW + timedelta(minutes=21))
    with pytest.raises(BrowserAuthenticationError) as oversized:
        codec.issue(_actor(expires_at=NOW + timedelta(minutes=31)), now=NOW)

    assert invalid.value.code == "invalid_session"
    assert expired.value.code == "session_expired"
    assert oversized.value.code == "invalid_session"


def test_mutations_require_exact_origin_same_site_and_bound_csrf_token() -> None:
    actor = _actor()
    codec = _codec()
    token = codec.issue(actor, now=NOW).csrf_token

    codec.validate_request(
        actor,
        method="POST",
        origin="https://app.pulseiq.africa",
        csrf_token=token,
        sec_fetch_site="same-origin",
    )
    codec.validate_request(actor, method="GET", origin=None, csrf_token=None)

    cases = (
        ({"method": "POST", "origin": None, "csrf_token": token}, "origin_required"),
        (
            {
                "method": "POST",
                "origin": "https://app.pulseiq.africa.evil.example",
                "csrf_token": token,
            },
            "origin_denied",
        ),
        (
            {
                "method": "POST",
                "origin": "https://app.pulseiq.africa",
                "csrf_token": token,
                "sec_fetch_site": "cross-site",
            },
            "cross_site_request",
        ),
        (
            {
                "method": "POST",
                "origin": "https://app.pulseiq.africa",
                "csrf_token": "wrong",
            },
            "csrf_invalid",
        ),
    )
    for request, code in cases:
        with pytest.raises(RequestIntegrityError) as error:
            codec.validate_request(actor, **request)
        assert error.value.code == code


def test_key_rotation_accepts_old_ticket_and_csrf_but_issues_with_active_key() -> None:
    old_key = _key("old")
    old_codec = _codec(key=old_key)
    actor = _actor()
    old_envelope = old_codec.issue(actor, now=NOW)
    active_key = BrowserSessionKey("active", b"n" * 32, b"x" * 32)
    rotating = BrowserSessionCodec(
        active_key,
        verification_keys=(old_key,),
        policy=BrowserSessionPolicy(allowed_origins=frozenset({"https://app.pulseiq.africa"})),
    )

    decoded = rotating.decode(_cookie_value(old_envelope.set_cookie), now=NOW)
    rotating.validate_request(
        decoded,
        method="POST",
        origin="https://app.pulseiq.africa",
        csrf_token=old_envelope.csrf_token,
    )
    new_envelope = rotating.issue(actor, now=NOW)

    assert new_envelope.csrf_token.startswith("v1.active.")


def test_policy_rejects_weak_keys_and_unsafe_origins() -> None:
    with pytest.raises(ValueError, match="256 bits"):
        BrowserSessionKey("weak", b"short", b"also-short")
    with pytest.raises(ValueError, match="HTTPS"):
        BrowserSessionPolicy(allowed_origins=frozenset({"http://app.pulseiq.africa"}))
    with pytest.raises(ValueError, match="paths"):
        BrowserSessionPolicy(allowed_origins=frozenset({"https://app.pulseiq.africa/path"}))


def test_policy_rejects_invalid_ids_reused_keys_and_unsafe_bounds() -> None:
    with pytest.raises(ValueError, match="key ID"):
        BrowserSessionKey("bad key", b"s" * 32, b"c" * 32)
    with pytest.raises(ValueError, match="independent"):
        BrowserSessionKey("same", b"s" * 32, b"s" * 32)
    with pytest.raises(ValueError, match="At least one"):
        BrowserSessionPolicy(allowed_origins=frozenset())
    with pytest.raises(ValueError, match="between 5 and 60"):
        BrowserSessionPolicy(
            allowed_origins=frozenset({"https://app.pulseiq.africa"}),
            maximum_session_age=timedelta(minutes=2),
        )
    with pytest.raises(ValueError, match="clock skew"):
        BrowserSessionPolicy(
            allowed_origins=frozenset({"https://app.pulseiq.africa"}),
            clock_skew=timedelta(minutes=3),
        )
    with pytest.raises(ValueError, match="__Host-"):
        BrowserSessionPolicy(
            allowed_origins=frozenset({"https://app.pulseiq.africa"}),
            cookie_name="session",
        )
    with pytest.raises(ValueError, match="unique"):
        BrowserSessionCodec(
            _key("same"),
            verification_keys=(_key("same"),),
            policy=BrowserSessionPolicy(allowed_origins=frozenset({"https://app.pulseiq.africa"})),
        )


def test_malformed_ticket_shapes_payloads_and_unknown_keys_fail_closed() -> None:
    codec = _codec()
    invalid_tickets = (
        "x" * 4097,
        "v2.key.payload.signature",
        "v1.unknown.payload.signature",
        _signed_ticket({**_valid_payload(), "extra": "field"}),
        _signed_ticket(["not", "an", "object"]),
        _signed_ticket({**_valid_payload(), "v": 2}),
        _signed_ticket({**_valid_payload(), "iat": True}),
    )

    for ticket in invalid_tickets:
        with pytest.raises(BrowserAuthenticationError) as error:
            codec.decode(ticket, now=NOW)
        assert error.value.code == "invalid_session"


def test_invalid_actor_assurance_future_time_and_naive_time_fail_closed() -> None:
    codec = _codec()
    invalid_uuid = AuthenticatedActor(
        actor_id="actor-not-uuid",
        session_id=SESSION_ID,
        authenticated_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
        authentication_methods=("mfa",),
    )
    missing_assurance = AuthenticatedActor(
        actor_id=ACTOR_ID,
        session_id=SESSION_ID,
        authenticated_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
        authentication_methods=(),
    )
    bad_assurance = AuthenticatedActor(
        actor_id=ACTOR_ID,
        session_id=SESSION_ID,
        authenticated_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
        authentication_methods=("bad method",),
    )
    future = AuthenticatedActor(
        actor_id=ACTOR_ID,
        session_id=SESSION_ID,
        authenticated_at=NOW + timedelta(minutes=2),
        expires_at=NOW + timedelta(minutes=12),
        authentication_methods=("mfa",),
    )

    for actor in (invalid_uuid, missing_assurance, bad_assurance):
        with pytest.raises(BrowserAuthenticationError) as error:
            codec.issue(actor, now=NOW)
        assert error.value.code == "invalid_session"
    with pytest.raises(BrowserAuthenticationError) as not_yet_valid:
        codec.issue(future, now=NOW)
    assert not_yet_valid.value.code == "session_not_yet_valid"
    with pytest.raises(ValueError, match="timezone-aware"):
        codec.issue(_actor(), now=datetime(2026, 8, 27))


def test_mutation_rejects_unknown_method_malformed_origin_and_missing_csrf() -> None:
    actor = _actor()
    codec = _codec()

    cases = (
        ({"method": "TRACE", "origin": "https://app.pulseiq.africa", "csrf_token": "token"}, "method_not_allowed"),
        ({"method": "POST", "origin": "not-an-origin", "csrf_token": "token"}, "origin_denied"),
        ({"method": "POST", "origin": "https://app.pulseiq.africa", "csrf_token": None}, "csrf_required"),
    )
    for request, code in cases:
        with pytest.raises(RequestIntegrityError) as error:
            codec.validate_request(actor, **request)
        assert error.value.code == code


def test_logout_cookie_expires_the_same_host_only_credential() -> None:
    cleared = _codec().clear_cookie()

    assert cleared.startswith("__Host-pulseiq_session=;")
    assert "Max-Age=0" in cleared
    assert "Secure" in cleared
    assert "HttpOnly" in cleared
    assert "SameSite=Strict" in cleared
