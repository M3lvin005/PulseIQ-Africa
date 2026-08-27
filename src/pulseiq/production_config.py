"""Executable fail-closed configuration gate for a future production service."""

from __future__ import annotations

import base64
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit

from .http_security import canonical_origin
from .identity import BrowserSessionKey, BrowserSessionPolicy, OidcProviderPolicy

_REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{2,127}$")
_KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class ProductionConfigurationError(RuntimeError):
    """Safe configuration failure containing field names but never secret values."""

    def __init__(self, invalid_fields: tuple[str, ...]) -> None:
        ordered = tuple(sorted(set(invalid_fields)))
        self.invalid_fields = ordered
        super().__init__(f"Production security configuration is incomplete or invalid: {', '.join(ordered)}")


@dataclass(frozen=True, slots=True)
class ProductionSecurityConfig:
    """Validated production settings; secret-bearing fields are hidden from repr."""

    app_origin: str
    allowed_origins: frozenset[str]
    oidc_issuer: str
    oidc_authorization_endpoint: str
    oidc_token_endpoint: str
    oidc_jwks_uri: str
    oidc_client_id: str
    oidc_redirect_uri: str
    session_key_id: str
    session_signing_key: bytes = field(repr=False)
    csrf_key: bytes = field(repr=False)
    rate_limit_pepper: bytes = field(repr=False)
    database_url: str = field(repr=False)
    redis_url: str = field(repr=False)
    quarantine_bucket: str
    kms_key_arn: str
    malware_scanner_endpoint: str
    audit_checkpoint_key_arn: str
    privacy_acceptance_reference: str
    security_acceptance_reference: str
    restore_drill_reference: str

    def browser_session_key(self) -> BrowserSessionKey:
        return BrowserSessionKey(self.session_key_id, self.session_signing_key, self.csrf_key)

    def browser_session_policy(self) -> BrowserSessionPolicy:
        return BrowserSessionPolicy(allowed_origins=self.allowed_origins)

    def oidc_provider_policy(self) -> OidcProviderPolicy:
        return OidcProviderPolicy(
            issuer=self.oidc_issuer,
            authorization_endpoint=self.oidc_authorization_endpoint,
            token_endpoint=self.oidc_token_endpoint,
            jwks_uri=self.oidc_jwks_uri,
            client_id=self.oidc_client_id,
            redirect_uri=self.oidc_redirect_uri,
        )


def load_production_security_config(environment: Mapping[str, str]) -> ProductionSecurityConfig:
    """Validate all launch-critical settings together and report safe field names."""

    invalid: list[str] = []

    def required(name: str) -> str:
        value = environment.get(name, "").strip()
        if not value:
            invalid.append(name)
        return value

    if environment.get("PULSEIQ_ENVIRONMENT", "").strip() != "production":
        invalid.append("PULSEIQ_ENVIRONMENT")

    app_origin = _validate_origin(required("PULSEIQ_APP_ORIGIN"), "PULSEIQ_APP_ORIGIN", invalid)
    allowed_origins = _validate_origins(
        required("PULSEIQ_ALLOWED_ORIGINS"),
        "PULSEIQ_ALLOWED_ORIGINS",
        invalid,
    )
    if app_origin and app_origin not in allowed_origins:
        invalid.append("PULSEIQ_ALLOWED_ORIGINS")

    oidc_issuer = required("PULSEIQ_OIDC_ISSUER")
    if oidc_issuer and not _valid_https_url(oidc_issuer):
        invalid.append("PULSEIQ_OIDC_ISSUER")
    oidc_authorization_endpoint = required("PULSEIQ_OIDC_AUTHORIZATION_ENDPOINT")
    if oidc_authorization_endpoint and not _valid_https_url(oidc_authorization_endpoint):
        invalid.append("PULSEIQ_OIDC_AUTHORIZATION_ENDPOINT")
    oidc_token_endpoint = required("PULSEIQ_OIDC_TOKEN_ENDPOINT")
    if oidc_token_endpoint and not _valid_https_url(oidc_token_endpoint):
        invalid.append("PULSEIQ_OIDC_TOKEN_ENDPOINT")
    oidc_jwks_uri = required("PULSEIQ_OIDC_JWKS_URI")
    if oidc_jwks_uri and not _valid_https_url(oidc_jwks_uri):
        invalid.append("PULSEIQ_OIDC_JWKS_URI")
    oidc_client_id = required("PULSEIQ_OIDC_CLIENT_ID")
    if oidc_client_id and len(oidc_client_id) > 256:
        invalid.append("PULSEIQ_OIDC_CLIENT_ID")
    oidc_redirect_uri = required("PULSEIQ_OIDC_REDIRECT_URI")
    if oidc_redirect_uri and not _valid_https_url(oidc_redirect_uri):
        invalid.append("PULSEIQ_OIDC_REDIRECT_URI")
    if oidc_redirect_uri and app_origin and oidc_redirect_uri != f"{app_origin}/auth/callback":
        invalid.append("PULSEIQ_OIDC_REDIRECT_URI")
    provider_urls = tuple(
        item
        for item in (
            oidc_issuer,
            oidc_authorization_endpoint,
            oidc_token_endpoint,
            oidc_jwks_uri,
        )
        if item and _valid_https_url(item)
    )
    if provider_urls and len({urlsplit(item).hostname for item in provider_urls}) != 1:
        invalid.extend(
            (
                "PULSEIQ_OIDC_AUTHORIZATION_ENDPOINT",
                "PULSEIQ_OIDC_TOKEN_ENDPOINT",
                "PULSEIQ_OIDC_JWKS_URI",
            )
        )

    session_key_id = required("PULSEIQ_SESSION_KEY_ID")
    if session_key_id and not _KEY_ID_PATTERN.fullmatch(session_key_id):
        invalid.append("PULSEIQ_SESSION_KEY_ID")
    session_signing_key = _decode_secret(
        required("PULSEIQ_SESSION_SIGNING_KEY_B64"),
        "PULSEIQ_SESSION_SIGNING_KEY_B64",
        invalid,
    )
    csrf_key = _decode_secret(required("PULSEIQ_CSRF_KEY_B64"), "PULSEIQ_CSRF_KEY_B64", invalid)
    rate_limit_pepper = _decode_secret(
        required("PULSEIQ_RATE_LIMIT_PEPPER_B64"),
        "PULSEIQ_RATE_LIMIT_PEPPER_B64",
        invalid,
    )
    nonempty_secrets = [item for item in (session_signing_key, csrf_key, rate_limit_pepper) if item]
    if len(set(nonempty_secrets)) != len(nonempty_secrets):
        invalid.extend(
            (
                "PULSEIQ_SESSION_SIGNING_KEY_B64",
                "PULSEIQ_CSRF_KEY_B64",
                "PULSEIQ_RATE_LIMIT_PEPPER_B64",
            )
        )

    database_url = required("PULSEIQ_DATABASE_URL")
    if database_url and not _valid_postgres_url(database_url):
        invalid.append("PULSEIQ_DATABASE_URL")
    redis_url = required("PULSEIQ_REDIS_URL")
    if redis_url and not _valid_redis_url(redis_url):
        invalid.append("PULSEIQ_REDIS_URL")

    quarantine_bucket = _validate_reference(
        required("PULSEIQ_QUARANTINE_BUCKET"),
        "PULSEIQ_QUARANTINE_BUCKET",
        invalid,
    )
    kms_key_arn = _validate_reference(required("PULSEIQ_KMS_KEY_ARN"), "PULSEIQ_KMS_KEY_ARN", invalid)
    malware_scanner_endpoint = required("PULSEIQ_MALWARE_SCANNER_ENDPOINT")
    if malware_scanner_endpoint and not _valid_https_url(malware_scanner_endpoint):
        invalid.append("PULSEIQ_MALWARE_SCANNER_ENDPOINT")
    audit_checkpoint_key_arn = _validate_reference(
        required("PULSEIQ_AUDIT_CHECKPOINT_KEY_ARN"),
        "PULSEIQ_AUDIT_CHECKPOINT_KEY_ARN",
        invalid,
    )
    privacy_acceptance_reference = _validate_reference(
        required("PULSEIQ_PRIVACY_ACCEPTANCE_REFERENCE"),
        "PULSEIQ_PRIVACY_ACCEPTANCE_REFERENCE",
        invalid,
    )
    security_acceptance_reference = _validate_reference(
        required("PULSEIQ_SECURITY_ACCEPTANCE_REFERENCE"),
        "PULSEIQ_SECURITY_ACCEPTANCE_REFERENCE",
        invalid,
    )
    restore_drill_reference = _validate_reference(
        required("PULSEIQ_RESTORE_DRILL_REFERENCE"),
        "PULSEIQ_RESTORE_DRILL_REFERENCE",
        invalid,
    )

    if invalid:
        raise ProductionConfigurationError(tuple(invalid))
    return ProductionSecurityConfig(
        app_origin=app_origin,
        allowed_origins=allowed_origins,
        oidc_issuer=oidc_issuer,
        oidc_authorization_endpoint=oidc_authorization_endpoint,
        oidc_token_endpoint=oidc_token_endpoint,
        oidc_jwks_uri=oidc_jwks_uri,
        oidc_client_id=oidc_client_id,
        oidc_redirect_uri=oidc_redirect_uri,
        session_key_id=session_key_id,
        session_signing_key=session_signing_key,
        csrf_key=csrf_key,
        rate_limit_pepper=rate_limit_pepper,
        database_url=database_url,
        redis_url=redis_url,
        quarantine_bucket=quarantine_bucket,
        kms_key_arn=kms_key_arn,
        malware_scanner_endpoint=malware_scanner_endpoint,
        audit_checkpoint_key_arn=audit_checkpoint_key_arn,
        privacy_acceptance_reference=privacy_acceptance_reference,
        security_acceptance_reference=security_acceptance_reference,
        restore_drill_reference=restore_drill_reference,
    )


def _validate_origin(value: str, name: str, invalid: list[str]) -> str:
    if not value:
        return ""
    try:
        canonical = canonical_origin(value)
    except ValueError:
        invalid.append(name)
        return ""
    if canonical != value or not canonical.startswith("https://"):
        invalid.append(name)
        return ""
    return canonical


def _validate_origins(value: str, name: str, invalid: list[str]) -> frozenset[str]:
    if not value:
        return frozenset()
    items = tuple(item.strip() for item in value.split(",") if item.strip())
    if not items:
        invalid.append(name)
        return frozenset()
    canonical_items: list[str] = []
    for item in items:
        canonical = _validate_origin(item, name, invalid)
        if canonical:
            canonical_items.append(canonical)
    if len(set(canonical_items)) != len(canonical_items):
        invalid.append(name)
    return frozenset(canonical_items)


def _decode_secret(value: str, name: str, invalid: list[str]) -> bytes:
    if not value:
        return b""
    try:
        padding = "=" * (-len(value) % 4)
        decoded = base64.b64decode(value + padding, altchars=b"-_", validate=True)
    except ValueError:
        invalid.append(name)
        return b""
    if len(decoded) < 32:
        invalid.append(name)
        return b""
    return decoded


def _valid_https_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme != "https" or not parsed.hostname or parsed.hostname in _LOCAL_HOSTS:
        return False
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return False
    return port in {None, 443}


def _valid_postgres_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        port = parsed.port
        query = parse_qs(parsed.query, keep_blank_values=True)
    except ValueError:
        return False
    return bool(
        parsed.scheme in {"postgres", "postgresql"}
        and parsed.hostname
        and parsed.hostname not in _LOCAL_HOSTS
        and (port is None or port >= 1)
        and query.get("sslmode") == ["verify-full"]
    )


def _valid_redis_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        port = parsed.port
        query = parse_qs(parsed.query, keep_blank_values=True)
    except ValueError:
        return False
    return bool(
        parsed.scheme == "rediss"
        and parsed.hostname
        and parsed.hostname not in _LOCAL_HOSTS
        and (port is None or port >= 1)
        and query.get("ssl_cert_reqs") == ["required"]
    )


def _validate_reference(value: str, name: str, invalid: list[str]) -> str:
    if value and not _REFERENCE_PATTERN.fullmatch(value):
        invalid.append(name)
        return ""
    return value
