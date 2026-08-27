# PulseIQ Africa Planning Pack

## Outcome

This planning pack defines what the repository currently does, why several outputs are unsafe or misleading outside a demo, and the full product, UI/UX, data, backend, model, analytics, security, operational, and delivery logic required for a controlled production path.

The initial reverse-engineering phase was read-only. Subsequent delivery cycles are tracked in `implementation_status.md` with verification evidence.

## Read in this order

1. [`../../specs/pulseiq_africa_reverse_spec.md`](../../specs/pulseiq_africa_reverse_spec.md) — evidence-based specification of every current module, page, formula, rule, model path, dataset property, limitation, and defect.
2. [`product_ui_ux_blueprint.md`](product_ui_ux_blueprint.md) — product wedge, personas, information architecture, user journeys, screen/state requirements, accessible design system, responsive behavior, and research plan.
3. [`design_system.md`](design_system.md) — portable light/dark tokens, spacing, alignment, responsive composition, component rules, and UI quality gate.
4. [`technical_architecture_delivery_blueprint.md`](technical_architecture_delivery_blueprint.md) — target architecture, modules, state machines, data model, API, security/privacy, NFRs, tools, testing, CI/CD, delivery phases, team, and definition of done.
5. [`analytics_and_model_governance.md`](analytics_and_model_governance.md) — KPI contracts, data quality, anomaly logic, ML lifecycle, decision policy, assistant, product analytics, operational telemetry, and governance cadence.
6. [`requirements_catalog.md`](requirements_catalog.md) — implementation-ready requirement IDs and stage priorities.
7. [`architecture_decision_records.md`](architecture_decision_records.md) — proposed decisions and trade-offs requiring stakeholder acceptance.
8. [`implementation_status.md`](implementation_status.md) — delivered production-cycle evidence, remaining gates, and the next vertical slice.
9. [`accessibility_verification.md`](accessibility_verification.md) — rendered responsive/accessibility evidence and residual manual checks.
10. [`security_audit_2026-08-25.md`](security_audit_2026-08-25.md) — OWASP-mapped source, configuration, dependency, secret, and production-readiness audit.
11. [`../runbooks/README.md`](../runbooks/README.md) — deployment, rollback, and security-incident procedures.
12. [`identity_authorization_contract.md`](identity_authorization_contract.md) — provider-neutral actor, workspace, RBAC, MFA, membership mutation, and adapter trust boundaries.
13. [`dataset_ingestion_contract.md`](dataset_ingestion_contract.md) — quarantine upload, immutable version, idempotent job, storage, scanner, and worker trust boundaries.

## What the current app is

A well-scoped portfolio prototype that proves this flow:

```text
CSV -> normalized headers -> simple quality score -> KPIs/charts
    -> hard-coded anomaly rules -> three-classifier comparison
    -> individual score -> deterministic Q&A -> PDF
```

It is not currently a production lending, fraud, analytics, or multi-tenant platform.

## Highest-priority evidence

- Empty or invalid data can receive 92% quality and 100% repayment.
- Missing model/KPI inputs silently become generic defaults or zeros.
- “Total revenue” is actually the sum of transaction amounts with no direction, accounting category, or multi-currency handling.
- Demo stored suspicious labels flag 2,164 rows; the live rules flag 740; only 714 overlap.
- Stored risk, live rule severity, and model risk share overlapping terminology without source/version provenance.
- The score explanation is a separate hand-written rule, not an explanation of the fitted model.
- Model selection reuses a single random test split and has no validation, calibration, fairness, drift, lineage, or approval workflow.
- No authentication, tenancy, persistence, audit, human override/appeal, retention, privacy workflow, background jobs, API, analytics instrumentation, or observability exists.
- The repository has no Python lock or reproducible environment; available validation runtime lacked Streamlit/scikit-learn.
- Home’s Upload CTA does not navigate.
- Current primary teal with white text is 2.93:1 and coral with white is 3.77:1, below the 4.5:1 normal-text target.

## Immediate decision gates

Implementation should not begin broadly until these are answered:

1. Product type: portfolio demo, internal lender tool, or multi-tenant SaaS?
2. First paying user and job: credit reviewer, finance analyst, SME owner, or consultant?
3. First jurisdiction and data-residency requirement?
4. Authoritative data sources, typical schemas, row volumes, refresh frequency, and data owner?
5. Governed meanings of revenue, customer, repayment, default, suspicious, risk, and final decision?
6. Human decision authority, thresholds, false-positive/false-negative cost, override, and appeal policy?
7. Availability, latency, RPO/RTO, budget, team, and launch date?
8. Is the assistant deterministic or LLM-backed, and may customer data reach an external model provider?

## Recommended delivery order

### Now: stabilize truth and reproducibility

- Create `pyproject.toml`/lock, CI, tests, environment check, and rendered cross-device test path.
- Introduce schema/semantic validation and block silent defaults.
- Rename invalid KPIs and define unavailable states.
- Add source/version/timestamp to every risk output.
- Correct Home navigation, errors, caching, CSV export safety, report provenance, and accessibility blockers.
- Display an explicit demo/non-production decision disclaimer.

### Then: production foundation

- Identity, organizations/workspaces, RBAC/RLS, PostgreSQL, object storage, immutable dataset versions, audit, retention, queued processing, observability, backups.
- Production web app and accessible Data/Quality/Overview flows.

### Then: operational value

- Versioned rules, alerts/cases, assignments/dispositions, governed portfolio metrics, reports/schedules/delivery.

### Only after governance is ready: production ML

- Point-in-time data, authoritative target, eligible training, independent validation, calibration/fairness, registry/approval/shadow/rollback, model + policy + human decision separation, override/appeal/outcomes.

### Last: LLM and broad connectors

- Typed governed tools first; optional LLM after privacy/evaluation/security/cost controls.
- Build only connectors requested by launch customers.

## Tool/resource map

| Workstream | Default tools/resources |
|---|---|
| Prototype Python | Python 3.12, uv, Ruff, mypy/pyright, pytest, Hypothesis, Pandera |
| UI validation | Streamlit AppTest for prototype; Next.js/TypeScript + Storybook + Playwright + axe for production |
| Data/analytics | pandas/Polars, DuckDB, Parquet; PostgreSQL; warehouse/dbt only after measured need |
| ML | scikit-learn, MLflow, SHAP, Fairlearn; governed temporal/group validation |
| Jobs | Redis + Celery initially; durable job records and idempotency |
| Storage | Managed PostgreSQL + S3-compatible object storage |
| Product analytics | PostHog or equivalent with explicit allowlist, pseudonyms, and session replay off by default |
| Observability | OpenTelemetry; Prometheus/Grafana-compatible metrics; error tracking with PII scrubbing |
| Security | OIDC provider, secrets manager, RLS, Gitleaks, Semgrep/Bandit, pip-audit, CodeQL/Trivy, SBOM/signing |
| Delivery | GitHub Actions, Docker, managed container platform, managed DB/storage, Terraform/OpenTofu when production account exists |
| Governance | Model/data cards, DPIA, threat model, metric/rule/model/policy approval, access/retention/incident runbooks |

## Official planning references

Regulatory applicability must be confirmed by qualified counsel for the launch entity and market.

- [Nigeria Data Protection Act 2023](https://ndpc.gov.ng/wp-content/uploads/2024/03/Nigeria_Data_Protection_Act_2023.pdf) — Section 37 addresses significant decisions based solely on automated processing and human intervention/contest rights.
- [CBN Consumer Protection Regulations](https://www.cbn.gov.ng/Out/2019/CCD/CBN%20Consumer%20Protection%20Regulations.pdf) — responsible lending includes sustainable repayment assessment, credit-history checks, clear authority, financial-difficulty policy, and monitoring.
- [Kenya Data Protection Act 2019](https://www.odpc.go.ke/wp-content/uploads/2024/02/TheDataProtectionAct__No24of2019.pdf) — notice and reconsideration safeguards around solely automated decisions.
- [Rwanda DPP Law rights](https://dpo.gov.rw/dpp-law/rights-of-the-data-subject) and [controller/processor obligations](https://dpo.gov.rw/dpp-law/obligations-of-the-data-controller-and-the-data-processor) — automated decisions, logic/consequence information, and DPIA duties.
- [Ghana Data Protection Commission data-subject rights](https://dataprotection.org.gh/for-individuals/) — access, objection, purpose/recipient information, complaints, and compensation.
- [African Union Data Policy Framework](https://au.int/en/documents/20220728/au-data-policy-framework) — trustworthy, rights-preserving, harmonized African data governance.
- [WCAG 2.2](https://www.w3.org/TR/WCAG22/) — target interface accessibility standard.
- [NIST AI Risk Management Framework](https://www.nist.gov/itl/ai-risk-management-framework) — Govern, Map, Measure, Manage; 1.0 is under revision as of 2026.
- [NIST Secure Software Development Framework](https://csrc.nist.gov/projects/ssdf) — secure development, provenance, vulnerability response.
- [Streamlit execution/caching](https://docs.streamlit.io/develop/concepts/architecture/caching), [session state](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.session_state), and [file upload](https://docs.streamlit.io/develop/api-reference/widgets/st.file_uploader) — rerun/cache behavior, session-local state, default upload constraints, and developer responsibility for validation.
- [FastAPI background tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/) — in-process tasks are suitable for small work; heavy computation benefits from a queue/worker system.
- [PostgreSQL row security](https://www.postgresql.org/docs/current/ddl-rowsecurity.html) — per-user/role row access and default-deny behavior when enabled without a policy.
- [MLflow tracking](https://mlflow.org/docs/latest/tracking) — runs, datasets, parameters, metrics, artifacts, and model registry lineage.
- [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/) and [Prometheus overview](https://prometheus.io/docs/introduction/overview/) — correlated telemetry and operational time-series monitoring.

## Planning completion checklist

- [x] Every repository file and source module inventoried/read.
- [x] Page, state, data, KPI, anomaly, ML, assistant, report, and UI logic traced.
- [x] Demo dataset profiled and stored/live risk mismatch quantified.
- [x] Data/analytics/anomaly/report paths executed and timed.
- [x] Invalid/empty/negative/duplicate-header/date edge cases executed.
- [x] Security, privacy, accessibility, reliability, performance, test, and delivery gaps recorded.
- [x] Product flows, target screens/states, design direction, and accessibility criteria defined.
- [x] Architecture, module boundaries, data model, APIs, jobs, security, NFRs, tools, tests, environments, phases, and ownership defined.
- [x] KPI, quality, rule, model, decision, assistant, product-event, and telemetry governance defined.
- [x] Major decisions documented with alternatives/trade-offs.
- [ ] Stakeholder review of personas, launch market, definitions, constraints, and ADRs.
- [x] Reproducible environment and rendered browser/device/accessibility validation, with manual AT residuals documented.
- [x] Automated dependency/source/secret gates and validated CycloneDX SBOM.
- [ ] Counsel/compliance acceptance and DPIA before real personal/credit data.
