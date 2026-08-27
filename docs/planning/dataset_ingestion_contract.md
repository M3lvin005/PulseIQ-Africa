# Governed Dataset Ingestion Contract

## Current boundary

The current slice implements the provider-neutral reservation/completion domain seam, deterministic in-memory adapters, PostgreSQL metadata/job constraints, pooled Psycopg repositories, Boto3-compatible quarantine/clean/normalized storage adapters, a bounded ClamAV protocol adapter, deterministic lexical CSV-to-Parquet normalization, and Redis/Celery job delivery. These are tested seams, not deployed infrastructure: the Streamlit prototype has no production API wiring, and no PostgreSQL, Redis, S3, or scanner provider has been approved or deployed.

## Direct-upload trust flow

```text
authenticated Data Steward + active server session
  -> authorize dataset.upload in exact organization/workspace
  -> validate CSV extension, MIME allowlist, exact bytes, SHA-256, and safe IDs
  -> create tenant/version-bound quarantine key with no caller filename
  -> create a 5–15 minute direct-upload policy
  -> persist upload_pending Dataset version + audit atomically
  -> browser uploads directly to private quarantine storage
  -> completion performs trusted object HEAD inspection
  -> exact metadata match: uploaded revision + idempotent scan job + audit/outbox
  -> any metadata mismatch: durable quarantined revision + audit; no job
  -> worker claim atomically moves uploaded -> scanning
  -> stream object through exact byte/hash/UTF-8 checks and isolated ClamAV INSTREAM
  -> clean verdict: conditionally copy to immutable-original storage and verify SHA-256
  -> re-read exact clean original; preserve lexical CSV values; write verified Parquet
  -> job success and scanning -> mapping_required commit atomically
  -> malware/tamper: permanently failed job + quarantined version atomically
```

File bytes do not pass through the API, PostgreSQL, audit event, or queue payload. The source filename is not stored or used in the object key; only an HMAC-SHA-256 binding is retained. The key is `quarantine/{organization_id}/{workspace_id}/{dataset_id}/{dataset_version_id}/original.csv` and every component must be server-controlled/validated.

## Reservation invariants

- Only explicit `dataset.upload` permission can reserve or complete an upload; the default role matrix grants it to Data Steward.
- CSV is the only current source format. Extension and claimed MIME are allowlisted before signing; signature, encoding, delimiter, and parser limits remain worker checks.
- Expected size is 1 byte through 10 MiB in the current product limit and SHA-256 is exactly 32 bytes/64 lowercase hex characters.
- A signed form expires in 5–15 minutes (10 minutes by default) and must enforce exact key, MIME, checksum, and a content-length range at the object-store policy layer.
- Completion trusts object-store HEAD metadata, not browser callback fields.
- Completion callbacks are idempotent: an already uploaded version returns its original scan job and creates no second audit event.
- Size, MIME, key, or checksum mismatch durably quarantines the version. Replacing object metadata cannot later queue it.

## Dataset and job persistence

Migration `0002_dataset_ingestion.sql` adds tenant-scoped `datasets`, immutable-expectation `dataset_versions`, and reference-only `import_jobs` under forced RLS.

- Dataset-version identity, tenant, object key, filename HMAC, expected MIME/bytes/checksum, creator, and creation time cannot be updated.
- Lifecycle transitions use optimistic revisions.
- Import payload JSON is capped at 8 KiB and contains IDs/object references only.
- Job idempotency keys are globally unique; attempts are bounded at five.
- Job insertion creates a `job.queued` outbox event in the same transaction.
- The request role can create/read jobs but cannot execute them. The isolated worker role is intentionally cross-tenant and may read/update job state.
- Migration `0004_dataset_worker_lifecycle.sql` gives the worker only the dataset-version read and lifecycle-column update access needed to settle scans under forced RLS.
- The Psycopg repository commits version transitions, audit evidence, import-job creation, and trigger-produced outbox work atomically under the exact actor/organization/workspace request scope.
- Live PostgreSQL tests prove successful completion/replay and durable mismatch quarantine; mismatches create neither a scan job nor an outbox message.
- Live PostgreSQL tests also prove scan claim, retry, success, and permanent-malware settlement coordinate import-job and dataset-version state in one transaction.

## S3-compatible adapter obligations

- The implemented adapter creates SigV4 presigned POST forms with exact server-owned key, MIME, byte length, SHA-256, success status, and SSE-S3 policy conditions. SHA-256 is converted from canonical hex to the base64 S3 form field.
- Trusted inspection uses `HeadObject` with checksum mode enabled, normalizes `ChecksumSHA256` from base64 to canonical hex, and never uses ETag. Missing objects return `None`; access/provider and malformed-metadata failures use stable safe error codes.
- Expected AWS bucket-owner checking is supported for HEAD. SSE-S3 is the default and may only be disabled explicitly for a local compatibility fixture whose server has no KMS.
- Use a private quarantine bucket/prefix with Block Public Access, TLS-only bucket policy, managed encryption at minimum, least-privilege credentials, access logging, and a short orphan lifecycle.
- Use presigned POST rather than an unrestricted PUT so content-length and form conditions are enforced by storage.
- Do not expose quarantine through a CDN or signed download URL.
- Verify object checksum support and normalize S3 checksum encoding; never trust ETag as a content checksum.
- The ClamAV adapter uses bounded INSTREAM frames, exact total-size ceiling, bounded response, socket timeout, guaranteed closure, and safe clean/malware/error classifications. Deployment must isolate scanner CPU/memory/time and deny general network egress.
- Clean originals are copied server-side with `If-None-Match: *`, SSE-S3, expected-owner binding, and checksum verification. Normalized Parquet is created with the same no-overwrite condition and checksum verification.
- Application preflight checks and conditional writes prevent accidental/racing overwrite; durable immutability additionally requires versioning, Object Lock/default retention, and bucket/IAM policies. Quarantined objects follow approved security retention and deletion policy.
- Object deletion, legal hold, residency/replication, KMS keys, and signed access require approved country/provider policy.

The adapter contract has deterministic fake-client coverage and a live localhost round trip against an ephemeral S3-compatible server: wrong bytes are rejected by checksum policy, the exact CSV is accepted, and checksum-enabled HEAD matches the reservation. MinIO's community repository is archived and its final image has unresolved advisories; that image was used only as a disposable, localhost-bound compatibility fixture and is not an approved deployment dependency. Patched MinIO AIStor was evaluated but requires a commercial license before it permits S3 operations.

## Queue/worker obligations

Redis/Celery is implemented behind the job/outbox seam, while PostgreSQL remains the source of truth. Delivery is at-least-once: the dispatcher leases rows with `FOR UPDATE SKIP LOCKED`, publishes small JSON reference envelopes to allowlisted named queues, and acknowledges with the exact lease token only after broker acceptance. Transient publication failures use bounded exponential database retries; permanent or fifth-attempt failures retain dead-letter time and safe error code.

Import workers validate the Celery envelope, claim the durable job by ID and execution token, and no-op on duplicate/running/terminal deliveries. Claims, retries, token-bound heartbeats, progress, success, permanent failure, expired-lease recovery, and the five-attempt ceiling are database state. Celery uses JSON only, late acknowledgement, one-message prefetch, no result backend, a 600-second Redis visibility timeout, and 270/300-second soft/hard task limits. File bytes never enter Redis. Unknown code failures are not misclassified; their lease expires for safe replay. Production still requires metrics/alerts for queue age/depth, stale heartbeat, retries, dead letters, and quarantine spikes, plus graceful worker shutdown and deployed failure drills.

The single `dataset.scan` lease covers scan, promotion, and normalization in order. The dataset version becomes `mapping_required` only after normalized Parquet is checksum-verified in storage and the job settles successfully. Retriable scanner/storage failures leave the version in `scanning`; malware and defined tamper/integrity failures quarantine it; exhausted infrastructure failures move it to `failed`.

## Normalized Parquet contract

- The clean original is independently re-read and checked against the reserved exact byte count and SHA-256 before parsing.
- Parsing retains the 10 MiB/100,000-row/200-column bounds and CSV delimiter/header/collision controls.
- All cells remain lexical strings at this stage: no imputation, scaling, business-type inference, or missing-value reinterpretation occurs before steward-approved semantic mapping.
- PyArrow writes Parquet 2.6 with Zstandard compression, 64K row groups, page checksums, statistics, and deterministic source checksum/header mapping/normalization-version schema metadata.
- Normalized output is capped at 25 MiB and stored at `normalized/{organization}/{workspace}/{dataset}/{version}/data.parquet`; S3 user metadata contains only row/column counts, source checksum, and normalization version.

## Target artifact, mapping, and validation schema

```mermaid
erDiagram
    DATASET_VERSIONS ||--o| DATASET_ARTIFACTS : produces
    DATASET_ARTIFACTS ||--|{ DATASET_ARTIFACT_FIELDS : describes
    DATASET_VERSIONS ||--o{ SCHEMA_MAPPING_VERSIONS : confirms_for
    SCHEMA_MAPPING_VERSIONS ||--|{ SCHEMA_MAPPING_FIELDS : contains
    SCHEMA_MAPPING_VERSIONS ||--o{ VALIDATION_RUNS : governs
    DATASET_VERSIONS ||--o{ VALIDATION_RUNS : evaluates
    VALIDATION_RUNS ||--|{ VALIDATION_DIMENSION_SCORES : scores
    VALIDATION_RUNS ||--|{ VALIDATION_CAPABILITY_RESULTS : gates
    VALIDATION_RUNS ||--o{ VALIDATION_ISSUES : reports
    VALIDATION_ISSUES ||--|{ VALIDATION_ISSUE_CAPABILITIES : affects
    VALIDATION_ISSUES ||--o{ VALIDATION_ISSUE_EXAMPLES : masks
    VALIDATION_ISSUES ||--o{ VALIDATION_ISSUE_OVERRIDES : acknowledges

    DATASET_ARTIFACTS {
        uuid dataset_version_id PK_FK
        text object_key UK
        bytea source_sha256
        bytea artifact_sha256
        bytea schema_fingerprint
        integer row_count
        integer column_count
        text normalization_version
        timestamptz created_at
    }
    DATASET_ARTIFACT_FIELDS {
        uuid dataset_version_id PK_FK
        smallint position PK
        text source_column
        text normalized_column
        text physical_type
        boolean nullable
    }
    SCHEMA_MAPPING_VERSIONS {
        uuid mapping_version_id PK
        uuid dataset_version_id FK
        bytea schema_fingerprint
        uuid confirmed_by FK
        timestamptz confirmed_at
    }
    SCHEMA_MAPPING_FIELDS {
        uuid mapping_version_id PK_FK
        text source_column PK
        text normalized_column
        text governed_concept
        text physical_type
        text unit_semantics
        text currency_code
        text period_semantics
        text amount_direction
        text time_semantics
        boolean nullable
    }
    VALIDATION_RUNS {
        uuid validation_run_id PK
        uuid dataset_version_id FK
        uuid mapping_version_id FK
        text validation_policy_version
        text definition_version
        text status
        text verdict
        integer row_count
        smallint column_count
        numeric composite_score
        timestamptz created_at
        timestamptz completed_at
    }
    VALIDATION_DIMENSION_SCORES {
        uuid validation_run_id PK_FK
        text dimension PK
        numeric score
    }
    VALIDATION_CAPABILITY_RESULTS {
        uuid validation_run_id PK_FK
        text capability PK
        text status
    }
    VALIDATION_ISSUES {
        uuid validation_run_id PK_FK
        smallint issue_ordinal PK
        text rule_id
        text rule_version
        text severity
        text dimension
        text normalized_column
        integer affected_count
        boolean override_allowed
    }
    VALIDATION_ISSUE_CAPABILITIES {
        uuid validation_run_id PK_FK
        smallint issue_ordinal PK_FK
        text capability PK
    }
    VALIDATION_ISSUE_EXAMPLES {
        uuid validation_run_id PK_FK
        smallint issue_ordinal PK_FK
        smallint example_ordinal PK
        text masked_hash
    }
    VALIDATION_ISSUE_OVERRIDES {
        uuid override_id PK
        uuid validation_run_id FK
        smallint issue_ordinal FK
        uuid overridden_by FK
        timestamptz overridden_at
        timestamptz expires_at
        uuid request_id UK
        text reason
    }
```

Normalization rationale:

- 1NF: every mapping field, dimension score, capability result, issue, affected capability, masked example, and warning override is one atomic row; no JSON/array column stores repeated validation evidence.
- 2NF: mapping-level schema/actor/time facts live on `schema_mapping_versions`; field semantics depend on the complete mapping-field key. Issue capabilities and examples depend on the complete `(validation_run_id, issue_ordinal, child key)`.
- 3NF: artifact identity is stored once on `dataset_artifacts`; run-level policy/verdict/summary facts live on `validation_runs`; dimension, capability, issue, and example facts live only in their owning relation. Override rows reference rule/severity through the issue instead of duplicating those facts. Currency/unit/time choices remain field facts and are never inferred transitively from a display name. Reusable mapping-template identity remains a future relation rather than a nullable pseudo-template in validation rows.
- Tenant coordinates are repeated only where required for forced-RLS default denial and are protected by composite foreign keys. Confirmed versions and artifact identities are immutable; new confirmation or normalization creates a new version/record rather than rewriting lineage.

Implemented mapping-confirmation invariants:

- `dataset_artifacts` and ordered `dataset_artifact_fields` are immutable normalized lineage, inserted idempotently by the worker only while the Dataset version is `scanning`.
- Mapping fields carry a database foreign key to the exact artifact `(dataset_version, source column, normalized column)`; service validation is therefore reinforced by relational integrity.
- Only `dataset.manage` may confirm. All governed concepts are unique within a version, and money/date/identifier concepts enforce compatible target type and semantic declarations.
- Fixed currency requires an uppercase three-letter code. Column currency requires a separately confirmed currency concept. Transaction amount requires transaction-period plus signed/inflow-positive/outflow-positive direction semantics.
- Confirmation commits mapping rows, `mapping_required → validating`, the validation job/outbox, and audit evidence together. Confirmed rows reject update/delete even for table owners while the trigger is enabled.

Implemented validation invariants:

- The worker accepts exactly `dataset_version_id`, `mapping_version_id`, and `schema_fingerprint` references; UUID/digest shape, tenant/version/mapping lineage, artifact SHA-256, Parquet page checksums, embedded schema fingerprint, and exact row/column dimensions are revalidated before use.
- Only confirmed fields are selected and renamed to governed concepts. Required blanks and target-type parse failures block quality review without imputation; optional parse failures warn. Up to three deterministic SHA-256 prefixes provide safe examples without persisting source values.
- Six dimension scores, six capability gates, issue rules/version/severity/recovery, affected capabilities, and masked examples are normalized into immutable, forced-RLS tables. Application reads are exact-tenant only; the isolated worker has insert/select but no mutation grant.
- A run may contain capability-local blocking issues while the version remains `ready`; `failed` is reserved for a block on the dataset's quality-review readiness. Job success means validation executed reproducibly, not that every capability passed.
- Run ID equals the durable validation job ID. Insert, exact evidence comparison, and `validating → ready/failed` are atomic and replay-safe. If evidence commits before broker acknowledgement, a later lease may recompute and match the immutable run before marking the job succeeded.
- Only `quality.override` may acknowledge an issue, and only when its immutable severity is `warn` and policy marks it overrideable. Every override requires a 10–1000 character reason and a 15-minute–90-day expiry; blocking/informational issues cannot be overridden.
- Override history is immutable and the original issue remains unchanged. A PostgreSQL exclusion constraint plus a transaction advisory lock prevents overlapping active windows; the request ID is tenant-idempotent, and the override/audit chain commit atomically. Expiry changes only the derived effective-warning view and never rewrites run scores, verdict, or capability readiness.
- The effective-quality query is evaluated at a server time, returns original block/warn/inform counts plus active/effective warning counts, and derives `blocked`, `warn`, or `healthy`. Active overrides can remove warnings from the effective count; they can never reduce block counts or change the immutable composite score.

## Remaining work

1. reusable mapping-template lineage, effective-quality API/UI presentation, activation, and downstream typed Parquet materialization without training/validation leakage;
2. retention/legal hold/deletion workflows, quotas/rate limits, operational telemetry, dead-letter operations, and scanner failure drills;
3. production S3 bucket/IAM/encryption/versioning/Object Lock/lifecycle/retention, isolated ClamAV, and managed Redis provisioning with provider approval;
4. API contracts, secure-cookie/CSRF integration, accessible upload/scanning/mapping/failure UI states, and deployed abuse/tenant tests.
