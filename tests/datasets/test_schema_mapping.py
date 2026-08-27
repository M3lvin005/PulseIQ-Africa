from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from pulseiq.datasets.mapping import (
    AmountDirection,
    ArtifactMappingContext,
    ConfirmedFieldMapping,
    ConfirmSchemaMapping,
    CurrencyMode,
    MappingConfirmationError,
    PeriodSemantics,
    SchemaMappingService,
    TargetType,
    TimeSemantics,
    UnitSemantics,
)
from pulseiq.datasets.normalization import NormalizedArtifactField
from pulseiq.datasets.upload_contracts import DatasetVersionStatus
from pulseiq.identity import (
    AuthenticatedActor,
    AuthorizationService,
    InMemoryMembershipRepository,
    InMemorySessionRepository,
    Membership,
    MembershipStatus,
    Role,
    SessionRecord,
    SessionStatus,
)
from pulseiq.ingestion import GovernedConcept

NOW = datetime(2026, 8, 25, 21, tzinfo=UTC)
SCHEMA_FINGERPRINT = hashlib.sha256(b"schema").hexdigest()


class FakeMappingRepository:
    def __init__(self, context: ArtifactMappingContext) -> None:
        self.context = context
        self.confirmations: list[tuple[object, ...]] = []

    def get_context(
        self,
        *,
        dataset_version_id: str,
        organization_id: str,
        workspace_id: str,
    ) -> ArtifactMappingContext | None:
        if (
            dataset_version_id == self.context.dataset_version_id
            and organization_id == self.context.organization_id
            and workspace_id == self.context.workspace_id
        ):
            return self.context
        return None

    def confirm_and_enqueue(self, *args: object, **kwargs: object) -> None:
        self.confirmations.append((*args, kwargs))


def _actor_and_authorization(role: Role = Role.DATA_STEWARD) -> tuple[AuthenticatedActor, AuthorizationService]:
    actor = AuthenticatedActor(
        actor_id="actor-1",
        session_id="session-1",
        authenticated_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(minutes=10),
        authentication_methods=("federated", "mfa"),
    )
    authorization = AuthorizationService(
        InMemoryMembershipRepository(
            [
                Membership(
                    membership_id="membership-1",
                    actor_id=actor.actor_id,
                    organization_id="org-1",
                    workspace_id="workspace-1",
                    role=role,
                    status=MembershipStatus.ACTIVE,
                )
            ]
        ),
        InMemorySessionRepository(
            [
                SessionRecord(
                    session_id=actor.session_id,
                    actor_id=actor.actor_id,
                    authenticated_at=actor.authenticated_at,
                    expires_at=actor.expires_at,
                    status=SessionStatus.ACTIVE,
                )
            ]
        ),
        clock=lambda: NOW,
    )
    return actor, authorization


def _context() -> ArtifactMappingContext:
    return ArtifactMappingContext(
        dataset_version_id="version-1",
        dataset_id="dataset-1",
        organization_id="org-1",
        workspace_id="workspace-1",
        dataset_revision=3,
        status=DatasetVersionStatus.MAPPING_REQUIRED,
        schema_fingerprint=SCHEMA_FINGERPRINT,
        fields=(
            NormalizedArtifactField(1, "Customer ID", "customer_id", "string", False),
            NormalizedArtifactField(2, "Amount", "amount", "string", False),
            NormalizedArtifactField(3, "Currency", "currency", "string", False),
        ),
    )


def _money_mapping(*, currency_mode: CurrencyMode = CurrencyMode.COLUMN) -> ConfirmedFieldMapping:
    return ConfirmedFieldMapping(
        source_column="Amount",
        normalized_column="amount",
        concept=GovernedConcept.TRANSACTION_AMOUNT,
        target_type=TargetType.DECIMAL,
        nullable=False,
        unit=UnitSemantics.MONEY,
        currency_mode=currency_mode,
        currency_code="NGN" if currency_mode is CurrencyMode.FIXED else None,
        period=PeriodSemantics.TRANSACTION,
        amount_direction=AmountDirection.SIGNED,
        time_semantics=TimeSemantics.NOT_APPLICABLE,
    )


def _command(actor: AuthenticatedActor, fields: tuple[ConfirmedFieldMapping, ...]) -> ConfirmSchemaMapping:
    return ConfirmSchemaMapping(
        actor=actor,
        organization_id="org-1",
        workspace_id="workspace-1",
        dataset_version_id="version-1",
        schema_fingerprint=SCHEMA_FINGERPRINT,
        fields=fields,
        request_id="request-map-1",
        reason="Confirmed source semantics with the data owner.",
    )


def test_data_steward_confirms_exact_artifact_schema_and_queues_validation() -> None:
    actor, authorization = _actor_and_authorization()
    repository = FakeMappingRepository(_context())
    service = SchemaMappingService(
        repository,
        authorization,
        clock=lambda: NOW,
        mapping_version_id_factory=lambda: "mapping-1",
        validation_job_id_factory=lambda: "job-validate-1",
        audit_event_id_factory=lambda: "audit-map-1",
    )
    fields = (
        ConfirmedFieldMapping.identifier(
            source_column="Customer ID",
            normalized_column="customer_id",
            concept=GovernedConcept.CUSTOMER_ID,
        ),
        _money_mapping(),
        ConfirmedFieldMapping.currency_column(source_column="Currency", normalized_column="currency"),
    )

    result = service.confirm(_command(actor, fields))

    assert result.mapping.mapping_version_id == "mapping-1"
    assert result.mapping.schema_fingerprint == SCHEMA_FINGERPRINT
    assert result.mapping.fields == fields
    assert result.validation_job.job_type == "dataset.validate"
    assert result.validation_job.input_reference["mapping_version_id"] == "mapping-1"
    assert result.dataset_status is DatasetVersionStatus.VALIDATING
    assert result.audit_event.action == "dataset.mapping_confirmed"
    assert len(repository.confirmations) == 1


def test_analyst_cannot_confirm_mapping() -> None:
    actor, authorization = _actor_and_authorization(Role.ANALYST)
    service = SchemaMappingService(
        FakeMappingRepository(_context()),
        authorization,
        clock=lambda: NOW,
        mapping_version_id_factory=lambda: "mapping-1",
        validation_job_id_factory=lambda: "job-1",
        audit_event_id_factory=lambda: "audit-1",
    )

    with pytest.raises(MappingConfirmationError) as error:
        service.confirm(_command(actor, (_money_mapping(currency_mode=CurrencyMode.FIXED),)))
    assert error.value.code == "permission_required"


@pytest.mark.parametrize(
    ("fields", "expected_code"),
    [
        (
            (_money_mapping(),),
            "currency_column_mapping_required",
        ),
        (
            (
                ConfirmedFieldMapping.identifier(
                    source_column="Caller Column",
                    normalized_column="caller_column",
                    concept=GovernedConcept.CUSTOMER_ID,
                ),
            ),
            "mapping_column_mismatch",
        ),
        (
            (
                ConfirmedFieldMapping.identifier(
                    source_column="Customer ID",
                    normalized_column="customer_id",
                    concept=GovernedConcept.CUSTOMER_ID,
                ),
                ConfirmedFieldMapping.identifier(
                    source_column="Currency",
                    normalized_column="currency",
                    concept=GovernedConcept.CUSTOMER_ID,
                ),
            ),
            "duplicate_governed_concept",
        ),
    ],
)
def test_confirmation_rejects_ambiguous_tampered_or_duplicate_semantics(
    fields: tuple[ConfirmedFieldMapping, ...],
    expected_code: str,
) -> None:
    actor, authorization = _actor_and_authorization()
    service = SchemaMappingService(
        FakeMappingRepository(_context()),
        authorization,
        clock=lambda: NOW,
        mapping_version_id_factory=lambda: "mapping-1",
        validation_job_id_factory=lambda: "job-1",
        audit_event_id_factory=lambda: "audit-1",
    )
    with pytest.raises(MappingConfirmationError) as error:
        service.confirm(_command(actor, fields))
    assert error.value.code == expected_code


@pytest.mark.parametrize(
    "field",
    [
        lambda: ConfirmedFieldMapping(
            " ", "status", GovernedConcept.REPAYMENT_STATUS, TargetType.STRING, False, UnitSemantics.CATEGORY
        ),
        lambda: ConfirmedFieldMapping(
            "Status",
            "status",
            GovernedConcept.REPAYMENT_STATUS,
            TargetType.STRING,
            False,
            UnitSemantics.CATEGORY,
            currency_mode=CurrencyMode.FIXED,
            currency_code="ng",
        ),
        lambda: ConfirmedFieldMapping(
            "Status",
            "status",
            GovernedConcept.REPAYMENT_STATUS,
            TargetType.STRING,
            False,
            UnitSemantics.CATEGORY,
            currency_code="NGN",
        ),
        lambda: ConfirmedFieldMapping(
            "Customer ID", "customer_id", GovernedConcept.CUSTOMER_ID, TargetType.STRING, False, UnitSemantics.CATEGORY
        ),
        lambda: ConfirmedFieldMapping(
            "Amount",
            "amount",
            GovernedConcept.TRANSACTION_AMOUNT,
            TargetType.STRING,
            False,
            UnitSemantics.MONEY,
            currency_mode=CurrencyMode.FIXED,
            currency_code="NGN",
            period=PeriodSemantics.TRANSACTION,
            amount_direction=AmountDirection.SIGNED,
        ),
        lambda: ConfirmedFieldMapping(
            "Amount",
            "amount",
            GovernedConcept.TRANSACTION_AMOUNT,
            TargetType.DECIMAL,
            False,
            UnitSemantics.MONEY,
            currency_mode=CurrencyMode.FIXED,
            currency_code="NGN",
            period=PeriodSemantics.TRANSACTION,
        ),
        lambda: ConfirmedFieldMapping(
            "Currency", "currency", GovernedConcept.CURRENCY, TargetType.STRING, False, UnitSemantics.CATEGORY
        ),
        lambda: ConfirmedFieldMapping(
            "Date", "date", GovernedConcept.DATE, TargetType.DATE, False, UnitSemantics.TEMPORAL
        ),
    ],
)
def test_field_contract_rejects_incompatible_semantics(field: object) -> None:
    with pytest.raises(ValueError):
        field()  # type: ignore[operator]


@pytest.mark.parametrize(
    ("context", "fingerprint", "fields", "expected_code"),
    [
        (
            replace(_context(), status=DatasetVersionStatus.FAILED),
            SCHEMA_FINGERPRINT,
            (_money_mapping(currency_mode=CurrencyMode.FIXED),),
            "dataset_not_mapping_required",
        ),
        (
            _context(),
            "0" * 64,
            (_money_mapping(currency_mode=CurrencyMode.FIXED),),
            "schema_fingerprint_mismatch",
        ),
        (_context(), SCHEMA_FINGERPRINT, (), "invalid_mapping_field_count"),
    ],
)
def test_confirmation_rejects_stale_state_schema_or_empty_mapping(
    context: ArtifactMappingContext,
    fingerprint: str,
    fields: tuple[ConfirmedFieldMapping, ...],
    expected_code: str,
) -> None:
    actor, authorization = _actor_and_authorization()
    service = SchemaMappingService(
        FakeMappingRepository(context),
        authorization,
        clock=lambda: NOW,
        mapping_version_id_factory=lambda: "mapping-1",
        validation_job_id_factory=lambda: "job-1",
        audit_event_id_factory=lambda: "audit-1",
    )
    command = replace(_command(actor, fields), schema_fingerprint=fingerprint)
    with pytest.raises(MappingConfirmationError) as error:
        service.confirm(command)
    assert error.value.code == expected_code
