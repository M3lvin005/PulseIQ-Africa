# PulseIQ Africa Analytics, Decision Logic, and Model Governance Plan

## 1. Measurement architecture

Keep four different measurement systems separate:

1. **Business analytics:** customer-owned portfolio facts and governed KPIs.
2. **Risk/model monitoring:** rule, prediction, outcome, drift, calibration, fairness, and decision quality.
3. **Product analytics:** privacy-safe behavior showing whether users reach value.
4. **Operational telemetry:** service logs, metrics, traces, errors, and SLOs.

Never send uploaded financial rows, customer names/IDs, loan/application IDs, free-text questions, feature values, predictions, or report contents to generic product analytics or error-monitoring tools.

## 2. Governed metric contract

Every metric definition shall include:

```text
metric_id, name, purpose, owner, version, status
entity and grain
formula, numerator, denominator
included/excluded statuses
event time and reporting period
currency/unit and conversion policy
filters/dimensions
minimum data requirements
quality block/warn rules
late-arriving data behavior
comparison/target logic
privacy classification
examples and tests
```

Metric responses and exports carry `definition_version`, `dataset_version`, filter set, generated timestamp, freshness, quality status, and trace/run ID.

## 3. Core KPI dictionary

Definitions are proposed and must be agreed with domain owners.

| KPI | Proposed definition | Required inputs | Important exclusions/notes |
|---|---|---|---|
| Transaction value | Sum of signed or absolute transaction amount by declared transaction type | amount, currency, type/direction, time | Never label revenue by default |
| Recognized revenue | Sum of transactions mapped to revenue under a versioned accounting rule | above + revenue category | No mixed currency without versioned FX |
| Active customers | Distinct customer IDs with qualifying activity in period | customer ID, activity time/type | Define qualifying activity |
| Average transaction value | qualifying value / qualifying count | same | Show count and sign convention |
| Approval rate | approved applications / decided applications | application and decision status/time | Exclude drafts/withdrawn; slice by policy/model |
| Default rate | defaulted exposures / eligible originated exposures | outcome definition/window | Define 30/60/90 DPD or charge-off explicitly |
| Repayment rate | paid due amount / due amount in period | schedule, due/paid amount/date | Do not derive from a row-level binary alone |
| Portfolio at risk | outstanding principal with arrears threshold / total outstanding | loan balance, days past due | Define PAR30/PAR90 separately |
| Flag rate | records/customers flagged by a specific ruleset run / evaluated population | run, entity | Source and version mandatory |
| Case confirmation rate | true-positive dispositions / resolved cases | case outcome | Monitor reviewer and rule bias |
| Time to triage | first acknowledgement - alert created | timestamps | Report percentile, not only mean |
| Decision turnaround | final decision - complete application | timestamps | Pause policy for awaiting data |
| Override rate | authorized overrides / final decisions | decision/override | Slice by direction/reason/reviewer |
| Data quality pass rate | active versions without blocking issue / validated versions | validation runs | Show dimension scores |

## 4. Data quality logic

### Block conditions

- Empty file or no data rows.
- Missing confirmed business key or effective/event date where required.
- Critical numeric concept has no parseable values.
- Currency/unit/period is missing or ambiguous for financial aggregation.
- Duplicate authoritative key above allowed tolerance.
- Target definition absent, leaked, out of observation window, or class/sample insufficient for training.
- Cross-field integrity failure above policy threshold.

### Warning conditions

- Missingness above a field-specific tolerance.
- Stale period, unrecognized categories, outliers, mixed formats, sparse segments.
- High duplicate non-key rows or likely repeated uploads.
- Distribution shift from the accepted prior dataset.

### Quality run output

For each issue: rule ID/version, severity, dimension, column/row/entity, actual/expected, count/rate, example values with masking, remediation, override policy, and owner. Composite quality is secondary to block/warn detail.

## 5. Anomaly/risk-rule framework

### Rule contract

```text
rule_id, name, purpose, owner, version, status
entity, required features, expression
absolute/relative threshold and peer group
severity and score contribution
explanation template and evidence fields
effective dates and jurisdiction/product scope
expected flag rate and validation sample
exceptions/suppressions
approval and change reason
```

### Evaluation semantics

- Evaluate each rule independently and preserve all results; do not collapse to only the first category.
- Distinguish `rule_severity`, `aggregate_priority`, `model_risk`, and `case_status`.
- Aggregate priority may use rule severity, count, amount/exposure, customer history, confidence, recency, and policy—not issue count alone.
- Missing input produces Not evaluated or an explicit missing-data rule, never median-imputed “normal.”
- Dataset-relative thresholds include peer group, baseline window, sample size, and fallback behavior.
- Every alert is immutable evidence from one ruleset run; later threshold changes create a new evaluation.

### Initial transparent rule families

- Data integrity: duplicate IDs, conflicting status/outcome, impossible dates, missing critical fields.
- Amount/velocity: absolute threshold, peer percentile, rapid count/value, sudden pattern shift.
- Affordability: loan-to-income/debt-service ratio using validated period/unit.
- Repayment: missed/late sequence, worsening days-past-due, restructures.
- Identity/profile consistency: changes or mismatches only where lawful and relevant.
- Network/device/counterparty behavior only after legal basis and data-quality assessment.

Each rule needs backtesting, reviewer sampling, confirmation rate, false-positive cost, subgroup check, and rollback threshold.

## 6. Credit model lifecycle

### 6.1 Use-case registration

Before code or data work, record decision supported, affected people, users, prohibited use, outcome window, cost matrix, human role, appeal, market, data sources, protected/sensitive feature policy, owner, and risk tier.

### 6.2 Dataset eligibility

- Authoritative outcome definition and observation/performance window.
- Point-in-time correctness; no post-decision feature or target leakage.
- Entity/group-aware and time-aware splitting; duplicate entities remain in one split.
- Minimum sample/class counts chosen through power/stability analysis, not an arbitrary row cutoff.
- Missingness/category/cardinality/outlier checks and documented treatment.
- Representativeness across intended products, regions, segments, channels, and time.
- Lawful basis, minimization, retention, and prohibited/proxy feature review.

Derived targets remain demo-only and are visibly watermarked; they cannot be approved or deployed.

### 6.3 Candidate/baseline evaluation

- Simple policy/logistic baseline before more complex candidates.
- Nested or well-separated model selection and final temporal holdout.
- Metrics: ROC-AUC, PR-AUC, precision/recall/F1 at policy thresholds, confusion/cost matrix, Brier/log loss, calibration curve/error, lift/gain, stability confidence intervals.
- Compare approval/decline/manual-review volume and business cost at candidate thresholds.
- Evaluate slices with adequate support: geography/product/channel/time and legally reviewed fairness groups or proxies.
- No candidate wins from one F1 value on the same test set used for selection.

### 6.4 Explanation and reason codes

- Separate model explanation, policy rule, and human rationale.
- Validate local explanation fidelity and stability.
- Map technical contributions to approved, truthful, specific reason codes; do not invent a hand-coded reason disconnected from the model.
- Avoid disclosing exploitable fraud logic while still giving affected people meaningful information and reconsideration.
- Store explanation method/version and feature snapshot.

### 6.5 Calibration and thresholds

- Calibrate probability on validation data if probability is displayed.
- Thresholds are decision-policy versions based on cost, risk appetite, capacity, and fairness—not hard-coded UI constants.
- Support at least approve/conditional/manual review bands only after policy approval.
- Low confidence, missing/stale data, out-of-distribution input, or unapproved model always routes to manual review/unavailable.

### 6.6 Model approval record

- Model card and use-case owner.
- Code/dependency/data/feature/parameter versions and hashes.
- Metrics, slices, calibration, threshold analysis, limitations, and known failure modes.
- Privacy/security/fairness/legal reviews.
- Independent validator and approval dates.
- Deployment alias, monitoring plan, rollback trigger, expiry/revalidation date.

### 6.7 Production monitoring

| Monitor | Example measure | Trigger action |
|---|---|---|
| Input quality | missing/invalid/category rate | route/manual review, investigate source |
| Drift | PSI/KS or domain-appropriate distance | investigate; retrain only after review |
| Prediction | score/band/approval distribution | compare policy/change/data causes |
| Performance | ROC/PR, recall, precision after outcomes mature | suspend/rollback on material degradation |
| Calibration | observed vs predicted by band | recalibrate/revalidate |
| Fairness | selection/error/calibration slices with support | governance review and remediation |
| Stability | explanation/rank/feature drift | investigate pipeline/model |
| Operations | latency, errors, timeout, fallback | fail safely to manual review |
| Override/appeal | rate, direction, reason, outcome | policy/model/reviewer review |

Outcomes arrive late; monitoring must define maturation windows and avoid reporting performance on incomplete cohorts.

## 7. Decision policy

Model score and policy are separate inputs to a human-controlled workflow:

```text
validated feature snapshot
  -> approved model prediction (or unavailable)
  -> deterministic policy evaluation
  -> data/model confidence and exception checks
  -> recommendation band
  -> authorized human decision
  -> customer notice/reconsideration path
  -> later outcome
```

Required controls:

- Dual approval for policy/threshold/model production changes.
- Reason-required override and second approval above defined exposure.
- Original recommendation remains immutable.
- Reconsideration can use corrected/additional data and creates a new decision version.
- Final decision cannot be produced by product analytics, assistant text, or an unapproved model.

## 8. Assistant architecture and logic

### Tool-first answer path

1. Authorize user/workspace/resource.
2. Classify intent and identify metric/entity/period/filter ambiguity.
3. Ask for clarification when business meaning can change the result.
4. Call governed query/metric/alert/model/report tools.
5. Validate returned provenance and quality.
6. Generate concise explanation from structured results.
7. Attach evidence links, definitions, source/version/period/filter, and uncertainty.
8. Log safe tool metadata and collect feedback.

### Initial deterministic intents

- KPI definition/value/trend/comparison.
- Data quality issue and remediation.
- Alert/case explanation and status.
- Model metric/card/score explanation within permissions.
- Report status/generation help.
- Workflow navigation and next action.

### Optional LLM controls

- LLM never receives unrestricted database access or constructs arbitrary SQL.
- Typed allowlisted tools enforce row/field/tenant permissions.
- Minimize and mask prompts; country/data-residency vendor review.
- Defend against prompt injection in uploaded content and tool output.
- No autonomous approval, rule/model promotion, access change, export, deletion, or report delivery.
- Evaluation set covers factuality, citations, permissions, ambiguity, refusal, injection, privacy, and African locale/currency cases.
- Cost/token/rate budgets, timeout, fallback to deterministic response, and kill switch.

## 9. Product analytics event contract

Common properties permitted on every event:

```text
event_id, event_name, schema_version, occurred_at
anonymous_or_pseudonymous_user_id
organization/workspace pseudonymous IDs
session_id, app_version, environment
role_group, plan, locale, device class
page/route, experiment flags
```

Never include raw file/customer/application/transaction IDs, filenames, emails, names, amounts, scores, decisions, questions, free text, table cells, report content, or stack traces.

### Event catalog

| Event | Trigger | Safe properties |
|---|---|---|
| `workspace_created` | setup completed | country pack, base-currency code, industry category |
| `invite_sent/accepted` | team action | role group |
| `dataset_upload_started` | signed upload begins | size bucket, source type |
| `dataset_upload_completed` | bytes accepted | size/row buckets, duration bucket |
| `dataset_upload_failed` | failure | safe error code, phase |
| `mapping_started` | mapping opened | detected-column bucket |
| `mapping_confirmed` | mapping committed | mapped/required/warn counts |
| `validation_completed` | run terminal | status, block/warn counts, duration bucket |
| `dataset_activated` | ready version active | row/date-span/quality buckets |
| `overview_viewed` | overview useful render | dataset state, quality status |
| `portfolio_filter_applied` | filter committed | dimension type, active-filter count |
| `chart_drilled_down` | aggregate → detail | chart/metric ID, dimension type |
| `alert_queue_viewed` | risk queue opened | active filter count |
| `alert_acknowledged` | acknowledgement | severity/age buckets |
| `case_dispositioned` | resolution | disposition class, duration bucket, rule family |
| `training_eligibility_checked` | eligibility run | pass/fail and safe reason codes |
| `training_started/completed/failed` | job state | candidate count, duration/status/error code |
| `model_validation_submitted/approved/rejected` | governance action | model family, validation status |
| `score_requested/completed/failed` | score flow | mode, latency/status; no score value |
| `decision_recorded` | final decision | decision band class, manual/override flags |
| `override_recorded` | authorized override | direction and reason-code class |
| `report_requested/generated/downloaded/delivered` | report flow | template, format, status, duration bucket |
| `assistant_question_submitted` | query submit | intent class, source page; no text |
| `assistant_answer_feedback` | feedback | helpful yes/no, safe issue category |
| `error_recovery_used` | retry/help path | component, safe error code, action |

### Funnels and product metrics

- Activation: workspace created → valid dataset active → first trusted insight viewed.
- Time to first trusted insight; median/p75/p90.
- Upload success and recovery rate by source/size bucket.
- Mapping completion and repeated mapping reuse.
- Quality-block resolution rate/time.
- Alert acknowledgement/disposition rate and time.
- Report generation/download/delivery completion.
- Model eligibility/validation completion—not “number of models trained” alone.
- Decision override/appeal workflow adoption.
- Weekly active organizations with a meaningful action, not page views.
- Retention by workspace reaching recurring portfolio review/report cadence.

Define success and guardrails before experiments. Examples: reduce mapping time without increasing validation overrides; improve alert triage time without lowering confirmed-positive rate.

## 10. Operational telemetry specification

### API/server

- Request count, status, latency histogram, payload-size bucket, rate-limit denial.
- DB query latency/error/pool saturation; cache hit/miss; external provider latency/error.
- Authentication failures and authorization denials (safe dimensions).

### Jobs/data

- Queue depth/oldest age, started/completed/failed/cancelled/retried, heartbeat.
- Bytes/rows processed, parse/validation/transform/compute time, memory high-water mark.
- Validation block/warn rates and schema drift by source category.

### ML/decisions

- Inference request/error/latency, model alias/version, fallback/manual-review rate.
- Monitoring freshness and overdue outcome/model validation.
- Do not expose labels with customer IDs or unbounded feature/category values.

### Reports/integrations

- Generation duration/failure/size buckets.
- Email/webhook attempt/delivery/bounce/retry/dead-letter.

## 11. Governance cadence

| Cadence | Review |
|---|---|
| Daily/on-call | incidents, stuck jobs, auth anomalies, SLO burn |
| Weekly | product funnel, import/quality failures, alert SLA, support themes |
| Monthly | rules confirmation/false positive, overrides, drift, fairness slices, access review |
| Quarterly | model validation, DPIA/threat model changes, restore test, retention, vendor/security review |
| Per release/change | metric/rule/model/policy/event schema approval and lineage |

Named councils can be lightweight, but responsibilities cannot be absent: Product owns user outcomes; Data owns contracts/metrics; Risk owns rules/policy; Model Validation independently approves models; Security/Privacy own controls; Engineering owns reliability; executives accept residual risk.

## 12. Reference framework

- NIST AI RMF: Govern, Map, Measure, Manage; note that 1.0 is being revised as of 2026.
- NIST SSDF 1.1 for secure software lifecycle and provenance.
- WCAG 2.2 AA for interface accessibility.
- OpenTelemetry for correlated traces/metrics/logs; Prometheus-compatible metrics for operational time series, not billing/business truth.
- MLflow tracking/registry for dataset, run, parameter, metric, artifact, and model lineage.
- Applicable country privacy and financial-consumer rules, with human intervention and contestability as product capabilities.
