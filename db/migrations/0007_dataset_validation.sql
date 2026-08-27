BEGIN;

ALTER TABLE pulseiq.dataset_artifacts
    ADD CONSTRAINT dataset_artifacts_version_digest_uk
    UNIQUE (dataset_version_id, artifact_sha256, schema_fingerprint);

CREATE TABLE pulseiq.validation_runs (
    validation_run_id uuid PRIMARY KEY,
    organization_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    dataset_version_id uuid NOT NULL,
    mapping_version_id uuid NOT NULL,
    validation_policy_version text NOT NULL CHECK (length(validation_policy_version) BETWEEN 1 AND 120),
    definition_version text NOT NULL CHECK (length(definition_version) BETWEEN 1 AND 120),
    artifact_sha256 bytea NOT NULL CHECK (octet_length(artifact_sha256) = 32),
    schema_fingerprint bytea NOT NULL CHECK (octet_length(schema_fingerprint) = 32),
    status text NOT NULL CHECK (status = 'completed'),
    verdict text NOT NULL CHECK (verdict IN ('passed', 'blocked')),
    row_count integer NOT NULL CHECK (row_count BETWEEN 1 AND 100000),
    column_count smallint NOT NULL CHECK (column_count BETWEEN 1 AND 200),
    composite_score numeric(5, 2) NOT NULL CHECK (composite_score BETWEEN 0 AND 100),
    block_count integer NOT NULL CHECK (block_count >= 0),
    warn_count integer NOT NULL CHECK (warn_count >= 0),
    info_count integer NOT NULL CHECK (info_count >= 0),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz NOT NULL,
    UNIQUE (mapping_version_id, validation_policy_version),
    UNIQUE (organization_id, workspace_id, validation_run_id),
    CONSTRAINT validation_runs_mapping_fk
        FOREIGN KEY (mapping_version_id, dataset_version_id)
        REFERENCES pulseiq.schema_mapping_versions (mapping_version_id, dataset_version_id),
    CONSTRAINT validation_runs_artifact_fk
        FOREIGN KEY (dataset_version_id, artifact_sha256, schema_fingerprint)
        REFERENCES pulseiq.dataset_artifacts (dataset_version_id, artifact_sha256, schema_fingerprint),
    CONSTRAINT validation_runs_dataset_tenant_fk
        FOREIGN KEY (organization_id, workspace_id, dataset_version_id)
        REFERENCES pulseiq.dataset_versions (organization_id, workspace_id, dataset_version_id),
    CHECK (completed_at >= created_at),
    CHECK (block_count + warn_count + info_count >= 0)
);

CREATE TABLE pulseiq.validation_dimension_scores (
    validation_run_id uuid NOT NULL REFERENCES pulseiq.validation_runs (validation_run_id),
    dimension text NOT NULL CHECK (
        dimension IN ('completeness', 'validity', 'uniqueness', 'consistency', 'timeliness', 'fitness')
    ),
    score numeric(5, 2) NOT NULL CHECK (score BETWEEN 0 AND 100),
    PRIMARY KEY (validation_run_id, dimension)
);

CREATE TABLE pulseiq.validation_capability_results (
    validation_run_id uuid NOT NULL REFERENCES pulseiq.validation_runs (validation_run_id),
    capability text NOT NULL CHECK (
        capability IN (
            'quality_review', 'transaction_analytics', 'customer_analytics',
            'repayment_analytics', 'risk_rule_evaluation', 'model_exploration'
        )
    ),
    status text NOT NULL CHECK (status IN ('ready', 'blocked')),
    PRIMARY KEY (validation_run_id, capability)
);

CREATE TABLE pulseiq.validation_issues (
    validation_run_id uuid NOT NULL REFERENCES pulseiq.validation_runs (validation_run_id),
    issue_ordinal smallint NOT NULL CHECK (issue_ordinal BETWEEN 1 AND 1000),
    rule_id text NOT NULL CHECK (rule_id ~ '^[a-z][a-z0-9_]{0,119}$'),
    rule_version text NOT NULL CHECK (length(rule_version) BETWEEN 1 AND 120),
    severity text NOT NULL CHECK (severity IN ('block', 'warn', 'info')),
    dimension text NOT NULL CHECK (
        dimension IN ('completeness', 'validity', 'uniqueness', 'consistency', 'timeliness', 'fitness')
    ),
    normalized_column text CHECK (
        normalized_column IS NULL OR normalized_column ~ '^[a-z][a-z0-9_]{0,127}$'
    ),
    affected_count integer CHECK (affected_count IS NULL OR affected_count >= 0),
    message text NOT NULL CHECK (length(message) BETWEEN 1 AND 1000),
    recovery text NOT NULL CHECK (length(recovery) BETWEEN 1 AND 1000),
    override_allowed boolean NOT NULL,
    PRIMARY KEY (validation_run_id, issue_ordinal),
    CHECK (NOT override_allowed OR severity = 'warn')
);

CREATE TABLE pulseiq.validation_issue_capabilities (
    validation_run_id uuid NOT NULL,
    issue_ordinal smallint NOT NULL,
    capability text NOT NULL CHECK (
        capability IN (
            'quality_review', 'transaction_analytics', 'customer_analytics',
            'repayment_analytics', 'risk_rule_evaluation', 'model_exploration'
        )
    ),
    PRIMARY KEY (validation_run_id, issue_ordinal, capability),
    FOREIGN KEY (validation_run_id, issue_ordinal)
        REFERENCES pulseiq.validation_issues (validation_run_id, issue_ordinal)
);

CREATE TABLE pulseiq.validation_issue_examples (
    validation_run_id uuid NOT NULL,
    issue_ordinal smallint NOT NULL,
    example_ordinal smallint NOT NULL CHECK (example_ordinal BETWEEN 1 AND 3),
    masked_hash text NOT NULL CHECK (masked_hash ~ '^sha256:[0-9a-f]{16}$'),
    PRIMARY KEY (validation_run_id, issue_ordinal, example_ordinal),
    FOREIGN KEY (validation_run_id, issue_ordinal)
        REFERENCES pulseiq.validation_issues (validation_run_id, issue_ordinal)
);

CREATE INDEX validation_runs_tenant_completed_idx
    ON pulseiq.validation_runs (organization_id, workspace_id, completed_at DESC)
    INCLUDE (dataset_version_id, mapping_version_id, verdict, composite_score);

CREATE INDEX validation_issues_rule_idx
    ON pulseiq.validation_issues (rule_id, severity, validation_run_id);

CREATE FUNCTION pulseiq.reject_validation_result_mutation() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    RAISE EXCEPTION 'completed validation evidence is immutable'
        USING ERRCODE = '55000';
END;
$$;

REVOKE ALL ON FUNCTION pulseiq.reject_validation_result_mutation() FROM PUBLIC;

CREATE TRIGGER validation_runs_reject_mutation
    BEFORE UPDATE OR DELETE ON pulseiq.validation_runs
    FOR EACH ROW EXECUTE FUNCTION pulseiq.reject_validation_result_mutation();
CREATE TRIGGER validation_dimension_scores_reject_mutation
    BEFORE UPDATE OR DELETE ON pulseiq.validation_dimension_scores
    FOR EACH ROW EXECUTE FUNCTION pulseiq.reject_validation_result_mutation();
CREATE TRIGGER validation_capability_results_reject_mutation
    BEFORE UPDATE OR DELETE ON pulseiq.validation_capability_results
    FOR EACH ROW EXECUTE FUNCTION pulseiq.reject_validation_result_mutation();
CREATE TRIGGER validation_issues_reject_mutation
    BEFORE UPDATE OR DELETE ON pulseiq.validation_issues
    FOR EACH ROW EXECUTE FUNCTION pulseiq.reject_validation_result_mutation();
CREATE TRIGGER validation_issue_capabilities_reject_mutation
    BEFORE UPDATE OR DELETE ON pulseiq.validation_issue_capabilities
    FOR EACH ROW EXECUTE FUNCTION pulseiq.reject_validation_result_mutation();
CREATE TRIGGER validation_issue_examples_reject_mutation
    BEFORE UPDATE OR DELETE ON pulseiq.validation_issue_examples
    FOR EACH ROW EXECUTE FUNCTION pulseiq.reject_validation_result_mutation();

ALTER TABLE pulseiq.validation_runs ENABLE ALWAYS TRIGGER validation_runs_reject_mutation;
ALTER TABLE pulseiq.validation_dimension_scores ENABLE ALWAYS TRIGGER validation_dimension_scores_reject_mutation;
ALTER TABLE pulseiq.validation_capability_results ENABLE ALWAYS TRIGGER validation_capability_results_reject_mutation;
ALTER TABLE pulseiq.validation_issues ENABLE ALWAYS TRIGGER validation_issues_reject_mutation;
ALTER TABLE pulseiq.validation_issue_capabilities ENABLE ALWAYS TRIGGER validation_issue_capabilities_reject_mutation;
ALTER TABLE pulseiq.validation_issue_examples ENABLE ALWAYS TRIGGER validation_issue_examples_reject_mutation;

ALTER TABLE pulseiq.validation_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.validation_runs FORCE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.validation_dimension_scores ENABLE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.validation_dimension_scores FORCE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.validation_capability_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.validation_capability_results FORCE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.validation_issues ENABLE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.validation_issues FORCE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.validation_issue_capabilities ENABLE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.validation_issue_capabilities FORCE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.validation_issue_examples ENABLE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.validation_issue_examples FORCE ROW LEVEL SECURITY;

CREATE POLICY validation_runs_current_tenant_select ON pulseiq.validation_runs
    FOR SELECT TO pulseiq_app
    USING (
        organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
        AND workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
    );
CREATE POLICY validation_runs_worker_select ON pulseiq.validation_runs
    FOR SELECT TO pulseiq_worker USING (true);
CREATE POLICY validation_runs_worker_insert ON pulseiq.validation_runs
    FOR INSERT TO pulseiq_worker WITH CHECK (true);

CREATE POLICY validation_dimension_scores_current_tenant_select ON pulseiq.validation_dimension_scores
    FOR SELECT TO pulseiq_app USING (
        EXISTS (
            SELECT 1 FROM pulseiq.validation_runs AS run
            WHERE run.validation_run_id = validation_dimension_scores.validation_run_id
              AND run.organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
              AND run.workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
        )
    );
CREATE POLICY validation_dimension_scores_worker_select ON pulseiq.validation_dimension_scores
    FOR SELECT TO pulseiq_worker USING (true);
CREATE POLICY validation_dimension_scores_worker_insert ON pulseiq.validation_dimension_scores
    FOR INSERT TO pulseiq_worker WITH CHECK (true);

CREATE POLICY validation_capability_results_current_tenant_select ON pulseiq.validation_capability_results
    FOR SELECT TO pulseiq_app USING (
        EXISTS (
            SELECT 1 FROM pulseiq.validation_runs AS run
            WHERE run.validation_run_id = validation_capability_results.validation_run_id
              AND run.organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
              AND run.workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
        )
    );
CREATE POLICY validation_capability_results_worker_select ON pulseiq.validation_capability_results
    FOR SELECT TO pulseiq_worker USING (true);
CREATE POLICY validation_capability_results_worker_insert ON pulseiq.validation_capability_results
    FOR INSERT TO pulseiq_worker WITH CHECK (true);

CREATE POLICY validation_issues_current_tenant_select ON pulseiq.validation_issues
    FOR SELECT TO pulseiq_app USING (
        EXISTS (
            SELECT 1 FROM pulseiq.validation_runs AS run
            WHERE run.validation_run_id = validation_issues.validation_run_id
              AND run.organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
              AND run.workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
        )
    );
CREATE POLICY validation_issues_worker_select ON pulseiq.validation_issues
    FOR SELECT TO pulseiq_worker USING (true);
CREATE POLICY validation_issues_worker_insert ON pulseiq.validation_issues
    FOR INSERT TO pulseiq_worker WITH CHECK (true);

CREATE POLICY validation_issue_capabilities_current_tenant_select ON pulseiq.validation_issue_capabilities
    FOR SELECT TO pulseiq_app USING (
        EXISTS (
            SELECT 1 FROM pulseiq.validation_runs AS run
            WHERE run.validation_run_id = validation_issue_capabilities.validation_run_id
              AND run.organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
              AND run.workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
        )
    );
CREATE POLICY validation_issue_capabilities_worker_select ON pulseiq.validation_issue_capabilities
    FOR SELECT TO pulseiq_worker USING (true);
CREATE POLICY validation_issue_capabilities_worker_insert ON pulseiq.validation_issue_capabilities
    FOR INSERT TO pulseiq_worker WITH CHECK (true);

CREATE POLICY validation_issue_examples_current_tenant_select ON pulseiq.validation_issue_examples
    FOR SELECT TO pulseiq_app USING (
        EXISTS (
            SELECT 1 FROM pulseiq.validation_runs AS run
            WHERE run.validation_run_id = validation_issue_examples.validation_run_id
              AND run.organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
              AND run.workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
        )
    );
CREATE POLICY validation_issue_examples_worker_select ON pulseiq.validation_issue_examples
    FOR SELECT TO pulseiq_worker USING (true);
CREATE POLICY validation_issue_examples_worker_insert ON pulseiq.validation_issue_examples
    FOR INSERT TO pulseiq_worker WITH CHECK (true);

CREATE POLICY schema_mapping_versions_worker_select ON pulseiq.schema_mapping_versions
    FOR SELECT TO pulseiq_worker USING (true);
CREATE POLICY schema_mapping_fields_worker_select ON pulseiq.schema_mapping_fields
    FOR SELECT TO pulseiq_worker USING (true);

GRANT SELECT ON pulseiq.schema_mapping_versions, pulseiq.schema_mapping_fields TO pulseiq_worker;
GRANT SELECT ON pulseiq.validation_runs, pulseiq.validation_dimension_scores,
    pulseiq.validation_capability_results, pulseiq.validation_issues,
    pulseiq.validation_issue_capabilities, pulseiq.validation_issue_examples TO pulseiq_app;
GRANT SELECT, INSERT ON pulseiq.validation_runs, pulseiq.validation_dimension_scores,
    pulseiq.validation_capability_results, pulseiq.validation_issues,
    pulseiq.validation_issue_capabilities, pulseiq.validation_issue_examples TO pulseiq_worker;

COMMIT;
