"""Provider-neutral OIDC authorization-code/PKCE login orchestration."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol
from urllib.parse import urlencode, urlsplit
from uuid import UUID, uuid4

from .contracts import AuthenticatedActor, SessionRecord, SessionStatus
from .web import BrowserSessionCodec, BrowserSessionEnvelope

_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,256}$")
_PKCE_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")
_SUBJECT_PATTERN = re.compile(r"^[^\s]{1,255}$")
_METHOD_PATTERN = re.compile(r"^[a-z0-9:_-]{1,32}$")


class OidcTransactionStatus(StrEnum):
    PENDING = "pending"
    CONSUMED = "consumed"
    FAILED = "failed"


class OidcLoginError(RuntimeError):
    """Fail-closed OIDC flow failure with a stable non-sensitive code."""

    def __init__(self, code: str = "login_unavailable") -> None:
        super().__init__("Sign-in could not be completed. Start a new sign-in attempt.")
        self.code = code


class OidcVerificationError(RuntimeError):
    """Expected adapter failure after token exchange/cryptographic verification."""

    def __init__(self, code: str = "provider_verification_failed") -> None:
        super().__init__("Identity-provider verification failed.")
        self.code = code


@dataclass(frozen=True, slots=True)
class OidcProviderPolicy:
    """Allowlisted provider endpoints and bounded login/session policy."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    client_id: str
    redirect_uri: str
    scopes: tuple[str, ...] = ("openid", "profile", "email")
    require_mfa: bool = True
    transaction_ttl: timedelta = timedelta(minutes=10)
    maximum_auth_age: timedelta = timedelta(minutes=10)
    session_lifetime: timedelta = timedelta(minutes=30)

    def __post_init__(self) -> None:
        issuer = _https_url(self.issuer, allow_query=False)
        issuer_host = urlsplit(issuer).hostname
        for endpoint, label in (
            (self.authorization_endpoint, "Authorization endpoint"),
            (self.token_endpoint, "Token endpoint"),
            (self.jwks_uri, "JWKS URI"),
        ):
            parsed = urlsplit(_https_url(endpoint, allow_query=False))
            if parsed.hostname != issuer_host:
                raise ValueError(f"{label} must use the exact configured issuer host.")
        _https_url(self.redirect_uri, allow_query=False)
        if not self.client_id or self.client_id.isspace() or len(self.client_id) > 256:
            raise ValueError("OIDC client ID must be a bounded non-empty value.")
        if not self.scopes or "openid" not in self.scopes or len(set(self.scopes)) != len(self.scopes):
            raise ValueError("OIDC scopes must be unique and include openid.")
        if any(not re.fullmatch(r"[a-zA-Z0-9:_-]{1,64}", scope) for scope in self.scopes):
            raise ValueError("OIDC scopes contain an invalid value.")
        if not timedelta(minutes=5) <= self.transaction_ttl <= timedelta(minutes=15):
            raise ValueError("OIDC transaction lifetime must be between 5 and 15 minutes.")
        if not timedelta(minutes=1) <= self.maximum_auth_age <= timedelta(hours=1):
            raise ValueError("OIDC authentication age must be between 1 and 60 minutes.")
        if not timedelta(minutes=5) <= self.session_lifetime <= timedelta(minutes=30):
            raise ValueError("OIDC session lifetime must be between 5 and 30 minutes.")


@dataclass(frozen=True, slots=True)
class OidcLoginTransaction:
    """Server-side one-time login state; raw state and authorization code are absent."""

    transaction_id: str
    state_digest: str
    nonce: str = field(repr=False)
    code_verifier: str = field(repr=False)
    created_at: datetime
    expires_at: datetime
    status: OidcTransactionStatus = OidcTransactionStatus.PENDING
    revision: int = 1
    completed_at: datetime | None = None
    failure_code: str | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.transaction_id, "OIDC transaction ID")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.state_digest):
            raise ValueError("OIDC state digest must be a SHA-256 encoding.")
        if not _TOKEN_PATTERN.fullmatch(self.nonce):
            raise ValueError("OIDC nonce must contain at least 192 bits of base64url entropy.")
        if not _PKCE_PATTERN.fullmatch(self.code_verifier):
            raise ValueError("OIDC PKCE verifier has an invalid format or length.")
        _require_aware(self.created_at, "OIDC transaction creation time")
        _require_aware(self.expires_at, "OIDC transaction expiry")
        if not self.created_at < self.expires_at:
            raise ValueError("OIDC transaction expiry must follow creation.")
        if self.revision < 1:
            raise ValueError("OIDC transaction revision must be positive.")
        if self.status is OidcTransactionStatus.PENDING:
            if self.completed_at is not None or self.failure_code is not None:
                raise ValueError("A pending OIDC transaction cannot have completion metadata.")
        elif self.completed_at is None:
            raise ValueError("A terminal OIDC transaction must record completion time.")
        if self.completed_at is not None:
            _require_aware(self.completed_at, "OIDC transaction completion time")
            if not self.created_at <= self.completed_at <= self.expires_at:
                raise ValueError("OIDC transaction completion must occur within its validity window.")
        if self.status is OidcTransactionStatus.FAILED and not self.failure_code:
            raise ValueError("A failed OIDC transaction must record a safe failure code.")
        if self.status is not OidcTransactionStatus.FAILED and self.failure_code is not None:
            raise ValueError("Only a failed OIDC transaction can record a failure code.")


@dataclass(frozen=True, slots=True)
class OidcVerifiedIdentity:
    """Claims returned only after adapter signature, issuer, and token validation."""

    issuer: str
    subject: str
    audience: tuple[str, ...]
    nonce: str = field(repr=False)
    authenticated_at: datetime
    expires_at: datetime
    authentication_methods: tuple[str, ...]

    def __post_init__(self) -> None:
        _https_url(self.issuer, allow_query=False)
        if not _SUBJECT_PATTERN.fullmatch(self.subject):
            raise ValueError("OIDC subject must be a bounded non-empty value.")
        if not self.audience or any(not item or item.isspace() for item in self.audience):
            raise ValueError("OIDC audience must contain bounded non-empty values.")
        if not _TOKEN_PATTERN.fullmatch(self.nonce):
            raise ValueError("OIDC nonce has an invalid format.")
        _require_aware(self.authenticated_at, "OIDC authentication time")
        _require_aware(self.expires_at, "OIDC token expiry")
        if self.expires_at <= self.authenticated_at:
            raise ValueError("OIDC token expiry must follow authentication.")
        if not self.authentication_methods or len(self.authentication_methods) > 8:
            raise ValueError("OIDC authentication methods must be present and bounded.")
        if any(not _METHOD_PATTERN.fullmatch(method) for method in self.authentication_methods):
            raise ValueError("OIDC authentication method has an invalid format.")


@dataclass(frozen=True, slots=True)
class AuthenticationEvent:
    """PII-free authentication event for atomic persistence and monitoring."""

    event_id: str
    occurred_at: datetime
    action: str
    outcome: str
    reason_code: str
    request_id: str
    transaction_id: str
    actor_id: str | None = None
    session_id: str | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.event_id, "Authentication event ID")
        _require_uuid(self.transaction_id, "OIDC transaction ID")
        _require_aware(self.occurred_at, "Authentication event time")
        for value, label in (
            (self.action, "Authentication event action"),
            (self.outcome, "Authentication event outcome"),
            (self.reason_code, "Authentication event reason"),
            (self.request_id, "Authentication request ID"),
        ):
            _require_bounded(value, label, 256)
        if self.actor_id is not None:
            _require_uuid(self.actor_id, "Authentication actor ID")
        if self.session_id is not None:
            _require_uuid(self.session_id, "Authentication session ID")


@dataclass(frozen=True, slots=True)
class OidcLoginStart:
    authorization_url: str
    transaction_id: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class OidcLoginResult:
    actor: AuthenticatedActor
    session: SessionRecord
    browser_session: BrowserSessionEnvelope
    authentication_event: AuthenticationEvent


class OidcTokenVerifier(Protocol):
    """Exchange the code and cryptographically verify the returned OIDC tokens."""

    def exchange_and_verify(
        self,
        *,
        authorization_code: str,
        code_verifier: str,
        redirect_uri: str,
        expected_nonce: str,
        now: datetime,
    ) -> OidcVerifiedIdentity: ...


class OidcLoginRepository(Protocol):
    """Persist one-time login state, identity links, sessions, and events atomically."""

    def save_transaction(self, transaction: OidcLoginTransaction) -> None: ...

    def find_pending(self, *, state_digest: str, active_at: datetime) -> OidcLoginTransaction | None: ...

    def resolve_actor(self, *, issuer: str, subject: str) -> str | None: ...

    def complete_login(
        self,
        transaction: OidcLoginTransaction,
        session: SessionRecord,
        event: AuthenticationEvent,
        *,
        expected_revision: int,
    ) -> None: ...

    def fail_login(
        self,
        transaction: OidcLoginTransaction,
        event: AuthenticationEvent,
        *,
        expected_revision: int,
    ) -> None: ...


class OidcLoginService:
    """Start and consume one-time OIDC authorization-code/PKCE transactions."""

    def __init__(
        self,
        policy: OidcProviderPolicy,
        repository: OidcLoginRepository,
        verifier: OidcTokenVerifier,
        browser_sessions: BrowserSessionCodec,
        *,
        clock: Callable[[], datetime],
        transaction_id_factory: Callable[[], str] = lambda: str(uuid4()),
        session_id_factory: Callable[[], str] = lambda: str(uuid4()),
        event_id_factory: Callable[[], str] = lambda: str(uuid4()),
        state_factory: Callable[[], str] = lambda: secrets.token_urlsafe(32),
        nonce_factory: Callable[[], str] = lambda: secrets.token_urlsafe(32),
        verifier_factory: Callable[[], str] = lambda: secrets.token_urlsafe(48),
    ) -> None:
        self._policy = policy
        self._repository = repository
        self._verifier = verifier
        self._browser_sessions = browser_sessions
        self._clock = clock
        self._transaction_id_factory = transaction_id_factory
        self._session_id_factory = session_id_factory
        self._event_id_factory = event_id_factory
        self._state_factory = state_factory
        self._nonce_factory = nonce_factory
        self._verifier_factory = verifier_factory

    def start(self) -> OidcLoginStart:
        now = self._clock()
        _require_aware(now, "Current time")
        state = self._state_factory()
        nonce = self._nonce_factory()
        code_verifier = self._verifier_factory()
        if not _TOKEN_PATTERN.fullmatch(state) or not _TOKEN_PATTERN.fullmatch(nonce):
            raise RuntimeError("OIDC token factories returned unsafe entropy.")
        if not _PKCE_PATTERN.fullmatch(code_verifier):
            raise RuntimeError("OIDC verifier factory returned an unsafe value.")
        transaction = OidcLoginTransaction(
            transaction_id=self._transaction_id_factory(),
            state_digest=_sha256(state),
            nonce=nonce,
            code_verifier=code_verifier,
            created_at=now,
            expires_at=now + self._policy.transaction_ttl,
        )
        self._repository.save_transaction(transaction)
        query = urlencode(
            {
                "client_id": self._policy.client_id,
                "code_challenge": _pkce_challenge(code_verifier),
                "code_challenge_method": "S256",
                "nonce": nonce,
                "redirect_uri": self._policy.redirect_uri,
                "response_type": "code",
                "scope": " ".join(self._policy.scopes),
                "state": state,
            }
        )
        return OidcLoginStart(
            authorization_url=f"{self._policy.authorization_endpoint}?{query}",
            transaction_id=transaction.transaction_id,
            expires_at=transaction.expires_at,
        )

    def complete(self, *, state: str, authorization_code: str, request_id: str) -> OidcLoginResult:
        now = self._clock()
        _require_aware(now, "Current time")
        _require_bounded(state, "OIDC state", 512)
        _require_bounded(authorization_code, "OIDC authorization code", 4096)
        _require_bounded(request_id, "Authentication request ID", 256)
        transaction = self._repository.find_pending(state_digest=_sha256(state), active_at=now)
        if transaction is None:
            raise OidcLoginError()

        try:
            identity = self._verifier.exchange_and_verify(
                authorization_code=authorization_code,
                code_verifier=transaction.code_verifier,
                redirect_uri=self._policy.redirect_uri,
                expected_nonce=transaction.nonce,
                now=now,
            )
        except OidcVerificationError as exc:
            self._fail(transaction, now=now, request_id=request_id, reason_code=exc.code)
            raise OidcLoginError() from exc

        failure = self._validate_identity(identity, transaction=transaction, now=now)
        if failure is not None:
            self._fail(transaction, now=now, request_id=request_id, reason_code=failure)
            raise OidcLoginError()
        actor_id = self._repository.resolve_actor(issuer=identity.issuer, subject=identity.subject)
        if actor_id is None:
            self._fail(transaction, now=now, request_id=request_id, reason_code="identity_not_provisioned")
            raise OidcLoginError()
        try:
            _require_uuid(actor_id, "Authentication actor ID")
            session_id = self._session_id_factory()
            _require_uuid(session_id, "Authentication session ID")
        except ValueError as exc:
            self._fail(transaction, now=now, request_id=request_id, reason_code="identity_mapping_invalid")
            raise OidcLoginError() from exc

        expires_at = min(now + self._policy.session_lifetime, identity.expires_at)
        actor = AuthenticatedActor(
            actor_id=actor_id,
            session_id=session_id,
            authenticated_at=now,
            expires_at=expires_at,
            authentication_methods=identity.authentication_methods,
        )
        session = SessionRecord(
            session_id=session_id,
            actor_id=actor_id,
            authenticated_at=now,
            expires_at=expires_at,
            status=SessionStatus.ACTIVE,
        )
        browser_session = self._browser_sessions.issue(actor, now=now)
        consumed = replace(
            transaction,
            status=OidcTransactionStatus.CONSUMED,
            revision=transaction.revision + 1,
            completed_at=now,
        )
        event = AuthenticationEvent(
            event_id=self._event_id_factory(),
            occurred_at=now,
            action="oidc.login",
            outcome="succeeded",
            reason_code="authenticated",
            request_id=request_id,
            transaction_id=transaction.transaction_id,
            actor_id=actor_id,
            session_id=session_id,
        )
        self._repository.complete_login(consumed, session, event, expected_revision=transaction.revision)
        return OidcLoginResult(actor, session, browser_session, event)

    def _validate_identity(
        self,
        identity: OidcVerifiedIdentity,
        *,
        transaction: OidcLoginTransaction,
        now: datetime,
    ) -> str | None:
        if identity.issuer != self._policy.issuer:
            return "issuer_mismatch"
        if self._policy.client_id not in identity.audience:
            return "audience_mismatch"
        if not hmac.compare_digest(identity.nonce, transaction.nonce):
            return "nonce_mismatch"
        if identity.expires_at <= now:
            return "identity_token_expired"
        if identity.authenticated_at > now + timedelta(seconds=30):
            return "authentication_time_invalid"
        if now - identity.authenticated_at > self._policy.maximum_auth_age:
            return "authentication_too_old"
        if self._policy.require_mfa and "mfa" not in identity.authentication_methods:
            return "mfa_required"
        return None

    def _fail(
        self,
        transaction: OidcLoginTransaction,
        *,
        now: datetime,
        request_id: str,
        reason_code: str,
    ) -> None:
        safe_reason = reason_code if re.fullmatch(r"[a-z0-9_]{1,64}", reason_code) else "verification_failed"
        failed = replace(
            transaction,
            status=OidcTransactionStatus.FAILED,
            revision=transaction.revision + 1,
            completed_at=now,
            failure_code=safe_reason,
        )
        event = AuthenticationEvent(
            event_id=self._event_id_factory(),
            occurred_at=now,
            action="oidc.login",
            outcome="failed",
            reason_code=safe_reason,
            request_id=request_id,
            transaction_id=transaction.transaction_id,
        )
        self._repository.fail_login(failed, event, expected_revision=transaction.revision)


class InMemoryOidcLoginRepository:
    """Deterministic adapter for transaction/replay/session tests and local composition."""

    def __init__(self, identities: Iterable[tuple[str, str, str]] = ()) -> None:
        identity_items = tuple(identities)
        self._identities = {(issuer, subject): actor_id for issuer, subject, actor_id in identity_items}
        if len(self._identities) != len(identity_items):
            raise ValueError("OIDC identity links must be unique by issuer and subject.")
        self._transactions: dict[str, OidcLoginTransaction] = {}
        self._sessions: dict[str, SessionRecord] = {}
        self._events: list[AuthenticationEvent] = []

    def save_transaction(self, transaction: OidcLoginTransaction) -> None:
        if transaction.state_digest in self._transactions:
            raise RuntimeError("OIDC state digest already exists.")
        self._transactions[transaction.state_digest] = transaction

    def find_pending(self, *, state_digest: str, active_at: datetime) -> OidcLoginTransaction | None:
        transaction = self._transactions.get(state_digest)
        if (
            transaction is None
            or transaction.status is not OidcTransactionStatus.PENDING
            or not transaction.created_at <= active_at < transaction.expires_at
        ):
            return None
        return transaction

    def resolve_actor(self, *, issuer: str, subject: str) -> str | None:
        return self._identities.get((issuer, subject))

    def complete_login(
        self,
        transaction: OidcLoginTransaction,
        session: SessionRecord,
        event: AuthenticationEvent,
        *,
        expected_revision: int,
    ) -> None:
        current = self._transactions.get(transaction.state_digest)
        if (
            current is None
            or current.status is not OidcTransactionStatus.PENDING
            or current.revision != expected_revision
        ):
            raise RuntimeError("OIDC transaction changed concurrently.")
        if transaction.status is not OidcTransactionStatus.CONSUMED:
            raise ValueError("Successful login must consume the transaction.")
        if session.session_id in self._sessions:
            raise RuntimeError("Session ID already exists.")
        if event.transaction_id != transaction.transaction_id or event.session_id != session.session_id:
            raise ValueError("Authentication event does not match the completed login.")
        self._transactions[transaction.state_digest] = transaction
        self._sessions[session.session_id] = session
        self._events.append(event)

    def fail_login(
        self,
        transaction: OidcLoginTransaction,
        event: AuthenticationEvent,
        *,
        expected_revision: int,
    ) -> None:
        current = self._transactions.get(transaction.state_digest)
        if (
            current is None
            or current.status is not OidcTransactionStatus.PENDING
            or current.revision != expected_revision
        ):
            raise RuntimeError("OIDC transaction changed concurrently.")
        if transaction.status is not OidcTransactionStatus.FAILED:
            raise ValueError("Rejected login must fail the transaction.")
        if event.transaction_id != transaction.transaction_id or event.outcome != "failed":
            raise ValueError("Authentication event does not match the rejected login.")
        self._transactions[transaction.state_digest] = transaction
        self._events.append(event)

    def find_active_session(
        self,
        *,
        session_id: str,
        actor_id: str,
        active_at: datetime,
    ) -> SessionRecord | None:
        session = self._sessions.get(session_id)
        if (
            session is None
            or session.actor_id != actor_id
            or session.status is not SessionStatus.ACTIVE
            or not session.authenticated_at <= active_at < session.expires_at
        ):
            return None
        return session

    @property
    def authentication_events(self) -> tuple[AuthenticationEvent, ...]:
        return tuple(self._events)

    @property
    def transactions(self) -> tuple[OidcLoginTransaction, ...]:
        return tuple(self._transactions.values())


def _sha256(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"


def _pkce_challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def _https_url(value: str, *, allow_query: bool) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("OIDC URL is invalid.") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.hostname in {"127.0.0.1", "::1", "localhost"}
        or parsed.username
        or parsed.password
        or parsed.fragment
        or (parsed.query and not allow_query)
        or port not in {None, 443}
    ):
        raise ValueError("OIDC URLs must be public HTTPS URLs without credentials or fragments.")
    return value


def _require_uuid(value: str, label: str) -> None:
    try:
        UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"{label} must be a UUID.") from exc


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{label} must be timezone-aware.")


def _require_bounded(value: str, label: str, maximum: int) -> None:
    if not value or value.isspace() or len(value) > maximum:
        raise ValueError(f"{label} must be a bounded non-empty value.")
