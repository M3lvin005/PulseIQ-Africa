BEGIN;

CREATE TABLE pulseiq.datasets (
    dataset_id uuid PRIMARY KEY,
    organization_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    created_by uuid NOT NULL REFERENCES pulseiq.actors (actor_id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, workspace_id, dataset_id),
    CONSTRAINT datasets_workspace_tenant_fk
        FOREIGN KEY (organization_id, workspace_id)
        REFERENCES pulseiq.workspaces (organization_id, workspace_id)
);

CREATE TABLE pulseiq.dataset_versions (
    dataset_version_id uuid PRIMARY KEY,
    dataset_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    status text NOT NULL CHECK (
        status IN (
            'upload_pending', 'uploaded', 'scanning', 'mapping_required',
            'quarantined', 'failed', 'cancelled'
        )
    ),
    object_key text NOT NULL UNIQUE CHECK (length(object_key) BETWEEN 1 AND 1024),
    filename_binding bytea NOT NULL CHECK (octet_length(filename_binding) = 32),
    content_type text NOT NULL CHECK (
        content_type IN ('text/csv', 'application/csv', 'application/vnd.ms-excel')
    ),
    expected_bytes bigint NOT NULL CHECK (expected_bytes BETWEEN 1 AND 10485760),
    expected_sha256 bytea NOT NULL CHECK (octet_length(expected_sha256) = 32),
    created_by uuid NOT NULL REFERENCES pulseiq.actors (actor_id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    uploaded_at timestamptz,
    failure_code text CHECK (failure_code IS NULL OR length(failure_code) BETWEEN 1 AND 120),
    UNIQUE (organization_id, workspace_id, dataset_version_id),
    CONSTRAINT dataset_versions_dataset_tenant_fk
        FOREIGN KEY (organization_id, workspace_id, dataset_id)
        REFERENCES pulseiq.datasets (organization_id, workspace_id, dataset_id),
    CHECK (uploaded_at IS NULL OR uploaded_at >= created_at),
    CHECK (
        (status = 'upload_pending' AND uploaded_at IS NULL AND failure_code IS NULL)
        OR (status = 'uploaded' AND uploaded_at IS NOT NULL AND failure_code IS NULL)
        OR (status = 'quarantined' AND failure_code IS NOT NULL)
        OR status IN ('scanning', 'mapping_required', 'failed', 'cancelled')
    )
);

CREATE INDEX dataset_versions_tenant_dataset_created_idx
    ON pulseiq.dataset_versions (organization_id, workspace_id, dataset_id, created_at DESC)
    INCLUDE (dataset_version_id, status, revision, expected_bytes);

CREATE INDEX dataset_versions_tenant_status_idx
    ON pulseiq.dataset_versions (organization_id, workspace_id, status, created_at)
    INCLUDE (dataset_version_id, dataset_id, revision);

CREATE TABLE pulseiq.import_jobs (
    job_id uuid PRIMARY KEY,
    organization_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    dataset_version_id uuid NOT NULL,
    job_type text NOT NULL CHECK (job_type IN ('dataset.scan', 'dataset.parse', 'dataset.validate')),
    status text NOT NULL CHECK (
        status IN (
            'queued', 'running', 'succeeded', 'failed', 'retry_queued',
            'permanently_failed', 'cancelling', 'cancelled'
        )
    ),
    input_reference jsonb NOT NULL CHECK (
        jsonb_typeof(input_reference) = 'object'
        AND octet_length(input_reference::text) <= 8192
    ),
    idempotency_key text NOT NULL UNIQUE CHECK (length(idempotency_key) BETWEEN 1 AND 512),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 5),
    available_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    started_at timestamptz,
    heartbeat_at timestamptz,
    completed_at timestamptz,
    error_code text CHECK (error_code IS NULL OR length(error_code) BETWEEN 1 AND 120),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    CONSTRAINT import_jobs_dataset_version_tenant_fk
        FOREIGN KEY (organization_id, workspace_id, dataset_version_id)
        REFERENCES pulseiq.dataset_versions (organization_id, workspace_id, dataset_version_id),
    CHECK (started_at IS NULL OR started_at >= created_at),
    CHECK (heartbeat_at IS NULL OR heartbeat_at >= started_at),
    CHECK (completed_at IS NULL OR completed_at >= created_at)
);

CREATE INDEX import_jobs_worker_pending_idx
    ON pulseiq.import_jobs (available_at, job_id)
    INCLUDE (organization_id, workspace_id, dataset_version_id, job_type, attempts)
    WHERE status IN ('queued', 'retry_queued');

CREATE INDEX import_jobs_tenant_created_idx
    ON pulseiq.import_jobs (organization_id, workspace_id, created_at DESC)
    INCLUDE (job_id, dataset_version_id, job_type, status, attempts);

CREATE FUNCTION pulseiq.reject_dataset_version_identity_mutation() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    IF NEW.dataset_version_id <> OLD.dataset_version_id
       OR NEW.dataset_id <> OLD.dataset_id
       OR NEW.organization_id <> OLD.organization_id
       OR NEW.workspace_id <> OLD.workspace_id
       OR NEW.object_key <> OLD.object_key
       OR NEW.filename_binding <> OLD.filename_binding
       OR NEW.content_type <> OLD.content_type
       OR NEW.expected_bytes <> OLD.expected_bytes
       OR NEW.expected_sha256 <> OLD.expected_sha256
       OR NEW.created_by <> OLD.created_by
       OR NEW.created_at <> OLD.created_at THEN
        RAISE EXCEPTION 'dataset version identity and upload expectations are immutable'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION pulseiq.outbox_import_job() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pulseiq
AS $$
BEGIN
    INSERT INTO pulseiq.outbox_events (topic, aggregate_id, payload)
    VALUES (
        'job.queued',
        NEW.job_id,
        pg_catalog.jsonb_build_object(
            'dataset_version_id', NEW.dataset_version_id,
            'job_id', NEW.job_id,
            'job_type', NEW.job_type,
            'organization_id', NEW.organization_id,
            'workspace_id', NEW.workspace_id
        )
    );
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION pulseiq.reject_dataset_version_identity_mutation() FROM PUBLIC;
REVOKE ALL ON FUNCTION pulseiq.outbox_import_job() FROM PUBLIC;

CREATE TRIGGER dataset_versions_reject_identity_mutation
    BEFORE UPDATE ON pulseiq.dataset_versions
    FOR EACH ROW EXECUTE FUNCTION pulseiq.reject_dataset_version_identity_mutation();

CREATE TRIGGER import_jobs_outbox_after_insert
    AFTER INSERT ON pulseiq.import_jobs
    FOR EACH ROW EXECUTE FUNCTION pulseiq.outbox_import_job();

ALTER TABLE pulseiq.dataset_versions ENABLE ALWAYS TRIGGER dataset_versions_reject_identity_mutation;
ALTER TABLE pulseiq.import_jobs ENABLE ALWAYS TRIGGER import_jobs_outbox_after_insert;

ALTER TABLE pulseiq.datasets ENABLE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.datasets FORCE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.dataset_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.dataset_versions FORCE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.import_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.import_jobs FORCE ROW LEVEL SECURITY;

CREATE POLICY datasets_current_tenant_select ON pulseiq.datasets
    FOR SELECT TO pulseiq_app
    USING (
        organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
        AND workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
    );

CREATE POLICY datasets_current_tenant_insert ON pulseiq.datasets
    FOR INSERT TO pulseiq_app
    WITH CHECK (
        organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
        AND workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
        AND created_by = NULLIF(current_setting('pulseiq.actor_id', true), '')::uuid
    );

CREATE POLICY dataset_versions_current_tenant_select ON pulseiq.dataset_versions
    FOR SELECT TO pulseiq_app
    USING (
        organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
        AND workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
    );

CREATE POLICY dataset_versions_current_tenant_insert ON pulseiq.dataset_versions
    FOR INSERT TO pulseiq_app
    WITH CHECK (
        organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
        AND workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
        AND created_by = NULLIF(current_setting('pulseiq.actor_id', true), '')::uuid
    );

CREATE POLICY dataset_versions_current_tenant_update ON pulseiq.dataset_versions
    FOR UPDATE TO pulseiq_app
    USING (
        organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
        AND workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
    )
    WITH CHECK (
        organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
        AND workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
    );

CREATE POLICY import_jobs_current_tenant_select ON pulseiq.import_jobs
    FOR SELECT TO pulseiq_app
    USING (
        organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
        AND workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
    );

CREATE POLICY import_jobs_current_tenant_insert ON pulseiq.import_jobs
    FOR INSERT TO pulseiq_app
    WITH CHECK (
        organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
        AND workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
    );

CREATE POLICY import_jobs_worker_select ON pulseiq.import_jobs
    FOR SELECT TO pulseiq_worker
    USING (true);

CREATE POLICY import_jobs_worker_update ON pulseiq.import_jobs
    FOR UPDATE TO pulseiq_worker
    USING (true)
    WITH CHECK (true);

GRANT SELECT, INSERT ON pulseiq.datasets TO pulseiq_app;
GRANT SELECT, INSERT ON pulseiq.dataset_versions TO pulseiq_app;
GRANT UPDATE (status, revision, uploaded_at, failure_code) ON pulseiq.dataset_versions TO pulseiq_app;
GRANT SELECT, INSERT ON pulseiq.import_jobs TO pulseiq_app;
GRANT SELECT, UPDATE ON pulseiq.import_jobs TO pulseiq_worker;

COMMIT;
