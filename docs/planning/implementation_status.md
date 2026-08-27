# Implementation Status

## Cycle 1 — Phase 1 truth and reproducibility

Status: **implemented and locally verified** on 2026-08-25. This is a stabilized demonstration slice, not the Phase 1 exit gate and not production approval.

### Delivered

- Python 3.12 project metadata, `uv.lock`, isolated `.venv`, locked hosting export, Ruff, strict mypy, pytest, branch coverage, and Streamlit AppTest.
- Deep `pulseiq.datasets` public seam with immutable contracts, six separately visible quality dimensions, block/warn issues, recovery actions, and capability-local readiness.
- Defense-in-depth guards on UI and direct rule/model service calls; missing critical columns no longer reach their legacy default paths.
- Deep `pulseiq.portfolio_metrics` seam with `AVAILABLE`/`UNAVAILABLE`, definition version, dataset SHA-256 reference, unit/currency, event period, quality state, numerator/denominator where relevant, and rule logic version.
- Removed Dashboard/Home claims that transaction value is revenue or binary non-default share is repayment rate.
- Version-stamped prototype anomaly outputs and rule-derived counts (`prototype-risk-rules/2.0.0`).
- Dashboard, deterministic assistant, semantic HTML report, and PDF report now consume the same governed metric snapshot.
- Empty data scores `0%`; missing or wholly invalid dependencies render `Not available` instead of zero/100%.
- Explicit upload currency confirmation; the synthetic demo alone defaults explicitly to NGN.
- Accessible textual validation states, recovery guidance, exact quality table, visible focus outline, HTML escaping, semantic HTML report, and primary teal corrected from 2.93:1 to 5.56:1 against white.

### Verification evidence

```text
uv lock --check                         pass
ruff check app.py src scripts tests     pass
mypy src/pulseiq                        pass (15 modules, strict)
pytest -q                               pass (coverage gate >=90%)
python scripts/smoke_check.py           pass (5,000-row demo workflow)
Streamlit AppTest                       empty/block/model/rule/dashboard/report/demo states pass
```

## Cycle 2 — Bounded ingestion, export safety, and CI

Status: **implemented and locally verified** on 2026-08-25.

- Immutable upload policy/result/error contracts with stable safe error codes.
- UTF-8/BOM decoding, allowed delimiter detection, binary rejection, atomic parsing, and 10 MB/100,000-row/200-column prototype limits.
- Content SHA-256 metadata and source-to-normalized header lineage; normalization collisions and empty headers are blocked.
- Conservative governed-concept suggestions remain visibly unconfirmed.
- Formula-neutralized UTF-8 CSV serialization for validation issues and flagged records.
- Read-only GitHub Actions quality workflow with commit-pinned checkout/setup actions and the local lock/lint/format/type/test/smoke gates.

## Cycle 3 — Rule evidence coverage

Status: **implemented and locally verified** on 2026-08-25.

- Seven stable rule definitions now return `triggered`, `clear`, or `not_evaluated` for each row.
- Missing or invalid row evidence is preserved rather than median-imputed.
- Per-row evaluated/non-evaluated counts, rule IDs, coverage state, ruleset version, and reviewer notes are exported.
- Rule coverage and trigger counts are separately visible in the UI, assistant answers, and HTML/PDF report.

## Cycle 4 — Governed model exploration

Status: **implemented and locally verified** on 2026-08-25. This remains an unapproved demonstration, not model validation.

- Immutable eligibility, feature-profile, issue, bundle, and run-provenance contracts.
- Only explicit versioned `defaulted`/`repayment_status` outcome mappings are accepted; unknown target rows are excluded and synthetic/single-class fallback targets are prohibited.
- Prototype minimum row/class, missingness, and categorical-cardinality guards render before training.
- Numeric/categorical treatment occurs inside scikit-learn pipelines rather than before splitting.
- Customer-group-isolated train/validation/holdout splitting where usable IDs exist; selection occurs on validation and final metrics on untouched holdout.
- Accuracy, precision, recall, F1, ROC-AUC, PR-AUC, Brier score, log loss, and confusion matrix carry run/data/target/feature/split/dependency/code lineage.
- Individual scoring is explicitly uncalibrated, routes only to manual review, and reports explanation unavailable instead of hand-written logic disconnected from the model.

## Cycle 5 — Rendered interaction and accessibility hardening

Status: **implemented and browser-verified** on 2026-08-25, with residual platform/manual checks documented separately.

- Browser checks at 320, 375, 768, 1024, and 1440 px found no horizontal overflow or clipped main content.
- Tablet/sidebar layouts wrap cards instead of truncating metric labels and values.
- Correct H1 → H2 hierarchy, non-heading sidebar brand, visible skip link/focus target, 3 px focus outline, and reduced-motion CSS.
- Repaired Home → Upload navigation through keyed widget callbacks.
- Browser uploader and parser now agree on the 10 MB limit.
- Every Plotly view has an adjacent named semantic-table alternative; compact tables use captions and explicit header scopes.
- Full rendered model eligibility → training → scoring flow passes with manual-review-only semantics.
- Evidence and honest Streamlit/assistive-technology residuals are in `accessibility_verification.md`.

## Cycle 6 — Security and supply-chain gates

Status: **implemented and locally verified** on 2026-08-25 for the synthetic-data prototype boundary. This is not production security approval.

- Separate read-only Security workflow on changes, manual dispatch, and a weekly schedule.
- Locked dependency audit (`pip-audit==2.10.1`), medium/high Python source gate (`bandit==1.9.4`), and fail-closed repository secret scan (`detect-secrets==1.5.0`).
- Reproducible, schema-validated CycloneDX 1.6 SBOM generated from the locked environment and retained for 30 days.
- All GitHub Actions pinned to immutable commits; scanners pinned to exact versions.
- Browser stack traces hidden, developer toolbar minimized, external error links and framework telemetry disabled, and CORS/XSRF explicitly enabled.
- Removed direct unused `joblib`; no model/pickle artifact loading surface exists.
- OWASP-mapped audit, severity/exception policy, responsible disclosure policy, and deployment/rollback/security-incident runbooks.
- Conditional-critical/high production blockers remain explicit: identity/tenancy/RBAC, secure persistence and upload quarantine, rate/job isolation, immutable audit telemetry, and hardened deployment infrastructure.

## Cycle 7 — Identity and workspace authorization foundation

Status: **in progress and locally verified at the domain seam** on 2026-08-25. No OIDC provider, secure-cookie/API adapter, database, or production tenant boundary is deployed.

- Canonical Actor, Organization, Workspace, Membership, Role, Permission, Portfolio Customer, and Dataset Version language in root `CONTEXT.md`.
- Provider-neutral authenticated-actor contract with session lifetime and authentication-method evidence; no custom password/JWT implementation.
- Exact organization/workspace active-membership lookup and default-deny authorization decisions.
- Seven required roles with an executable exact least-privilege permission matrix and separation between model training and approval.
- Configurable MFA policy with conservative MFA defaults for mutation-capable roles.
- Audited role-change and revocation commands with required reason/request ID, membership revision, immediate effect, before/after hashes, and an atomic persistence port.
- One-time, bounded workspace invitations with admin authorization, HMAC-bound normalized email, digest-only token persistence, verified-recipient acceptance, MFA, expiry/reissue, duplicate suppression, atomic membership activation, and replay resistance.
- Mandatory authoritative server-session lookup on every authorization decision plus audited self-logout and immediate revocation, with no permissive fallback.
- PostgreSQL 18.6 migration and pooled Psycopg adapter for organization/workspace membership, actor-scoped sessions, digest-only invitations, optimistic revisions, forced RLS, append-only per-workspace audit chaining, and transactional outbox creation.
- Adversarial live-database verification covers active RLS, cross-tenant reads/writes, actor/session isolation, invitation acceptance/reissue/overlap, domain-service transactions, audit immutability/outbox, and authorization-index planner eligibility.
- Duplicate active membership/ID, cross-workspace target, no-op/unauthorized mutation, session expiry/revocation/mismatch, invitation recipient/expiry/replay, and last-admin guards.
- Full gate: 117 tests, 91.66% branch-aware coverage, 37 strictly typed source files, and 11 live PostgreSQL integration tests.
- Detailed adapter obligations and open production work in `identity_authorization_contract.md`.

### Still required for the Phase 1 exit gate

- Reusable mapping-template lineage, validation execution/issues/overrides, typed materialization, activation, and the complete accessible mapping UI/API workflow.
- Managed OIDC and secure-cookie/CSRF integration, invitation delivery/revocation, deployed PostgreSQL operations/PITR, cross-process revocation propagation, and externally verifiable audit storage.
- Removal of legacy metric/default helpers after all remaining callers and compatibility needs are proven absent.
- Independent model validation, temporal/point-in-time leakage review, confidence intervals, calibration, threshold/cost analysis, fairness/slice evaluation, explanation validation, registry approval, and monitoring.
- Manual NVDA/VoiceOver, actual 200% zoom, axe integration, and production-shell landmark verification.
- Deployed-environment smoke/rollback exercise and dynamic security evidence once a hosting environment exists.
- Stakeholder decisions, representative source schemas, metric glossary, privacy/security review, and legal/DPIA gates.

## Current next vertical slice

Continue from the verified identity, ingestion, and mapping foundations without treating them as deployed production services:

1. implement accessible effective-quality and override API/UI presentation;
2. implement reusable mapping templates with schema compatibility checks and explicit target-version confirmation;
3. implement activation plus downstream typed Parquet materialization without training/validation leakage;
4. expose secure API contracts and accessible upload/scanning/mapping/validation UI states backed by current server sessions and CSRF controls;
5. add quotas/rate limits, retention/legal hold/deletion, queue/scanner/object-store telemetry, and operator workflows;
6. approve providers/jurisdictions, deploy a non-production environment, and prove tenant abuse, restore, incident, rollback, and accessibility controls.

## Cycle 8 — Governed dataset persistence and isolated ingestion

Status: **in progress and locally verified at the domain/database/storage/job-adapter seams** on 2026-08-25. No approved S3-compatible provider, deployed malware-scanner service, deployed Redis/Celery worker, API, or production database is deployed.

- Authorized, tenant-bound direct-upload reservation with filename-free quarantine keys, keyed filename binding, exact MIME/size/SHA-256 expectations, and bounded 5–15 minute policy lifetime.
- Trusted object-metadata completion, durable mismatch quarantine, idempotent completion replay, and reference-only scan jobs.
- PostgreSQL migration for dataset/version/job metadata with forced RLS, immutable upload expectations, optimistic revisions, globally unique job idempotency, five-attempt bound, 8 KiB payload cap, and transactional `job.queued` outbox creation.
- Pooled Psycopg repository sharing the identity adapter's validated request-scope transaction kernel; pending reservation, completion/job/audit, and quarantine/audit writes are atomic.
- Live PostgreSQL proof covers matching completion, replay returning the original job, mismatch quarantine, and absence of job/outbox work after mismatch.
- Boto3-compatible private-quarantine adapter with exact presigned-POST policy conditions, default SSE-S3, checksum-enabled HEAD, base64/hex normalization, ETag rejection, safe provider errors, and strict server-owned key shape.
- Live localhost S3-compatible proof rejects incorrect payload bytes and accepts/inspects the exact checksum-bound CSV. The archived MinIO community image is test-only and explicitly not an approved deployment dependency.
- PostgreSQL outbox and import-job lease migration with `SKIP LOCKED` claims, token-bound settlement/heartbeat, bounded payloads, retry availability, dead-letter evidence, expired-lease recovery, and five-attempt ceilings.
- Celery 5.6/Redis publisher and consumer with allowlisted queues/topics, reference-only JSON envelopes, stable outbox task IDs, no result backend, late acknowledgements, bounded publish retry, visibility/task timeouts, one-message prefetch, and duplicate-safe job claiming.
- Live PostgreSQL→dispatcher→Celery→Redis proof verifies publication acknowledgement, exclusive execution, retry/heartbeat/success, stale-token rejection, and duplicate no-op behavior.
- Bounded ClamAV INSTREAM adapter with framed 10 MiB ceiling, response/time limits, guaranteed connection closure, safe verdicts, and retryable provider-error classification.
- Scan pipeline re-verifies bytes, SHA-256, UTF-8, binary exclusion, and tenant/version-owned keys while streaming to the scanner; only a clean exact object can be promoted.
- Idempotent server-side promotion to the clean-original prefix uses SHA-256 verification and conditional creation. Normalized Parquet writes also use exact SHA-256, SSE-S3, owner binding, conditional creation, and post-write verification; production immutability still requires bucket versioning/Object Lock and IAM policy.
- Lexical CSV normalization preserves values such as leading-zero identifiers and literal empty/`N/A` cells until semantic mapping. PyArrow 25 writes deterministic Zstandard Parquet with page checksums, source/header lineage, normalized names, and normalization version metadata.
- Worker migration and repository atomically coordinate job and dataset state: `uploaded → scanning`; retries remain scanning; complete scan/promotion/normalization moves to `mapping_required`; malware/tamper outcomes quarantine; exhausted infrastructure outcomes fail.
- Immutable PostgreSQL normalized-artifact lineage records object/source/schema SHA-256, dimensions, normalization version, and exact ordered source/normalized field evidence. Worker access is insert-only and idempotent; forced RLS exposes rows only to the exact request tenant.
- Steward-only schema confirmation binds every submitted field to trusted artifact evidence and requires explicit target type, unit, currency mode/code, period, transaction direction, and time semantics. Caller-invented columns, duplicate concepts, implicit row currency, stale schema fingerprints, and unauthorized roles are rejected.
- Confirmed mapping versions/fields are immutable under forced RLS. Confirmation atomically moves `mapping_required → validating`, inserts the mapping, queues a reference-only `dataset.validate` job/outbox, and appends chained audit evidence.
- Validation re-verifies the exact object SHA-256, Parquet page checksums, embedded schema fingerprint, dimensions, mapping identity, and target-type parseability. It never imputes missing/invalid values and persists only bounded hashed examples.
- Completed run evidence is normalized across immutable run, dimension, capability, issue, affected-capability, and masked-example tables under forced RLS. Dataset settlement is capability-aware: quality-review readiness drives `ready/failed`, while dependent-purpose blocks remain visible rather than failing a usable version.
- Validation completion is replay-safe across the evidence-commit/job-ack boundary: the durable job ID is the run ID, exact persisted details are compared on retry, and job success denotes completed execution independently of the data verdict.
- Data Stewards can create only policy-approved warning overrides under `quality.override`; every acknowledgement has bounded expiry, reason, actor, request ID, before/after hashes, and an atomic chained audit event. Blocking issues remain immutable and non-overrideable.
- Override history is append-only under forced RLS. Transaction serialization and a PostgreSQL exclusion constraint prevent overlapping windows, while request replay returns the original row without duplicating audit evidence.
- The authorized effective-quality read model preserves original issue counts, excludes only currently active warning overrides, restores warnings automatically at expiry, and never lets an override suppress blocking status.
- Combined infrastructure gate: 277 tests, 1 optional S3-compatible environment skip, and 90.06% branch-aware coverage across 64 strictly typed source files. All PostgreSQL/Redis integration tests pass against disposable PostgreSQL 18.6 and Redis 8.10.1 containers; pinned dependencies have no known vulnerabilities, and Ruff, formatting, mypy, Bandit, fail-closed secret scanning, and the previously validated reproducible CycloneDX 1.6 SBOM gate pass.
- Detailed provider, worker, scanner, lifecycle, and operations obligations in `dataset_ingestion_contract.md`.

## Cycle 9 — Trust-first responsive workspace shell

Status: **implemented and browser-verified for the Streamlit prototype** on 2026-08-25. This is a high-fidelity prototype shell, not the authenticated production web client.

- Synthesized the supplied references into PulseIQ's own light cobalt decision workspace: white labeled desktop rail, pale canvas, dense governed metric surfaces, and semantic green only for healthy/approved state.
- Added the distinctive workspace trust ribbon so source, semantic meaning, quality, and the next governed action precede KPI interpretation.
- Rebuilt Overview around governed measurements, portfolio evidence, and an attention queue; unavailable evidence and warnings remain explicit.
- Replaced the rule-priority pie with a sorted horizontal bar comparison and retained the named semantic-table alternative.
- Added one native five-destination phone control bound to the same page state as the desktop rail; browser interaction proved Data routes to Upload Data.
- Browser geometry at 320, 375, 768, and 1440 px found no horizontal overflow. Mobile hides the desktop rail and redundant expand control; tablet/desktop hide the bottom control.
- Token contrast checks pass for the implemented normal-text pairs, 44px primary targets remain in place, focus/reduced-motion rules are preserved, and trust-ribbon source text is escaped.
- UI behavior coverage is 11 passing AppTest/unit checks, including shared mobile navigation and trust-ribbon injection resistance.
- The design selection, comparison wireframes, tokens, information architecture, residual accessibility work, and production-shell release gate remain explicit in the UI/UX and accessibility documents.

## Cycle 10 — Semantic themes and cross-device alignment

Status: **implemented and browser-verified for the Streamlit prototype** on 2026-08-27. Production preference persistence and framework-independent components remain part of the later web client.

- Replaced page-level colour literals with one semantic token contract covering canvas, surfaces, fields, text, borders, actions, status, charts, overlays, shadows, spacing, radius, and motion.
- Added native System, Light, and Dark appearance modes. System follows `prefers-color-scheme`; explicit choices survive Streamlit reruns and navigation within the session.
- Mapped dark surfaces and status colours independently rather than inverting the light palette. Verified normal-text contrast examples range from 7.11:1 to 14.91:1 in the dark mapping and from 5.41:1 to 14.33:1 in the light mapping.
- Made Plotly backgrounds transparent to the semantic card surface and mapped tick, title, legend, and grid styling in both themes.
- Normalized the 4 px spacing scale, adaptive page/card/hero padding, 16 px layout gaps, 44 px primary controls, and 50 px-or-taller mobile navigation targets.
- Corrected the mobile boundary to 767.98 px and browser-proved navigation handoff at both 767 and 768 px. Rendered checks at 320, 375, 767, 768, and 1440 px found zero document-level horizontal overflow and no fixed-control collision.
- Added a portable design-system contract in `design_system.md`; the production client must preserve these semantics while replacing Streamlit-specific selectors and adding durable no-flash preference persistence.
- UI behavior coverage is 15 passing AppTest/unit checks. The full locally available suite passes with 259 tests and 23 expected PostgreSQL/Redis environment skips; Ruff, formatting, mypy across 64 source files, lock integrity, Bandit, dependency audit, fail-closed secret inspection, and the 5,000-row application smoke check also pass. Cycle 8 retains the independent disposable PostgreSQL/Redis 90.06% coverage proof because Docker Desktop failed before this UI-only rerun could create any service container.

## Cycle 11 — Evidence intake and risk review workflows

Status: **implemented and browser-verified for the Streamlit prototype** on 2026-08-27. Durable schema confirmation, case assignment/disposition, and production search remain later authenticated workflows.

- Reframed Data as an evidence-intake workflow rather than a file utility: source validation, semantic/currency confirmation, quality review, and downstream use expose explicit pending/current/ready/warning/blocked language.
- Added a responsive intake surface that separates upload action from exact prototype checks and limits. Demo and sidebar loading now execute before rendering, keeping the active-source label and page evidence state consistent.
- Preserved exact issue severity, affected counts, recovery guidance, capability blocking, safe issue export, and source preview; the visual workflow does not invent an activation state that the prototype cannot govern.
- Reframed Risk as human review evidence, with an explicit non-fraud/non-decision disclaimer, the workspace trust ribbon, flagged share, high-priority count, rule coverage, and the existing chart/table alternatives.
- Added Priority, Triggered rule, and customer/transaction filters. Filters change only the review subset, announce the matching count, preserve source rule output, and export the filtered evidence.
- Browser interaction proved the High filter narrows 735 flagged demo records to the expected two. Geometry at 320, 375, and 1440 px found no document-level horizontal overflow; the intake stages and risk filters stack in source order on phone.
- Rendered inspection caught and fixed an H1→H3 heading skip and a one-render stale sidebar source. Focused UI coverage is 17 passing tests. The full locally available gate passes with 261 tests and 23 expected PostgreSQL/Redis environment skips, plus Ruff, formatting, mypy across 64 source files, lock integrity, Bandit, and the representative 5,000-row smoke check.
