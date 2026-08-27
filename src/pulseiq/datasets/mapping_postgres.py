"""Request-scoped PostgreSQL persistence for confirmed schema mappings."""

from __future__ import annotations

from uuid import UUID

from psycopg.types.json import Jsonb

from pulseiq.audit import AuditEvent
from pulseiq.postgres import PostgresRequestRepository

from .mapping import ArtifactMappingContext, SchemaMappingVersion
from .normalization import NormalizedArtifactField
from .upload_contracts import DatasetVersionStatus, ImportJob


class PostgresSchemaMappingRepository(PostgresRequestRepository):
    """Read trusted artifact schema and atomically confirm mapping/validation work."""

    def get_context(
        self,
        *,
        dataset_version_id: str,
        organization_id: str,
        workspace_id: str,
    ) -> ArtifactMappingContext | None:
        self._require_scope(organization_id, workspace_id)
        UUID(dataset_version_id)
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT version.dataset_version_id::text, version.dataset_id::text,
                       version.organization_id::text, version.workspace_id::text,
                       version.revision, version.status,
                       encode(artifact.schema_fingerprint, 'hex')
                FROM pulseiq.dataset_versions AS version
                JOIN pulseiq.dataset_artifacts AS artifact USING (
                    dataset_version_id, organization_id, workspace_id
                )
                WHERE version.dataset_version_id = %s
                  AND version.organization_id = %s
                  AND version.workspace_id = %s
                """,
                (dataset_version_id, organization_id, workspace_id),
                prepare=True,
            ).fetchone()
            if row is None:
                return None
            field_rows = connection.execute(
                """
                SELECT position, source_column, normalized_column, physical_type, nullable
                FROM pulseiq.dataset_artifact_fields
                WHERE dataset_version_id = %s
                ORDER BY position
                """,
                (dataset_version_id,),
                prepare=True,
            ).fetchall()
        return ArtifactMappingContext(
            dataset_version_id=str(row[0]),
            dataset_id=str(row[1]),
            organization_id=str(row[2]),
            workspace_id=str(row[3]),
            dataset_revision=int(row[4]),
            status=DatasetVersionStatus(str(row[5])),
            schema_fingerprint=str(row[6]),
            fields=tuple(
                NormalizedArtifactField(
                    position=int(field[0]),
                    source_column=str(field[1]),
                    normalized_column=str(field[2]),
                    physical_type=str(field[3]),
                    nullable=bool(field[4]),
                )
                for field in field_rows
            ),
        )

    def confirm_and_enqueue(
        self,
        mapping: SchemaMappingVersion,
        validation_job: ImportJob,
        audit_event: AuditEvent,
        *,
        expected_revision: int,
    ) -> None:
        self._require_scope(mapping.organization_id, mapping.workspace_id)
        if (
            validation_job.organization_id != mapping.organization_id
            or validation_job.workspace_id != mapping.workspace_id
            or validation_job.job_type != "dataset.validate"
            or validation_job.input_reference.get("dataset_version_id") != mapping.dataset_version_id
            or validation_job.input_reference.get("mapping_version_id") != mapping.mapping_version_id
        ):
            raise ValueError("Validation job does not match the confirmed mapping.")
        for identifier in (
            mapping.mapping_version_id,
            mapping.dataset_version_id,
            mapping.dataset_id,
            validation_job.job_id,
        ):
            UUID(identifier)
        with self._transaction() as connection:
            changed = connection.execute(
                """
                UPDATE pulseiq.dataset_versions
                SET status = 'validating', revision = revision + 1
                WHERE dataset_version_id = %s
                  AND organization_id = %s
                  AND workspace_id = %s
                  AND status = 'mapping_required'
                  AND revision = %s
                RETURNING dataset_version_id
                """,
                (
                    mapping.dataset_version_id,
                    mapping.organization_id,
                    mapping.workspace_id,
                    expected_revision,
                ),
                prepare=True,
            ).fetchone()
            if changed is None:
                raise RuntimeError("Dataset mapping lifecycle is no longer current.")
            connection.execute(
                """
                INSERT INTO pulseiq.schema_mapping_versions (
                    mapping_version_id, organization_id, workspace_id, dataset_id,
                    dataset_version_id, schema_fingerprint, confirmed_by,
                    confirmed_at, request_id, reason
                ) VALUES (%s, %s, %s, %s, %s, decode(%s, 'hex'), %s, %s, %s, %s)
                """,
                (
                    mapping.mapping_version_id,
                    mapping.organization_id,
                    mapping.workspace_id,
                    mapping.dataset_id,
                    mapping.dataset_version_id,
                    mapping.schema_fingerprint,
                    mapping.confirmed_by,
                    mapping.confirmed_at,
                    audit_event.request_id,
                    mapping.reason,
                ),
                prepare=True,
            )
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO pulseiq.schema_mapping_fields (
                        mapping_version_id, dataset_version_id, source_column,
                        normalized_column, governed_concept, target_type, nullable,
                        unit_semantics, currency_mode, currency_code, period_semantics,
                        amount_direction, time_semantics
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        (
                            mapping.mapping_version_id,
                            mapping.dataset_version_id,
                            field.source_column,
                            field.normalized_column,
                            field.concept.value,
                            field.target_type.value,
                            field.nullable,
                            field.unit.value,
                            field.currency_mode.value,
                            field.currency_code,
                            field.period.value,
                            field.amount_direction.value,
                            field.time_semantics.value,
                        )
                        for field in mapping.fields
                    ),
                )
            connection.execute(
                """
                INSERT INTO pulseiq.import_jobs (
                    job_id, organization_id, workspace_id, dataset_version_id,
                    job_type, status, input_reference, idempotency_key,
                    attempts, available_at, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    validation_job.job_id,
                    mapping.organization_id,
                    mapping.workspace_id,
                    mapping.dataset_version_id,
                    validation_job.job_type,
                    validation_job.status.value,
                    Jsonb(dict(validation_job.input_reference)),
                    validation_job.idempotency_key,
                    validation_job.attempts,
                    validation_job.created_at,
                    validation_job.created_at,
                ),
                prepare=True,
            )
            self._insert_audit(connection, audit_event)
