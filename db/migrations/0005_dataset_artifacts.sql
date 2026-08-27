BEGIN;

CREATE TABLE pulseiq.dataset_artifacts (
    dataset_version_id uuid PRIMARY KEY,
    organization_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    object_key text NOT NULL UNIQUE CHECK (
        object_key ~ '^normalized/[A-Za-z0-9][A-Za-z0-9_-]{0,127}/[A-Za-z0-9][A-Za-z0-9_-]{0,127}/[A-Za-z0-9][A-Za-z0-9_-]{0,127}/[A-Za-z0-9][A-Za-z0-9_-]{0,127}/data[.]parquet$'
    ),
    source_sha256 bytea NOT NULL CHECK (octet_length(source_sha256) = 32),
    artifact_sha256 bytea NOT NULL CHECK (octet_length(artifact_sha256) = 32),
    schema_fingerprint bytea NOT NULL CHECK (octet_length(schema_fingerprint) = 32),
    row_count integer NOT NULL CHECK (row_count BETWEEN 1 AND 100000),
    column_count smallint NOT NULL CHECK (column_count BETWEEN 1 AND 200),
    normalization_version text NOT NULL CHECK (normalization_version ~ '^[1-9][0-9]{0,8}$'),
    created_at timestamptz NOT NULL,
    UNIQUE (organization_id, workspace_id, dataset_version_id),
    CONSTRAINT dataset_artifacts_version_tenant_fk
        FOREIGN KEY (organization_id, workspace_id, dataset_version_id)
        REFERENCES pulseiq.dataset_versions (organization_id, workspace_id, dataset_version_id)
);

CREATE INDEX dataset_artifacts_tenant_created_idx
    ON pulseiq.dataset_artifacts (organization_id, workspace_id, created_at DESC)
    INCLUDE (dataset_version_id, row_count, column_count, normalization_version);

CREATE TABLE pulseiq.dataset_artifact_fields (
    dataset_version_id uuid NOT NULL REFERENCES pulseiq.dataset_artifacts (dataset_version_id),
    position smallint NOT NULL CHECK (position BETWEEN 1 AND 200),
    source_column text NOT NULL CHECK (length(source_column) BETWEEN 1 AND 512),
    normalized_column text NOT NULL CHECK (
        normalized_column ~ '^[a-z][a-z0-9_]{0,127}$'
    ),
    physical_type text NOT NULL CHECK (physical_type = 'string'),
    nullable boolean NOT NULL,
    PRIMARY KEY (dataset_version_id, position),
    UNIQUE (dataset_version_id, source_column),
    UNIQUE (dataset_version_id, normalized_column),
    UNIQUE (dataset_version_id, source_column, normalized_column)
);

CREATE FUNCTION pulseiq.reject_dataset_artifact_mutation() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    RAISE EXCEPTION 'normalized dataset artifact lineage is immutable'
        USING ERRCODE = '55000';
END;
$$;

REVOKE ALL ON FUNCTION pulseiq.reject_dataset_artifact_mutation() FROM PUBLIC;

CREATE TRIGGER dataset_artifacts_reject_mutation
    BEFORE UPDATE OR DELETE ON pulseiq.dataset_artifacts
    FOR EACH ROW EXECUTE FUNCTION pulseiq.reject_dataset_artifact_mutation();

CREATE TRIGGER dataset_artifact_fields_reject_mutation
    BEFORE UPDATE OR DELETE ON pulseiq.dataset_artifact_fields
    FOR EACH ROW EXECUTE FUNCTION pulseiq.reject_dataset_artifact_mutation();

ALTER TABLE pulseiq.dataset_artifacts ENABLE ALWAYS TRIGGER dataset_artifacts_reject_mutation;
ALTER TABLE pulseiq.dataset_artifact_fields ENABLE ALWAYS TRIGGER dataset_artifact_fields_reject_mutation;
ALTER TABLE pulseiq.dataset_artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.dataset_artifacts FORCE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.dataset_artifact_fields ENABLE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.dataset_artifact_fields FORCE ROW LEVEL SECURITY;

CREATE POLICY dataset_artifacts_current_tenant_select ON pulseiq.dataset_artifacts
    FOR SELECT TO pulseiq_app
    USING (
        organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
        AND workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
    );

CREATE POLICY dataset_artifacts_worker_select ON pulseiq.dataset_artifacts
    FOR SELECT TO pulseiq_worker USING (true);

CREATE POLICY dataset_artifacts_worker_insert ON pulseiq.dataset_artifacts
    FOR INSERT TO pulseiq_worker WITH CHECK (true);

CREATE POLICY dataset_artifact_fields_current_tenant_select ON pulseiq.dataset_artifact_fields
    FOR SELECT TO pulseiq_app
    USING (
        EXISTS (
            SELECT 1 FROM pulseiq.dataset_artifacts AS artifact
            WHERE artifact.dataset_version_id = dataset_artifact_fields.dataset_version_id
              AND artifact.organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
              AND artifact.workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
        )
    );

CREATE POLICY dataset_artifact_fields_worker_select ON pulseiq.dataset_artifact_fields
    FOR SELECT TO pulseiq_worker USING (true);

CREATE POLICY dataset_artifact_fields_worker_insert ON pulseiq.dataset_artifact_fields
    FOR INSERT TO pulseiq_worker WITH CHECK (true);

GRANT SELECT ON pulseiq.dataset_artifacts TO pulseiq_app;
GRANT SELECT, INSERT ON pulseiq.dataset_artifacts TO pulseiq_worker;
GRANT SELECT ON pulseiq.dataset_artifact_fields TO pulseiq_app;
GRANT SELECT, INSERT ON pulseiq.dataset_artifact_fields TO pulseiq_worker;

COMMIT;
