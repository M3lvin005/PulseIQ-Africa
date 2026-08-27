# Security Incident Runbook

## Declare and classify

Open a private incident record and assign an incident commander, technical lead, communications owner, and evidence recorder.

- SEV-1: confirmed or likely unauthorized real-data/credential access, cross-tenant exposure, malicious code execution, or loss of decision integrity.
- SEV-2: contained vulnerability with meaningful exposure, leaked non-production credential, persistent security-control failure, or exploitable denial of service.
- SEV-3: suspicious event or low-impact weakness with no evidence of compromise.

The current application is not authorized to hold real data. Discovery of real personal/financial data in the prototype is at least SEV-2 and may be SEV-1 depending on exposure.

## First response

1. Protect people and data; restrict or disable the affected environment.
2. Revoke and rotate suspected credentials/tokens from the authoritative provider. Do not paste values into the incident record.
3. Preserve access logs, release/commit IDs, configuration, SBOM, timestamps, actor/session identifiers, and relevant alerts using least privilege.
4. Do not alter original evidence. Record who collected each item and its hash/location.
5. Identify the earliest/latest possible exposure, affected tenants/data classes, actions available to the attacker, and whether model/report outputs lost integrity.
6. Engage the privacy/legal owner to determine notification and regulatory duties; engineers do not make that decision alone.

## Containment and eradication

- Remove public access or isolate the workload/network path.
- Block affected accounts, sessions, routes, files, releases, or dependencies.
- Rotate secrets from a trusted environment and check downstream use.
- Patch the root cause, add a regression test, audit adjacent paths, and rebuild from the reviewed lock.
- Produce a new SBOM and verify the source, secret, dependency, quality, and smoke gates.
- If a dependency or action is implicated, inventory every release containing it.

## Recovery

Deploy a new immutable reviewed release or roll back to a verified known-good release. Validate manual-review routing, upload limits, report/export safety, and security configuration. Restore traffic gradually only when the incident commander and service owner accept the evidence.

## Communication and review

Use factual, time-stamped updates. State what is known, unknown, contained, affected, and next. Never expose credentials or unnecessary personal data.

Within five working days of recovery, document timeline, root cause, control failures, impact, detection gap, response effectiveness, corrective actions, owners, due dates, and whether the threat model/runbooks need revision. Test the highest-risk corrective action rather than closing it on documentation alone.
