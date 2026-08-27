"""Worker-role PostgreSQL persistence for immutable dataset validation evidence."""

from __future__ import annotations

from uuid import UUID

from psycopg import Connection
from psycopg.rows import TupleRow
from psycopg_pool import ConnectionPool

from pulseiq.ingestion import GovernedConcept

from .contracts import IssueSeverity
from .mapping import (
    AmountDirection,
    ConfirmedFieldMapping,
    CurrencyMode,
    PeriodSemantics,
    SchemaMappingVersion,
    TargetType,
    TimeSemantics,
    UnitSemantics,
)
from .upload_contracts import DatasetVersionStatus
from .validation import ValidationContext, ValidationRun


class PostgresDatasetValidationRepository:
    """Load exact mapping lineage and atomically settle completed validation."""

    def __init__(self, pool: ConnectionPool[Connection[TupleRow]]) -> None:
        self._pool = pool

    def get_context(
        self,
        *,
        dataset_version_id: str,
        mapping_version_id: str,
        organization_id: str,
        workspace_id: str,
    ) -> ValidationContext | None:
        for identifier in (dataset_version_id, mapping_version_id, organization_id, workspace_id):
            UUID(identifier)
        with self._pool.connection() as connection, connection.transaction():
            row = connection.execute(
                """
                SELECT version.revision, version.status, artifact.object_key,
                       encode(artifact.artifact_sha256, 'hex'),
                       encode(artifact.schema_fingerprint, 'hex'),
                       artifact.row_count, artifact.column_count,
                       mapping.dataset_id::text, mapping.confirmed_by::text,
                       mapping.confirmed_at, mapping.reason,
                       run.validation_run_id::text
                FROM pulseiq.dataset_versions AS version
                JOIN pulseiq.dataset_artifacts AS artifact USING (
                    dataset_version_id, organization_id, workspace_id
                )
                JOIN pulseiq.schema_mapping_versions AS mapping USING (
                    dataset_version_id, organization_id, workspace_id
                )
                LEFT JOIN pulseiq.validation_runs AS run
                  ON run.mapping_version_id = mapping.mapping_version_id
                WHERE version.dataset_version_id = %s
                  AND mapping.mapping_version_id = %s
                  AND version.organization_id = %s
                  AND version.workspace_id = %s
                """,
                (dataset_version_id, mapping_version_id, organization_id, workspace_id),
                prepare=True,
            ).fetchone()
            if row is None:
                return None
            field_rows = connection.execute(
                """
                SELECT source_column, normalized_column, governed_concept,
                       target_type, nullable, unit_semantics, currency_mode,
                       currency_code, period_semantics, amount_direction, time_semantics
                FROM pulseiq.schema_mapping_fields
                WHERE mapping_version_id = %s AND dataset_version_id = %s
                ORDER BY source_column
                """,
                (mapping_version_id, dataset_version_id),
                prepare=True,
            ).fetchall()
        fingerprint = str(row[4])
        mapping = SchemaMappingVersion(
            mapping_version_id=mapping_version_id,
            dataset_version_id=dataset_version_id,
            dataset_id=str(row[7]),
            organization_id=organization_id,
            workspace_id=workspace_id,
            schema_fingerprint=fingerprint,
            fields=tuple(self._mapping_field(field) for field in field_rows),
            confirmed_by=str(row[8]),
            confirmed_at=row[9],
            reason=str(row[10]),
        )
        return ValidationContext(
            dataset_version_id=dataset_version_id,
            organization_id=organization_id,
            workspace_id=workspace_id,
            dataset_revision=int(row[0]),
            status=DatasetVersionStatus(str(row[1])),
            artifact_object_key=str(row[2]),
            artifact_sha256=str(row[3]),
            schema_fingerprint=fingerprint,
            artifact_row_count=int(row[5]),
            artifact_column_count=int(row[6]),
            mapping=mapping,
            existing_validation_run_id=str(row[11]) if row[11] is not None else None,
        )

    def complete_validation(self, run: ValidationRun, *, expected_revision: int) -> None:
        for identifier in (
            run.validation_run_id,
            run.organization_id,
            run.workspace_id,
            run.dataset_version_id,
            run.mapping_version_id,
        ):
            UUID(identifier)
        if expected_revision < 1 or len(run.assessment.issues) > 1000:
            raise ValueError("Validation persistence input is outside supported bounds.")
        block_count = sum(issue.severity is IssueSeverity.BLOCK for issue in run.assessment.issues)
        warn_count = sum(issue.severity is IssueSeverity.WARN for issue in run.assessment.issues)
        info_count = sum(issue.severity is IssueSeverity.INFO for issue in run.assessment.issues)
        expected_summary = (
            run.organization_id,
            run.workspace_id,
            run.dataset_version_id,
            run.mapping_version_id,
            run.validation_policy_version,
            run.assessment.definition_version,
            run.artifact_sha256,
            run.schema_fingerprint,
            "completed",
            run.verdict.value,
            run.assessment.rows,
            run.assessment.columns,
            round(run.assessment.composite_score, 2),
            block_count,
            warn_count,
            info_count,
        )
        with self._pool.connection() as connection, connection.transaction():
            connection.execute(
                """
                INSERT INTO pulseiq.validation_runs (
                    validation_run_id, organization_id, workspace_id,
                    dataset_version_id, mapping_version_id, validation_policy_version,
                    definition_version, artifact_sha256, schema_fingerprint,
                    status, verdict, row_count, column_count, composite_score,
                    block_count, warn_count, info_count, created_at, completed_at
                )
                SELECT %s, version.organization_id, version.workspace_id,
                       version.dataset_version_id, %s, %s, %s,
                       decode(%s, 'hex'), decode(%s, 'hex'),
                       'completed', %s, %s, %s, %s, %s, %s, %s, %s, %s
                FROM pulseiq.dataset_versions AS version
                WHERE version.dataset_version_id = %s
                  AND version.organization_id = %s
                  AND version.workspace_id = %s
                  AND version.status = 'validating'
                  AND version.revision = %s
                ON CONFLICT (validation_run_id) DO NOTHING
                """,
                (
                    run.validation_run_id,
                    run.mapping_version_id,
                    run.validation_policy_version,
                    run.assessment.definition_version,
                    run.artifact_sha256,
                    run.schema_fingerprint,
                    run.verdict.value,
                    run.assessment.rows,
                    run.assessment.columns,
                    run.assessment.composite_score,
                    block_count,
                    warn_count,
                    info_count,
                    run.completed_at,
                    run.completed_at,
                    run.dataset_version_id,
                    run.organization_id,
                    run.workspace_id,
                    expected_revision,
                ),
                prepare=True,
            )
            persisted = connection.execute(
                """
                SELECT organization_id::text, workspace_id::text, dataset_version_id::text,
                       mapping_version_id::text, validation_policy_version, definition_version,
                       encode(artifact_sha256, 'hex'), encode(schema_fingerprint, 'hex'),
                       status, verdict, row_count, column_count, composite_score::double precision,
                       block_count, warn_count, info_count
                FROM pulseiq.validation_runs
                WHERE validation_run_id = %s
                """,
                (run.validation_run_id,),
                prepare=True,
            ).fetchone()
            if persisted is None or self._normalized_summary(persisted) != expected_summary:
                raise RuntimeError("Validation evidence conflicts with persisted lineage.")
            self._insert_details(connection, run)
            changed = connection.execute(
                """
                UPDATE pulseiq.dataset_versions
                SET status = %s, failure_code = NULL, revision = revision + 1
                WHERE dataset_version_id = %s
                  AND organization_id = %s
                  AND workspace_id = %s
                  AND status = 'validating'
                  AND revision = %s
                RETURNING status
                """,
                (
                    run.dataset_status.value,
                    run.dataset_version_id,
                    run.organization_id,
                    run.workspace_id,
                    expected_revision,
                ),
                prepare=True,
            ).fetchone()
            if changed is None:
                current = connection.execute(
                    """
                    SELECT status
                    FROM pulseiq.dataset_versions
                    WHERE dataset_version_id = %s
                      AND organization_id = %s
                      AND workspace_id = %s
                    """,
                    (run.dataset_version_id, run.organization_id, run.workspace_id),
                    prepare=True,
                ).fetchone()
                if current is None or str(current[0]) != run.dataset_status.value:
                    raise RuntimeError("Dataset validation lifecycle is no longer current.")

    @staticmethod
    def _insert_details(connection: Connection[TupleRow], run: ValidationRun) -> None:
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO pulseiq.validation_dimension_scores (validation_run_id, dimension, score)
                VALUES (%s, %s, %s) ON CONFLICT DO NOTHING
                """,
                ((run.validation_run_id, item.dimension.value, item.score) for item in run.assessment.dimensions),
            )
            cursor.executemany(
                """
                INSERT INTO pulseiq.validation_capability_results (validation_run_id, capability, status)
                VALUES (%s, %s, %s) ON CONFLICT DO NOTHING
                """,
                (
                    (run.validation_run_id, item.capability.value, item.status.value)
                    for item in run.assessment.capabilities
                ),
            )
            cursor.executemany(
                """
                INSERT INTO pulseiq.validation_issues (
                    validation_run_id, issue_ordinal, rule_id, rule_version,
                    severity, dimension, normalized_column, affected_count,
                    message, recovery, override_allowed
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    (
                        run.validation_run_id,
                        ordinal,
                        issue.code,
                        run.assessment.definition_version,
                        issue.severity.value,
                        issue.dimension.value,
                        issue.column,
                        issue.count,
                        issue.message,
                        issue.recovery,
                        issue.override_allowed,
                    )
                    for ordinal, issue in enumerate(run.assessment.issues, start=1)
                ),
            )
            cursor.executemany(
                """
                INSERT INTO pulseiq.validation_issue_capabilities (
                    validation_run_id, issue_ordinal, capability
                ) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING
                """,
                (
                    (run.validation_run_id, ordinal, capability.value)
                    for ordinal, issue in enumerate(run.assessment.issues, start=1)
                    for capability in issue.affected_capabilities
                ),
            )
            cursor.executemany(
                """
                INSERT INTO pulseiq.validation_issue_examples (
                    validation_run_id, issue_ordinal, example_ordinal, masked_hash
                ) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING
                """,
                (
                    (run.validation_run_id, ordinal, example_ordinal, masked_hash)
                    for ordinal, issue in enumerate(run.assessment.issues, start=1)
                    for example_ordinal, masked_hash in enumerate(issue.masked_examples, start=1)
                ),
            )
        PostgresDatasetValidationRepository._verify_details(connection, run)

    @staticmethod
    def _verify_details(connection: Connection[TupleRow], run: ValidationRun) -> None:
        dimensions = connection.execute(
            """
            SELECT dimension, score::double precision
            FROM pulseiq.validation_dimension_scores
            WHERE validation_run_id = %s ORDER BY dimension
            """,
            (run.validation_run_id,),
            prepare=True,
        ).fetchall()
        capabilities = connection.execute(
            """
            SELECT capability, status
            FROM pulseiq.validation_capability_results
            WHERE validation_run_id = %s ORDER BY capability
            """,
            (run.validation_run_id,),
            prepare=True,
        ).fetchall()
        issues = connection.execute(
            """
            SELECT issue_ordinal, rule_id, rule_version, severity, dimension,
                   normalized_column, affected_count, message, recovery, override_allowed
            FROM pulseiq.validation_issues
            WHERE validation_run_id = %s ORDER BY issue_ordinal
            """,
            (run.validation_run_id,),
            prepare=True,
        ).fetchall()
        issue_capabilities = connection.execute(
            """
            SELECT issue_ordinal, capability
            FROM pulseiq.validation_issue_capabilities
            WHERE validation_run_id = %s ORDER BY issue_ordinal, capability
            """,
            (run.validation_run_id,),
            prepare=True,
        ).fetchall()
        examples = connection.execute(
            """
            SELECT issue_ordinal, example_ordinal, masked_hash
            FROM pulseiq.validation_issue_examples
            WHERE validation_run_id = %s ORDER BY issue_ordinal, example_ordinal
            """,
            (run.validation_run_id,),
            prepare=True,
        ).fetchall()
        expected_dimensions = sorted((item.dimension.value, round(item.score, 2)) for item in run.assessment.dimensions)
        expected_capabilities = sorted(
            (item.capability.value, item.status.value) for item in run.assessment.capabilities
        )
        expected_issues = [
            (
                ordinal,
                issue.code,
                run.assessment.definition_version,
                issue.severity.value,
                issue.dimension.value,
                issue.column,
                issue.count,
                issue.message,
                issue.recovery,
                issue.override_allowed,
            )
            for ordinal, issue in enumerate(run.assessment.issues, start=1)
        ]
        expected_issue_capabilities = sorted(
            (ordinal, capability.value)
            for ordinal, issue in enumerate(run.assessment.issues, start=1)
            for capability in issue.affected_capabilities
        )
        expected_examples = [
            (ordinal, example_ordinal, masked_hash)
            for ordinal, issue in enumerate(run.assessment.issues, start=1)
            for example_ordinal, masked_hash in enumerate(issue.masked_examples, start=1)
        ]
        normalized_dimensions = [(str(row[0]), round(float(row[1]), 2)) for row in dimensions]
        if (
            normalized_dimensions != expected_dimensions
            or capabilities != expected_capabilities
            or issues != expected_issues
            or issue_capabilities != expected_issue_capabilities
            or examples != expected_examples
        ):
            raise RuntimeError("Validation detail evidence conflicts with persisted lineage.")

    @staticmethod
    def _normalized_summary(row: TupleRow) -> tuple[object, ...]:
        values = list(row)
        values[12] = round(float(values[12]), 2)
        return tuple(values)

    @staticmethod
    def _mapping_field(row: TupleRow) -> ConfirmedFieldMapping:
        return ConfirmedFieldMapping(
            source_column=str(row[0]),
            normalized_column=str(row[1]),
            concept=GovernedConcept(str(row[2])),
            target_type=TargetType(str(row[3])),
            nullable=bool(row[4]),
            unit=UnitSemantics(str(row[5])),
            currency_mode=CurrencyMode(str(row[6])),
            currency_code=str(row[7]) if row[7] is not None else None,
            period=PeriodSemantics(str(row[8])),
            amount_direction=AmountDirection(str(row[9])),
            time_semantics=TimeSemantics(str(row[10])),
        )
