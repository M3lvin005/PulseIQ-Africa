"""Shared pooled PostgreSQL request context and atomic audit plumbing."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID

from psycopg import Connection
from psycopg.rows import TupleRow
from psycopg_pool import ConnectionPool

from pulseiq.audit import AuditEvent


@dataclass(frozen=True, slots=True)
class DatabaseScope:
    """Trusted actor and tenant UUIDs installed transaction-locally for RLS."""

    actor_id: str
    organization_id: str
    workspace_id: str

    def __post_init__(self) -> None:
        for value in (self.actor_id, self.organization_id, self.workspace_id):
            UUID(value)


class PostgresRequestRepository:
    """Deep internal module for pooled RLS transactions and chained audit inserts."""

    def __init__(
        self,
        pool: ConnectionPool[Connection[TupleRow]],
        scope: DatabaseScope,
    ) -> None:
        self._pool = pool
        self._scope = scope

    @contextmanager
    def _transaction(self) -> Iterator[Connection[TupleRow]]:
        with self._pool.connection() as connection, connection.transaction():
            connection.execute(
                "SELECT set_config('pulseiq.actor_id', %s, true)",
                (self._scope.actor_id,),
                prepare=True,
            )
            connection.execute(
                "SELECT set_config('pulseiq.organization_id', %s, true)",
                (self._scope.organization_id,),
                prepare=True,
            )
            connection.execute(
                "SELECT set_config('pulseiq.workspace_id', %s, true)",
                (self._scope.workspace_id,),
                prepare=True,
            )
            yield connection

    def _is_scope(self, organization_id: str, workspace_id: str) -> bool:
        return organization_id == self._scope.organization_id and workspace_id == self._scope.workspace_id

    def _require_scope(self, organization_id: str, workspace_id: str) -> None:
        if not self._is_scope(organization_id, workspace_id):
            raise ValueError("State is outside the trusted request scope.")

    def _insert_audit(self, connection: Connection[TupleRow], event: AuditEvent) -> None:
        self._require_scope(event.organization_id, event.workspace_id)
        if event.actor_id != self._scope.actor_id:
            raise ValueError("Audit actor is outside the trusted request scope.")
        connection.execute(
            """
            INSERT INTO pulseiq.audit_events (
                event_id, occurred_at, organization_id, workspace_id, actor_id,
                action, target_type, target_id, request_id, reason,
                before_hash, after_hash
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                event.event_id,
                event.occurred_at,
                event.organization_id,
                event.workspace_id,
                event.actor_id,
                event.action,
                event.target_type,
                event.target_id,
                event.request_id,
                event.reason,
                event.before_hash,
                event.after_hash,
            ),
            prepare=True,
        )
