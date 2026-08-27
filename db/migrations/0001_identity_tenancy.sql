BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS btree_gist;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

CREATE SCHEMA pulseiq;
REVOKE ALL ON SCHEMA pulseiq FROM PUBLIC;

CREATE TABLE pulseiq.organizations (
    organization_id uuid PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE pulseiq.workspaces (
    workspace_id uuid PRIMARY KEY,
    organization_id uuid NOT NULL REFERENCES pulseiq.organizations (organization_id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, workspace_id)
);

CREATE TABLE pulseiq.actors (
    actor_id uuid PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE pulseiq.memberships (
    membership_id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES pulseiq.actors (actor_id),
    organization_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    role text NOT NULL CHECK (
        role IN ('admin', 'data_steward', 'analyst', 'risk_reviewer', 'approver', 'auditor', 'read_only')
    ),
    status text NOT NULL CHECK (status IN ('invited', 'active', 'revoked')),
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    activated_at timestamptz,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT memberships_workspace_tenant_fk
        FOREIGN KEY (organization_id, workspace_id)
        REFERENCES pulseiq.workspaces (organization_id, workspace_id),
    CONSTRAINT memberships_lifecycle_check CHECK (
        (status = 'invited' AND activated_at IS NULL AND revoked_at IS NULL)
        OR (status = 'active' AND activated_at IS NOT NULL AND revoked_at IS NULL)
        OR (
            status = 'revoked'
            AND activated_at IS NOT NULL
            AND revoked_at IS NOT NULL
            AND revoked_at >= activated_at
        )
    )
);

CREATE UNIQUE INDEX memberships_one_active_actor_workspace_idx
    ON pulseiq.memberships (actor_id, organization_id, workspace_id)
    WHERE status = 'active';

CREATE INDEX memberships_active_actor_scope_idx
    ON pulseiq.memberships (actor_id, organization_id, workspace_id)
    INCLUDE (membership_id, role, revision, activated_at)
    WHERE status = 'active';

CREATE TABLE pulseiq.sessions (
    session_id uuid PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES pulseiq.actors (actor_id),
    authenticated_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    status text NOT NULL CHECK (status IN ('active', 'revoked')),
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (expires_at > authenticated_at),
    CHECK (
        (status = 'active' AND revoked_at IS NULL)
        OR (
            status = 'revoked'
            AND revoked_at IS NOT NULL
            AND revoked_at >= authenticated_at
        )
    )
);

CREATE INDEX sessions_active_lookup_idx
    ON pulseiq.sessions (session_id, actor_id)
    INCLUDE (authenticated_at, expires_at, revision)
    WHERE status = 'active';

CREATE TABLE pulseiq.workspace_invitations (
    invitation_id uuid PRIMARY KEY,
    organization_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    email_binding bytea NOT NULL CHECK (octet_length(email_binding) = 32),
    role text NOT NULL CHECK (
        role IN ('admin', 'data_steward', 'analyst', 'risk_reviewer', 'approver', 'auditor', 'read_only')
    ),
    status text NOT NULL CHECK (status IN ('pending', 'accepted', 'expired', 'revoked')),
    token_digest bytea NOT NULL UNIQUE CHECK (octet_length(token_digest) = 32),
    issued_by uuid NOT NULL REFERENCES pulseiq.actors (actor_id),
    issued_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    accepted_by uuid REFERENCES pulseiq.actors (actor_id),
    accepted_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT workspace_invitations_workspace_tenant_fk
        FOREIGN KEY (organization_id, workspace_id)
        REFERENCES pulseiq.workspaces (organization_id, workspace_id),
    CHECK (expires_at > issued_at),
    CHECK (
        (
            status = 'accepted'
            AND accepted_by IS NOT NULL
            AND accepted_at IS NOT NULL
            AND accepted_at >= issued_at
            AND accepted_at < expires_at
        )
        OR (status <> 'accepted' AND accepted_by IS NULL AND accepted_at IS NULL)
    )
);

ALTER TABLE pulseiq.workspace_invitations
    ADD CONSTRAINT workspace_invitations_no_overlapping_pending_recipient
    EXCLUDE USING gist (
        organization_id WITH =,
        workspace_id WITH =,
        email_binding WITH =,
        tstzrange(issued_at, expires_at, '[)') WITH &&
    ) WHERE (status = 'pending');

CREATE INDEX workspace_invitations_tenant_status_expiry_idx
    ON pulseiq.workspace_invitations (organization_id, workspace_id, status, expires_at)
    INCLUDE (invitation_id, role, revision, issued_by);

CREATE TABLE pulseiq.audit_chain_heads (
    organization_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    last_sequence bigint NOT NULL CHECK (last_sequence >= 0),
    last_hash bytea NOT NULL CHECK (octet_length(last_hash) = 32),
    PRIMARY KEY (organization_id, workspace_id),
    CONSTRAINT audit_chain_heads_workspace_tenant_fk
        FOREIGN KEY (organization_id, workspace_id)
        REFERENCES pulseiq.workspaces (organization_id, workspace_id)
);

CREATE TABLE pulseiq.audit_events (
    audit_sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id uuid NOT NULL UNIQUE,
    occurred_at timestamptz NOT NULL,
    organization_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    actor_id uuid NOT NULL REFERENCES pulseiq.actors (actor_id),
    action text NOT NULL CHECK (length(action) BETWEEN 1 AND 120),
    target_type text NOT NULL CHECK (length(target_type) BETWEEN 1 AND 80),
    target_id uuid NOT NULL,
    request_id uuid NOT NULL,
    reason text NOT NULL CHECK (length(reason) BETWEEN 1 AND 1000),
    before_hash text NOT NULL CHECK (before_hash ~ '^sha256:[0-9a-f]{64}$'),
    after_hash text NOT NULL CHECK (after_hash ~ '^sha256:[0-9a-f]{64}$'),
    previous_event_hash bytea NOT NULL CHECK (octet_length(previous_event_hash) = 32),
    event_hash bytea NOT NULL CHECK (octet_length(event_hash) = 32),
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT audit_events_workspace_tenant_fk
        FOREIGN KEY (organization_id, workspace_id)
        REFERENCES pulseiq.workspaces (organization_id, workspace_id)
);

CREATE INDEX audit_events_tenant_time_idx
    ON pulseiq.audit_events (organization_id, workspace_id, occurred_at DESC, audit_sequence DESC)
    INCLUDE (event_id, action, target_type, target_id, actor_id);

CREATE TABLE pulseiq.outbox_events (
    outbox_sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    topic text NOT NULL CHECK (length(topic) BETWEEN 1 AND 120),
    aggregate_id uuid NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    available_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    published_at timestamptz,
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (published_at IS NULL OR published_at >= created_at)
);

CREATE INDEX outbox_events_pending_idx
    ON pulseiq.outbox_events (available_at, outbox_sequence)
    INCLUDE (topic, aggregate_id, attempts)
    WHERE published_at IS NULL;

CREATE FUNCTION pulseiq.prepare_audit_event() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pulseiq, public
AS $$
DECLARE
    chain_hash bytea;
BEGIN
    INSERT INTO pulseiq.audit_chain_heads (
        organization_id, workspace_id, last_sequence, last_hash
    ) VALUES (
        NEW.organization_id,
        NEW.workspace_id,
        0,
        public.digest(''::bytea, 'sha256')
    ) ON CONFLICT (organization_id, workspace_id) DO NOTHING;

    SELECT last_hash
    INTO STRICT chain_hash
    FROM pulseiq.audit_chain_heads
    WHERE organization_id = NEW.organization_id
      AND workspace_id = NEW.workspace_id
    FOR UPDATE;

    NEW.previous_event_hash := chain_hash;
    NEW.event_hash := public.digest(
        pg_catalog.convert_to(
            pg_catalog.jsonb_build_object(
                'action', NEW.action,
                'actor_id', NEW.actor_id,
                'after_hash', NEW.after_hash,
                'audit_sequence', NEW.audit_sequence,
                'before_hash', NEW.before_hash,
                'event_id', NEW.event_id,
                'occurred_at', NEW.occurred_at,
                'organization_id', NEW.organization_id,
                'previous_event_hash', pg_catalog.encode(chain_hash, 'hex'),
                'reason', NEW.reason,
                'request_id', NEW.request_id,
                'target_id', NEW.target_id,
                'target_type', NEW.target_type,
                'workspace_id', NEW.workspace_id
            )::text,
            'UTF8'
        ),
        'sha256'
    );

    UPDATE pulseiq.audit_chain_heads
    SET last_sequence = NEW.audit_sequence,
        last_hash = NEW.event_hash
    WHERE organization_id = NEW.organization_id
      AND workspace_id = NEW.workspace_id;

    RETURN NEW;
END;
$$;

CREATE FUNCTION pulseiq.outbox_audit_event() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pulseiq
AS $$
BEGIN
    INSERT INTO pulseiq.outbox_events (topic, aggregate_id, payload)
    VALUES (
        'audit.recorded',
        NEW.event_id,
        pg_catalog.jsonb_build_object(
            'action', NEW.action,
            'actor_id', NEW.actor_id,
            'audit_sequence', NEW.audit_sequence,
            'event_hash', pg_catalog.encode(NEW.event_hash, 'hex'),
            'event_id', NEW.event_id,
            'organization_id', NEW.organization_id,
            'target_id', NEW.target_id,
            'target_type', NEW.target_type,
            'workspace_id', NEW.workspace_id
        )
    );
    RETURN NEW;
END;
$$;

CREATE FUNCTION pulseiq.reject_audit_mutation() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    RAISE EXCEPTION 'audit events are append-only' USING ERRCODE = '55000';
END;
$$;

REVOKE ALL ON FUNCTION pulseiq.prepare_audit_event() FROM PUBLIC;
REVOKE ALL ON FUNCTION pulseiq.outbox_audit_event() FROM PUBLIC;
REVOKE ALL ON FUNCTION pulseiq.reject_audit_mutation() FROM PUBLIC;

CREATE TRIGGER audit_events_prepare_before_insert
    BEFORE INSERT ON pulseiq.audit_events
    FOR EACH ROW EXECUTE FUNCTION pulseiq.prepare_audit_event();

CREATE TRIGGER audit_events_outbox_after_insert
    AFTER INSERT ON pulseiq.audit_events
    FOR EACH ROW EXECUTE FUNCTION pulseiq.outbox_audit_event();

CREATE TRIGGER audit_events_reject_mutation
    BEFORE UPDATE OR DELETE ON pulseiq.audit_events
    FOR EACH ROW EXECUTE FUNCTION pulseiq.reject_audit_mutation();

ALTER TABLE pulseiq.audit_events ENABLE ALWAYS TRIGGER audit_events_prepare_before_insert;
ALTER TABLE pulseiq.audit_events ENABLE ALWAYS TRIGGER audit_events_outbox_after_insert;
ALTER TABLE pulseiq.audit_events ENABLE ALWAYS TRIGGER audit_events_reject_mutation;

ALTER TABLE pulseiq.organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.organizations FORCE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.workspaces FORCE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.actors ENABLE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.actors FORCE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.memberships FORCE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.sessions FORCE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.workspace_invitations ENABLE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.workspace_invitations FORCE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE pulseiq.audit_events FORCE ROW LEVEL SECURITY;

CREATE POLICY organizations_current_tenant_select ON pulseiq.organizations
    FOR SELECT TO pulseiq_app
    USING (
        organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
    );

CREATE POLICY workspaces_current_tenant_select ON pulseiq.workspaces
    FOR SELECT TO pulseiq_app
    USING (
        organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
        AND workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
    );

CREATE POLICY actors_current_actor_select ON pulseiq.actors
    FOR SELECT TO pulseiq_app
    USING (
        actor_id = NULLIF(current_setting('pulseiq.actor_id', true), '')::uuid
    );

CREATE POLICY memberships_current_tenant_select ON pulseiq.memberships
    FOR SELECT TO pulseiq_app
    USING (
        organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
        AND workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
    );

CREATE POLICY memberships_current_tenant_insert ON pulseiq.memberships
    FOR INSERT TO pulseiq_app
    WITH CHECK (
        organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
        AND workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
    );

CREATE POLICY memberships_current_tenant_update ON pulseiq.memberships
    FOR UPDATE TO pulseiq_app
    USING (
        organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
        AND workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
    )
    WITH CHECK (
        organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
        AND workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
    );

CREATE POLICY sessions_current_actor_select ON pulseiq.sessions
    FOR SELECT TO pulseiq_app
    USING (
        actor_id = NULLIF(current_setting('pulseiq.actor_id', true), '')::uuid
    );

CREATE POLICY sessions_current_actor_update ON pulseiq.sessions
    FOR UPDATE TO pulseiq_app
    USING (
        actor_id = NULLIF(current_setting('pulseiq.actor_id', true), '')::uuid
    )
    WITH CHECK (
        actor_id = NULLIF(current_setting('pulseiq.actor_id', true), '')::uuid
    );

CREATE POLICY workspace_invitations_current_tenant_select ON pulseiq.workspace_invitations
    FOR SELECT TO pulseiq_app
    USING (
        organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
        AND workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
    );

CREATE POLICY workspace_invitations_current_tenant_insert ON pulseiq.workspace_invitations
    FOR INSERT TO pulseiq_app
    WITH CHECK (
        organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
        AND workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
    );

CREATE POLICY workspace_invitations_current_tenant_update ON pulseiq.workspace_invitations
    FOR UPDATE TO pulseiq_app
    USING (
        organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
        AND workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
    )
    WITH CHECK (
        organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
        AND workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
    );

CREATE POLICY audit_events_current_tenant_select ON pulseiq.audit_events
    FOR SELECT TO pulseiq_app
    USING (
        organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
        AND workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
    );

CREATE POLICY audit_events_current_tenant_insert ON pulseiq.audit_events
    FOR INSERT TO pulseiq_app
    WITH CHECK (
        organization_id = NULLIF(current_setting('pulseiq.organization_id', true), '')::uuid
        AND workspace_id = NULLIF(current_setting('pulseiq.workspace_id', true), '')::uuid
        AND actor_id = NULLIF(current_setting('pulseiq.actor_id', true), '')::uuid
    );

GRANT USAGE ON SCHEMA pulseiq TO pulseiq_app;
GRANT SELECT ON pulseiq.organizations, pulseiq.workspaces, pulseiq.actors TO pulseiq_app;
GRANT SELECT, INSERT, UPDATE ON pulseiq.memberships TO pulseiq_app;
GRANT SELECT, UPDATE ON pulseiq.sessions TO pulseiq_app;
GRANT SELECT, INSERT, UPDATE ON pulseiq.workspace_invitations TO pulseiq_app;
GRANT SELECT, INSERT ON pulseiq.audit_events TO pulseiq_app;
GRANT SELECT, UPDATE ON pulseiq.outbox_events TO pulseiq_worker;

COMMIT;
