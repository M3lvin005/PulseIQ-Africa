BEGIN;

ALTER TABLE pulseiq.import_jobs
    ADD COLUMN execution_token uuid,
    ADD COLUMN leased_until timestamptz,
    ADD COLUMN progress_percent smallint NOT NULL DEFAULT 0 CHECK (progress_percent BETWEEN 0 AND 100),
    ADD CONSTRAINT import_jobs_execution_lease_pair_check CHECK (
        (execution_token IS NULL) = (leased_until IS NULL)
    ),
    ADD CONSTRAINT import_jobs_running_lease_check CHECK (
        (status = 'running') = (execution_token IS NOT NULL)
    ),
    ADD CONSTRAINT import_jobs_running_timing_check CHECK (
        status <> 'running'
        OR (started_at IS NOT NULL AND heartbeat_at IS NOT NULL AND completed_at IS NULL)
    ),
    ADD CONSTRAINT import_jobs_terminal_timing_check CHECK (
        status NOT IN ('succeeded', 'permanently_failed', 'cancelled')
        OR completed_at IS NOT NULL
    );

ALTER TABLE pulseiq.outbox_events
    DROP CONSTRAINT outbox_events_attempts_check,
    ADD COLUMN lease_token uuid,
    ADD COLUMN leased_until timestamptz,
    ADD COLUMN last_attempt_at timestamptz,
    ADD COLUMN last_error_code text,
    ADD COLUMN dead_lettered_at timestamptz,
    ADD CONSTRAINT outbox_events_attempts_check CHECK (attempts BETWEEN 0 AND 5),
    ADD CONSTRAINT outbox_events_payload_size_check CHECK (octet_length(payload::text) <= 16384),
    ADD CONSTRAINT outbox_events_lease_pair_check CHECK (
        (lease_token IS NULL) = (leased_until IS NULL)
    ),
    ADD CONSTRAINT outbox_events_terminal_exclusive_check CHECK (
        NOT (published_at IS NOT NULL AND dead_lettered_at IS NOT NULL)
    ),
    ADD CONSTRAINT outbox_events_terminal_lease_check CHECK (
        (published_at IS NULL AND dead_lettered_at IS NULL)
        OR (lease_token IS NULL AND leased_until IS NULL)
    ),
    ADD CONSTRAINT outbox_events_last_attempt_check CHECK (
        last_attempt_at IS NULL OR last_attempt_at >= created_at
    ),
    ADD CONSTRAINT outbox_events_error_code_check CHECK (
        last_error_code IS NULL OR last_error_code ~ '^[a-z][a-z0-9_]{0,119}$'
    ),
    ADD CONSTRAINT outbox_events_dead_letter_check CHECK (
        dead_lettered_at IS NULL
        OR (dead_lettered_at >= created_at AND last_error_code IS NOT NULL AND attempts > 0)
    );

DROP INDEX pulseiq.outbox_events_pending_idx;

CREATE INDEX outbox_events_pending_idx
    ON pulseiq.outbox_events (available_at, outbox_sequence)
    INCLUDE (topic, aggregate_id, attempts, leased_until)
    WHERE published_at IS NULL AND dead_lettered_at IS NULL;

CREATE INDEX outbox_events_dead_letter_idx
    ON pulseiq.outbox_events (dead_lettered_at DESC, outbox_sequence)
    INCLUDE (topic, aggregate_id, attempts, last_error_code)
    WHERE dead_lettered_at IS NOT NULL;

CREATE INDEX import_jobs_worker_lease_idx
    ON pulseiq.import_jobs (leased_until, job_id)
    INCLUDE (status, attempts, heartbeat_at)
    WHERE status = 'running';

GRANT USAGE ON SCHEMA pulseiq TO pulseiq_worker;

COMMIT;
