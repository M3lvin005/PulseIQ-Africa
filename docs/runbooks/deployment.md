# Deployment Runbook

## Authorized deployment

The current release may be deployed only as an isolated synthetic-data demonstration. Do not enable public real-data uploads. A real-data pilot requires written closure of SEC-001 through SEC-005 and legal/privacy approval.

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

## Accept or rollback

Accept only if every smoke item passes and monitoring stays stable for the observation window chosen by the release owner. Otherwise execute [`rollback.md`](rollback.md). Preserve the failed release logs and identifiers without preserving uploaded test records.
