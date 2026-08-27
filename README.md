# PulseIQ Africa

PulseIQ Africa is a stabilized Streamlit decision-intelligence prototype for exploring portfolio CSVs. It provides governed data-quality results, transaction/customer/outcome metrics, transparent suspicious-activity rules, demonstration model comparison, a deterministic assistant, and accessible HTML/PDF reports.

> Demonstration only. PulseIQ is not production lending infrastructure and must not be used as the sole basis for a credit or other significant decision.

## Current product boundary

The prototype validates this controlled flow:

```text
CSV or synthetic demo data
  -> bounded UTF-8 CSV validation and traceable normalized headers
  -> capability-specific validation and six quality dimensions
  -> governed metrics with unavailable states and provenance
  -> versioned prototype rules
  -> guarded model exploration
  -> evidence-linked assistant and HTML/PDF report
```

The Streamlit prototype does not connect authentication, tenancy, persistence, human decision/appeal workflows, production model governance, asynchronous workers, durable audit storage, or production observability. Tested domain and adapter seams exist for several of those controls, but they are not deployed services. See [`docs/planning/README.md`](docs/planning/README.md) for the production blueprint and requirements.

## What it does

- **Dataset assessment:** separately scores completeness, validity, uniqueness, consistency, timeliness, and fitness; blocking issues override the composite score.
- **Capability guards:** transaction, customer, outcome, rule, and model paths stop when required inputs are absent or wholly invalid.
- **Governed metrics:** every value carries status, unit/currency, period, quality, definition version, dataset hash, and recovery guidance. Transaction value is not labelled revenue; row outcome share is not labelled repayment rate.
- **Bounded, privacy-gated ingestion:** uploads are limited to 10 MB, 100,000 rows, and 200 columns; encoding, delimiter, extension, binary content, parsing, empty headers, normalized-header collisions, restricted identifier columns, and high-confidence contact/account patterns receive safe error codes and recovery guidance. Demo exports drop restricted identifier columns and redact detected values.
- **Transparent rules:** `prototype-risk-rules/2.0.0` records triggered, clear, or `not_evaluated` status per rule and row; missing evidence is never median-imputed into a clear rule result.
- **Model exploration:** a governed eligibility seam requires explicit allowlisted outcomes, sufficient rows/classes, bounded missingness/cardinality, and complete feature mappings. Candidates are selected on validation data and reported on a separate holdout; scores are visibly unapproved and uncalibrated.
- **Reporting and assistant:** both consume the same governed metric snapshot. Semantic HTML is the primary accessible report; PDF is secondary.
- **Production identity seam:** provider-neutral contracts define authoritative server sessions, current-membership RBAC, MFA, audited role/revocation administration, and secure one-time workspace invitations. OIDC authorization-code orchestration now uses one-time state/nonce, PKCE S256, replay consumption, exact issuer/audience/nonce/time/MFA checks, pre-provisioned subject mapping, atomic session/event creation, and signed `__Host-` secure cookies with CSRF/exact-origin enforcement and key rotation. PostgreSQL/RLS persistence exists locally; the cryptographic provider/token-exchange adapter, API composition, deployed database, and Streamlit integration remain open.
- **Governed upload seam:** authorized direct-upload reservations bind a tenant/version quarantine key to exact type, bytes, and SHA-256; completion is idempotent, mismatches are durably quarantined, and scan jobs carry references only. PostgreSQL/RLS metadata exists locally, but S3, scanning, Celery/Redis, API, and UI adapters remain undeployed.
- **Production edge seam:** exact-origin credentialed CORS, nonce CSP/security headers, privacy-preserving rate-limit keys, atomic Redis sliding windows, and a fail-closed production configuration validator are implemented and tested. Deployment and operational acceptance remain mandatory.

## Toolchain

| Need | Choice |
|---|---|
| Runtime | Python 3.12 |
| Environment/lock | uv + `pyproject.toml` + `uv.lock` |
| Web | Streamlit |
| Data/charts | pandas, NumPy, Plotly |
| Demonstration ML | scikit-learn |
| PDF | ReportLab |
| Quality gates | pytest, pytest-cov, Hypothesis, Ruff, strict mypy, Streamlit AppTest |
| Security gates | pip-audit, Bandit, detect-secrets, CycloneDX SBOM, commit-pinned GitHub Actions |

## Run locally

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run:

```powershell
uv sync --locked
uv run python scripts/generate_demo_data.py
uv run streamlit run app.py
```

The app opens at `http://localhost:8501`. The built-in synthetic dataset has an explicitly confirmed `NGN` currency. Uploaded datasets begin with currency unconfirmed, so financial metrics remain unavailable until the user confirms it.

Run the complete local verification cycle:

```powershell
uv lock --check
uv run ruff check app.py src scripts tests
uv run ruff format --check app.py src scripts tests
uv run mypy
uv run pytest -q
uv run python scripts/smoke_check.py
```

A future production service must also run `uv run python scripts/verify_production_config.py` at startup. It fails closed unless managed OIDC, exact HTTPS origins, independent session/CSRF/rate-limit keys, PostgreSQL and Redis TLS verification, quarantine/scanner/KMS configuration, audit checkpointing, privacy/security approvals, and a restore-drill reference are present. Structural validation does not replace deployment testing or sign-off.

`requirements.txt` is an exported, locked compatibility file for hosts that do not install from `pyproject.toml`; `uv.lock` remains the source of truth.

The Security workflow performs a weekly and change-triggered dependency, source, and secret scan and retains a validated CycloneDX SBOM. See [`SECURITY.md`](SECURITY.md), the [security audit](docs/planning/security_audit_2026-08-25.md), and [operational runbooks](docs/runbooks/README.md).

## Canonical prototype fields

Headers are normalized to snake case only after bounded parsing and collision checks. The UI shows conservative concept suggestions, but a column's name or presence does not confirm its business meaning.

| Capability | Required canonical inputs |
|---|---|
| Transaction metrics | `transaction_amount`, `date`, plus one confirmed currency |
| Customer metrics | `customer_id` |
| Outcome share | canonical binary `defaulted` |
| Prototype rules | `transaction_amount`, `income`, `loan_amount`, `existing_debt`, `repayment_history_score`, `transaction_frequency` |
| Model exploration | `income`, `loan_amount`, `repayment_history_score`, `existing_debt`, `transaction_frequency`, `account_age_months`, `employment_status`, `segment`, `business_type`, `region`, plus `defaulted` or `repayment_status` |

Uploads still need a persistent confirmation workflow for units, periods, business keys, amount direction, time semantics, and reusable mapping versions. Do not treat suggestions or header normalization as authoritative semantic mapping.

## Deployment boundary

The prototype can be deployed to Streamlit-compatible hosting with `app.py` as the entrypoint and `requirements.txt` as the compatibility dependency file. Use synthetic data only. Production deployment is intentionally blocked on the identity, tenant isolation, storage, audit, privacy, job, accessibility, security, and governance controls in the planning pack.

## Known limitations

- Single-session Streamlit prototype; the tested identity, secure-cookie, RLS, storage, worker, rate-limit, and audit seams are not composed into its request path or deployed infrastructure.
- Identity-domain scaffolding does not make the Streamlit prototype authenticated or multi-tenant; real-data use remains prohibited until the adapters and defense-in-depth controls in `docs/planning/identity_authorization_contract.md` are deployed and tested.
- Prototype rules are hard-coded and not yet stored in an approval/rollback workflow.
- Model comparison now isolates customer groups across train/validation/holdout when usable IDs exist, but still lacks temporal validation, confidence intervals, calibration, fairness/slice review, drift monitoring, registry approval, and human decision workflows.
- Uploaded files are bounded, privacy-gated, and parsed in-process but do not yet use the production object-storage, content-signature, malware-scanning, or quarantine adapters.
- Rendered responsive, heading, focus, skip-link, chart-table, and model-flow checks are recorded in `docs/planning/accessibility_verification.md`; NVDA/VoiceOver, actual 200% zoom, axe integration, and Streamlit landmark acceptance remain open.
- Jurisdiction, residency, DPIA, responsible-lending policy, metric glossary, and stakeholder ADR acceptance remain open decision gates.
- Internet-facing real-data use remains blocked on managed OIDC/API composition, deployed tenant-isolated persistence and upload quarantine, worker/rate-limit operation, immutable audit telemetry, hardened infrastructure, and external privacy/security/restore acceptance.

## Author

Jomilojuoluwa Melvin Salami — [GitHub](https://github.com/M3lvin005) · [LinkedIn](https://linkedin.com/in/jomilojuoluwa-salami-493209227)
