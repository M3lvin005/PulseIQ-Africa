"""Worker-role PostgreSQL persistence for normalized artifact lineage."""

from __future__ import annotations

import re
from uuid import UUID

from psycopg import Connection
from psycopg.rows import TupleRow
from psycopg_pool import ConnectionPool

from .normalization import NormalizedDatasetArtifact

_NORMALIZED_KEY_PATTERN = re.compile(
    r"^normalized/[A-Za-z0-9][A-Za-z0-9_-]{0,127}/[A-Za-z0-9][A-Za-z0-9_-]{0,127}/"
    r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}/[A-Za-z0-9][A-Za-z0-9_-]{0,127}/data\.parquet$"
)


class PostgresNormalizedArtifactRepository:
    """Insert immutable lineage idempotently while a dataset scan is active."""

    def __init__(self, pool: ConnectionPool[Connection[TupleRow]]) -> None:
        self._pool = pool

    def record_artifact(self, artifact: NormalizedDatasetArtifact) -> None:
        UUID(artifact.dataset_version_id)
        UUID(artifact.organization_id)
        UUID(artifact.workspace_id)
        if _NORMALIZED_KEY_PATTERN.fullmatch(artifact.object_key) is None:
            raise ValueError("Normalized artifact key is invalid.")
        with self._pool.connection() as connection, connection.transaction():
            connection.execute(
                """
                INSERT INTO pulseiq.dataset_artifacts (
                    dataset_version_id, organization_id, workspace_id, object_key,
                    source_sha256, artifact_sha256, schema_fingerprint,
                    row_count, column_count, normalization_version, created_at
                )
                SELECT version.dataset_version_id, version.organization_id, version.workspace_id,
                       %s, decode(%s, 'hex'), decode(%s, 'hex'), decode(%s, 'hex'),
                       %s, %s, %s, %s
                FROM pulseiq.dataset_versions AS version
                WHERE version.dataset_version_id = %s
                  AND version.organization_id = %s
                  AND version.workspace_id = %s
                  AND version.status = 'scanning'
                ON CONFLICT (dataset_version_id) DO NOTHING
                """,
                (
                    artifact.object_key,
                    artifact.source_sha256,
                    artifact.artifact_sha256,
                    artifact.schema_fingerprint,
                    artifact.row_count,
                    artifact.column_count,
                    artifact.normalization_version,
                    artifact.created_at,
                    artifact.dataset_version_id,
                    artifact.organization_id,
                    artifact.workspace_id,
                ),
                prepare=True,
            )
            persisted = connection.execute(
                """
                SELECT organization_id::text, workspace_id::text, object_key,
                       encode(source_sha256, 'hex'), encode(artifact_sha256, 'hex'),
                       encode(schema_fingerprint, 'hex'), row_count, column_count,
                       normalization_version, created_at
                FROM pulseiq.dataset_artifacts
                WHERE dataset_version_id = %s
                """,
                (artifact.dataset_version_id,),
                prepare=True,
            ).fetchone()
            if persisted != self._expected_row(artifact):
                raise RuntimeError("Normalized artifact lineage conflicts with persisted evidence.")
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO pulseiq.dataset_artifact_fields (
                        dataset_version_id, position, source_column, normalized_column,
                        physical_type, nullable
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        (
                            artifact.dataset_version_id,
                            field.position,
                            field.source_column,
                            field.normalized_column,
                            field.physical_type,
                            field.nullable,
                        )
                        for field in artifact.fields
                    ),
                )
            fields = connection.execute(
                """
                SELECT position, source_column, normalized_column, physical_type, nullable
                FROM pulseiq.dataset_artifact_fields
                WHERE dataset_version_id = %s
                ORDER BY position
                """,
                (artifact.dataset_version_id,),
                prepare=True,
            ).fetchall()
            expected_fields = [
                (
                    field.position,
                    field.source_column,
                    field.normalized_column,
                    field.physical_type,
                    field.nullable,
                )
                for field in artifact.fields
            ]
            if fields != expected_fields:
                raise RuntimeError("Normalized artifact fields conflict with persisted evidence.")

    @staticmethod
    def _expected_row(artifact: NormalizedDatasetArtifact) -> tuple[object, ...]:
        return (
            artifact.organization_id,
            artifact.workspace_id,
            artifact.object_key,
            artifact.source_sha256,
            artifact.artifact_sha256,
            artifact.schema_fingerprint,
            artifact.row_count,
            artifact.column_count,
            artifact.normalization_version,
            artifact.created_at,
        )
