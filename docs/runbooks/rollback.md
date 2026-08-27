# Rollback Runbook

## Trigger

Rollback immediately for a security control regression, possible data exposure, incorrect decision semantics, broken manual-review routing, dependency integrity failure, persistent unhandled errors, unavailable core flow, or a smoke-test failure. For suspected compromise, also start [`security_incident.md`](security_incident.md).

## Procedure

1. Freeze new deployment changes and record the incident/release identifier.
2. Disable or restrict access when continued traffic could increase impact.
3. Select the last immutable release whose Quality and Security workflows, SBOM, and deployment smoke passed.
4. Repoint traffic using the hosting platform's atomic release/traffic control; do not rebuild the old commit with current dependencies.
5. Confirm the active commit/release identifier and configuration match the known-good record.
6. Run the built-in-demo post-deployment smoke from [`deployment.md`](deployment.md).
7. Observe error rate, resource usage, and availability for the declared rollback window.
8. Notify the release owner of rollback status, customer impact if any, and the next update time.

## Data and schema note

The current prototype has no database or persistent upload store, so there is no schema or data rollback. That property must not be assumed once persistence is introduced. Future migrations need backward compatibility, a tested restore path, RPO/RTO, and an explicit decision on roll-forward versus restore.

## Closure

Keep the failed release disabled. Preserve minimal PII-free evidence, identify the first bad commit and control gap, add a regression test, rerun both workflows, and require a fresh deployment approval. Do not redeploy by merely repeating the failed action.
