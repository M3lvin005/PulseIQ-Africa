BEGIN;

ALTER TABLE pulseiq.dataset_versions
    DROP CONSTRAINT dataset_versions_status_check,
    DROP CONSTRAINT dataset_versions_check1,
    ADD CONSTRAINT dataset_versions_status_check CHECK (
        status IN (
            'upload_pending', 'uploaded', 'scanning', 'mapping_required',
            'validating', 'ready', 'active', 'quarantined', 'failed', 'cancelled'
        )
    ),
    ADD CONSTRAINT dataset_versions_lifecycle_shape_check CHECK (
        (status = 'upload_pending' AND uploaded_at IS NULL AND failure_code IS NULL)
        OR (status = 'uploaded' AND uploaded_at IS NOT NULL AND failure_code IS NULL)
        OR (status = 'quarantined' AND failure_code IS NOT NULL)
        OR status IN ('scanning', 'mapping_required', 'validating', 'ready', 'active', 'failed', 'cancelled')
    );

CREATE TABLE pulseiq.schema_mapping_versions (
    mapping_version_id uuid PRIMARY KEY,
    organization_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    dataset_id uuid NOT NULL,
    dataset_version_id uuid NOT NULL,
    schema_fingerprint bytea NOT NULL CHECK (octet_length(schema_fingerprint) = 32),
    reused_from_mapping_version_id uuid REFERENCES pulseiq.schema_mapping_versions (mapping_version_id),
    confirmed_by uuid NOT NULL REFERENCES pulseiq.actors (actor_id),
    confirmed_at timestamptz NOT NULL,
    request_id uuid NOT NULL,
    reason text NOT NULL CHECK (length(reason) BETWEEN 10 AND 1000),
    UNIQUE (dataset_version_id),
    UNIQUE (organization_id, workspace_id, request_id),
    UNIQUE (organization_id, workspace_id, mapping_version_id),
    UNIQUE (mapping_version_id, dataset_version_id),
    CONSTRAINT schema_mapping_version_dataset_fk
        FOREIGN KEY (organization_id, workspace_id, dataset_id)
        REFERENCES pulseiq.datasets (organization_id, workspace_id, dataset_id),
    CONSTRAINT schema_mapping_version_artifact_fk
        FOREIGN KEY (organization_id, workspace_id, dataset_version_id)
        REFERENCES pulseiq.dataset_artifacts (organization_id, workspace_id, dataset_version_id)
);

CREATE TABLE pulseiq.schema_mapping_fields (
    mapping_version_id uuid NOT NULL,
    dataset_version_id uuid NOT NULL,
    source_column text NOT NULL CHECK (length(source_column) BETWEEN 1 AND 512),
    normalized_column text NOT NULL CHECK (normalized_column ~ '^[a-z][a-z0-9_]{0,127}$'),
    governed_concept text NOT NULL CHECK (
        governed_concept IN (
            'customer_id', 'transaction_id', 'date', 'transaction_amount', 'currency',
            'income', 'loan_amount', 'existing_debt', 'repayment_history_score',
            'defaulted', 'repayment_status'
        )
    ),
    target_type text NOT NULL CHECK (target_type IN ('string', 'decimal', 'integer', 'boolean', 'date', 'datetime')),
    nullable boolean NOT NULL,
    unit_semantics text NOT NULL CHECK (
        unit_semantics IN ('identifier', 'money', 'currency_code', 'temporal', 'score', 'category', 'outcome')
    ),
    currency_mode text NOT NULL CHECK (currency_mode IN ('not_applicable', 'fixed', 'column')),
    currency_code text CHECK (currency_code IS NULL OR currency_code ~ '^[A-Z]{3}$'),
    period_semantics text NOT NULL CHECK (
        period_semantics IN ('not_applicable', 'transaction', 'daily', 'weekly', 'monthly', 'quarterly', 'annual')
    ),
    amount_direction text NOT NULL CHECK (
        amount_direction IN ('not_applicable', 'signed', 'inflow_positive', 'outflow_positive')
    ),
    time_semantics text NOT NULL CHECK (
        time_semantics IN ('not_applicable', 'event_time', 'effective_time', 'observation_time')
    ),
    PRIMARY KEY (mapping_version_id, source_column),
    UNIQUE (mapping_version_id, normalized_column),
    UNIQUE (mapping_version_id, governed_concept),
    CHECK ((currency_mode = 'fixed') = (currency_code IS NOT NULL)),
    CONSTRAINT schema_mapping_fields_version_fk
        FOREIGN KEY (mapping_version_id, dataset_version_id)
        REFERENCES pulseiq.schema_mapping_versions (mapping_version_id, dataset_version_id),
    CONSTRAINT schema_mapping_fields_artifact_field_fk
        FOREIGN KEY (dataset_version_id, source_column, normalized_column)
        REFERENCES pulseiq.dataset_artifact_fields (dataset_version_id, source_column, normalized_column)
);

CREATE INDEX schema_mapping_versions_tenant_confirmed_idx
    ON pulseiq.schema_mapping_versions (organization_id, workspace_id, confirmed_at DESC)
    INCLUDE (mapping_version_id, dataset_id, dataset_version_id);

CREATE FUNCTION pulseiq.reject_schema_mapping_mutation() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    RAISE EXCEPTION 'confirmed schema mapping versions are immutable'
        USING ERRCODE = '55000';
END;
$$;

REVOKE ALL ON FUNCTION pulseiq.reject_schema_mapping_mutation() FROM PUBLIC;

CREATE TRIGGER schema_mapping_versions_reject_mutation
    BEFORE UPDATE OR DELETE ON pulseiq.schema_mapping_versions
    FOR EACH ROW EXECUTE FUNCTION pulseiq.reject_schema_mapping_mutation();

CREATE TRIGGER schema_mapping_fields_reject_mutation
    BEFORE UPDATE OR DELETE ON pulseiq.schema_mapping_fields
    FOR EACH ROW EXECUTE FUNCTION pulseiq.reject_schema_mapping_mutation();

ALTER TABLE pulseiq.schema_mapping_versions ENABLE ALWAYS TRIGGER schema_mapping_versions_reject_mutation;
ALTER TABLE pulseiq.schema_mapping_fields ENABLE ALWAYS TRIGGER schema_mapping_fields_reject_mutation;
ALTER TABLE pulseiq.schema_mapping_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.schema_mapping_versions FORCE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.schema_mapping_fields ENABLE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.schema_mapping_fields FORCE ROW LEVEL SECURITY;

CREATE POLICY schema_mapping_versions_current_tenant_select ON pulseiq.schema_mapping_versions
    FOR SELECT TO pulseiq_app
    USING (
        organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
        AND workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
    );

CREATE POLICY schema_mapping_versions_current_tenant_insert ON pulseiq.schema_mapping_versions
    FOR INSERT TO pulseiq_app
    WITH CHECK (
        organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
        AND workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
        AND confirmed_by = NULLIF(current_setting('pulseiq.actor_id', true), '')::uuid
    );

CREATE POLICY schema_mapping_fields_current_tenant_select ON pulseiq.schema_mapping_fields
    FOR SELECT TO pulseiq_app
    USING (
        EXISTS (
            SELECT 1 FROM pulseiq.schema_mapping_versions AS mapping
            WHERE mapping.mapping_version_id = schema_mapping_fields.mapping_version_id
              AND mapping.organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
              AND mapping.workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
        )
    );

CREATE POLICY schema_mapping_fields_current_tenant_insert ON pulseiq.schema_mapping_fields
    FOR INSERT TO pulseiq_app
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM pulseiq.schema_mapping_versions AS mapping
            WHERE mapping.mapping_version_id = schema_mapping_fields.mapping_version_id
              AND mapping.organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
              AND mapping.workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
        )
    );

GRANT SELECT, INSERT ON pulseiq.schema_mapping_versions TO pulseiq_app;
GRANT SELECT, INSERT ON pulseiq.schema_mapping_fields TO pulseiq_app;

COMMIT;
