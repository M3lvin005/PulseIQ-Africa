"""OIDC state/nonce/PKCE, replay, claim, and session-orchestration tests."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest

from pulseiq.identity import (
    BrowserRequestAuthenticator,
    BrowserSessionCodec,
    BrowserSessionKey,
    BrowserSessionPolicy,
    InMemoryOidcLoginRepository,
    OidcLoginError,
    OidcLoginService,
    OidcLoginTransaction,
    OidcProviderPolicy,
    OidcTransactionStatus,
    OidcVerificationError,
    OidcVerifiedIdentity,
)

NOW = datetime(2026, 8, 27, 12, tzinfo=UTC)
ISSUER = "https://identity.example.com/tenant"
ACTOR_ID = "5f680135-a9af-4d91-a36e-966e990f082e"
TRANSACTION_ID = "ea76705a-8a7c-42e9-86ca-1f20b6ba33bb"
SESSION_ID = "8a6c820a-344d-4a60-8440-251d8e9922ab"
EVENT_ID = "36a2d1cf-d3cf-4948-9900-1494a3eac568"
STATE = "s" * 43
NONCE = "n" * 43
VERIFIER = "v" * 64


class _Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class _Verifier:
    def __init__(self, identity: OidcVerifiedIdentity | None = None, error: str | None = None) -> None:
        self.identity = identity or _identity()
        self.error = error
        self.calls: list[dict[str, object]] = []

    def exchange_and_verify(self, **values: object) -> OidcVerifiedIdentity:
        self.calls.append(values)
        if self.error is not None:
            raise OidcVerificationError(self.error)
        return self.identity


def _policy(**changes: object) -> OidcProviderPolicy:
    values: dict[str, object] = {
        "issuer": ISSUER,
        "authorization_endpoint": "https://identity.example.com/oauth2/authorize",
        "token_endpoint": "https://identity.example.com/oauth2/token",
        "jwks_uri": "https://identity.example.com/.well-known/jwks.json",
        "client_id": "pulseiq-production",
        "redirect_uri": "https://app.pulseiq.africa/auth/callback",
    }
    values.update(changes)
    return OidcProviderPolicy(**cast(Any, values))


def _identity(**changes: object) -> OidcVerifiedIdentity:
    values: dict[str, object] = {
        "issuer": ISSUER,
        "subject": "provider-subject-1",
        "audience": ("pulseiq-production",),
        "nonce": NONCE,
        "authenticated_at": NOW - timedelta(minutes=1),
        "expires_at": NOW + timedelta(minutes=20),
        "authentication_methods": ("pwd", "mfa"),
    }
    values.update(changes)
    return OidcVerifiedIdentity(**cast(Any, values))


def _browser_codec() -> BrowserSessionCodec:
    return BrowserSessionCodec(
        BrowserSessionKey("active", b"s" * 32, b"c" * 32),
        policy=BrowserSessionPolicy(allowed_origins=frozenset({"https://app.pulseiq.africa"})),
    )


def _service(
    *,
    identity: OidcVerifiedIdentity | None = None,
    verifier_error: str | None = None,
    actor_id: str | None = ACTOR_ID,
    policy: OidcProviderPolicy | None = None,
) -> tuple[OidcLoginService, InMemoryOidcLoginRepository, _Verifier, _Clock]:
    clock = _Clock()
    identities = () if actor_id is None else ((ISSUER, "provider-subject-1", actor_id),)
    repository = InMemoryOidcLoginRepository(identities)
    verifier = _Verifier(identity, verifier_error)
    service = OidcLoginService(
        policy or _policy(),
        repository,
        verifier,
        _browser_codec(),
        clock=clock,
        transaction_id_factory=lambda: TRANSACTION_ID,
        session_id_factory=lambda: SESSION_ID,
        event_id_factory=lambda: EVENT_ID,
        state_factory=lambda: STATE,
        nonce_factory=lambda: NONCE,
        verifier_factory=lambda: VERIFIER,
    )
    return service, repository, verifier, clock


def _start_state(service: OidcLoginService) -> str:
    start = service.start()
    return parse_qs(urlsplit(start.authorization_url).query)["state"][0]


def test_start_persists_digest_only_and_builds_nonce_pkce_authorization_url() -> None:
    service, repository, _, _ = _service()

    start = service.start()
    query = parse_qs(urlsplit(start.authorization_url).query)
    expected_challenge = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
    transaction = repository.transactions[0]

    assert query["response_type"] == ["code"]
    assert query["client_id"] == ["pulseiq-production"]
    assert query["state"] == [STATE]
    assert query["nonce"] == [NONCE]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == [expected_challenge]
    assert query["scope"] == ["openid profile email"]
    assert transaction.state_digest == f"sha256:{hashlib.sha256(STATE.encode()).hexdigest()}"
    assert STATE not in repr(transaction)
    assert NONCE not in repr(transaction)
    assert VERIFIER not in repr(transaction)


def test_success_creates_authoritative_session_event_and_secure_cookie_atomically() -> None:
    service, repository, verifier, _ = _service()
    state = _start_state(service)

    result = service.complete(state=state, authorization_code="authorization-code", request_id="request-1")

    assert result.actor.actor_id == ACTOR_ID
    assert result.actor.session_id == SESSION_ID
    assert result.session.status.value == "active"
    assert result.authentication_event.outcome == "succeeded"
    assert result.authentication_event.reason_code == "authenticated"
    assert "Secure" in result.browser_session.set_cookie
    assert "HttpOnly" in result.browser_session.set_cookie
    assert repository.transactions[0].status is OidcTransactionStatus.CONSUMED
    assert repository.find_active_session(session_id=SESSION_ID, actor_id=ACTOR_ID, active_at=NOW) is not None
    assert verifier.calls[0]["authorization_code"] == "authorization-code"
    assert verifier.calls[0]["code_verifier"] == VERIFIER
    assert verifier.calls[0]["expected_nonce"] == NONCE

    cookie = result.browser_session.set_cookie.split(";", 1)[0]
    authenticated = BrowserRequestAuthenticator(_browser_codec(), repository).authenticate(cookie, now=NOW)
    assert authenticated == result.actor


def test_consumed_state_replay_and_unknown_state_fail_with_same_safe_error() -> None:
    service, _, _, _ = _service()
    state = _start_state(service)
    service.complete(state=state, authorization_code="authorization-code", request_id="request-1")

    for attempted_state in (state, "u" * 43):
        with pytest.raises(OidcLoginError) as error:
            service.complete(
                state=attempted_state,
                authorization_code="another-code",
                request_id="request-2",
            )
        assert error.value.code == "login_unavailable"
        assert attempted_state not in str(error.value)


def test_provider_verification_failure_consumes_attempt_and_records_safe_event() -> None:
    service, repository, _, _ = _service(verifier_error="signature_invalid")
    state = _start_state(service)

    with pytest.raises(OidcLoginError):
        service.complete(state=state, authorization_code="secret-code", request_id="request-failed")

    transaction = repository.transactions[0]
    event = repository.authentication_events[0]
    assert transaction.status is OidcTransactionStatus.FAILED
    assert transaction.failure_code == "signature_invalid"
    assert event.outcome == "failed"
    assert event.reason_code == "signature_invalid"
    assert "secret-code" not in repr(event)


@pytest.mark.parametrize(
    ("identity", "reason"),
    [
        (_identity(issuer="https://other.example.com/tenant"), "issuer_mismatch"),
        (_identity(audience=("different-client",)), "audience_mismatch"),
        (_identity(nonce="x" * 43), "nonce_mismatch"),
        (_identity(expires_at=NOW), "identity_token_expired"),
        (_identity(authenticated_at=NOW + timedelta(minutes=1)), "authentication_time_invalid"),
        (_identity(authenticated_at=NOW - timedelta(minutes=11)), "authentication_too_old"),
        (_identity(authentication_methods=("pwd",)), "mfa_required"),
    ],
)
def test_claim_mismatches_fail_and_consume_the_transaction(
    identity: OidcVerifiedIdentity,
    reason: str,
) -> None:
    service, repository, _, _ = _service(identity=identity)
    state = _start_state(service)

    with pytest.raises(OidcLoginError):
        service.complete(state=state, authorization_code="authorization-code", request_id="request-1")

    assert repository.transactions[0].status is OidcTransactionStatus.FAILED
    assert repository.authentication_events[0].reason_code == reason


def test_unprovisioned_or_invalid_actor_mapping_fails_closed() -> None:
    for actor_id, expected in ((None, "identity_not_provisioned"), ("not-a-uuid", "identity_mapping_invalid")):
        service, repository, _, _ = _service(actor_id=actor_id)
        state = _start_state(service)

        with pytest.raises(OidcLoginError):
            service.complete(state=state, authorization_code="authorization-code", request_id="request-1")

        assert repository.authentication_events[0].reason_code == expected


def test_expired_transaction_cannot_reach_the_provider() -> None:
    service, _, verifier, clock = _service()
    state = _start_state(service)
    clock.now += timedelta(minutes=11)

    with pytest.raises(OidcLoginError):
        service.complete(state=state, authorization_code="authorization-code", request_id="request-1")

    assert verifier.calls == []


def test_session_expiry_is_bounded_by_the_verified_identity_token() -> None:
    identity = _identity(expires_at=NOW + timedelta(minutes=7))
    service, _, _, _ = _service(identity=identity)
    state = _start_state(service)

    result = service.complete(state=state, authorization_code="authorization-code", request_id="request-1")

    assert result.session.expires_at == identity.expires_at


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("authorization_endpoint", "https://evil.example.com/authorize"),
        ("token_endpoint", "http://identity.example.com/token"),
        ("jwks_uri", "https://user@identity.example.com/jwks"),
        ("client_id", ""),
        ("scopes", ("profile",)),
        ("transaction_ttl", timedelta(minutes=1)),
        ("maximum_auth_age", timedelta(0)),
        ("session_lifetime", timedelta(hours=1)),
    ],
)
def test_provider_policy_rejects_unsafe_configuration(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        _policy(**{field: value})


def test_factories_must_return_bounded_entropy_and_uuid_identifiers() -> None:
    service, _, _, _ = _service()
    service._state_factory = lambda: "short"
    with pytest.raises(RuntimeError, match="unsafe entropy"):
        service.start()

    invalid, _, _, _ = _service()
    invalid._transaction_id_factory = lambda: "not-a-uuid"
    with pytest.raises(ValueError, match="UUID"):
        invalid.start()

    bad_verifier, _, _, _ = _service()
    bad_verifier._verifier_factory = lambda: "short"
    with pytest.raises(RuntimeError, match="verifier factory"):
        bad_verifier.start()


@pytest.mark.parametrize(
    "changes",
    [
        {"state_digest": "bad"},
        {"nonce": "short"},
        {"code_verifier": "short"},
        {"expires_at": NOW},
        {"revision": 0},
        {"completed_at": NOW},
        {"status": OidcTransactionStatus.CONSUMED},
        {"status": OidcTransactionStatus.CONSUMED, "completed_at": NOW + timedelta(minutes=11)},
        {"status": OidcTransactionStatus.FAILED, "completed_at": NOW},
        {
            "status": OidcTransactionStatus.CONSUMED,
            "completed_at": NOW,
            "failure_code": "not_allowed",
        },
    ],
)
def test_login_transaction_rejects_invalid_lifecycle_or_secret_metadata(changes: dict[str, object]) -> None:
    transaction = OidcLoginTransaction(
        transaction_id=TRANSACTION_ID,
        state_digest=f"sha256:{hashlib.sha256(STATE.encode()).hexdigest()}",
        nonce=NONCE,
        code_verifier=VERIFIER,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )

    with pytest.raises(ValueError):
        replace(transaction, **cast(Any, changes))


@pytest.mark.parametrize(
    "changes",
    [
        {"subject": " "},
        {"audience": ()},
        {"nonce": "short"},
        {"expires_at": NOW - timedelta(minutes=1)},
        {"authentication_methods": ()},
        {"authentication_methods": ("bad method",)},
    ],
)
def test_verified_identity_rejects_invalid_claim_contract(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _identity(**changes)


def test_repository_rejects_duplicate_identity_and_state() -> None:
    with pytest.raises(ValueError, match="unique"):
        InMemoryOidcLoginRepository(
            (
                (ISSUER, "subject", ACTOR_ID),
                (ISSUER, "subject", ACTOR_ID),
            )
        )

    service, repository, _, _ = _service()
    service.start()
    transaction = repository.transactions[0]
    with pytest.raises(RuntimeError, match="state digest"):
        repository.save_transaction(transaction)


def test_bad_port_naive_clock_and_empty_callback_values_fail_before_exchange() -> None:
    with pytest.raises(ValueError, match="OIDC URL"):
        _policy(token_endpoint="https://identity.example.com:bad/token")

    service, _, verifier, clock = _service()
    clock.now = datetime(2026, 8, 27)
    with pytest.raises(ValueError, match="timezone-aware"):
        service.start()
    clock.now = NOW
    service.start()
    with pytest.raises(ValueError, match="OIDC state"):
        service.complete(state="", authorization_code="code", request_id="request")
    assert verifier.calls == []
