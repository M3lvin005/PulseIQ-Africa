BEGIN;

CREATE POLICY dataset_versions_worker_select ON pulseiq.dataset_versions
    FOR SELECT TO pulseiq_worker
    USING (true);

CREATE POLICY dataset_versions_worker_update ON pulseiq.dataset_versions
    FOR UPDATE TO pulseiq_worker
    USING (true)
    WITH CHECK (true);

GRANT SELECT ON pulseiq.dataset_versions TO pulseiq_worker;
GRANT UPDATE (status, revision, failure_code) ON pulseiq.dataset_versions TO pulseiq_worker;

COMMIT;
