"""Request-scoped PostgreSQL identity repository with mandatory RLS context."""

from __future__ import annotations

from datetime import datetime

from psycopg.rows import TupleRow

from pulseiq.audit import AuditEvent
from pulseiq.postgres import PostgresRequestRepository

from .contracts import (
    InvitationStatus,
    Membership,
    MembershipStatus,
    Role,
    SessionRecord,
    SessionStatus,
    WorkspaceInvitation,
)


def _decode_hash(value: str, prefix: str) -> bytes:
    expected_prefix = f"{prefix}:"
    if not value.startswith(expected_prefix):
        raise ValueError(f"Expected {prefix} hash encoding.")
    try:
        decoded = bytes.fromhex(value.removeprefix(expected_prefix))
    except ValueError as exc:
        raise ValueError(f"Expected {prefix} hash encoding.") from exc
    if len(decoded) != 32:
        raise ValueError(f"Expected 32-byte {prefix} hash.")
    return decoded


def _encode_hash(value: bytes, prefix: str) -> str:
    return f"{prefix}:{value.hex()}"


class PostgresIdentityRepository(PostgresRequestRepository):
    """Implement identity ports through parameterized SQL and database RLS."""

    def find_active(
        self,
        *,
        actor_id: str,
        organization_id: str,
        workspace_id: str,
    ) -> Membership | None:
        if not self._is_scope(organization_id, workspace_id):
            return None
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT membership_id::text, actor_id::text, organization_id::text,
                       workspace_id::text, role, status, revision, activated_at, revoked_at
                FROM pulseiq.memberships
                WHERE actor_id = %s AND organization_id = %s AND workspace_id = %s
                  AND status = 'active'
                """,
                (actor_id, organization_id, workspace_id),
                prepare=True,
            ).fetchone()
        return self._membership(row) if row is not None else None

    def get_in_scope(
        self,
        *,
        membership_id: str,
        organization_id: str,
        workspace_id: str,
    ) -> Membership | None:
        if not self._is_scope(organization_id, workspace_id):
            return None
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT membership_id::text, actor_id::text, organization_id::text,
                       workspace_id::text, role, status, revision, activated_at, revoked_at
                FROM pulseiq.memberships
                WHERE membership_id = %s AND organization_id = %s AND workspace_id = %s
                """,
                (membership_id, organization_id, workspace_id),
                prepare=True,
            ).fetchone()
        return self._membership(row) if row is not None else None

    def save_change(
        self,
        membership: Membership,
        audit_event: AuditEvent,
        *,
        expected_revision: int,
    ) -> None:
        self._require_scope(membership.organization_id, membership.workspace_id)
        with self._transaction() as connection:
            row = connection.execute(
                """
                UPDATE pulseiq.memberships
                SET role = %s, status = %s, revision = %s,
                    activated_at = %s, revoked_at = %s
                WHERE membership_id = %s AND organization_id = %s AND workspace_id = %s
                  AND revision = %s
                RETURNING membership_id
                """,
                (
                    membership.role.value,
                    membership.status.value,
                    membership.revision,
                    membership.activated_at,
                    membership.revoked_at,
                    membership.membership_id,
                    membership.organization_id,
                    membership.workspace_id,
                    expected_revision,
                ),
                prepare=True,
            ).fetchone()
            if row is None:
                raise RuntimeError("Membership changed concurrently.")
            self._insert_audit(connection, audit_event)

    def count_active_role(
        self,
        *,
        organization_id: str,
        workspace_id: str,
        role: Role,
    ) -> int:
        if not self._is_scope(organization_id, workspace_id):
            return 0
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT count(*)
                FROM pulseiq.memberships
                WHERE organization_id = %s AND workspace_id = %s
                  AND role = %s AND status = 'active'
                """,
                (organization_id, workspace_id, role.value),
                prepare=True,
            ).fetchone()
        if row is None:
            return 0
        return int(row[0])

    def has_pending_invitation(
        self,
        *,
        organization_id: str,
        workspace_id: str,
        email_binding: str,
        active_at: datetime,
    ) -> bool:
        if not self._is_scope(organization_id, workspace_id):
            return False
        binding = _decode_hash(email_binding, "hmac-sha256")
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM pulseiq.workspace_invitations
                WHERE organization_id = %s AND workspace_id = %s
                  AND email_binding = %s AND status = 'pending' AND expires_at > %s
                LIMIT 1
                """,
                (organization_id, workspace_id, binding, active_at),
                prepare=True,
            ).fetchone()
        return row is not None

    def save_invitation(self, invitation: WorkspaceInvitation, audit_event: AuditEvent) -> None:
        self._require_scope(invitation.organization_id, invitation.workspace_id)
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO pulseiq.workspace_invitations (
                    invitation_id, organization_id, workspace_id, email_binding,
                    role, status, token_digest, issued_by, issued_at, expires_at,
                    revision, accepted_by, accepted_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    invitation.invitation_id,
                    invitation.organization_id,
                    invitation.workspace_id,
                    _decode_hash(invitation.email_binding, "hmac-sha256"),
                    invitation.role.value,
                    invitation.status.value,
                    _decode_hash(invitation.token_digest, "sha256"),
                    invitation.issued_by,
                    invitation.issued_at,
                    invitation.expires_at,
                    invitation.revision,
                    invitation.accepted_by,
                    invitation.accepted_at,
                ),
                prepare=True,
            )
            self._insert_audit(connection, audit_event)

    def find_invitation_by_token_digest(self, token_digest: str) -> WorkspaceInvitation | None:
        digest = _decode_hash(token_digest, "sha256")
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT invitation_id::text, organization_id::text, workspace_id::text,
                       email_binding, role, status, token_digest, issued_by::text,
                       issued_at, expires_at, revision, accepted_by::text, accepted_at
                FROM pulseiq.workspace_invitations
                WHERE token_digest = %s
                """,
                (digest,),
                prepare=True,
            ).fetchone()
        return self._invitation(row) if row is not None else None

    def accept_invitation(
        self,
        invitation: WorkspaceInvitation,
        membership: Membership,
        audit_event: AuditEvent,
        *,
        expected_revision: int,
    ) -> None:
        self._require_scope(invitation.organization_id, invitation.workspace_id)
        with self._transaction() as connection:
            changed = connection.execute(
                """
                UPDATE pulseiq.workspace_invitations
                SET status = %s, revision = %s, accepted_by = %s, accepted_at = %s
                WHERE invitation_id = %s AND revision = %s AND status = 'pending'
                RETURNING invitation_id
                """,
                (
                    invitation.status.value,
                    invitation.revision,
                    invitation.accepted_by,
                    invitation.accepted_at,
                    invitation.invitation_id,
                    expected_revision,
                ),
                prepare=True,
            ).fetchone()
            if changed is None:
                raise RuntimeError("Invitation changed concurrently.")
            connection.execute(
                """
                INSERT INTO pulseiq.memberships (
                    membership_id, actor_id, organization_id, workspace_id,
                    role, status, revision, activated_at, revoked_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    membership.membership_id,
                    membership.actor_id,
                    membership.organization_id,
                    membership.workspace_id,
                    membership.role.value,
                    membership.status.value,
                    membership.revision,
                    membership.activated_at,
                    membership.revoked_at,
                ),
                prepare=True,
            )
            self._insert_audit(connection, audit_event)

    def find_active_session(
        self,
        *,
        session_id: str,
        actor_id: str,
        active_at: datetime,
    ) -> SessionRecord | None:
        if actor_id != self._scope.actor_id:
            return None
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT session_id::text, actor_id::text, authenticated_at,
                       expires_at, status, revision, revoked_at
                FROM pulseiq.sessions
                WHERE session_id = %s AND actor_id = %s AND status = 'active'
                  AND authenticated_at <= %s AND expires_at > %s
                """,
                (session_id, actor_id, active_at, active_at),
                prepare=True,
            ).fetchone()
        return self._session(row) if row is not None else None

    def save_session_revocation(
        self,
        session: SessionRecord,
        audit_event: AuditEvent,
        *,
        expected_revision: int,
    ) -> None:
        if session.actor_id != self._scope.actor_id:
            raise ValueError("Session actor is outside the request scope.")
        with self._transaction() as connection:
            changed = connection.execute(
                """
                UPDATE pulseiq.sessions
                SET status = %s, revision = %s, revoked_at = %s
                WHERE session_id = %s AND actor_id = %s
                  AND revision = %s AND status = 'active'
                RETURNING session_id
                """,
                (
                    session.status.value,
                    session.revision,
                    session.revoked_at,
                    session.session_id,
                    session.actor_id,
                    expected_revision,
                ),
                prepare=True,
            ).fetchone()
            if changed is None:
                raise RuntimeError("Session changed concurrently.")
            self._insert_audit(connection, audit_event)

    @staticmethod
    def _membership(row: TupleRow) -> Membership:
        return Membership(
            membership_id=str(row[0]),
            actor_id=str(row[1]),
            organization_id=str(row[2]),
            workspace_id=str(row[3]),
            role=Role(str(row[4])),
            status=MembershipStatus(str(row[5])),
            revision=int(row[6]),
            activated_at=row[7],
            revoked_at=row[8],
        )

    @staticmethod
    def _invitation(row: TupleRow) -> WorkspaceInvitation:
        return WorkspaceInvitation(
            invitation_id=str(row[0]),
            organization_id=str(row[1]),
            workspace_id=str(row[2]),
            email_binding=_encode_hash(bytes(row[3]), "hmac-sha256"),
            role=Role(str(row[4])),
            status=InvitationStatus(str(row[5])),
            token_digest=_encode_hash(bytes(row[6]), "sha256"),
            issued_by=str(row[7]),
            issued_at=row[8],
            expires_at=row[9],
            revision=int(row[10]),
            accepted_by=str(row[11]) if row[11] is not None else None,
            accepted_at=row[12],
        )

    @staticmethod
    def _session(row: TupleRow) -> SessionRecord:
        return SessionRecord(
            session_id=str(row[0]),
            actor_id=str(row[1]),
            authenticated_at=row[2],
            expires_at=row[3],
            status=SessionStatus(str(row[4])),
            revision=int(row[5]),
            revoked_at=row[6],
        )
