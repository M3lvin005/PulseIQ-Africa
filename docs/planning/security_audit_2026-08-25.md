# Security and Supply-Chain Audit — 2026-08-25

## Decision

The repository is acceptable for a local or isolated synthetic-data demonstration after the controls recorded below. It is **not approved for internet-facing real-data use**. Identity, tenancy, secure storage, workload isolation, and immutable audit telemetry remain blocking architecture work.

Scope: `app.py`, `src/`, `scripts/`, project and Streamlit configuration, dependency manifests, GitHub Actions, upload/export surfaces, report rendering, model execution, and documented deployment assumptions. This is a source/configuration assessment, not a penetration test of a deployed environment.

## Automated evidence

| Control | Pinned implementation | Result on 2026-08-25 |
|---|---|---|
| Locked dependency audit | `pip-audit==2.10.1`, hashed `requirements.txt`, no dependency re-resolution | No known vulnerabilities |
| Python static analysis | `bandit==1.9.4`, `app.py src scripts` | No medium/high findings |
| Full Bandit triage | all severities | Initial 11 low findings: seven smoke-script assertions, two internal assertions, one false credential keyword, and one safe output-escaping import; code findings remediated or renamed |
| Secret scan | `detect-secrets==1.5.0`, fail-closed JSON verifier | No repository findings after cache-only false positives were excluded |
| Component inventory | `cyclonedx-bom==7.3.1`, environment + `pyproject.toml`, CycloneDX 1.6 JSON | Schema-valid reproducible SBOM generated |
| CI action integrity | commit-pinned checkout, uv setup, and artifact upload | Read-only workflow permissions |

`joblib` was removed as a direct dependency because PulseIQ does not serialize or load model artifacts. It remains only as a transitive scikit-learn dependency. No pickle/joblib upload or deserialization path exists.

## Findings and release gates

Severity describes impact if the prototype boundary were expanded. “Conditional critical” means the issue is not exploitable against real records while real records are prohibited, but becomes critical before such use.

| ID | Severity | Finding | Current control | Required closure |
|---|---|---|---|---|
| SEC-001 | Conditional critical | No identity, organization, tenant boundary, RBAC, or object-level authorization | Synthetic, single-session demo only | OIDC/MFA policy, workspace membership, server-side RBAC, default-deny tenant isolation, negative authorization tests, access reviews |
| SEC-002 | High | Uploads are parsed in-process with no immutable object storage, content-signature inspection, malware scan, quarantine, retention, deletion, or encryption-key design | UTF-8 CSV only; 10 MB, 100k-row, 200-column bounds; binary/delimiter/parser/header checks; SHA-256 lineage | Private encrypted object storage, quarantine/scan pipeline, immutable dataset versions, tenant-scoped keys/paths, retention and verified deletion |
| SEC-003 | High | No append-only audit/security event store or production detection/alerting | Local console only; browser stack traces hidden | PII-scrubbed security events, actor/tenant/request correlation, immutable retention, alert rules, on-call ownership, tested incident access |
| SEC-004 | High | CPU-heavy parsing, rules, reports, and model fitting run synchronously; there is no rate limit, quota, timeout, cancellation, or worker isolation | Bounded file/rows/columns and model eligibility limits | Authenticated rate limits, tenant quotas, queued jobs, hard resource/time limits, idempotency, cancellation, backpressure, worker isolation |
| SEC-005 | High | No production secrets manager, TLS/proxy baseline, network policy, hardened container, backup, restore, or signed release implementation | No application secrets are currently required; CORS/XSRF explicitly enabled | Environment-specific threat model and IaC; managed TLS; security headers at proxy; non-root/read-only workload; secret rotation; backup/restore evidence; artifact signing |
| SEC-006 | Medium | Streamlit controls application markup and shell semantics; a few `unsafe_allow_html` calls remain | Dynamic table/report values are escaped; unsafe fragments are static or escaped; no external URL fetch or script injection path found | Re-test every framework upgrade; CSP/security headers at deployment edge; migrate production shell to an accessible, security-controlled frontend |
| SEC-007 | Medium | Unexpected runtime failures could previously expose details in the browser | `client.showErrorDetails="none"`, minimal toolbar, error links off | Central exception capture with PII scrubbing, correlation IDs, generic user errors, secure operator diagnostics |
| SEC-008 | Medium | Privacy, jurisdiction, consent, data-subject rights, and automated-decision obligations are undecided | Prominent demo/manual-review disclaimers; telemetry disabled | DPIA and legal sign-off, data inventory/classification, lawful basis, notice/consent, rights workflows, residency and processor decisions |
| SEC-009 | Medium | No abuse-case tests or deployed dynamic security test exists | Unit/property/UI tests and source scans | Threat model, authorization matrix tests, upload fuzz corpus, deployed DAST, dependency/container scanning, recovery exercise |

## OWASP Top 10 review

| OWASP 2021 category | Assessment |
|---|---|
| A01 Broken Access Control | Production blocker SEC-001. There is no privileged route because there is no identity or tenancy at all. |
| A02 Cryptographic Failures | SEC-002/005/008. No persistent application store exists, but transport, at-rest encryption, keys, retention, and privacy controls are not implemented. |
| A03 Injection | No SQL, shell, template evaluation, dynamic import, `eval`, `exec`, or server-side URL path was found. CSV exports neutralize spreadsheet formulas; dynamic HTML/report values are escaped. |
| A04 Insecure Design | SEC-001 through SEC-005 and SEC-008 are explicit release gates. Manual review is mandatory for model outputs. |
| A05 Security Misconfiguration | Error detail, toolbar, telemetry, CORS, and XSRF settings are hardened locally. Edge headers, TLS, network policy, container and host configuration remain SEC-005. |
| A06 Vulnerable and Outdated Components | Lock, hashed export, weekly audit, exact scanner versions, commit-pinned actions, and retained SBOM are implemented. No known vulnerability was reported in this snapshot. |
| A07 Identification and Authentication Failures | Production blocker SEC-001. Authentication is intentionally absent in the prototype. |
| A08 Software and Data Integrity Failures | Commit-pinned actions and locked dependencies reduce build risk. No model artifact deserialization exists. Signing, provenance attestation, immutable uploads, and approval/rollback stores remain open. |
| A09 Security Logging and Monitoring Failures | Production blocker SEC-003. No production telemetry pipeline or immutable audit store exists. |
| A10 Server-Side Request Forgery | No application HTTP client or user-controlled server-side URL fetch was found. Reassess before connectors, webhooks, or an LLM tool layer are added. |

The category mapping follows the [OWASP Top 10:2021](https://owasp.org/Top10/). CWE links and detector details are available from Bandit's generated output; CI intentionally fails only medium/high findings while all low findings require triage during scheduled review.

## Existing defense-in-depth

- Upload byte, row, column, extension, encoding, binary, delimiter, parse, empty-header, and normalized-collision checks return stable safe error codes.
- Uploaded data stays in Streamlit session memory; the application does not write it to disk, call an external service, or train/persist an artifact.
- Capability guards block analysis when required evidence is missing or invalid.
- Spreadsheet formula prefixes are neutralized before CSV download.
- HTML table/report values are escaped and PDF paragraph inputs are escaped.
- Model targets are allowlisted, splits are isolated, results are uncalibrated, and every individual score routes to manual review.
- CI permissions are `contents: read`; third-party actions are pinned to immutable commits.

## Failure and exception policy

- Critical or conditional-critical: block real-data use and deployment; no waiver can bypass the synthetic-data boundary.
- High: block pilot/release until remediated and verified.
- Medium: owner and due date required; target closure within 30 days once a production program starts.
- Low: triage and target closure within 90 days, or record why it is a detector false positive.
- Known vulnerable dependency: CI fails. An exception requires vulnerability ID, exploitability analysis, compensating control, owner, approver, and an expiry no longer than 30 days.
- Secret finding: CI fails. Treat the value as compromised, revoke/rotate it, purge where legally and operationally appropriate, then add only a narrowly justified allowlist marker for demonstrably synthetic fixtures.

Re-run this audit after any authentication, persistence, connector, webhook, external model, artifact upload/load, deployment, or multi-tenant change.

## 2026-08-27 implementation addendum

The production decision remains unchanged: the repository is not approved for internet-facing real-data use. The following controls now reduce implementation risk but are not deployed-control evidence:

- **SEC-001/A07:** added one-time OIDC state/nonce, PKCE S256, replay consumption, exact issuer/audience/nonce/time/MFA checks, pre-provisioned subject mapping, atomic session/auth-event creation, signed bounded `__Host-` cookies, independent CSRF keys, exact-origin mutation checks, authoritative session lookup, duplicate/tamper/expiry rejection, logout expiration, and verification-key rotation. Managed-provider code exchange/JWKS cryptographic verification and API composition remain open.
- **SEC-004/A04:** added named sliding-window policies for login IP, failed-login account, OIDC callback, upload, Assistant, report, and export scopes. Subjects and request IDs are HMAC-derived before storage; the Redis Lua adapter is atomic and the service fails closed when the store is unavailable. Deployment, tenant quotas, and worker resource isolation remain open.
- **SEC-005/A05:** added strict nonce-based CSP, HSTS, no-store, frame/content/referrer/permissions policies, exact allowlisted credentialed CORS, and an executable production configuration gate. Edge integration, IaC, secret-manager operation, hardened workloads, signing, and restore evidence remain open.
- **SEC-008/A02:** demo intake now rejects restricted identifier columns and high-confidence email/phone/IBAN patterns without recording matched values. CSV export minimization drops restricted columns and redacts detected textual cells. Source-system de-identification, DLP, DPIA, residency, rights, retention, and deletion remain open.

Regression tests cover the new OIDC, privacy, browser-session, CSRF/origin, CORS/CSP, rate-limit, Redis-adapter, and configuration-gate contracts at 96.57% combined focused branch coverage. The 2026-08-27 rerun reported 392 passing tests with 23 expected service-environment skips, no Bandit findings, no known dependency vulnerabilities, and no secret-scan findings. Re-run the automated audit and an authorized deployed penetration test when the production API and infrastructure exist.
