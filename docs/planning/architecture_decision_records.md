# PulseIQ Africa Architecture Decision Records

All records are **Proposed** until stakeholder review. They document planning decisions, alternatives, consequences, and validation gates.

## ADR-001: Use a staged architecture rather than immediately replacing Streamlit

### Status

Accepted for the current product shell on 2026-08-25

### Context

The existing Streamlit code is useful for validating domain language and transparent calculations but lacks production identity, persistence, workflows, accessibility control, asynchronous processing, and operational safeguards. A full rewrite before user/data validation risks encoding the wrong product.

### Decision

Stabilize the Streamlit prototype for safe demonstrations and research while building the production workspace only after launch-market, persona, data contract, and workflow decisions are accepted.

### Consequences

- Positive: preserves learning speed; creates a trustworthy demo; reduces premature architecture work.
- Negative: temporary dual-track cost; code is not expected to migrate mechanically.
- Neutral: shared pure Python domain logic can be extracted where contracts are valid.

### Alternatives considered

- Keep Streamlit for production: rejected because critical multi-user, authorization, workflow, accessibility, and job requirements are awkward or unsafe.
- Rewrite immediately: rejected until product/data decisions are validated.

## ADR-002: Use a modular monolith for the production backend

### Status

Proposed

### Context

The domain includes datasets, risk, models, decisions, reports, and governance, but the team, scale, and bounded contexts are not proven.

### Decision

Use one FastAPI deployment organized into enforced domain modules, plus separate worker processes from the same codebase.

### Consequences

- Positive: transactional consistency, simpler deployment/debugging, lower cost, easier boundary changes.
- Negative: independent module scaling/deployment is limited.
- Neutral: modules may later be extracted when ownership or load demonstrates the need.

### Alternatives considered

- Microservices: rejected for premature distributed-system complexity.
- Single unstructured script/service: rejected because current coupling already obscures semantics.

## ADR-003: Use PostgreSQL for transactional metadata and object storage/Parquet for files and analytical artifacts

### Status

Proposed

### Context

PulseIQ needs ACID workflow state, relationships, audit references, tenant controls, large immutable uploads, normalized data, reports, and model artifacts.

### Decision

Use managed PostgreSQL for domain state and row-level security; use S3-compatible object storage for original uploads, normalized Parquet, reports, and model artifacts. Query Parquet with Polars/DuckDB for medium analytical workloads.

### Consequences

- Positive: strong integrity and query capability; low-cost scalable artifacts; avoids stuffing files into DB.
- Negative: cross-store consistency requires idempotent jobs and artifact status records.
- Neutral: a warehouse can be added only after cross-workspace analytical demand is measured.

### Alternatives considered

- MongoDB: rejected because core relationships/workflows are strongly relational.
- Store DataFrames/files in PostgreSQL: rejected for cost and analytical/file-management friction.
- Warehouse from day one: rejected for cost and operational overhead.

## ADR-004: Run imports, analytics, model training, batch scoring, and reports asynchronously

### Status

Proposed

### Context

The current app performs all work synchronously during UI reruns. Production uploads and training can exceed web-request timeouts and require retry/cancel/progress.

### Decision

Use a durable queue with Redis/Celery initially, explicit job records, heartbeats, idempotency keys, bounded retries, cancellation, and dead-letter handling. Small non-critical post-response work may use framework background tasks.

### Consequences

- Positive: responsive API, horizontal workers, retries, progress, failure isolation.
- Negative: queue/worker operations and eventual completion semantics.
- Neutral: the queue provider can be swapped behind an application interface.

### Alternatives considered

- FastAPI in-process BackgroundTasks for all jobs: rejected for heavy multi-process/server work; official FastAPI guidance points to larger queue tools for heavy computation.
- Kafka: rejected because event-stream scale/replay is not yet required.

## ADR-005: Separate rules, models, policy, and human decisions

### Status

Proposed

### Context

The current UI uses overlapping `risk_level` terms for stored demo risk, anomaly severity, and model probability. Scoring reasons are independent hand-coded rules, not fitted-model explanations.

### Decision

Store and present four explicit layers: rule evaluations/alerts, model predictions, deterministic policy evaluations, and immutable human final decisions. Each layer has its own version, owner, explanation, and audit event.

### Consequences

- Positive: clarity, contestability, model/rule replacement, accurate explanation, regulatory evidence.
- Negative: more entities and UI complexity.
- Neutral: aggregate views may summarize layers but cannot erase provenance.

### Alternatives considered

- Single combined “risk score”: rejected because it hides source and accountability.
- Model-only decisions: rejected for safety, responsible lending, and automated-decision rights.

## ADR-006: Make data, definition, rule, feature, model, threshold, decision, and report artifacts immutable and versioned

### Status

Proposed

### Context

Reviewers and auditors must reconstruct an outcome even after data, rules, or models change.

### Decision

Use immutable dataset versions and feature snapshots; version metric definitions, rulesets, models, thresholds, policies, decisions, reports, and notices. New information creates a new version linked to its predecessor.

### Consequences

- Positive: reproducibility, rollback, audit, defensible reports.
- Negative: storage growth and more explicit lifecycle/retention handling.
- Neutral: authorized erasure may tombstone/delete personal artifacts while retaining lawful non-identifying audit evidence.

### Alternatives considered

- Mutable “latest” rows only: rejected because historical results become unreproducible.
- Full event sourcing: deferred; useful immutability can be achieved without event-sourcing every domain.

## ADR-007: Use managed OIDC, application RBAC, and PostgreSQL row-level security

### Status

Proposed

### Context

Financial and personal data requires strong identity and tenant isolation. Custom password/auth implementation increases risk.

### Decision

Use a managed OIDC provider initially, secure server sessions, workspace RBAC, service-level authorization, and PostgreSQL RLS as defense in depth. Require MFA for privileged roles and separate model/risk approval duties.

### Consequences

- Positive: mature authentication, least privilege, layered tenant control.
- Negative: provider cost/dependency and careful RLS testing.
- Neutral: use a provider adapter and revisit self-hosted identity only for residency/procurement needs.

### Alternatives considered

- Custom auth: rejected for security and maintenance risk.
- RBAC only in UI/API: rejected because DB-level defense reduces cross-tenant blast radius.

## ADR-008: Separate product analytics from business/model data and operational telemetry

### Status

Proposed

### Context

The application needs adoption measurement, customer-owned business analytics, ML monitoring, and system observability. Mixing them risks PII leakage and misleading metrics.

### Decision

Use a privacy-reviewed product event schema with pseudonymous IDs and allowlisted properties; keep portfolio/model/decision facts in governed domain stores; use OpenTelemetry and an operational backend for logs/metrics/traces. Disable raw session replay by default.

### Consequences

- Positive: privacy boundaries, reliable business truth, vendor portability, useful operations.
- Negative: multiple pipelines and governance responsibilities.
- Neutral: one vendor may receive multiple telemetry types only if contracts, residency, access, and schemas preserve separation.

### Alternatives considered

- Send all data to a product analytics vendor: rejected for privacy and semantic integrity.
- No product analytics: rejected because delivery cannot be optimized without behavior evidence.

## ADR-009: Use a deterministic, tool-first assistant; make an LLM optional

### Status

Proposed

### Context

The existing assistant is transparent but shallow. An unrestricted LLM over financial/PII data can hallucinate, cross boundaries, expose data, and imply autonomous advice.

### Decision

Build governed typed query tools and evidence-linked deterministic answers first. Add an LLM only as a language planner/synthesizer after privacy/vendor review, evaluation, prompt/tool-injection controls, cost limits, and a kill switch.

### Consequences

- Positive: factuality, permissions, provenance, graceful no-LLM operation.
- Negative: more tool/schema engineering; less open-ended early experience.
- Neutral: LLM vendor/model can change without changing business truth.

### Alternatives considered

- Direct text-to-SQL/database access: rejected for security and correctness.
- Keep keyword matching forever: rejected because ambiguity and evidence navigation require richer intent handling.

## ADR-010: Use a light-first accessible financial design system

### Status

Accepted for the current product shell on 2026-08-27

### Context

The current app is light-themed and report-oriented. Automated design search suggested a dark technical style, but the main contexts include daylight business work, tables, forms, and printable evidence.

### Decision

Use a light-first high-trust design with navy identity, accessible cobalt action and selection, cyan analytic support, restrained semantic green/amber/red, tabular numerals, and WCAG 2.2 AA. The signature component is a workspace trust ribbon from source to meaning to quality to next action. Provide System, Light, and Dark appearance modes through semantic tokens. Dark mode is allowed only because text, status, surface, control, chart, and breakpoint behavior were independently mapped and browser-tested.

### Consequences

- Positive: readable business workflow, print alignment, accessible controls, clear hierarchy, and a validated low-light preference.
- Negative: two palettes increase regression scope; every framework/chart/token change must be tested in both.
- Neutral: Light remains the print/reference palette while System is the first-run preference.

### Alternatives considered

- OLED dark default: rejected as a poor primary fit for the validated use context.
- Preserve the earlier raw colors: rejected because the earlier primary teal/white and coral/white fail 4.5:1 normal-text contrast and do not distinguish action from healthy state.

## Required review decisions

- Confirm product stage and production rewrite trigger.
- Confirm launch cloud/region and managed vendors after data-residency, budget, and team review.
- Confirm queue choice and operational owner.
- Confirm identity provider and enterprise SSO timing.
- Confirm dataset scale/latency/availability targets.
- Confirm responsible model-use and human-decision policy with legal/risk owners.
