"""Production configuration gate tests."""

from __future__ import annotations

import base64

import pytest

from pulseiq.production_config import ProductionConfigurationError, load_production_security_config


def _secret(character: bytes) -> str:
    return base64.urlsafe_b64encode(character * 32).rstrip(b"=").decode("ascii")


def _environment() -> dict[str, str]:
    return {
        "PULSEIQ_ENVIRONMENT": "production",
        "PULSEIQ_APP_ORIGIN": "https://app.pulseiq.africa",
        "PULSEIQ_ALLOWED_ORIGINS": "https://app.pulseiq.africa,https://admin.pulseiq.africa",
        "PULSEIQ_OIDC_ISSUER": "https://identity.example.com/tenant/v2.0",
        "PULSEIQ_OIDC_AUTHORIZATION_ENDPOINT": "https://identity.example.com/oauth2/authorize",
        "PULSEIQ_OIDC_TOKEN_ENDPOINT": "https://identity.example.com/oauth2/token",
        "PULSEIQ_OIDC_JWKS_URI": "https://identity.example.com/.well-known/jwks.json",
        "PULSEIQ_OIDC_CLIENT_ID": "pulseiq-production",
        "PULSEIQ_OIDC_REDIRECT_URI": "https://app.pulseiq.africa/auth/callback",
        "PULSEIQ_SESSION_KEY_ID": "2026-08",
        "PULSEIQ_SESSION_SIGNING_KEY_B64": _secret(b"s"),
        "PULSEIQ_CSRF_KEY_B64": _secret(b"c"),
        "PULSEIQ_RATE_LIMIT_PEPPER_B64": _secret(b"p"),
        "PULSEIQ_DATABASE_URL": "postgresql://pulseiq@db.internal/pulseiq?sslmode=verify-full",
        "PULSEIQ_REDIS_URL": "rediss://redis.internal:6380/0?ssl_cert_reqs=required",
        "PULSEIQ_QUARANTINE_BUCKET": "pulseiq-production-quarantine",
        "PULSEIQ_KMS_KEY_ARN": "arn:aws:kms:eu-west-1:123456789012:key/example",
        "PULSEIQ_MALWARE_SCANNER_ENDPOINT": "https://scanner.internal.example.com/v1/scan",
        "PULSEIQ_AUDIT_CHECKPOINT_KEY_ARN": "arn:aws:kms:eu-west-1:123456789012:key/audit",
        "PULSEIQ_PRIVACY_ACCEPTANCE_REFERENCE": "privacy/DPIA-2026-001",
        "PULSEIQ_SECURITY_ACCEPTANCE_REFERENCE": "security/PEN-2026-001",
        "PULSEIQ_RESTORE_DRILL_REFERENCE": "ops/RESTORE-2026-001",
    }


def test_valid_config_builds_secret_safe_runtime_contracts() -> None:
    config = load_production_security_config(_environment())

    assert config.app_origin == "https://app.pulseiq.africa"
    assert config.browser_session_key().key_id == "2026-08"
    assert config.browser_session_policy().allowed_origins == frozenset(
        {"https://app.pulseiq.africa", "https://admin.pulseiq.africa"}
    )
    assert config.oidc_provider_policy().token_endpoint == "https://identity.example.com/oauth2/token"
    rendered = repr(config)
    for secret_name in (
        "session_signing_key",
        "csrf_key",
        "rate_limit_pepper",
        "database_url",
        "redis_url",
    ):
        assert secret_name not in rendered
    assert "postgresql://" not in rendered
    assert "rediss://" not in rendered


def test_missing_values_fail_together_without_exposing_other_values() -> None:
    environment = _environment()
    environment.pop("PULSEIQ_OIDC_CLIENT_ID")
    environment.pop("PULSEIQ_CSRF_KEY_B64")

    with pytest.raises(ProductionConfigurationError) as error:
        load_production_security_config(environment)

    assert error.value.invalid_fields == ("PULSEIQ_CSRF_KEY_B64", "PULSEIQ_OIDC_CLIENT_ID")
    assert "identity.example.com" not in str(error.value)
    assert _environment()["PULSEIQ_SESSION_SIGNING_KEY_B64"] not in str(error.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("PULSEIQ_ENVIRONMENT", "staging"),
        ("PULSEIQ_APP_ORIGIN", "http://app.pulseiq.africa"),
        ("PULSEIQ_ALLOWED_ORIGINS", "https://app.pulseiq.africa.evil.example"),
        ("PULSEIQ_OIDC_ISSUER", "http://identity.example.com"),
        ("PULSEIQ_OIDC_TOKEN_ENDPOINT", "https://evil.example.com/token"),
        ("PULSEIQ_OIDC_REDIRECT_URI", "https://app.pulseiq.africa/wrong-callback"),
        ("PULSEIQ_SESSION_SIGNING_KEY_B64", "short"),
        ("PULSEIQ_DATABASE_URL", "postgresql://localhost/pulseiq?sslmode=disable"),
        ("PULSEIQ_DATABASE_URL", "postgresql://db.internal/pulseiq?sslmode=require"),
        ("PULSEIQ_REDIS_URL", "redis://redis.internal:6379/0"),
        ("PULSEIQ_MALWARE_SCANNER_ENDPOINT", "http://scanner.internal/scan"),
        ("PULSEIQ_PRIVACY_ACCEPTANCE_REFERENCE", "bad reference with spaces"),
    ],
)
def test_each_unsafe_production_setting_fails_closed(field: str, value: str) -> None:
    environment = _environment()
    environment[field] = value

    with pytest.raises(ProductionConfigurationError) as error:
        load_production_security_config(environment)

    assert field in error.value.invalid_fields


def test_reused_key_material_is_rejected_for_domain_separation() -> None:
    environment = _environment()
    environment["PULSEIQ_CSRF_KEY_B64"] = environment["PULSEIQ_SESSION_SIGNING_KEY_B64"]

    with pytest.raises(ProductionConfigurationError) as error:
        load_production_security_config(environment)

    assert "PULSEIQ_SESSION_SIGNING_KEY_B64" in error.value.invalid_fields
    assert "PULSEIQ_CSRF_KEY_B64" in error.value.invalid_fields


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("PULSEIQ_APP_ORIGIN", "https://app.pulseiq.africa/"),
        ("PULSEIQ_OIDC_CLIENT_ID", "x" * 257),
        ("PULSEIQ_SESSION_KEY_ID", "invalid key id"),
        ("PULSEIQ_CSRF_KEY_B64", "***not-base64***"),
        ("PULSEIQ_RATE_LIMIT_PEPPER_B64", base64.urlsafe_b64encode(b"short").decode()),
        ("PULSEIQ_OIDC_ISSUER", "https://identity.example.com:bad"),
        ("PULSEIQ_DATABASE_URL", "postgresql://db.internal:bad/pulseiq?sslmode=verify-full"),
        ("PULSEIQ_REDIS_URL", "rediss://redis.internal:bad/0?ssl_cert_reqs=required"),
    ],
)
def test_additional_malformed_values_fail_closed(field: str, value: str) -> None:
    environment = _environment()
    environment[field] = value

    with pytest.raises(ProductionConfigurationError) as error:
        load_production_security_config(environment)

    assert field in error.value.invalid_fields


def test_allowed_origins_must_include_app_and_must_not_repeat() -> None:
    missing_app = _environment()
    missing_app["PULSEIQ_ALLOWED_ORIGINS"] = "https://admin.pulseiq.africa"
    with pytest.raises(ProductionConfigurationError) as absent:
        load_production_security_config(missing_app)
    assert "PULSEIQ_ALLOWED_ORIGINS" in absent.value.invalid_fields

    duplicate = _environment()
    duplicate["PULSEIQ_ALLOWED_ORIGINS"] = "https://app.pulseiq.africa,https://app.pulseiq.africa"
    with pytest.raises(ProductionConfigurationError) as repeated:
        load_production_security_config(duplicate)
    assert "PULSEIQ_ALLOWED_ORIGINS" in repeated.value.invalid_fields


def test_empty_origin_fields_are_reported_without_parser_errors() -> None:
    environment = _environment()
    environment["PULSEIQ_APP_ORIGIN"] = ""
    environment["PULSEIQ_ALLOWED_ORIGINS"] = ""

    with pytest.raises(ProductionConfigurationError) as error:
        load_production_security_config(environment)

    assert "PULSEIQ_APP_ORIGIN" in error.value.invalid_fields
    assert "PULSEIQ_ALLOWED_ORIGINS" in error.value.invalid_fields
