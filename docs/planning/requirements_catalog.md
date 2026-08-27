# PulseIQ Africa Target Requirements Catalog

Status values: **MVP** (required before handling real customer decisions), **Next** (next controlled release), **Later** (validated demand required). Every requirement needs detailed Given/When/Then tests before implementation.

## Identity, tenancy, and governance

| ID | Requirement | Stage |
|---|---|---|
| REQ-ID-001 | The system shall isolate every tenant-owned row, object, cache entry, job, artifact, and event by organization/workspace. | MVP |
| REQ-ID-002 | When a user accesses a resource, the system shall authorize the action from authenticated membership and server-side permission, not client state. | MVP |
| REQ-ID-003 | When a privileged role signs in, the system shall require MFA according to organization policy. | MVP |
| REQ-ID-004 | When membership or role changes, the system shall revoke affected active access within the defined propagation SLO and audit the change. | MVP |
| REQ-ID-005 | The system shall support Admin, Data Steward, Analyst, Risk Reviewer, Approver, Auditor, and Read Only permissions with least privilege. | MVP |
| REQ-ID-006 | Where enterprise SSO is enabled, the system shall support OIDC/SAML provisioning and organization enforcement. | Later |

## Dataset ingestion and mapping

| ID | Requirement | Stage |
|---|---|---|
| REQ-DATA-001 | When an authorized user begins upload, the system shall issue a tenant-bound, short-lived signed upload and enforce workspace quota. | MVP |
| REQ-DATA-002 | When an upload completes, the system shall verify size, type/signature, checksum, malware result, encoding, delimiter, and safe parse limits before use. | MVP |
| REQ-DATA-003 | When a source is accepted, the system shall preserve an immutable original and create an immutable normalized dataset version. | MVP |
| REQ-DATA-004 | When concepts are ambiguous, the system shall require a human to confirm column, type, unit, currency, period, direction, and time semantics. | MVP |
| REQ-DATA-005 | When a mapping is confirmed, the system shall version it and allow authorized reuse for later versions of the same source. | MVP |
| REQ-DATA-006 | When a critical field is missing or unparseable, the system shall block dependent analysis rather than silently substitute a healthy value. | MVP |
| REQ-DATA-007 | When validation fails, the system shall provide a safe issue export with row/column, rule, masked example, and recovery action. | MVP |
| REQ-DATA-008 | Where connectors are enabled, the system shall checkpoint, retry idempotently, reconcile source totals, and expose last-success/failure state. | Next |

## Data quality

| ID | Requirement | Stage |
|---|---|---|
| REQ-QUAL-001 | The system shall measure completeness, validity, uniqueness, consistency, timeliness, and fitness/integrity separately. | MVP |
| REQ-QUAL-002 | When any blocking issue exists, the system shall mark the dataset unfit for the affected purpose even if its composite score is high. | MVP |
| REQ-QUAL-003 | When a warning is overridden, the system shall require permission, reason, actor, expiry where relevant, and audit event. | MVP |
| REQ-QUAL-004 | When a new dataset version differs materially from its predecessor, the system shall show schema and distribution changes. | Next |
| REQ-QUAL-005 | The system shall never report a positive quality score for an empty dataset. | MVP |

## Analytics and portfolio

| ID | Requirement | Stage |
|---|---|---|
| REQ-KPI-001 | Every KPI shall use an approved metric definition and return unit/currency, period, filters, freshness, quality, source, and definition version. | MVP |
| REQ-KPI-002 | When a KPI dependency is missing, the system shall return Not available with the dependency/recovery path, not zero or 100%. | MVP |
| REQ-KPI-003 | When multiple currencies exist, the system shall separate them or apply a versioned conversion source/rate/time that is shown to the user. | MVP |
| REQ-KPI-004 | When users filter or drill down, the system shall preserve filters, scroll, and back navigation and retain metric provenance. | MVP |
| REQ-KPI-005 | Every chart shall provide exact values, accessible summary/table, unit, period, error/empty/loading state, and export where relevant. | MVP |
| REQ-KPI-006 | Where a transaction is not explicitly mapped to revenue, the system shall label the aggregate transaction value rather than revenue. | MVP |

## Rule-based risk and cases

| ID | Requirement | Stage |
|---|---|---|
| REQ-RISK-001 | Every rule shall be versioned with owner, purpose, expression, inputs, threshold, severity, scope, effective dates, explanation, and approval. | MVP |
| REQ-RISK-002 | When a rule lacks required input, the system shall record Not evaluated or an explicit missing-data result, not median-impute normality. | MVP |
| REQ-RISK-003 | When multiple rules trigger, the system shall preserve and display every rule and evidence item. | MVP |
| REQ-RISK-004 | Every alert shall identify entity, run/ruleset version, evidence, threshold/baseline, priority, created time, and current workflow state. | MVP |
| REQ-RISK-005 | When a reviewer dispositions a case, the system shall require an allowed outcome and reason and shall retain notes/assignment/history. | MVP |
| REQ-RISK-006 | When ruleset performance or confirmation rate crosses a guardrail, the system shall notify the owner and support suspension/rollback. | Next |

## Model lifecycle

| ID | Requirement | Stage |
|---|---|---|
| REQ-ML-001 | When training is requested, the system shall validate target provenance, sample/classes, point-in-time correctness, leakage, quality, and representativeness. | MVP |
| REQ-ML-002 | The system shall prohibit production approval of a model trained on a derived demonstration target. | MVP |
| REQ-ML-003 | Every training run shall record code, dependency, data, mapping, feature, parameter, random-seed, metric, artifact, and environment lineage. | MVP |
| REQ-ML-004 | Candidate selection shall use an appropriate baseline, cross-validation/model-selection set, and untouched temporal validation set. | MVP |
| REQ-ML-005 | Evaluation shall include threshold-specific cost/confusion metrics, discrimination, calibration, stability, and approved subgroup analysis. | MVP |
| REQ-ML-006 | When a model is promoted, an independent authorized approver shall accept its model card, limitations, monitoring, threshold, expiry, and rollback plan. | MVP |
| REQ-ML-007 | When live data is missing, stale, out-of-distribution, or the approved model is unavailable, the system shall fail safely to manual review/unavailable. | MVP |
| REQ-ML-008 | The system shall monitor input quality/drift, predictions, outcomes, calibration, performance, fairness, overrides, and operations using matured cohorts. | Next |

## Scoring and human decisions

| ID | Requirement | Stage |
|---|---|---|
| REQ-DEC-001 | Every prediction shall bind to an immutable feature snapshot and approved model/threshold versions. | MVP |
| REQ-DEC-002 | The UI/API shall distinguish facts, model prediction, policy evaluation, recommendation, and final human decision. | MVP |
| REQ-DEC-003 | Explanation/reason codes shall be truthful to the actual model or named policy rule and carry method/version. | MVP |
| REQ-DEC-004 | When a decision has significant effect, the system shall support human intervention, contest/reconsideration, corrected data, and a new versioned decision. | MVP |
| REQ-DEC-005 | When an authorized user overrides a recommendation, the system shall require reason, preserve the original, and apply second approval at configured exposure. | MVP |
| REQ-DEC-006 | When later repayment/outcome arrives, the system shall attach it to the original cohort without rewriting historical prediction/decision evidence. | Next |

## Reports and delivery

| ID | Requirement | Stage |
|---|---|---|
| REQ-RPT-001 | Every report shall bind to dataset/metric/ruleset/model/policy/filter versions and show period, currency, generated time, owner, and limitations. | MVP |
| REQ-RPT-002 | Report generation shall be asynchronous, idempotent, status-visible, cancellable where safe, and retryable. | MVP |
| REQ-RPT-003 | The system shall provide an accessible HTML report; PDF and data exports shall be secondary formats. | MVP |
| REQ-RPT-004 | When a report is externally delivered, the system shall enforce approval, recipient authorization, expiry/revocation, delivery tracking, and audit. | Next |
| REQ-RPT-005 | Spreadsheet exports shall neutralize formulas by default and record export provenance. | MVP |

## Assistant

| ID | Requirement | Stage |
|---|---|---|
| REQ-AST-001 | When a user asks a business question, the system shall authorize every evidence/tool request under the same tenant/field permissions as the UI. | MVP |
| REQ-AST-002 | When metric, entity, period, currency, or risk source is ambiguous, the assistant shall clarify rather than guess. | MVP |
| REQ-AST-003 | Every answer shall state source/version/period/filter and link to governed evidence. | MVP |
| REQ-AST-004 | The assistant shall not autonomously decide credit, promote models/rules, change access, export/delete data, or deliver reports. | MVP |
| REQ-AST-005 | Where an LLM is used, the system shall mask/minimize data, use typed allowlisted tools, evaluate factuality/permissions/injection/privacy, and provide fallback/kill switch. | Later |

## Product analytics and observability

| ID | Requirement | Stage |
|---|---|---|
| REQ-OBS-001 | The system shall keep business/model data, product events, and operational telemetry in separate governed schemas/pipelines. | MVP |
| REQ-OBS-002 | Product events shall use allowlisted properties and exclude raw IDs, filenames, amounts, scores, decisions, questions, and free text. | MVP |
| REQ-OBS-003 | The system shall propagate request/trace/job IDs through web, API, DB, queue, worker, storage, model, report, and integration calls. | MVP |
| REQ-OBS-004 | When an error is shown, the user shall receive a safe code/recovery action and operators shall receive correlated diagnostic context without raw PII. | MVP |
| REQ-OBS-005 | The system shall alert on SLO burn, auth/tenant anomalies, stuck jobs, backup failure, integration failure, and model/data health guardrails. | Next |

## Security, privacy, and compliance

| ID | Requirement | Stage |
|---|---|---|
| REQ-SEC-001 | The system shall encrypt data in transit/at rest, use centralized secrets, least privilege, secure sessions, and controlled signed URLs. | MVP |
| REQ-SEC-002 | The delivery pipeline shall lock dependencies, generate SBOM/provenance, and scan secrets, source, dependencies, licenses, and containers. | MVP |
| REQ-SEC-003 | The system shall support purpose/notice, retention, access/correction/export, restriction/objection, deletion where lawful, legal hold, and breach response. | MVP |
| REQ-SEC-004 | When data crosses a country/provider boundary, the system shall enforce the approved country pack, contract, transfer, residency, and encryption policy. | MVP |
| REQ-SEC-005 | Privileged, data, rule, model, decision, report, integration, privacy, and support access actions shall create tamper-evident audit events. | MVP |
| REQ-SEC-006 | The system shall undergo upload/tenant/model/assistant/report threat modeling and authorization testing before production. | MVP |

## Reliability, performance, and accessibility

| ID | Requirement | Stage |
|---|---|---|
| REQ-NFR-001 | Production shall meet accepted availability, latency, concurrency, RPO/RTO, and job-feedback SLOs with dashboards/runbooks. | MVP |
| REQ-NFR-002 | Heavy work shall run in bounded asynchronous jobs with idempotency, progress, cancellation, retries, heartbeat, and dead-letter handling. | MVP |
| REQ-NFR-003 | When model/email/analytics dependencies fail, the system shall preserve a safe manual/core path and explain degradation. | MVP |
| REQ-NFR-004 | Critical web workflows shall meet WCAG 2.2 AA and pass keyboard, focus, screen-reader, contrast, zoom, reduced-motion, and responsive checks. | MVP |
| REQ-NFR-005 | The system shall render defined empty/loading/partial/stale/permission/error/timeout/offline/success states for every critical component. | MVP |
| REQ-NFR-006 | The system shall restore tested backups within accepted RTO and data-loss bounds and shall exercise rollback/forward-fix procedures. | MVP |

## Integrations

| ID | Requirement | Stage |
|---|---|---|
| REQ-INT-001 | Every integration shall declare scopes, data classes, country/region, secret owner, last health, retention, and revocation. | Next |
| REQ-INT-002 | Connector and webhook processing shall be idempotent, signed where applicable, retryable, reconciled, and dead-lettered. | Next |
| REQ-INT-003 | Email/report providers shall receive only approved minimum data and expose delivery/bounce/complaint state. | Next |
| REQ-INT-004 | New data connectors shall be prioritized by validated customer demand, not generic breadth. | Next |

## Global acceptance gate

No MVP requirement is complete without: implementation evidence, automated tests, authorization/audit verification, privacy/security review, accessibility coverage where user-facing, telemetry/alerting, runbook/rollback, and stakeholder acceptance against representative data.
