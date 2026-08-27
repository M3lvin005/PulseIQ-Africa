BEGIN;

CREATE TABLE pulseiq.validation_issue_overrides (
    override_id uuid PRIMARY KEY,
    organization_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    validation_run_id uuid NOT NULL,
    issue_ordinal smallint NOT NULL CHECK (issue_ordinal BETWEEN 1 AND 1000),
    overridden_by uuid NOT NULL REFERENCES pulseiq.actors (actor_id),
    overridden_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    request_id uuid NOT NULL,
    reason text NOT NULL CHECK (
        length(reason) BETWEEN 10 AND 1000
        AND reason = btrim(reason)
    ),
    UNIQUE (organization_id, workspace_id, request_id),
    UNIQUE (organization_id, workspace_id, override_id),
    CONSTRAINT validation_issue_overrides_run_tenant_fk
        FOREIGN KEY (organization_id, workspace_id, validation_run_id)
        REFERENCES pulseiq.validation_runs (organization_id, workspace_id, validation_run_id),
    CONSTRAINT validation_issue_overrides_issue_fk
        FOREIGN KEY (validation_run_id, issue_ordinal)
        REFERENCES pulseiq.validation_issues (validation_run_id, issue_ordinal),
    CONSTRAINT validation_issue_overrides_expiry_check CHECK (
        expires_at >= overridden_at + interval '15 minutes'
        AND expires_at <= overridden_at + interval '90 days'
    ),
    EXCLUDE USING gist (
        validation_run_id WITH =,
        issue_ordinal WITH =,
        tstzrange(overridden_at, expires_at, '[)') WITH &&
    )
);

CREATE INDEX validation_issue_overrides_tenant_expiry_idx
    ON pulseiq.validation_issue_overrides (
        organization_id, workspace_id, validation_run_id, expires_at DESC
    )
    INCLUDE (issue_ordinal, override_id, overridden_by);

CREATE FUNCTION pulseiq.reject_quality_override_mutation() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    RAISE EXCEPTION 'quality warning overrides are immutable'
        USING ERRCODE = '55000';
END;
$$;

REVOKE ALL ON FUNCTION pulseiq.reject_quality_override_mutation() FROM PUBLIC;

CREATE TRIGGER validation_issue_overrides_reject_mutation
    BEFORE UPDATE OR DELETE ON pulseiq.validation_issue_overrides
    FOR EACH ROW EXECUTE FUNCTION pulseiq.reject_quality_override_mutation();

ALTER TABLE pulseiq.validation_issue_overrides
    ENABLE ALWAYS TRIGGER validation_issue_overrides_reject_mutation;
ALTER TABLE pulseiq.validation_issue_overrides ENABLE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.validation_issue_overrides FORCE ROW LEVEL SECURITY;

CREATE POLICY validation_issue_overrides_current_tenant_select
    ON pulseiq.validation_issue_overrides
    FOR SELECT TO pulseiq_app
    USING (
        organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
        AND workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
    );

CREATE POLICY validation_issue_overrides_current_tenant_insert
    ON pulseiq.validation_issue_overrides
    FOR INSERT TO pulseiq_app
    WITH CHECK (
        organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
        AND workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
        AND overridden_by = NULLIF(current_setting('pulseiq.actor_id', true), '')::uuid
    );

GRANT SELECT, INSERT ON pulseiq.validation_issue_overrides TO pulseiq_app;

COMMIT;
