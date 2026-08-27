from __future__ import annotations

import hashlib
import hmac
import json
import os
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import psycopg
import pytest
from psycopg import Connection
from psycopg_pool import ConnectionPool
from redis import Redis

from pulseiq.datasets import (
    AmountDirection,
    BeginDatasetUpload,
    CompleteDatasetUpload,
    ConfirmedFieldMapping,
    ConfirmSchemaMapping,
    CurrencyMode,
    DatasetUploadError,
    DatasetUploadService,
    DatasetValidationHandler,
    EffectiveQualityStatus,
    GetEffectiveValidationQuality,
    InMemoryQuarantineUploadSigner,
    NormalizedArtifactField,
    NormalizedDatasetArtifact,
    OverrideQualityWarning,
    PeriodSemantics,
    PostgresDatasetUploadRepository,
    PostgresDatasetValidationRepository,
    PostgresNormalizedArtifactRepository,
    PostgresQualityWarningOverrideRepository,
    PostgresSchemaMappingRepository,
    QualityWarningOverrideError,
    QualityWarningOverrideService,
    SchemaMappingService,
    TargetType,
    TimeSemantics,
    UnitSemantics,
    ValidationQualityQueryService,
)
from pulseiq.identity import (
    AcceptWorkspaceInvitation,
    AuthenticatedActor,
    AuthorizationRequest,
    AuthorizationService,
    ChangeMembershipRole,
    DatabaseScope,
    IdentityAdministrationService,
    IdentityInvitationService,
    InviteWorkspaceMember,
    Permission,
    PostgresIdentityRepository,
    ResourceScope,
    RevokeSession,
    Role,
    SessionAdministrationService,
)
from pulseiq.ingestion import GovernedConcept, normalize_csv_to_parquet
from pulseiq.jobs import (
    CeleryMessagePublisher,
    OutboxDispatcher,
    PostgresImportJobRepository,
    PostgresOutboxRepository,
    create_celery_app,
)

ADMIN_DSN = os.environ.get("PULSEIQ_TEST_DATABASE_URL")
REDIS_URL = os.environ.get("PULSEIQ_TEST_REDIS_URL")
MIGRATIONS_PATH = Path(__file__).parents[2] / "db" / "migrations"

ORG_A = "11111111-1111-4111-8111-111111111111"
ORG_B = "22222222-2222-4222-8222-222222222222"
WORKSPACE_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
WORKSPACE_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
ACTOR_A = "aaaaaaaa-1111-4111-8111-111111111111"
ACTOR_B = "bbbbbbbb-2222-4222-8222-222222222222"
ACTOR_C = "cccccccc-2222-4222-8222-222222222222"
ACTOR_D = "dddddddd-2222-4222-8222-222222222222"
ACTOR_E = "eeeeeeee-2222-4222-8222-222222222222"
MEMBERSHIP_A = "aaaaaaaa-3333-4333-8333-333333333333"
MEMBERSHIP_B = "bbbbbbbb-4444-4444-8444-444444444444"
MEMBERSHIP_C = "cccccccc-4444-4444-8444-444444444444"
MEMBERSHIP_D = "dddddddd-4444-4444-8444-444444444444"
MEMBERSHIP_E = "eeeeeeee-4444-4444-8444-444444444444"
CROSS_TENANT_MEMBERSHIP = "cccccccc-5555-4555-8555-555555555555"
AUDIT_EVENT_A = "aaaaaaaa-6666-4666-8666-666666666666"
REQUEST_A = "aaaaaaaa-7777-4777-8777-777777777777"
SESSION_A = "aaaaaaaa-8888-4888-8888-888888888888"
SESSION_B = "bbbbbbbb-9999-4999-8999-999999999999"
SESSION_D = "dddddddd-9999-4999-8999-999999999999"
SESSION_E = "eeeeeeee-9999-4999-8999-999999999999"
INVITATION_A = "aaaaaaaa-aaaa-4aaa-8aaa-000000000001"
INVITATION_B = "bbbbbbbb-bbbb-4bbb-8bbb-000000000002"
INVITATION_D = "dddddddd-dddd-4ddd-8ddd-000000000003"
INVITATION_EXPIRED = "eeeeeeee-eeee-4eee-8eee-000000000004"
INVITATION_REISSUE = "ffffffff-ffff-4fff-8fff-000000000005"
AUDIT_EVENT_ROLE = "cccccccc-6666-4666-8666-666666666666"
AUDIT_EVENT_INVITE = "dddddddd-6666-4666-8666-666666666666"
AUDIT_EVENT_ACCEPT = "eeeeeeee-6666-4666-8666-666666666666"
REQUEST_ROLE = "cccccccc-7777-4777-8777-777777777777"
REQUEST_INVITE = "dddddddd-7777-4777-8777-777777777777"
REQUEST_ACCEPT = "eeeeeeee-7777-4777-8777-777777777777"
AUDIT_EVENT_REISSUE = "ffffffff-6666-4666-8666-666666666666"
REQUEST_REISSUE = "ffffffff-7777-4777-8777-777777777777"
DATASET_A = "11111111-aaaa-4aaa-8aaa-111111111111"
DATASET_B = "22222222-bbbb-4bbb-8bbb-222222222222"
DATASET_VERSION_A = "11111111-cccc-4ccc-8ccc-111111111111"
DATASET_VERSION_B = "22222222-dddd-4ddd-8ddd-222222222222"
IMPORT_JOB_A = "11111111-eeee-4eee-8eee-111111111111"
DATASET_VERSION_UPLOAD = "33333333-cccc-4ccc-8ccc-333333333333"
IMPORT_JOB_UPLOAD = "33333333-eeee-4eee-8eee-333333333333"
AUDIT_EVENT_UPLOAD_RESERVED = "33333333-6666-4666-8666-333333333333"
AUDIT_EVENT_UPLOAD_COMPLETED = "44444444-6666-4666-8666-444444444444"
REQUEST_UPLOAD_RESERVED = "33333333-7777-4777-8777-333333333333"
REQUEST_UPLOAD_COMPLETED = "44444444-7777-4777-8777-444444444444"
DATASET_VERSION_QUARANTINED = "55555555-cccc-4ccc-8ccc-555555555555"
AUDIT_EVENT_QUARANTINE_RESERVED = "55555555-6666-4666-8666-555555555555"
AUDIT_EVENT_QUARANTINED = "66666666-6666-4666-8666-666666666666"
REQUEST_QUARANTINE_RESERVED = "55555555-7777-4777-8777-555555555555"
REQUEST_QUARANTINED = "66666666-7777-4777-8777-666666666666"


@pytest.fixture
def migrated_database() -> Iterator[str]:
    if ADMIN_DSN is None:
        pytest.skip("Set PULSEIQ_TEST_DATABASE_URL to run PostgreSQL integration tests.")

    migrations = tuple(path.read_text(encoding="utf-8") for path in sorted(MIGRATIONS_PATH.glob("*.sql")))
    with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
        connection.execute("DROP SCHEMA IF EXISTS pulseiq CASCADE")
        connection.execute("DROP ROLE IF EXISTS pulseiq_app")
        connection.execute("DROP ROLE IF EXISTS pulseiq_worker")
        connection.execute("CREATE ROLE pulseiq_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS")
        connection.execute(
            "CREATE ROLE pulseiq_worker NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
        )
        for migration in migrations:
            connection.execute(migration)
        connection.execute(
            "INSERT INTO pulseiq.organizations (organization_id) VALUES (%s), (%s)",
            (ORG_A, ORG_B),
        )
        connection.execute(
            """
            INSERT INTO pulseiq.workspaces (workspace_id, organization_id)
            VALUES (%s, %s), (%s, %s)
            """,
            (WORKSPACE_A, ORG_A, WORKSPACE_B, ORG_B),
        )
        connection.execute(
            "INSERT INTO pulseiq.actors (actor_id) VALUES (%s), (%s), (%s), (%s), (%s)",
            (ACTOR_A, ACTOR_B, ACTOR_C, ACTOR_D, ACTOR_E),
        )
        connection.execute(
            """
            INSERT INTO pulseiq.memberships (
                membership_id, actor_id, organization_id, workspace_id, role, status, activated_at
            ) VALUES
                (%s, %s, %s, %s, 'admin', 'active', clock_timestamp()),
                (%s, %s, %s, %s, 'read_only', 'active', clock_timestamp()),
                (%s, %s, %s, %s, 'admin', 'active', clock_timestamp()),
                (%s, %s, %s, %s, 'data_steward', 'active', clock_timestamp())
            """,
            (
                MEMBERSHIP_A,
                ACTOR_A,
                ORG_A,
                WORKSPACE_A,
                MEMBERSHIP_B,
                ACTOR_B,
                ORG_B,
                WORKSPACE_B,
                MEMBERSHIP_C,
                ACTOR_C,
                ORG_A,
                WORKSPACE_A,
                MEMBERSHIP_E,
                ACTOR_E,
                ORG_A,
                WORKSPACE_A,
            ),
        )
        connection.execute(
            """
            INSERT INTO pulseiq.sessions (
                session_id, actor_id, authenticated_at, expires_at, status
            ) VALUES
                (%s, %s, clock_timestamp() - interval '5 minutes', clock_timestamp() + interval '10 minutes', 'active'),
                (%s, %s, clock_timestamp() - interval '5 minutes', clock_timestamp() + interval '10 minutes', 'active'),
                (%s, %s, clock_timestamp() - interval '5 minutes', clock_timestamp() + interval '10 minutes', 'active'),
                (%s, %s, clock_timestamp() - interval '5 minutes', clock_timestamp() + interval '10 minutes', 'active')
            """,
            (SESSION_A, ACTOR_A, SESSION_B, ACTOR_B, SESSION_D, ACTOR_D, SESSION_E, ACTOR_E),
        )
        connection.execute(
            """
            INSERT INTO pulseiq.workspace_invitations (
                invitation_id, organization_id, workspace_id, email_binding,
                role, status, token_digest, issued_by, issued_at, expires_at
            ) VALUES
                (%s, %s, %s, decode(repeat('a1', 32), 'hex'), 'read_only', 'pending',
                    decode(repeat('b1', 32), 'hex'), %s, clock_timestamp(), clock_timestamp() + interval '1 hour'),
                (%s, %s, %s, decode(repeat('a2', 32), 'hex'), 'read_only', 'pending',
                    decode(repeat('b2', 32), 'hex'), %s, clock_timestamp(), clock_timestamp() + interval '1 hour')
            """,
            (INVITATION_A, ORG_A, WORKSPACE_A, ACTOR_A, INVITATION_B, ORG_B, WORKSPACE_B, ACTOR_B),
        )

    yield ADMIN_DSN

    with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
        connection.execute("DROP SCHEMA IF EXISTS pulseiq CASCADE")
        connection.execute("DROP ROLE IF EXISTS pulseiq_app")
        connection.execute("DROP ROLE IF EXISTS pulseiq_worker")


def _set_application_context(
    connection: Connection[tuple[object, ...]],
    *,
    actor_id: str,
    organization_id: str,
    workspace_id: str,
) -> None:
    connection.execute("SET LOCAL ROLE pulseiq_app")
    connection.execute("SELECT set_config('pulseiq.actor_id', %s, true)", (actor_id,))
    connection.execute("SELECT set_config('pulseiq.organization_id', %s, true)", (organization_id,))
    connection.execute("SELECT set_config('pulseiq.workspace_id', %s, true)", (workspace_id,))


def _configure_application_role(connection: Connection[tuple[object, ...]]) -> None:
    connection.execute("SET ROLE pulseiq_app")
    connection.commit()


def _configure_worker_role(connection: Connection[tuple[object, ...]]) -> None:
    connection.execute("SET ROLE pulseiq_worker")
    connection.commit()


def test_application_role_reads_only_current_tenant_memberships(migrated_database: str) -> None:
    with psycopg.connect(migrated_database) as connection:
        _set_application_context(
            connection,
            actor_id=ACTOR_A,
            organization_id=ORG_A,
            workspace_id=WORKSPACE_A,
        )
        row_security_active = connection.execute("SELECT row_security_active('pulseiq.memberships')").fetchone()
        memberships = connection.execute(
            "SELECT membership_id::text FROM pulseiq.memberships ORDER BY membership_id"
        ).fetchall()

    assert row_security_active == (True,)
    assert memberships == [(MEMBERSHIP_A,), (MEMBERSHIP_C,), (MEMBERSHIP_E,)]


def test_application_role_cannot_insert_membership_into_another_tenant(migrated_database: str) -> None:
    with psycopg.connect(migrated_database) as connection:
        _set_application_context(
            connection,
            actor_id=ACTOR_A,
            organization_id=ORG_A,
            workspace_id=WORKSPACE_A,
        )

        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="row-level security"):
            connection.execute(
                """
                INSERT INTO pulseiq.memberships (
                    membership_id, actor_id, organization_id, workspace_id,
                    role, status, activated_at
                ) VALUES (%s, %s, %s, %s, 'read_only', 'active', clock_timestamp())
                """,
                (CROSS_TENANT_MEMBERSHIP, ACTOR_B, ORG_B, WORKSPACE_B),
            )


def test_audit_insert_is_chained_outboxed_and_append_only(migrated_database: str) -> None:
    state_hash = "sha256:" + "a" * 64
    with psycopg.connect(migrated_database) as connection:
        _set_application_context(
            connection,
            actor_id=ACTOR_A,
            organization_id=ORG_A,
            workspace_id=WORKSPACE_A,
        )
        hashes = connection.execute(
            """
            INSERT INTO pulseiq.audit_events (
                event_id, occurred_at, organization_id, workspace_id, actor_id,
                action, target_type, target_id, request_id, reason,
                before_hash, after_hash
            ) VALUES (
                %s, clock_timestamp(), %s, %s, %s,
                'membership.role_changed', 'membership', %s, %s,
                'Separate model training from approval.', %s, %s
            )
            RETURNING previous_event_hash, event_hash
            """,
            (AUDIT_EVENT_A, ORG_A, WORKSPACE_A, ACTOR_A, MEMBERSHIP_A, REQUEST_A, state_hash, state_hash),
        ).fetchone()

    assert hashes is not None
    assert len(hashes[0]) == 32
    assert len(hashes[1]) == 32
    assert hashes[0] != hashes[1]

    with psycopg.connect(migrated_database) as connection:
        outbox = connection.execute(
            "SELECT topic, aggregate_id::text, payload->>'action' FROM pulseiq.outbox_events"
        ).fetchall()
    assert outbox == [("audit.recorded", AUDIT_EVENT_A, "membership.role_changed")]

    with (
        psycopg.connect(migrated_database, autocommit=True) as connection,
        pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="append-only"),
    ):
        connection.execute(
            "UPDATE pulseiq.audit_events SET reason = 'tampered' WHERE event_id = %s",
            (AUDIT_EVENT_A,),
        )
    with (
        psycopg.connect(migrated_database, autocommit=True) as connection,
        pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="append-only"),
    ):
        connection.execute("DELETE FROM pulseiq.audit_events WHERE event_id = %s", (AUDIT_EVENT_A,))


def test_application_role_can_only_read_and_revoke_its_own_session(migrated_database: str) -> None:
    with psycopg.connect(migrated_database) as connection:
        _set_application_context(
            connection,
            actor_id=ACTOR_A,
            organization_id=ORG_A,
            workspace_id=WORKSPACE_A,
        )
        visible = connection.execute("SELECT session_id::text FROM pulseiq.sessions").fetchall()
        revoked = connection.execute(
            """
            UPDATE pulseiq.sessions
            SET status = 'revoked', revoked_at = clock_timestamp(), revision = revision + 1
            WHERE session_id = %s
            RETURNING status, revision
            """,
            (SESSION_A,),
        ).fetchone()
        cross_actor_update = connection.execute(
            """
            UPDATE pulseiq.sessions
            SET status = 'revoked', revoked_at = clock_timestamp(), revision = revision + 1
            WHERE session_id = %s
            """,
            (SESSION_B,),
        ).rowcount

    assert visible == [(SESSION_A,)]
    assert revoked == ("revoked", 2)
    assert cross_actor_update == 0


def test_application_role_can_only_read_and_accept_current_tenant_invitation(migrated_database: str) -> None:
    with psycopg.connect(migrated_database) as connection:
        _set_application_context(
            connection,
            actor_id=ACTOR_A,
            organization_id=ORG_A,
            workspace_id=WORKSPACE_A,
        )
        visible = connection.execute("SELECT invitation_id::text FROM pulseiq.workspace_invitations").fetchall()
        accepted = connection.execute(
            """
            UPDATE pulseiq.workspace_invitations
            SET status = 'accepted', accepted_by = %s,
                accepted_at = clock_timestamp(), revision = revision + 1
            WHERE invitation_id = %s
            RETURNING status, revision
            """,
            (ACTOR_A, INVITATION_A),
        ).fetchone()
        cross_tenant_update = connection.execute(
            """
            UPDATE pulseiq.workspace_invitations
            SET status = 'revoked', revision = revision + 1
            WHERE invitation_id = %s
            """,
            (INVITATION_B,),
        ).rowcount

    assert visible == [(INVITATION_A,)]
    assert accepted == ("accepted", 2)
    assert cross_tenant_update == 0


def test_postgres_adapter_revokes_session_with_atomic_audit_evidence(migrated_database: str) -> None:
    scope = DatabaseScope(actor_id=ACTOR_A, organization_id=ORG_A, workspace_id=WORKSPACE_A)
    with ConnectionPool(
        conninfo=migrated_database,
        min_size=1,
        max_size=2,
        configure=_configure_application_role,
    ) as pool:
        repository = PostgresIdentityRepository(pool, scope)
        session = repository.find_active_session(
            session_id=SESSION_A,
            actor_id=ACTOR_A,
            active_at=datetime.now(UTC),
        )
        assert session is not None
        actor = AuthenticatedActor(
            actor_id=ACTOR_A,
            session_id=SESSION_A,
            authenticated_at=session.authenticated_at,
            expires_at=session.expires_at,
            authentication_methods=("federated", "mfa"),
        )
        authorization = AuthorizationService(repository, repository, clock=lambda: datetime.now(UTC))
        request = AuthorizationRequest(
            actor=actor,
            permission=Permission.WORKSPACE_VIEW,
            scope=ResourceScope(
                organization_id=ORG_A,
                workspace_id=WORKSPACE_A,
                resource_type="workspace",
                resource_id=WORKSPACE_A,
            ),
        )
        assert authorization.authorize(request).allowed

        result = SessionAdministrationService(
            repository,
            clock=lambda: datetime.now(UTC),
            event_id_factory=lambda: AUDIT_EVENT_A,
        ).logout(
            RevokeSession(
                actor=actor,
                organization_id=ORG_A,
                workspace_id=WORKSPACE_A,
                reason="User signed out.",
                request_id=REQUEST_A,
            )
        )

        assert result.session.revision == 2
        assert authorization.authorize(request).reason_code == "session_inactive"

    with psycopg.connect(migrated_database) as connection:
        recorded = connection.execute(
            "SELECT action, target_id::text FROM pulseiq.audit_events WHERE event_id = %s",
            (AUDIT_EVENT_A,),
        ).fetchone()
        outboxed = connection.execute(
            "SELECT topic FROM pulseiq.outbox_events WHERE aggregate_id = %s",
            (AUDIT_EVENT_A,),
        ).fetchone()
    assert recorded == ("session.revoked", SESSION_A)
    assert outboxed == ("audit.recorded",)


def test_postgres_adapter_changes_role_with_optimistic_revision_and_audit(migrated_database: str) -> None:
    scope = DatabaseScope(actor_id=ACTOR_A, organization_id=ORG_A, workspace_id=WORKSPACE_A)
    with ConnectionPool(
        conninfo=migrated_database,
        min_size=1,
        max_size=2,
        configure=_configure_application_role,
    ) as pool:
        repository = PostgresIdentityRepository(pool, scope)
        session = repository.find_active_session(
            session_id=SESSION_A,
            actor_id=ACTOR_A,
            active_at=datetime.now(UTC),
        )
        assert session is not None
        actor = AuthenticatedActor(
            actor_id=ACTOR_A,
            session_id=SESSION_A,
            authenticated_at=session.authenticated_at,
            expires_at=session.expires_at,
            authentication_methods=("federated", "mfa"),
        )
        authorization = AuthorizationService(repository, repository, clock=lambda: datetime.now(UTC))
        result = IdentityAdministrationService(
            repository,
            authorization,
            clock=lambda: datetime.now(UTC),
            event_id_factory=lambda: AUDIT_EVENT_ROLE,
        ).change_role(
            ChangeMembershipRole(
                actor=actor,
                organization_id=ORG_A,
                workspace_id=WORKSPACE_A,
                membership_id=MEMBERSHIP_C,
                new_role=Role.APPROVER,
                reason="Separate model training from approval.",
                request_id=REQUEST_ROLE,
            )
        )

    assert result.membership.role is Role.APPROVER
    assert result.membership.revision == 2
    with psycopg.connect(migrated_database) as connection:
        persisted = connection.execute(
            "SELECT role, revision FROM pulseiq.memberships WHERE membership_id = %s",
            (MEMBERSHIP_C,),
        ).fetchone()
        audit = connection.execute(
            "SELECT action, target_id::text FROM pulseiq.audit_events WHERE event_id = %s",
            (AUDIT_EVENT_ROLE,),
        ).fetchone()
    assert persisted == ("approver", 2)
    assert audit == ("membership.role_changed", MEMBERSHIP_C)


def test_postgres_adapter_accepts_invitation_with_membership_and_audit_atomically(migrated_database: str) -> None:
    issuer_scope = DatabaseScope(actor_id=ACTOR_A, organization_id=ORG_A, workspace_id=WORKSPACE_A)
    recipient_scope = DatabaseScope(actor_id=ACTOR_D, organization_id=ORG_A, workspace_id=WORKSPACE_A)
    email_binding_key = b"integration-email-binding-key-32-bytes"
    raw_token = "integration-one-time-invitation-token-0001"
    with ConnectionPool(
        conninfo=migrated_database,
        min_size=1,
        max_size=3,
        configure=_configure_application_role,
    ) as pool:
        issuer_repository = PostgresIdentityRepository(pool, issuer_scope)
        issuer_session = issuer_repository.find_active_session(
            session_id=SESSION_A,
            actor_id=ACTOR_A,
            active_at=datetime.now(UTC),
        )
        assert issuer_session is not None
        issuer = AuthenticatedActor(
            actor_id=ACTOR_A,
            session_id=SESSION_A,
            authenticated_at=issuer_session.authenticated_at,
            expires_at=issuer_session.expires_at,
            authentication_methods=("federated", "mfa"),
        )
        issued = IdentityInvitationService(
            issuer_repository,
            AuthorizationService(issuer_repository, issuer_repository, clock=lambda: datetime.now(UTC)),
            email_binding_key=email_binding_key,
            clock=lambda: datetime.now(UTC),
            invitation_id_factory=lambda: INVITATION_D,
            event_id_factory=lambda: AUDIT_EVENT_INVITE,
            token_factory=lambda: raw_token,
        ).issue(
            InviteWorkspaceMember(
                actor=issuer,
                organization_id=ORG_A,
                workspace_id=WORKSPACE_A,
                invitee_email="new.reviewer@example.com",
                role=Role.RISK_REVIEWER,
                expires_in=timedelta(hours=1),
                reason="Add the assigned risk reviewer.",
                request_id=REQUEST_INVITE,
            )
        )

        recipient_repository = PostgresIdentityRepository(pool, recipient_scope)
        recipient_session = recipient_repository.find_active_session(
            session_id=SESSION_D,
            actor_id=ACTOR_D,
            active_at=datetime.now(UTC),
        )
        assert recipient_session is not None
        recipient = AuthenticatedActor(
            actor_id=ACTOR_D,
            session_id=SESSION_D,
            authenticated_at=recipient_session.authenticated_at,
            expires_at=recipient_session.expires_at,
            authentication_methods=("federated", "mfa"),
        )
        accepted = IdentityInvitationService(
            recipient_repository,
            AuthorizationService(recipient_repository, recipient_repository, clock=lambda: datetime.now(UTC)),
            email_binding_key=email_binding_key,
            clock=lambda: datetime.now(UTC),
            invitation_id_factory=lambda: "unused",
            membership_id_factory=lambda: MEMBERSHIP_D,
            event_id_factory=lambda: AUDIT_EVENT_ACCEPT,
        ).accept(
            AcceptWorkspaceInvitation(
                actor=recipient,
                verified_email="NEW.REVIEWER@example.com",
                token=issued.token,
                request_id=REQUEST_ACCEPT,
            )
        )

    assert accepted.membership.membership_id == MEMBERSHIP_D
    assert accepted.membership.role is Role.RISK_REVIEWER
    with psycopg.connect(migrated_database) as connection:
        persisted = connection.execute(
            "SELECT role, status FROM pulseiq.memberships WHERE membership_id = %s",
            (MEMBERSHIP_D,),
        ).fetchone()
        audit_actions = connection.execute(
            """
            SELECT action FROM pulseiq.audit_events
            WHERE event_id IN (%s, %s)
            ORDER BY occurred_at
            """,
            (AUDIT_EVENT_INVITE, AUDIT_EVENT_ACCEPT),
        ).fetchall()
    assert persisted == ("risk_reviewer", "active")
    assert audit_actions == [("membership.invitation_issued",), ("membership.invitation_accepted",)]


def test_postgres_adapter_allows_reissue_after_pending_invitation_expires(migrated_database: str) -> None:
    email_binding_key = b"integration-email-binding-key-32-bytes"
    email = "expired.recipient@example.com"
    email_binding = hmac.new(email_binding_key, email.encode(), hashlib.sha256).digest()
    with psycopg.connect(migrated_database, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO pulseiq.workspace_invitations (
                invitation_id, organization_id, workspace_id, email_binding,
                role, status, token_digest, issued_by, issued_at, expires_at
            ) VALUES (
                %s, %s, %s, %s, 'read_only', 'pending',
                decode(repeat('c1', 32), 'hex'), %s,
                clock_timestamp() - interval '2 hours', clock_timestamp() - interval '1 hour'
            )
            """,
            (INVITATION_EXPIRED, ORG_A, WORKSPACE_A, email_binding, ACTOR_A),
        )

    scope = DatabaseScope(actor_id=ACTOR_A, organization_id=ORG_A, workspace_id=WORKSPACE_A)
    with ConnectionPool(
        conninfo=migrated_database,
        min_size=1,
        max_size=2,
        configure=_configure_application_role,
    ) as pool:
        repository = PostgresIdentityRepository(pool, scope)
        session = repository.find_active_session(
            session_id=SESSION_A,
            actor_id=ACTOR_A,
            active_at=datetime.now(UTC),
        )
        assert session is not None
        actor = AuthenticatedActor(
            actor_id=ACTOR_A,
            session_id=SESSION_A,
            authenticated_at=session.authenticated_at,
            expires_at=session.expires_at,
            authentication_methods=("federated", "mfa"),
        )
        issued = IdentityInvitationService(
            repository,
            AuthorizationService(repository, repository, clock=lambda: datetime.now(UTC)),
            email_binding_key=email_binding_key,
            clock=lambda: datetime.now(UTC),
            invitation_id_factory=lambda: INVITATION_REISSUE,
            event_id_factory=lambda: AUDIT_EVENT_REISSUE,
            token_factory=lambda: "replacement-one-time-invitation-token-0001",
        ).issue(
            InviteWorkspaceMember(
                actor=actor,
                organization_id=ORG_A,
                workspace_id=WORKSPACE_A,
                invitee_email=email,
                role=Role.READ_ONLY,
                expires_in=timedelta(hours=1),
                reason="Replace the expired invitation.",
                request_id=REQUEST_REISSUE,
            )
        )

    assert issued.invitation.invitation_id == INVITATION_REISSUE


def test_overlapping_pending_invitations_are_rejected_by_database_constraint(migrated_database: str) -> None:
    binding = bytes.fromhex("d1" * 32)
    with psycopg.connect(migrated_database, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO pulseiq.workspace_invitations (
                invitation_id, organization_id, workspace_id, email_binding,
                role, status, token_digest, issued_by, issued_at, expires_at
            ) VALUES (
                '12345678-1111-4111-8111-111111111111', %s, %s, %s,
                'read_only', 'pending', decode(repeat('d2', 32), 'hex'), %s,
                clock_timestamp(), clock_timestamp() + interval '1 hour'
            )
            """,
            (ORG_A, WORKSPACE_A, binding, ACTOR_A),
        )
        with pytest.raises(psycopg.errors.ExclusionViolation):
            connection.execute(
                """
                INSERT INTO pulseiq.workspace_invitations (
                    invitation_id, organization_id, workspace_id, email_binding,
                    role, status, token_digest, issued_by, issued_at, expires_at
                ) VALUES (
                    '12345678-2222-4222-8222-222222222222', %s, %s, %s,
                    'read_only', 'pending', decode(repeat('d3', 32), 'hex'), %s,
                    clock_timestamp() + interval '30 minutes', clock_timestamp() + interval '2 hours'
                )
                """,
                (ORG_A, WORKSPACE_A, binding, ACTOR_A),
            )


def test_authorization_lookup_index_is_planner_eligible(migrated_database: str) -> None:
    with psycopg.connect(migrated_database) as connection:
        _set_application_context(
            connection,
            actor_id=ACTOR_A,
            organization_id=ORG_A,
            workspace_id=WORKSPACE_A,
        )
        connection.execute("SET LOCAL enable_seqscan = off")
        row = connection.execute(
            """
            EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
            SELECT membership_id, role, revision, activated_at
            FROM pulseiq.memberships
            WHERE actor_id = %s AND organization_id = %s AND workspace_id = %s
              AND status = 'active'
            """,
            (ACTOR_A, ORG_A, WORKSPACE_A),
        ).fetchone()

    assert row is not None
    plan = json.dumps(row[0])
    assert "memberships_active_actor_scope_idx" in plan
    assert '"Actual Rows": 1' in plan


def test_dataset_versions_and_import_jobs_are_tenant_scoped_and_idempotent(migrated_database: str) -> None:
    checksum = bytes.fromhex("e1" * 32)
    filename_binding = bytes.fromhex("e2" * 32)
    with psycopg.connect(migrated_database, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO pulseiq.datasets (dataset_id, organization_id, workspace_id, created_by)
            VALUES (%s, %s, %s, %s), (%s, %s, %s, %s)
            """,
            (DATASET_A, ORG_A, WORKSPACE_A, ACTOR_A, DATASET_B, ORG_B, WORKSPACE_B, ACTOR_B),
        )
        connection.execute(
            """
            INSERT INTO pulseiq.dataset_versions (
                dataset_version_id, dataset_id, organization_id, workspace_id,
                status, object_key, filename_binding, content_type,
                expected_bytes, expected_sha256, created_by
            ) VALUES
                (%s, %s, %s, %s, 'upload_pending', %s, %s, 'text/csv', 1024, %s, %s),
                (%s, %s, %s, %s, 'upload_pending', %s, %s, 'text/csv', 2048, %s, %s)
            """,
            (
                DATASET_VERSION_A,
                DATASET_A,
                ORG_A,
                WORKSPACE_A,
                f"quarantine/{ORG_A}/{WORKSPACE_A}/{DATASET_A}/{DATASET_VERSION_A}/original.csv",
                filename_binding,
                checksum,
                ACTOR_A,
                DATASET_VERSION_B,
                DATASET_B,
                ORG_B,
                WORKSPACE_B,
                f"quarantine/{ORG_B}/{WORKSPACE_B}/{DATASET_B}/{DATASET_VERSION_B}/original.csv",
                filename_binding,
                checksum,
                ACTOR_B,
            ),
        )

    with psycopg.connect(migrated_database) as connection:
        _set_application_context(
            connection,
            actor_id=ACTOR_A,
            organization_id=ORG_A,
            workspace_id=WORKSPACE_A,
        )
        visible = connection.execute("SELECT dataset_version_id::text FROM pulseiq.dataset_versions").fetchall()
        connection.execute(
            """
            INSERT INTO pulseiq.import_jobs (
                job_id, organization_id, workspace_id, dataset_version_id,
                job_type, status, input_reference, idempotency_key
            ) VALUES (%s, %s, %s, %s, 'dataset.scan', 'queued', %s::jsonb, %s)
            """,
            (
                IMPORT_JOB_A,
                ORG_A,
                WORKSPACE_A,
                DATASET_VERSION_A,
                json.dumps({"dataset_version_id": DATASET_VERSION_A}),
                f"dataset.scan:{DATASET_VERSION_A}:{checksum.hex()}",
            ),
        )

    assert visible == [(DATASET_VERSION_A,)]
    with psycopg.connect(migrated_database) as connection:
        queued = connection.execute(
            "SELECT topic, aggregate_id::text FROM pulseiq.outbox_events WHERE aggregate_id = %s",
            (IMPORT_JOB_A,),
        ).fetchone()
    assert queued == ("job.queued", IMPORT_JOB_A)


def test_postgres_dataset_repository_completes_upload_and_replays_original_job(migrated_database: str) -> None:
    checksum = "6f8db599de986fab7a21625b7916589c94cc3107c10fcb27c01f9564a047f8f1"  # pragma: allowlist secret
    with psycopg.connect(migrated_database, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO pulseiq.datasets (dataset_id, organization_id, workspace_id, created_by)
            VALUES (%s, %s, %s, %s)
            """,
            (DATASET_A, ORG_A, WORKSPACE_A, ACTOR_E),
        )

    scope = DatabaseScope(actor_id=ACTOR_E, organization_id=ORG_A, workspace_id=WORKSPACE_A)
    storage = InMemoryQuarantineUploadSigner(base_url="https://quarantine.invalid")
    with ConnectionPool(
        conninfo=migrated_database,
        min_size=1,
        max_size=3,
        configure=_configure_application_role,
    ) as pool:
        identity_repository = PostgresIdentityRepository(pool, scope)
        dataset_repository = PostgresDatasetUploadRepository(pool, scope)
        session = identity_repository.find_active_session(
            session_id=SESSION_E,
            actor_id=ACTOR_E,
            active_at=datetime.now(UTC),
        )
        assert session is not None
        actor = AuthenticatedActor(
            actor_id=ACTOR_E,
            session_id=SESSION_E,
            authenticated_at=session.authenticated_at,
            expires_at=session.expires_at,
            authentication_methods=("federated", "mfa"),
        )
        service = DatasetUploadService(
            dataset_repository,
            storage,
            AuthorizationService(identity_repository, identity_repository, clock=lambda: datetime.now(UTC)),
            filename_binding_key=b"integration-filename-binding-key-32-bytes",
            clock=lambda: datetime.now(UTC),
            dataset_version_id_factory=lambda: DATASET_VERSION_UPLOAD,
            audit_event_id_factory=iter((AUDIT_EVENT_UPLOAD_RESERVED, AUDIT_EVENT_UPLOAD_COMPLETED)).__next__,
            job_id_factory=lambda: IMPORT_JOB_UPLOAD,
        )
        reservation = service.begin_upload(
            BeginDatasetUpload(
                actor=actor,
                organization_id=ORG_A,
                workspace_id=WORKSPACE_A,
                dataset_id=DATASET_A,
                source_filename="customers.csv",
                content_type="text/csv",
                content_length=1024,
                checksum_sha256=checksum,
                request_id=REQUEST_UPLOAD_RESERVED,
            )
        )
        storage.record_uploaded_object(
            object_key=reservation.version.object_key,
            content_type="text/csv",
            content_length=1024,
            checksum_sha256=checksum,
        )
        command = CompleteDatasetUpload(
            actor=actor,
            organization_id=ORG_A,
            workspace_id=WORKSPACE_A,
            dataset_version_id=DATASET_VERSION_UPLOAD,
            request_id=REQUEST_UPLOAD_COMPLETED,
        )
        completed = service.complete_upload(command)
        replay = service.complete_upload(command)

    assert replay.job == completed.job
    assert replay.audit_event is None
    with psycopg.connect(migrated_database) as connection:
        persisted = connection.execute(
            "SELECT status, revision FROM pulseiq.dataset_versions WHERE dataset_version_id = %s",
            (DATASET_VERSION_UPLOAD,),
        ).fetchone()
        job = connection.execute(
            "SELECT status, idempotency_key FROM pulseiq.import_jobs WHERE job_id = %s",
            (IMPORT_JOB_UPLOAD,),
        ).fetchone()
        actions = connection.execute(
            """
            SELECT action FROM pulseiq.audit_events
            WHERE event_id IN (%s, %s)
            ORDER BY occurred_at
            """,
            (AUDIT_EVENT_UPLOAD_RESERVED, AUDIT_EVENT_UPLOAD_COMPLETED),
        ).fetchall()
    assert persisted == ("uploaded", 2)
    assert job == ("queued", f"dataset.scan:{DATASET_VERSION_UPLOAD}:{checksum}")
    assert actions == [("dataset.upload_reserved",), ("dataset.upload_completed",)]


def test_postgres_dataset_repository_persists_metadata_mismatch_quarantine(migrated_database: str) -> None:
    checksum = "6f8db599de986fab7a21625b7916589c94cc3107c10fcb27c01f9564a047f8f1"  # pragma: allowlist secret
    with psycopg.connect(migrated_database, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO pulseiq.datasets (dataset_id, organization_id, workspace_id, created_by)
            VALUES (%s, %s, %s, %s)
            """,
            (DATASET_A, ORG_A, WORKSPACE_A, ACTOR_E),
        )

    scope = DatabaseScope(actor_id=ACTOR_E, organization_id=ORG_A, workspace_id=WORKSPACE_A)
    storage = InMemoryQuarantineUploadSigner(base_url="https://quarantine.invalid")
    with ConnectionPool(
        conninfo=migrated_database,
        min_size=1,
        max_size=3,
        configure=_configure_application_role,
    ) as pool:
        identity_repository = PostgresIdentityRepository(pool, scope)
        session = identity_repository.find_active_session(
            session_id=SESSION_E,
            actor_id=ACTOR_E,
            active_at=datetime.now(UTC),
        )
        assert session is not None
        actor = AuthenticatedActor(
            actor_id=ACTOR_E,
            session_id=SESSION_E,
            authenticated_at=session.authenticated_at,
            expires_at=session.expires_at,
            authentication_methods=("federated", "mfa"),
        )
        service = DatasetUploadService(
            PostgresDatasetUploadRepository(pool, scope),
            storage,
            AuthorizationService(identity_repository, identity_repository, clock=lambda: datetime.now(UTC)),
            filename_binding_key=b"integration-filename-binding-key-32-bytes",
            clock=lambda: datetime.now(UTC),
            dataset_version_id_factory=lambda: DATASET_VERSION_QUARANTINED,
            audit_event_id_factory=iter((AUDIT_EVENT_QUARANTINE_RESERVED, AUDIT_EVENT_QUARANTINED)).__next__,
            job_id_factory=lambda: pytest.fail("A mismatched upload must not enqueue a scan job."),
        )
        reservation = service.begin_upload(
            BeginDatasetUpload(
                actor=actor,
                organization_id=ORG_A,
                workspace_id=WORKSPACE_A,
                dataset_id=DATASET_A,
                source_filename="customers.csv",
                content_type="text/csv",
                content_length=1024,
                checksum_sha256=checksum,
                request_id=REQUEST_QUARANTINE_RESERVED,
            )
        )
        storage.record_uploaded_object(
            object_key=reservation.version.object_key,
            content_type="text/csv",
            content_length=2048,
            checksum_sha256=checksum,
        )
        with pytest.raises(DatasetUploadError, match="Dataset upload could not be reserved") as error:
            service.complete_upload(
                CompleteDatasetUpload(
                    actor=actor,
                    organization_id=ORG_A,
                    workspace_id=WORKSPACE_A,
                    dataset_version_id=DATASET_VERSION_QUARANTINED,
                    request_id=REQUEST_QUARANTINED,
                )
            )

    assert error.value.code == "upload_metadata_mismatch"
    with psycopg.connect(migrated_database) as connection:
        persisted = connection.execute(
            """
            SELECT status, revision, failure_code
            FROM pulseiq.dataset_versions
            WHERE dataset_version_id = %s
            """,
            (DATASET_VERSION_QUARANTINED,),
        ).fetchone()
        jobs = connection.execute(
            "SELECT count(*) FROM pulseiq.import_jobs WHERE dataset_version_id = %s",
            (DATASET_VERSION_QUARANTINED,),
        ).fetchone()
        outbox = connection.execute(
            "SELECT count(*) FROM pulseiq.outbox_events WHERE aggregate_id = %s",
            (DATASET_VERSION_QUARANTINED,),
        ).fetchone()
        actions = connection.execute(
            """
            SELECT action FROM pulseiq.audit_events
            WHERE event_id IN (%s, %s)
            ORDER BY occurred_at
            """,
            (AUDIT_EVENT_QUARANTINE_RESERVED, AUDIT_EVENT_QUARANTINED),
        ).fetchall()
    assert persisted == ("quarantined", 2, "upload_metadata_mismatch")
    assert jobs == (0,)
    assert outbox == (0,)
    assert actions == [("dataset.upload_reserved",), ("dataset.upload_quarantined",)]


def test_postgres_outbox_claims_are_exclusive_retryable_and_dead_lettered(migrated_database: str) -> None:
    with psycopg.connect(migrated_database, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO pulseiq.outbox_events (topic, aggregate_id, payload)
            VALUES
                ('job.queued', %s, %s::jsonb),
                ('job.queued', %s, %s::jsonb)
            """,
            (
                IMPORT_JOB_A,
                json.dumps({"job_id": IMPORT_JOB_A}),
                IMPORT_JOB_UPLOAD,
                json.dumps({"job_id": IMPORT_JOB_UPLOAD}),
            ),
        )

    now = datetime.now(UTC) + timedelta(seconds=1)
    with ConnectionPool(
        conninfo=migrated_database,
        min_size=1,
        max_size=3,
        configure=_configure_worker_role,
    ) as pool:
        first_repository = PostgresOutboxRepository(
            pool,
            lease_token_factory=lambda: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        )
        second_repository = PostgresOutboxRepository(
            pool,
            lease_token_factory=lambda: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        )
        first = first_repository.claim_batch(limit=1, claimed_at=now, lease_for=timedelta(seconds=30))
        second = second_repository.claim_batch(limit=10, claimed_at=now, lease_for=timedelta(seconds=30))

        assert len(first) == 1
        assert len(second) == 1
        assert first[0].event.sequence != second[0].event.sequence
        assert first[0].event.attempts == 1
        assert second[0].event.attempts == 1

        first_repository.mark_published(
            sequence=first[0].event.sequence,
            lease_token=first[0].lease_token,
            published_at=now,
        )
        retry_at = now + timedelta(seconds=5)
        second_repository.record_failure(
            sequence=second[0].event.sequence,
            lease_token=second[0].lease_token,
            failed_at=now,
            error_code="broker_unavailable",
            retry_at=retry_at,
            dead_letter=False,
        )
        assert (
            second_repository.claim_batch(
                limit=10,
                claimed_at=now + timedelta(seconds=4),
                lease_for=timedelta(seconds=30),
            )
            == ()
        )
        retry = second_repository.claim_batch(
            limit=10,
            claimed_at=now + timedelta(seconds=6),
            lease_for=timedelta(seconds=30),
        )
        assert len(retry) == 1
        assert retry[0].event.sequence == second[0].event.sequence
        assert retry[0].event.attempts == 2
        second_repository.record_failure(
            sequence=retry[0].event.sequence,
            lease_token=retry[0].lease_token,
            failed_at=now + timedelta(seconds=6),
            error_code="invalid_topic",
            retry_at=None,
            dead_letter=True,
        )

    with psycopg.connect(migrated_database) as connection:
        rows = connection.execute(
            """
            SELECT published_at IS NOT NULL, dead_lettered_at IS NOT NULL,
                   attempts, last_error_code, lease_token
            FROM pulseiq.outbox_events
            ORDER BY outbox_sequence
            """
        ).fetchall()
    assert rows == [
        (True, False, 1, None, None),
        (False, True, 2, "invalid_topic", None),
    ]


def test_outbox_dispatcher_publishes_postgres_event_to_local_redis(migrated_database: str) -> None:
    if REDIS_URL is None:
        pytest.skip("Set PULSEIQ_TEST_REDIS_URL to run the Redis outbox integration test.")
    parsed = urlparse(REDIS_URL)
    if parsed.scheme != "redis" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.path != "/15":
        pytest.fail("The destructive Redis integration test is restricted to local database 15.")

    with psycopg.connect(migrated_database, autocommit=True) as connection:
        sequence = connection.execute(
            """
            INSERT INTO pulseiq.outbox_events (topic, aggregate_id, payload)
            VALUES ('job.queued', %s, %s::jsonb)
            RETURNING outbox_sequence
            """,
            (IMPORT_JOB_UPLOAD, json.dumps({"job_id": IMPORT_JOB_UPLOAD})),
        ).fetchone()
    assert sequence is not None

    redis_client = Redis.from_url(REDIS_URL, socket_connect_timeout=3, socket_timeout=3)
    redis_client.flushdb()
    now = datetime.now(UTC) + timedelta(seconds=1)
    try:
        with ConnectionPool(
            conninfo=migrated_database,
            min_size=1,
            max_size=3,
            configure=_configure_worker_role,
        ) as pool:
            dispatcher = OutboxDispatcher(
                PostgresOutboxRepository(
                    pool,
                    lease_token_factory=lambda: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                ),
                CeleryMessagePublisher(create_celery_app(REDIS_URL)),
                clock=lambda: now,
            )
            report = dispatcher.dispatch_once(limit=10)

        assert report.claimed == 1
        assert report.published == 1
        assert redis_client.llen("dataset-ingestion") == 1
        with psycopg.connect(migrated_database) as connection:
            persisted = connection.execute(
                """
                SELECT published_at IS NOT NULL, attempts, lease_token, dead_lettered_at
                FROM pulseiq.outbox_events
                WHERE outbox_sequence = %s
                """,
                (sequence[0],),
            ).fetchone()
        assert persisted == (True, 1, None, None)
    finally:
        redis_client.flushdb()
        redis_client.close()


def test_postgres_import_job_execution_lease_retry_heartbeat_and_success(migrated_database: str) -> None:
    checksum = hashlib.sha256(b"import-job").digest()
    with psycopg.connect(migrated_database, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO pulseiq.datasets (dataset_id, organization_id, workspace_id, created_by)
            VALUES (%s, %s, %s, %s)
            """,
            (DATASET_A, ORG_A, WORKSPACE_A, ACTOR_E),
        )
        connection.execute(
            """
            INSERT INTO pulseiq.dataset_versions (
                dataset_version_id, dataset_id, organization_id, workspace_id,
                status, object_key, filename_binding, content_type,
                expected_bytes, expected_sha256, created_by, uploaded_at
            ) VALUES (%s, %s, %s, %s, 'uploaded', %s, %s, 'text/csv', %s, %s, %s, clock_timestamp())
            """,
            (
                DATASET_VERSION_UPLOAD,
                DATASET_A,
                ORG_A,
                WORKSPACE_A,
                f"quarantine/{ORG_A}/{WORKSPACE_A}/{DATASET_A}/{DATASET_VERSION_UPLOAD}/original.csv",
                checksum,
                1024,
                checksum,
                ACTOR_E,
            ),
        )
        connection.execute(
            """
            INSERT INTO pulseiq.import_jobs (
                job_id, organization_id, workspace_id, dataset_version_id,
                job_type, status, input_reference, idempotency_key
            ) VALUES (%s, %s, %s, %s, 'dataset.scan', 'queued', %s::jsonb, %s)
            """,
            (
                IMPORT_JOB_UPLOAD,
                ORG_A,
                WORKSPACE_A,
                DATASET_VERSION_UPLOAD,
                json.dumps({"dataset_version_id": DATASET_VERSION_UPLOAD}),
                f"dataset.scan:{DATASET_VERSION_UPLOAD}:{checksum.hex()}",
            ),
        )

    now = datetime.now(UTC) + timedelta(seconds=1)
    with ConnectionPool(
        conninfo=migrated_database,
        min_size=1,
        max_size=3,
        configure=_configure_worker_role,
    ) as pool:
        repository = PostgresImportJobRepository(
            pool,
            execution_token_factory=iter(
                (
                    "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                    "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                    "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
                    "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
                )
            ).__next__,
        )
        first = repository.claim_job(
            job_id=IMPORT_JOB_UPLOAD,
            claimed_at=now,
            lease_for=timedelta(minutes=5),
        )
        assert first is not None
        assert first.attempts == 1
        with psycopg.connect(migrated_database) as connection:
            assert connection.execute(
                "SELECT status, revision FROM pulseiq.dataset_versions WHERE dataset_version_id = %s",
                (DATASET_VERSION_UPLOAD,),
            ).fetchone() == ("scanning", 2)
        assert (
            repository.claim_job(
                job_id=IMPORT_JOB_UPLOAD,
                claimed_at=now,
                lease_for=timedelta(minutes=5),
            )
            is None
        )
        retry_at = now + timedelta(seconds=5)
        repository.record_failure(
            job_id=first.job_id,
            execution_token=first.execution_token,
            failed_at=now,
            error_code="scanner_unavailable",
            retry_at=retry_at,
            permanent=False,
        )
        with pytest.raises(RuntimeError, match="lease is no longer current"):
            repository.heartbeat(
                job_id=first.job_id,
                execution_token=first.execution_token,
                heartbeat_at=now + timedelta(seconds=1),
                lease_for=timedelta(minutes=5),
                progress_percent=25,
            )
        second = repository.claim_job(
            job_id=IMPORT_JOB_UPLOAD,
            claimed_at=now + timedelta(seconds=6),
            lease_for=timedelta(minutes=5),
        )
        assert second is not None
        assert second.attempts == 2
        repository.heartbeat(
            job_id=second.job_id,
            execution_token=second.execution_token,
            heartbeat_at=now + timedelta(seconds=7),
            lease_for=timedelta(minutes=5),
            progress_percent=50,
        )
        repository.mark_succeeded(
            job_id=second.job_id,
            execution_token=second.execution_token,
            completed_at=now + timedelta(seconds=8),
        )
        assert (
            repository.claim_job(
                job_id=IMPORT_JOB_UPLOAD,
                claimed_at=now + timedelta(minutes=10),
                lease_for=timedelta(minutes=5),
            )
            is None
        )

    with psycopg.connect(migrated_database) as connection:
        persisted = connection.execute(
            """
            SELECT status, attempts, progress_percent, execution_token,
                   completed_at IS NOT NULL, error_code
            FROM pulseiq.import_jobs WHERE job_id = %s
            """,
            (IMPORT_JOB_UPLOAD,),
        ).fetchone()
        version = connection.execute(
            "SELECT status, revision, failure_code FROM pulseiq.dataset_versions WHERE dataset_version_id = %s",
            (DATASET_VERSION_UPLOAD,),
        ).fetchone()
    assert persisted == ("succeeded", 2, 100, None, True, None)
    assert version == ("mapping_required", 3, None)


def test_postgres_permanent_malware_failure_quarantines_dataset_atomically(migrated_database: str) -> None:
    checksum = hashlib.sha256(b"malware-job").digest()
    with psycopg.connect(migrated_database, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO pulseiq.datasets (dataset_id, organization_id, workspace_id, created_by)
            VALUES (%s, %s, %s, %s)
            """,
            (DATASET_A, ORG_A, WORKSPACE_A, ACTOR_E),
        )
        connection.execute(
            """
            INSERT INTO pulseiq.dataset_versions (
                dataset_version_id, dataset_id, organization_id, workspace_id,
                status, object_key, filename_binding, content_type,
                expected_bytes, expected_sha256, created_by, uploaded_at
            ) VALUES (%s, %s, %s, %s, 'uploaded', %s, %s, 'text/csv', %s, %s, %s, clock_timestamp())
            """,
            (
                DATASET_VERSION_UPLOAD,
                DATASET_A,
                ORG_A,
                WORKSPACE_A,
                f"quarantine/{ORG_A}/{WORKSPACE_A}/{DATASET_A}/{DATASET_VERSION_UPLOAD}/original.csv",
                checksum,
                1024,
                checksum,
                ACTOR_E,
            ),
        )
        connection.execute(
            """
            INSERT INTO pulseiq.import_jobs (
                job_id, organization_id, workspace_id, dataset_version_id,
                job_type, status, input_reference, idempotency_key
            ) VALUES (%s, %s, %s, %s, 'dataset.scan', 'queued', %s::jsonb, %s)
            """,
            (
                IMPORT_JOB_UPLOAD,
                ORG_A,
                WORKSPACE_A,
                DATASET_VERSION_UPLOAD,
                json.dumps({"dataset_version_id": DATASET_VERSION_UPLOAD}),
                f"dataset.scan:{DATASET_VERSION_UPLOAD}:{checksum.hex()}",
            ),
        )

    now = datetime.now(UTC) + timedelta(seconds=1)
    with ConnectionPool(
        conninfo=migrated_database,
        min_size=1,
        max_size=2,
        configure=_configure_worker_role,
    ) as pool:
        repository = PostgresImportJobRepository(
            pool,
            execution_token_factory=lambda: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        )
        claim = repository.claim_job(
            job_id=IMPORT_JOB_UPLOAD,
            claimed_at=now,
            lease_for=timedelta(minutes=5),
        )
        assert claim is not None
        repository.record_failure(
            job_id=claim.job_id,
            execution_token=claim.execution_token,
            failed_at=now + timedelta(seconds=1),
            error_code="malware_detected",
            retry_at=None,
            permanent=True,
        )

    with psycopg.connect(migrated_database) as connection:
        persisted = connection.execute(
            """
            SELECT job.status, job.error_code, version.status, version.failure_code, version.revision
            FROM pulseiq.import_jobs AS job
            JOIN pulseiq.dataset_versions AS version USING (dataset_version_id)
            WHERE job.job_id = %s
            """,
            (IMPORT_JOB_UPLOAD,),
        ).fetchone()
    assert persisted == ("permanently_failed", "malware_detected", "quarantined", "malware_detected", 3)


def test_postgres_normalized_artifact_lineage_is_idempotent_and_immutable(migrated_database: str) -> None:
    source_checksum = hashlib.sha256(b"source").hexdigest()
    artifact_checksum = hashlib.sha256(b"parquet").hexdigest()
    schema_fingerprint = hashlib.sha256(b"schema").hexdigest()
    created_at = datetime.now(UTC)
    with psycopg.connect(migrated_database, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO pulseiq.datasets (dataset_id, organization_id, workspace_id, created_by)
            VALUES (%s, %s, %s, %s)
            """,
            (DATASET_A, ORG_A, WORKSPACE_A, ACTOR_E),
        )
        connection.execute(
            """
            INSERT INTO pulseiq.dataset_versions (
                dataset_version_id, dataset_id, organization_id, workspace_id,
                status, object_key, filename_binding, content_type,
                expected_bytes, expected_sha256, created_by
            ) VALUES (%s, %s, %s, %s, 'scanning', %s, %s, 'text/csv', %s, %s, %s)
            """,
            (
                DATASET_VERSION_UPLOAD,
                DATASET_A,
                ORG_A,
                WORKSPACE_A,
                f"quarantine/{ORG_A}/{WORKSPACE_A}/{DATASET_A}/{DATASET_VERSION_UPLOAD}/original.csv",
                bytes.fromhex(source_checksum),
                1024,
                bytes.fromhex(source_checksum),
                ACTOR_E,
            ),
        )

    artifact = NormalizedDatasetArtifact(
        dataset_version_id=DATASET_VERSION_UPLOAD,
        organization_id=ORG_A,
        workspace_id=WORKSPACE_A,
        object_key=f"normalized/{ORG_A}/{WORKSPACE_A}/{DATASET_A}/{DATASET_VERSION_UPLOAD}/data.parquet",
        source_sha256=source_checksum,
        artifact_sha256=artifact_checksum,
        schema_fingerprint=schema_fingerprint,
        row_count=10,
        column_count=3,
        normalization_version="1",
        fields=(
            NormalizedArtifactField(1, "Customer ID", "customer_id", "string", False),
            NormalizedArtifactField(2, "Amount", "amount", "string", False),
            NormalizedArtifactField(3, "Currency", "currency", "string", False),
        ),
        created_at=created_at,
    )
    with ConnectionPool(
        conninfo=migrated_database,
        min_size=1,
        max_size=2,
        configure=_configure_worker_role,
    ) as pool:
        repository = PostgresNormalizedArtifactRepository(pool)
        repository.record_artifact(artifact)
        repository.record_artifact(artifact)
        conflicting = NormalizedDatasetArtifact(
            dataset_version_id=artifact.dataset_version_id,
            organization_id=artifact.organization_id,
            workspace_id=artifact.workspace_id,
            object_key=artifact.object_key,
            source_sha256=artifact.source_sha256,
            artifact_sha256="0" * 64,
            schema_fingerprint=artifact.schema_fingerprint,
            row_count=artifact.row_count,
            column_count=artifact.column_count,
            normalization_version=artifact.normalization_version,
            fields=artifact.fields,
            created_at=artifact.created_at,
        )
        with pytest.raises(RuntimeError, match="lineage conflicts"):
            repository.record_artifact(conflicting)

    with psycopg.connect(migrated_database) as connection:
        persisted = connection.execute(
            """
            SELECT encode(artifact_sha256, 'hex'), encode(schema_fingerprint, 'hex'),
                   row_count, column_count
            FROM pulseiq.dataset_artifacts WHERE dataset_version_id = %s
            """,
            (DATASET_VERSION_UPLOAD,),
        ).fetchone()
        assert persisted == (artifact_checksum, schema_fingerprint, 10, 3)
        fields = connection.execute(
            """
            SELECT position, source_column, normalized_column, physical_type, nullable
            FROM pulseiq.dataset_artifact_fields
            WHERE dataset_version_id = %s ORDER BY position
            """,
            (DATASET_VERSION_UPLOAD,),
        ).fetchall()
        assert fields == [
            (1, "Customer ID", "customer_id", "string", False),
            (2, "Amount", "amount", "string", False),
            (3, "Currency", "currency", "string", False),
        ]
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            connection.execute(
                "UPDATE pulseiq.dataset_artifacts SET row_count = 11 WHERE dataset_version_id = %s",
                (DATASET_VERSION_UPLOAD,),
            )


def test_postgres_schema_mapping_confirmation_is_atomic_and_schema_bound(migrated_database: str) -> None:
    mapping_version_id = "77777777-cccc-4ccc-8ccc-777777777777"
    validation_job_id = "77777777-eeee-4eee-8eee-777777777777"
    audit_event_id = "77777777-6666-4666-8666-777777777777"
    request_id = "77777777-7777-4777-8777-777777777777"
    checksum = hashlib.sha256(b"mapping-source").digest()
    artifact_checksum = hashlib.sha256(b"mapping-parquet").digest()
    schema_fingerprint = hashlib.sha256(b"mapping-schema").hexdigest()
    now = datetime.now(UTC)
    with psycopg.connect(migrated_database, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO pulseiq.datasets (dataset_id, organization_id, workspace_id, created_by)
            VALUES (%s, %s, %s, %s)
            """,
            (DATASET_A, ORG_A, WORKSPACE_A, ACTOR_E),
        )
        connection.execute(
            """
            INSERT INTO pulseiq.dataset_versions (
                dataset_version_id, dataset_id, organization_id, workspace_id,
                status, object_key, filename_binding, content_type,
                expected_bytes, expected_sha256, created_by
            ) VALUES (%s, %s, %s, %s, 'mapping_required', %s, %s, 'text/csv', %s, %s, %s)
            """,
            (
                DATASET_VERSION_UPLOAD,
                DATASET_A,
                ORG_A,
                WORKSPACE_A,
                f"quarantine/{ORG_A}/{WORKSPACE_A}/{DATASET_A}/{DATASET_VERSION_UPLOAD}/original.csv",
                checksum,
                1024,
                checksum,
                ACTOR_E,
            ),
        )
        connection.execute(
            """
            INSERT INTO pulseiq.dataset_artifacts (
                dataset_version_id, organization_id, workspace_id, object_key,
                source_sha256, artifact_sha256, schema_fingerprint,
                row_count, column_count, normalization_version, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, decode(%s, 'hex'), 10, 2, '1', %s)
            """,
            (
                DATASET_VERSION_UPLOAD,
                ORG_A,
                WORKSPACE_A,
                f"normalized/{ORG_A}/{WORKSPACE_A}/{DATASET_A}/{DATASET_VERSION_UPLOAD}/data.parquet",
                checksum,
                artifact_checksum,
                schema_fingerprint,
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO pulseiq.dataset_artifact_fields (
                dataset_version_id, position, source_column, normalized_column, physical_type, nullable
            ) VALUES
                (%s, 1, 'Customer ID', 'customer_id', 'string', false),
                (%s, 2, 'Amount', 'amount', 'string', false)
            """,
            (DATASET_VERSION_UPLOAD, DATASET_VERSION_UPLOAD),
        )

    scope = DatabaseScope(actor_id=ACTOR_E, organization_id=ORG_A, workspace_id=WORKSPACE_A)
    actor = AuthenticatedActor(
        actor_id=ACTOR_E,
        session_id=SESSION_E,
        authenticated_at=now - timedelta(minutes=5),
        expires_at=now + timedelta(minutes=10),
        authentication_methods=("federated", "mfa"),
    )
    with ConnectionPool(
        conninfo=migrated_database,
        min_size=1,
        max_size=3,
        configure=_configure_application_role,
    ) as pool:
        identity = PostgresIdentityRepository(pool, scope)
        repository = PostgresSchemaMappingRepository(pool, scope)
        context = repository.get_context(
            dataset_version_id=DATASET_VERSION_UPLOAD,
            organization_id=ORG_A,
            workspace_id=WORKSPACE_A,
        )
        assert context is not None
        assert [field.normalized_column for field in context.fields] == ["customer_id", "amount"]
        service = SchemaMappingService(
            repository,
            AuthorizationService(identity, identity, clock=lambda: now),
            clock=lambda: now,
            mapping_version_id_factory=lambda: mapping_version_id,
            validation_job_id_factory=lambda: validation_job_id,
            audit_event_id_factory=lambda: audit_event_id,
        )
        result = service.confirm(
            ConfirmSchemaMapping(
                actor=actor,
                organization_id=ORG_A,
                workspace_id=WORKSPACE_A,
                dataset_version_id=DATASET_VERSION_UPLOAD,
                schema_fingerprint=schema_fingerprint,
                fields=(
                    ConfirmedFieldMapping.identifier(
                        source_column="Customer ID",
                        normalized_column="customer_id",
                        concept=GovernedConcept.CUSTOMER_ID,
                    ),
                    ConfirmedFieldMapping(
                        source_column="Amount",
                        normalized_column="amount",
                        concept=GovernedConcept.TRANSACTION_AMOUNT,
                        target_type=TargetType.DECIMAL,
                        nullable=False,
                        unit=UnitSemantics.MONEY,
                        currency_mode=CurrencyMode.FIXED,
                        currency_code="NGN",
                        period=PeriodSemantics.TRANSACTION,
                        amount_direction=AmountDirection.SIGNED,
                        time_semantics=TimeSemantics.NOT_APPLICABLE,
                    ),
                ),
                request_id=request_id,
                reason="Confirmed the customer identifier and signed NGN amount with the source owner.",
            )
        )
        assert result.dataset_status.value == "validating"

    with psycopg.connect(migrated_database) as connection:
        persisted = connection.execute(
            """
            SELECT version.status, version.revision, mapping.mapping_version_id::text,
                   job.status, event.action
            FROM pulseiq.dataset_versions AS version
            JOIN pulseiq.schema_mapping_versions AS mapping USING (dataset_version_id)
            JOIN pulseiq.import_jobs AS job USING (dataset_version_id)
            JOIN pulseiq.audit_events AS event ON event.target_id = mapping.mapping_version_id
            WHERE version.dataset_version_id = %s AND job.job_id = %s
            """,
            (DATASET_VERSION_UPLOAD, validation_job_id),
        ).fetchone()
        mapped_fields = connection.execute(
            """
            SELECT normalized_column, governed_concept, currency_mode, currency_code, amount_direction
            FROM pulseiq.schema_mapping_fields
            WHERE mapping_version_id = %s ORDER BY normalized_column
            """,
            (mapping_version_id,),
        ).fetchall()
        outbox = connection.execute(
            "SELECT topic FROM pulseiq.outbox_events WHERE aggregate_id = %s",
            (validation_job_id,),
        ).fetchall()
    assert persisted == ("validating", 2, mapping_version_id, "queued", "dataset.mapping_confirmed")
    assert mapped_fields == [
        ("amount", "transaction_amount", "fixed", "NGN", "signed"),
        ("customer_id", "customer_id", "not_applicable", None, "not_applicable"),
    ]
    assert outbox == [("job.queued",)]


def test_postgres_validation_persists_evidence_settles_and_replays_safely(migrated_database: str) -> None:
    mapping_version_id = "88888888-cccc-4ccc-8ccc-888888888888"
    validation_job_id = "88888888-eeee-4eee-8eee-888888888888"
    execution_token = "88888888-aaaa-4aaa-8aaa-888888888888"
    payload = b"Customer ID,Amount\nC-1,1000.50\nC-1,1000.50\n"
    artifact = normalize_csv_to_parquet(payload)
    now = datetime.now(UTC)
    object_key = f"normalized/{ORG_A}/{WORKSPACE_A}/{DATASET_A}/{DATASET_VERSION_UPLOAD}/data.parquet"
    with psycopg.connect(migrated_database, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO pulseiq.datasets (dataset_id, organization_id, workspace_id, created_by)
            VALUES (%s, %s, %s, %s)
            """,
            (DATASET_A, ORG_A, WORKSPACE_A, ACTOR_E),
        )
        connection.execute(
            """
            INSERT INTO pulseiq.dataset_versions (
                dataset_version_id, dataset_id, organization_id, workspace_id,
                status, object_key, filename_binding, content_type,
                expected_bytes, expected_sha256, created_by
            ) VALUES (%s, %s, %s, %s, 'validating', %s, %s, 'text/csv', %s, %s, %s)
            """,
            (
                DATASET_VERSION_UPLOAD,
                DATASET_A,
                ORG_A,
                WORKSPACE_A,
                f"quarantine/{ORG_A}/{WORKSPACE_A}/{DATASET_A}/{DATASET_VERSION_UPLOAD}/original.csv",
                hashlib.sha256(b"binding").digest(),
                len(payload),
                bytes.fromhex(artifact.source_sha256),
                ACTOR_E,
            ),
        )
        connection.execute(
            """
            INSERT INTO pulseiq.dataset_artifacts (
                dataset_version_id, organization_id, workspace_id, object_key,
                source_sha256, artifact_sha256, schema_fingerprint,
                row_count, column_count, normalization_version, created_at
            ) VALUES (%s, %s, %s, %s, decode(%s, 'hex'), decode(%s, 'hex'),
                      decode(%s, 'hex'), %s, %s, '1', %s)
            """,
            (
                DATASET_VERSION_UPLOAD,
                ORG_A,
                WORKSPACE_A,
                object_key,
                artifact.source_sha256,
                artifact.parquet_sha256,
                artifact.schema_fingerprint,
                artifact.rows,
                artifact.columns,
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO pulseiq.dataset_artifact_fields (
                dataset_version_id, position, source_column, normalized_column, physical_type, nullable
            ) VALUES
                (%s, 1, 'Customer ID', 'customer_id', 'string', false),
                (%s, 2, 'Amount', 'amount', 'string', false)
            """,
            (DATASET_VERSION_UPLOAD, DATASET_VERSION_UPLOAD),
        )
        connection.execute(
            """
            INSERT INTO pulseiq.schema_mapping_versions (
                mapping_version_id, organization_id, workspace_id, dataset_id,
                dataset_version_id, schema_fingerprint, confirmed_by,
                confirmed_at, request_id, reason
            ) VALUES (%s, %s, %s, %s, %s, decode(%s, 'hex'), %s, %s, %s, %s)
            """,
            (
                mapping_version_id,
                ORG_A,
                WORKSPACE_A,
                DATASET_A,
                DATASET_VERSION_UPLOAD,
                artifact.schema_fingerprint,
                ACTOR_E,
                now,
                REQUEST_A,
                "Confirmed exact customer and monetary semantics for validation.",
            ),
        )
        connection.execute(
            """
            INSERT INTO pulseiq.schema_mapping_fields (
                mapping_version_id, dataset_version_id, source_column, normalized_column,
                governed_concept, target_type, nullable, unit_semantics,
                currency_mode, currency_code, period_semantics, amount_direction, time_semantics
            ) VALUES
                (%s, %s, 'Customer ID', 'customer_id', 'customer_id', 'string', false,
                 'identifier', 'not_applicable', NULL, 'not_applicable', 'not_applicable', 'not_applicable'),
                (%s, %s, 'Amount', 'amount', 'transaction_amount', 'decimal', false,
                 'money', 'fixed', 'NGN', 'transaction', 'signed', 'not_applicable')
            """,
            (mapping_version_id, DATASET_VERSION_UPLOAD, mapping_version_id, DATASET_VERSION_UPLOAD),
        )
        connection.execute(
            """
            INSERT INTO pulseiq.import_jobs (
                job_id, organization_id, workspace_id, dataset_version_id,
                job_type, status, input_reference, idempotency_key, available_at, created_at
            ) VALUES (%s, %s, %s, %s, 'dataset.validate', 'queued', %s::jsonb, %s, %s, %s)
            """,
            (
                validation_job_id,
                ORG_A,
                WORKSPACE_A,
                DATASET_VERSION_UPLOAD,
                json.dumps(
                    {
                        "dataset_version_id": DATASET_VERSION_UPLOAD,
                        "mapping_version_id": mapping_version_id,
                        "schema_fingerprint": artifact.schema_fingerprint,
                    }
                ),
                f"dataset.validate:{DATASET_VERSION_UPLOAD}:{mapping_version_id}",
                now,
                now,
            ),
        )

    class ExactStorage:
        def read_normalized(self, *, object_key: str, expected_sha256: str) -> bytes:
            assert (object_key, expected_sha256) == (object_key_value, artifact.parquet_sha256)
            return artifact.payload

    object_key_value = object_key
    tokens = iter((execution_token, "99999999-aaaa-4aaa-8aaa-999999999999"))
    with ConnectionPool(
        conninfo=migrated_database,
        min_size=1,
        max_size=2,
        configure=_configure_worker_role,
    ) as pool:
        jobs = PostgresImportJobRepository(pool, execution_token_factory=lambda: next(tokens))
        validations = PostgresDatasetValidationRepository(pool)
        claim = jobs.claim_job(job_id=validation_job_id, claimed_at=now, lease_for=timedelta(minutes=5))
        assert claim is not None
        handler = DatasetValidationHandler(ExactStorage(), validations, clock=lambda: now + timedelta(seconds=1))
        handler.execute(claim)

        replay_context = validations.get_context(
            dataset_version_id=DATASET_VERSION_UPLOAD,
            mapping_version_id=mapping_version_id,
            organization_id=ORG_A,
            workspace_id=WORKSPACE_A,
        )
        assert replay_context is not None
        assert replay_context.status.value == "ready"
        assert replay_context.existing_validation_run_id == validation_job_id
        handler.execute(claim)
        jobs.mark_succeeded(
            job_id=claim.job_id,
            execution_token=claim.execution_token,
            completed_at=now + timedelta(seconds=2),
        )

    scope = DatabaseScope(actor_id=ACTOR_E, organization_id=ORG_A, workspace_id=WORKSPACE_A)
    actor = AuthenticatedActor(
        actor_id=ACTOR_E,
        session_id=SESSION_E,
        authenticated_at=now - timedelta(minutes=5),
        expires_at=now + timedelta(minutes=10),
        authentication_methods=("federated", "mfa"),
    )
    with ConnectionPool(
        conninfo=migrated_database,
        min_size=1,
        max_size=2,
        configure=_configure_application_role,
    ) as pool:
        identity = PostgresIdentityRepository(pool, scope)
        overrides = PostgresQualityWarningOverrideRepository(pool, scope)
        service = QualityWarningOverrideService(
            overrides,
            AuthorizationService(identity, identity, clock=lambda: now + timedelta(seconds=3)),
            clock=lambda: now + timedelta(seconds=3),
            override_id_factory=lambda: "88888888-bbbb-4bbb-8bbb-888888888888",
            audit_event_id_factory=lambda: "88888888-6666-4666-8666-888888888888",
        )
        command = OverrideQualityWarning(
            actor=actor,
            organization_id=ORG_A,
            workspace_id=WORKSPACE_A,
            validation_run_id=validation_job_id,
            issue_ordinal=1,
            expires_at=now + timedelta(days=30),
            request_id="88888888-7777-4777-8777-888888888888",
            reason="The source owner confirmed the bounded duplicate rows are expected for this period.",
        )
        override_result = service.override(command)
        assert service.override(command).audit_event is None
        assert override_result.audit_event is not None
        quality = ValidationQualityQueryService(
            overrides,
            AuthorizationService(identity, identity, clock=lambda: now + timedelta(seconds=4)),
            clock=lambda: now + timedelta(seconds=4),
        ).get(
            GetEffectiveValidationQuality(
                actor=actor,
                organization_id=ORG_A,
                workspace_id=WORKSPACE_A,
                validation_run_id=validation_job_id,
            )
        )
        assert quality.status is EffectiveQualityStatus.BLOCKED
        assert (
            quality.warning_issue_count,
            quality.active_override_count,
            quality.effective_warning_count,
        ) == (1, 1, 0)
        expired_quality = overrides.get_effective_quality(
            validation_run_id=validation_job_id,
            organization_id=ORG_A,
            workspace_id=WORKSPACE_A,
            evaluated_at=now + timedelta(days=31),
        )
        assert expired_quality is not None
        assert (expired_quality.active_override_count, expired_quality.effective_warning_count) == (0, 1)
        with pytest.raises(QualityWarningOverrideError) as overlap:
            service.override(
                replace(
                    command,
                    request_id="99999999-7777-4777-8777-999999999999",
                    reason="A second overlapping acknowledgement must not replace governed history.",
                )
            )
        assert overlap.value.code == "active_override_exists"

    with psycopg.connect(migrated_database) as connection:
        summary = connection.execute(
            """
            SELECT version.status, job.status, run.verdict, run.row_count,
                   run.block_count, count(issue.issue_ordinal)
            FROM pulseiq.dataset_versions AS version
            JOIN pulseiq.import_jobs AS job USING (dataset_version_id)
            JOIN pulseiq.validation_runs AS run USING (dataset_version_id)
            JOIN pulseiq.validation_issues AS issue USING (validation_run_id)
            WHERE version.dataset_version_id = %s AND job.job_id = %s
            GROUP BY version.status, job.status, run.verdict, run.row_count, run.block_count
            """,
            (DATASET_VERSION_UPLOAD, validation_job_id),
        ).fetchone()
        assert summary == ("ready", "succeeded", "passed", 2, 5, 6)
        persisted_override = connection.execute(
            """
            SELECT issue.rule_id, override.overridden_by::text, event.action
            FROM pulseiq.validation_issue_overrides AS override
            JOIN pulseiq.validation_issues AS issue USING (validation_run_id, issue_ordinal)
            JOIN pulseiq.audit_events AS event ON event.target_id = override.override_id
            WHERE override.validation_run_id = %s
            """,
            (validation_job_id,),
        ).fetchone()
        assert persisted_override == ("duplicate_rows", ACTOR_E, "quality.warning_overridden")
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            connection.execute(
                "UPDATE pulseiq.validation_runs SET verdict = 'blocked' WHERE validation_run_id = %s",
                (validation_job_id,),
            )
        connection.rollback()
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            connection.execute(
                "UPDATE pulseiq.validation_issue_overrides SET reason = 'Changed reason' WHERE validation_run_id = %s",
                (validation_job_id,),
            )

    with ConnectionPool(
        conninfo=migrated_database,
        min_size=1,
        max_size=1,
        configure=_configure_application_role,
    ) as pool:
        with pool.connection() as connection, connection.transaction():
            _set_application_context(
                connection,
                actor_id=ACTOR_E,
                organization_id=ORG_A,
                workspace_id=WORKSPACE_A,
            )
            assert connection.execute("SELECT count(*) FROM pulseiq.validation_runs").fetchone() == (1,)
            assert connection.execute("SELECT count(*) FROM pulseiq.validation_issue_overrides").fetchone() == (1,)
        with pool.connection() as connection, connection.transaction():
            _set_application_context(
                connection,
                actor_id=ACTOR_B,
                organization_id=ORG_B,
                workspace_id=WORKSPACE_B,
            )
            assert connection.execute("SELECT count(*) FROM pulseiq.validation_runs").fetchone() == (0,)
            assert connection.execute("SELECT count(*) FROM pulseiq.validation_issue_overrides").fetchone() == (0,)
