"""Request-scoped PostgreSQL persistence for governed quality-warning overrides."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from psycopg import Connection
from psycopg.rows import TupleRow

from pulseiq.audit import AuditEvent
from pulseiq.postgres import PostgresRequestRepository

from .contracts import IssueSeverity
from .quality_overrides import (
    EffectiveQualityStatus,
    EffectiveValidationQuality,
    QualityWarningContext,
    QualityWarningOverride,
    QualityWarningOverrideError,
)


class PostgresQualityWarningOverrideRepository(PostgresRequestRepository):
    """Read exact warning facts and atomically append override/audit evidence."""

    def get_warning_context(
        self,
        *,
        validation_run_id: str,
        issue_ordinal: int,
        organization_id: str,
        workspace_id: str,
    ) -> QualityWarningContext | None:
        self._require_scope(organization_id, workspace_id)
        UUID(validation_run_id)
        if not 1 <= issue_ordinal <= 1000:
            raise ValueError("Validation issue ordinal is invalid.")
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT run.validation_run_id::text, run.organization_id::text,
                       run.workspace_id::text, run.dataset_version_id::text,
                       issue.issue_ordinal, issue.rule_id, issue.rule_version,
                       issue.severity, issue.override_allowed
                FROM pulseiq.validation_runs AS run
                JOIN pulseiq.validation_issues AS issue USING (validation_run_id)
                WHERE run.validation_run_id = %s
                  AND issue.issue_ordinal = %s
                  AND run.organization_id = %s
                  AND run.workspace_id = %s
                """,
                (validation_run_id, issue_ordinal, organization_id, workspace_id),
                prepare=True,
            ).fetchone()
        return self._context(row) if row is not None else None

    def find_by_request_id(
        self,
        *,
        organization_id: str,
        workspace_id: str,
        request_id: str,
    ) -> QualityWarningOverride | None:
        self._require_scope(organization_id, workspace_id)
        UUID(request_id)
        with self._transaction() as connection:
            row = self._select_request(
                connection,
                organization_id=organization_id,
                workspace_id=workspace_id,
                request_id=request_id,
            )
        return self._override(row) if row is not None else None

    def create_override(
        self,
        override: QualityWarningOverride,
        audit_event: AuditEvent,
    ) -> QualityWarningOverride:
        self._require_scope(override.organization_id, override.workspace_id)
        for identifier in (
            override.override_id,
            override.organization_id,
            override.workspace_id,
            override.dataset_version_id,
            override.validation_run_id,
            override.overridden_by,
            override.request_id,
            audit_event.event_id,
            audit_event.request_id,
        ):
            UUID(identifier)
        if (
            audit_event.organization_id != override.organization_id
            or audit_event.workspace_id != override.workspace_id
            or audit_event.actor_id != override.overridden_by
            or audit_event.target_id != override.override_id
            or audit_event.request_id != override.request_id
            or audit_event.action != "quality.warning_overridden"
            or audit_event.target_type != "validation_issue_override"
        ):
            raise ValueError("Override audit evidence does not match the command.")
        with self._transaction() as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"quality-override:{override.validation_run_id}:{override.issue_ordinal}",),
                prepare=True,
            )
            existing = self._select_request(
                connection,
                organization_id=override.organization_id,
                workspace_id=override.workspace_id,
                request_id=override.request_id,
            )
            if existing is not None:
                return self._override(existing)
            overlap = connection.execute(
                """
                SELECT override_id
                FROM pulseiq.validation_issue_overrides
                WHERE validation_run_id = %s
                  AND issue_ordinal = %s
                  AND tstzrange(overridden_at, expires_at, '[)')
                      && tstzrange(%s, %s, '[)')
                LIMIT 1
                """,
                (
                    override.validation_run_id,
                    override.issue_ordinal,
                    override.overridden_at,
                    override.expires_at,
                ),
                prepare=True,
            ).fetchone()
            if overlap is not None:
                raise QualityWarningOverrideError("active_override_exists")
            inserted = connection.execute(
                """
                INSERT INTO pulseiq.validation_issue_overrides (
                    override_id, organization_id, workspace_id, validation_run_id,
                    issue_ordinal, overridden_by, overridden_at, expires_at,
                    request_id, reason
                )
                SELECT %s, run.organization_id, run.workspace_id, run.validation_run_id,
                       %s, %s, %s, %s, %s, %s
                FROM pulseiq.validation_runs AS run
                JOIN pulseiq.validation_issues AS issue USING (validation_run_id)
                WHERE run.validation_run_id = %s
                  AND issue.issue_ordinal = %s
                  AND run.organization_id = %s
                  AND run.workspace_id = %s
                  AND run.dataset_version_id = %s
                  AND issue.rule_id = %s
                  AND issue.rule_version = %s
                  AND issue.severity = 'warn'
                  AND issue.override_allowed
                RETURNING override_id
                """,
                (
                    override.override_id,
                    override.issue_ordinal,
                    override.overridden_by,
                    override.overridden_at,
                    override.expires_at,
                    override.request_id,
                    override.reason,
                    override.validation_run_id,
                    override.issue_ordinal,
                    override.organization_id,
                    override.workspace_id,
                    override.dataset_version_id,
                    override.rule_id,
                    override.rule_version,
                ),
                prepare=True,
            ).fetchone()
            if inserted is None:
                raise QualityWarningOverrideError("warning_override_not_allowed")
            self._insert_audit(connection, audit_event)
        return override

    def get_effective_quality(
        self,
        *,
        validation_run_id: str,
        organization_id: str,
        workspace_id: str,
        evaluated_at: datetime,
    ) -> EffectiveValidationQuality | None:
        self._require_scope(organization_id, workspace_id)
        UUID(validation_run_id)
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT run.validation_run_id::text, run.dataset_version_id::text,
                       run.organization_id::text, run.workspace_id::text,
                       run.composite_score::double precision,
                       run.block_count, run.warn_count,
                       count(override.override_id) FILTER (
                           WHERE override.overridden_at <= %s AND override.expires_at > %s
                       )::integer AS active_override_count,
                       run.info_count
                FROM pulseiq.validation_runs AS run
                LEFT JOIN pulseiq.validation_issue_overrides AS override
                  ON override.validation_run_id = run.validation_run_id
                WHERE run.validation_run_id = %s
                  AND run.organization_id = %s
                  AND run.workspace_id = %s
                GROUP BY run.validation_run_id
                """,
                (evaluated_at, evaluated_at, validation_run_id, organization_id, workspace_id),
                prepare=True,
            ).fetchone()
        if row is None:
            return None
        blocking = int(row[5])
        warnings = int(row[6])
        active = int(row[7])
        effective = warnings - active
        status = (
            EffectiveQualityStatus.BLOCKED
            if blocking
            else EffectiveQualityStatus.WARN
            if effective
            else EffectiveQualityStatus.HEALTHY
        )
        return EffectiveValidationQuality(
            validation_run_id=str(row[0]),
            dataset_version_id=str(row[1]),
            organization_id=str(row[2]),
            workspace_id=str(row[3]),
            composite_score=float(row[4]),
            blocking_issue_count=blocking,
            warning_issue_count=warnings,
            active_override_count=active,
            effective_warning_count=effective,
            informational_issue_count=int(row[8]),
            status=status,
            evaluated_at=evaluated_at,
        )

    @staticmethod
    def _select_request(
        connection: Connection[TupleRow],
        *,
        organization_id: str,
        workspace_id: str,
        request_id: str,
    ) -> TupleRow | None:
        return connection.execute(
            """
            SELECT override.override_id::text, override.organization_id::text,
                   override.workspace_id::text, run.dataset_version_id::text,
                   override.validation_run_id::text, override.issue_ordinal,
                   issue.rule_id, issue.rule_version, override.overridden_by::text,
                   override.overridden_at, override.expires_at,
                   override.request_id::text, override.reason
            FROM pulseiq.validation_issue_overrides AS override
            JOIN pulseiq.validation_runs AS run USING (validation_run_id)
            JOIN pulseiq.validation_issues AS issue USING (validation_run_id, issue_ordinal)
            WHERE override.organization_id = %s
              AND override.workspace_id = %s
              AND override.request_id = %s
            """,
            (organization_id, workspace_id, request_id),
            prepare=True,
        ).fetchone()

    @staticmethod
    def _context(row: TupleRow) -> QualityWarningContext:
        return QualityWarningContext(
            validation_run_id=str(row[0]),
            organization_id=str(row[1]),
            workspace_id=str(row[2]),
            dataset_version_id=str(row[3]),
            issue_ordinal=int(row[4]),
            rule_id=str(row[5]),
            rule_version=str(row[6]),
            severity=IssueSeverity(str(row[7])),
            override_allowed=bool(row[8]),
        )

    @staticmethod
    def _override(row: TupleRow) -> QualityWarningOverride:
        return QualityWarningOverride(
            override_id=str(row[0]),
            organization_id=str(row[1]),
            workspace_id=str(row[2]),
            dataset_version_id=str(row[3]),
            validation_run_id=str(row[4]),
            issue_ordinal=int(row[5]),
            rule_id=str(row[6]),
            rule_version=str(row[7]),
            overridden_by=str(row[8]),
            overridden_at=row[9],
            expires_at=row[10],
            request_id=str(row[11]),
            reason=str(row[12]),
        )
