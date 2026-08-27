# PulseIQ PostgreSQL boundary

`migrations/0001_identity_tenancy.sql` is the first production-schema migration for organization/workspace identity state. It targets PostgreSQL 18.6 and is integration-tested against the digest-pinned official container used in CI.

## Role separation

Provision these roles before applying the migration:

- `pulseiq_app`: the request-serving role; `NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS`;
- `pulseiq_worker`: the isolated outbox/import worker role with the same restrictions;
- a separate migration owner that is never used by the application or worker pool.

The migration intentionally does not create login credentials. Supply credentials through the deployment secret manager, rotate them independently, and never give the app role table ownership, membership in the migration role, or `BYPASSRLS`.

## Request transaction contract

Every request repository is constructed with a server-verified actor, organization, and workspace UUID. At the start of each transaction it installs them with parameterized, transaction-local settings:

```sql
SELECT set_config('pulseiq.actor_id', $1, true);
SELECT set_config('pulseiq.organization_id', $1, true);
SELECT set_config('pulseiq.workspace_id', $1, true);
```

RLS is enabled and forced on tenant tables. A missing, malformed, or mismatched context is default-deny. The application must still perform permission checks: RLS provides tenant/actor isolation, not the role-permission matrix.

Use a bounded Psycopg pool with the `pulseiq_app` DSN. Do not connect as the migration owner and then `SET ROLE` in production; CI uses `SET ROLE` only to prove RLS against a disposable database without storing a test password.

## Persistence guarantees

- UUID keys and composite workspace/organization foreign keys prevent tenant-coordinate drift.
- Membership lifecycle checks and a partial unique index enforce one active membership per actor/workspace.
- Session rows are actor-scoped and reject invalid expiry/revocation state.
- Invitations store only 32-byte email HMAC and token digests. A GiST exclusion constraint rejects overlapping pending windows for the same recipient/workspace while allowing reissue after expiry.
- Membership, invitation, and session mutations use optimistic revisions.
- Audit events are append-only, serialized per workspace under a chain-head row lock, SHA-256 chained inside PostgreSQL, and outboxed in the same transaction.
- The worker is intentionally cross-tenant and receives only schema usage, `SELECT, UPDATE` on outbox/import-job state, and narrowly column-scoped dataset-version lifecycle updates. It must run in a separately isolated process and credential boundary.
- Outbox rows use expiring UUID leases, `SKIP LOCKED`, bounded delivery attempts, retry availability, and retained dead-letter evidence. Attempts are charged only when an outcome is settled, so a dispatcher crash cannot strand the final attempt.
- Import jobs use separate execution-token leases, late-acknowledged reference-only Celery messages, token-bound heartbeat/progress/settlement, retry scheduling, and terminal duplicate no-ops.
- Scan-job claim and settlement coordinate dataset state atomically: `uploaded → scanning → mapping_required`, with classified quarantine/failure terminal paths and no mapping-ready state before storage normalization succeeds.
- Normalized artifact and field lineage is immutable, checksum/schema-bound, worker-insert-only, tenant-readable, and idempotent across job replay.
- Mapping confirmation binds fields to exact artifact columns using composite foreign keys and atomically commits the immutable mapping, `validating` transition, validation job/outbox, and chained audit evidence.
- Completed validation runs normalize dimension scores, capability readiness, issues, affected capabilities, and masked examples into immutable worker-inserted rows. A completed execution—not its pass/block verdict—is job success; the verdict atomically settles `validating → ready/failed`, and exact evidence replay closes the commit-before-ack crash window.
- Quality-warning overrides are expiring append-only acknowledgements, not edits to validation evidence. PostgreSQL prevents overlapping windows per issue, RLS binds inserts to the current actor/tenant, and the override plus chained audit event commit together.

The migration requires `pgcrypto` and `btree_gist`. Large files and portfolio payloads do not belong in PostgreSQL; the later dataset slice uses encrypted object storage plus immutable metadata rows.

## Apply and verify

Apply migrations as the migration owner inside the deployment release process. Run the integration suite against an empty disposable database:

```powershell
$env:PULSEIQ_TEST_DATABASE_URL = "postgresql://postgres@localhost:5432/postgres"
uv run --locked pytest tests/integration/test_postgres_identity_rls.py -q --no-cov
```

The suite proves active RLS, cross-tenant read/write denial, actor-scoped sessions, invitation isolation and reissue, append-only chained audit/outbox behavior, domain adapter transactions, and planner eligibility with `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`.

Production migrations are forward-only. Before deployment, take and verify a backup, test the migration on production-like volume, observe lock time, and prepare a forward repair migration. Do not roll back by dropping identity or audit tables.

## Still required operationally

- managed database encryption, private networking, TLS verification, PITR, restore drills, replicas, and connection limits;
- a chain verifier/signed checkpoint export stored outside the database;
- outbox/job lag alerts, dead-letter operator workflow, graceful-shutdown drills, and retention;
- autovacuum/statistics monitoring and production-cardinality `EXPLAIN` evidence;
- credential rotation, break-glass controls, migration approvals, and privileged-access audit.
