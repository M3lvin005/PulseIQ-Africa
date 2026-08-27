# Security Policy

## Supported boundary

PulseIQ Africa `0.1.x` is a synthetic-data decision-intelligence prototype. Only the current `main` branch is maintained. It is not approved to receive personal, financial, credit, customer, production, or otherwise confidential data.

The Streamlit request path has no connected authentication, tenancy, persistent store, immutable audit service, malware quarantine, shared rate-limit service, or production monitoring. The repository contains tested default-deny identity/RLS, secure-cookie/CSRF, quarantine/scanner, worker, audit/outbox, exact-origin/CSP, Redis rate-limit, privacy-minimization, and startup-gate seams; none of those local seams is evidence of a deployed control. The unresolved deployment and operational gates remain blockers, not accepted production risks. See [`docs/planning/security_audit_2026-08-25.md`](docs/planning/security_audit_2026-08-25.md).

## Reporting a vulnerability

Use the repository host's private vulnerability-reporting channel when it is enabled. Do not open a public issue for an unpatched vulnerability and do not include real customer data, credentials, tokens, or exploit data belonging to another party.

Include:

- the affected commit and component;
- a minimal synthetic-data reproduction;
- likely impact and required preconditions;
- any suggested mitigation;
- a safe way to contact the reporter.

Do not perform denial-of-service testing, social engineering, credential attacks, persistence, data exfiltration, or tests against infrastructure you do not own or lack permission to assess.

## Maintainer handling

Maintainers should acknowledge a valid private report, assign a severity and owner, contain exposure, add a regression test where practical, and publish a remediation or explicit time-bounded exception. No exception can authorize real-data use while a production blocker in the security audit remains open.

## Automated controls

Pull requests and `main` are gated by:

- exact Python lock verification and hashed deployment export;
- `pip-audit` against the locked requirements;
- Bandit medium/high source findings;
- `detect-secrets` with fail-closed report verification;
- a validated, reproducible CycloneDX 1.6 SBOM retained as a CI artifact;
- lint, formatting, strict typing, coverage, and application smoke tests.

GitHub Actions dependencies and security tools are pinned to exact versions or commit SHAs. Security exceptions must name the finding, rationale, compensating control, owner, approver, and expiry date.
