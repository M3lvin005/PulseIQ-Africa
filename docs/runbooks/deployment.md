# Deployment Runbook

## Authorized deployment

The current release may be deployed only as an isolated synthetic-data demonstration. Do not enable public real-data uploads. A real-data pilot requires written closure of SEC-001 through SEC-005 and legal/privacy approval.

The in-process demo privacy gate rejects restricted identifier columns and high-confidence contact/account patterns, but it is defense-in-depth rather than a substitute for source-system de-identification, DLP, tenancy, quarantine, and approved retention.

## Release inputs

- immutable source commit and release owner;
- green Quality and Security workflows for that commit;
- reviewed dependency diff and retained CycloneDX SBOM;
- hosting environment, owner, region, access list, URL, and expiry date;
- previous known-good immutable release identifier;
- incident contact and rollback operator.

## Pre-deployment verification

Run from a clean checkout of the release commit:

```powershell
uv lock --check
uv sync --locked --all-groups
uv export --locked --no-dev --no-emit-project --format requirements-txt --output-file requirements.txt
uv run --locked ruff check app.py src scripts tests
uv run --locked ruff format --check app.py src scripts tests
uv run --locked mypy
uv run --locked pytest -q
uv run --locked python scripts/smoke_check.py
```

Confirm the exported requirements file has no diff. Confirm the security workflow audited the same commit and uploaded `pulseiq-africa-cyclonedx-sbom`.

## Production-service preflight

The current Streamlit release must not be switched into production mode. A future authenticated API/worker deployment must run this fail-closed startup check before accepting traffic:

```powershell
uv run --locked python scripts/verify_production_config.py
```

The validator requires exact HTTPS origins, managed OIDC issuer/authorization/token/JWKS/callback configuration, independent 256-bit session/CSRF/rate-limit keys, PostgreSQL `sslmode=verify-full`, Redis TLS certificate verification, quarantine/KMS/scanner configuration, an audit-checkpoint key, and explicit privacy, security, and restore-drill references. Store secret values in an approved secret manager and inject them at runtime; never commit them. A passing structural check does not prove provider signature validation, the referenced services, or approvals—deployment smoke, negative authorization, restore, incident, and penetration-test evidence remain mandatory.

## Deploy

1. Create a new immutable release; do not mutate the prior release.
2. Install from the locked export or `uv.lock` using Python 3.12.
3. Set the entry point to `app.py` and load `.streamlit/config.toml` from the repository root.
4. Keep framework telemetry disabled, error details hidden, CORS/XSRF enabled, and uploads capped at 10 MB.
5. Put TLS and deployment-edge security headers in front of the app. Restrict access to named demo participants.
6. Do not configure customer credentials, production connectors, persistent upload storage, or an external model provider.
7. Record release ID, commit, SBOM artifact, operator, time, environment, and previous release.

## Post-deployment smoke

Use only the built-in demo data:

- Home loads and shows the non-production warning.
- Home → Upload navigation works.
- Demo load records the NGN currency and displays its synthetic source.
- Data Quality, Dashboard, Anomaly Detection, Model Insights, Reports, and Assistant render without an unhandled error.
- Model scoring still says `Manual review required` and explanation `unavailable`.
- HTML/PDF and safe CSV downloads complete.
- Browser console and platform logs contain no exception or user data.
- An oversized or non-CSV test fixture is rejected with a safe error.
- A fixture with an `email_address` or `phone_number` field is rejected without echoing the value.
- A safe CSV export drops restricted direct-identifier fields and redacts embedded contact/account patterns.

## Accept or rollback

Accept only if every smoke item passes and monitoring stays stable for the observation window chosen by the release owner. Otherwise execute [`rollback.md`](rollback.md). Preserve the failed release logs and identifiers without preserving uploaded test records.
