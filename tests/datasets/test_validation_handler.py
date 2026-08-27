from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from types import MappingProxyType

import pandas as pd
import pytest

from pulseiq.datasets import (
    AmountDirection,
    ConfirmedFieldMapping,
    CurrencyMode,
    DatasetValidationHandler,
    DatasetValidationStorageError,
    DatasetVersionStatus,
    PeriodSemantics,
    SchemaMappingVersion,
    TargetType,
    TimeSemantics,
    UnitSemantics,
    ValidationContext,
    ValidationRun,
    ValidationVerdict,
)
from pulseiq.ingestion import GovernedConcept, normalize_csv_to_parquet
from pulseiq.jobs import ImportJobClaim, JobExecutionError

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
VERSION_ID = "33333333-cccc-4ccc-8ccc-333333333333"
MAPPING_ID = "77777777-aaaa-4aaa-8aaa-777777777777"
JOB_ID = "77777777-eeee-4eee-8eee-777777777777"
ARTIFACT_KEY = f"normalized/org-1/workspace-1/dataset-1/{VERSION_ID}/data.parquet"


def _mapping(schema_fingerprint: str) -> SchemaMappingVersion:
    return SchemaMappingVersion(
        mapping_version_id=MAPPING_ID,
        dataset_version_id=VERSION_ID,
        dataset_id="dataset-1",
        organization_id="org-1",
        workspace_id="workspace-1",
        schema_fingerprint=schema_fingerprint,
        fields=(
            ConfirmedFieldMapping.identifier(
                source_column="Customer ID",
                normalized_column="customer_id",
                concept=GovernedConcept.CUSTOMER_ID,
            ),
            ConfirmedFieldMapping(
                source_column="Date",
                normalized_column="date",
                concept=GovernedConcept.DATE,
                target_type=TargetType.DATE,
                nullable=False,
                unit=UnitSemantics.TEMPORAL,
                time_semantics=TimeSemantics.EVENT_TIME,
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
            ),
            ConfirmedFieldMapping(
                source_column="Defaulted",
                normalized_column="defaulted",
                concept=GovernedConcept.DEFAULTED,
                target_type=TargetType.BOOLEAN,
                nullable=False,
                unit=UnitSemantics.OUTCOME,
            ),
        ),
        confirmed_by="actor-1",
        confirmed_at=NOW,
        reason="Confirm the exact source semantics for validation.",
    )


def _claim(schema_fingerprint: str, **reference_changes: str) -> ImportJobClaim:
    reference = {
        "dataset_version_id": VERSION_ID,
        "mapping_version_id": MAPPING_ID,
        "schema_fingerprint": schema_fingerprint,
        **reference_changes,
    }
    return ImportJobClaim(
        job_id=JOB_ID,
        organization_id="org-1",
        workspace_id="workspace-1",
        dataset_version_id=VERSION_ID,
        job_type="dataset.validate",
        input_reference=MappingProxyType(reference),
        attempts=1,
        execution_token="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        leased_until=NOW,
    )


class FakeValidationStorage:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.reads: list[tuple[str, str]] = []

    def read_normalized(self, *, object_key: str, expected_sha256: str) -> bytes:
        self.reads.append((object_key, expected_sha256))
        return self.payload


class FakeValidationRepository:
    def __init__(self, context: ValidationContext) -> None:
        self.context = context
        self.runs: list[tuple[ValidationRun, int]] = []

    def get_context(
        self,
        *,
        dataset_version_id: str,
        mapping_version_id: str,
        organization_id: str,
        workspace_id: str,
    ) -> ValidationContext | None:
        assert (dataset_version_id, mapping_version_id, organization_id, workspace_id) == (
            VERSION_ID,
            MAPPING_ID,
            "org-1",
            "workspace-1",
        )
        return self.context

    def complete_validation(self, run: ValidationRun, *, expected_revision: int) -> None:
        self.runs.append((run, expected_revision))


def _setup(payload: bytes) -> tuple[DatasetValidationHandler, FakeValidationRepository, str]:
    artifact = normalize_csv_to_parquet(payload)
    context = ValidationContext(
        dataset_version_id=VERSION_ID,
        organization_id="org-1",
        workspace_id="workspace-1",
        dataset_revision=2,
        status=DatasetVersionStatus.VALIDATING,
        artifact_object_key=ARTIFACT_KEY,
        artifact_sha256=artifact.parquet_sha256,
        schema_fingerprint=artifact.schema_fingerprint,
        artifact_row_count=artifact.rows,
        artifact_column_count=artifact.columns,
        mapping=_mapping(artifact.schema_fingerprint),
    )
    repository = FakeValidationRepository(context)
    handler = DatasetValidationHandler(FakeValidationStorage(artifact.payload), repository, clock=lambda: NOW)
    return handler, repository, artifact.schema_fingerprint


def test_validation_executes_exact_mapping_and_marks_usable_data_ready() -> None:
    handler, repository, fingerprint = _setup(
        b"Customer ID,Date,Amount,Defaulted\nC-1,2026-08-01,1000.50,0\nC-2,2026-08-02,800,1\n"
    )

    handler.execute(_claim(fingerprint))

    run, revision = repository.runs[0]
    assert revision == 2
    assert run.validation_run_id == JOB_ID
    assert run.verdict is ValidationVerdict.PASSED
    assert run.dataset_status is DatasetVersionStatus.READY
    assert run.assessment.rows == 2
    assert run.assessment.can(run.readiness_capability)
    assert any(issue.code == "missing_model_inputs" for issue in run.assessment.issues)


def test_unparseable_required_mapping_blocks_the_dataset_without_imputation() -> None:
    handler, repository, fingerprint = _setup(b"Customer ID,Date,Amount,Defaulted\nC-1,2026-08-01,not-money,0\n")

    handler.execute(_claim(fingerprint))

    run = repository.runs[0][0]
    assert run.verdict is ValidationVerdict.BLOCKED
    assert run.dataset_status is DatasetVersionStatus.FAILED
    issue = next(issue for issue in run.assessment.issues if issue.code == "unparseable_required_field")
    assert issue.column == "transaction_amount"
    assert issue.count == 1
    assert issue.masked_examples[0].startswith("sha256:")
    assert "not-money" not in issue.masked_examples[0]


@pytest.mark.parametrize(
    "claim",
    [
        ImportJobClaim(
            job_id=JOB_ID,
            organization_id="org-1",
            workspace_id="workspace-1",
            dataset_version_id=VERSION_ID,
            job_type="dataset.scan",
            input_reference=MappingProxyType({}),
            attempts=1,
            execution_token="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            leased_until=NOW,
        ),
        _claim("0" * 64, unexpected="value"),
    ],
)
def test_validation_rejects_wrong_job_type_or_non_exact_reference(claim: ImportJobClaim) -> None:
    handler, _, _ = _setup(b"Customer ID,Date,Amount,Defaulted\nC-1,2026-08-01,100,0\n")

    with pytest.raises(JobExecutionError) as error:
        handler.execute(claim)

    assert error.value.code == "invalid_validation_reference"
    assert error.value.retryable is False


def test_validation_rejects_artifact_bytes_that_do_not_match_lineage() -> None:
    handler, repository, fingerprint = _setup(b"Customer ID,Date,Amount,Defaulted\nC-1,2026-08-01,100,0\n")
    repository.context = replace(
        repository.context,
        artifact_sha256=hashlib.sha256(b"different").hexdigest(),
    )

    with pytest.raises(JobExecutionError) as error:
        handler.execute(_claim(fingerprint))

    assert error.value.code == "normalized_checksum_mismatch"
    assert repository.runs == []


def test_validation_maps_storage_failure_and_rejects_invalid_parquet_or_dimensions() -> None:
    handler, repository, fingerprint = _setup(b"Customer ID,Date,Amount,Defaulted\nC-1,2026-08-01,100,0\n")

    class BrokenStorage(FakeValidationStorage):
        def read_normalized(self, *, object_key: str, expected_sha256: str) -> bytes:
            raise DatasetValidationStorageError("normalized_read_unavailable", retryable=True)

    broken = DatasetValidationHandler(BrokenStorage(b""), repository, clock=lambda: NOW)
    with pytest.raises(JobExecutionError) as storage_error:
        broken.execute(_claim(fingerprint))
    assert (storage_error.value.code, storage_error.value.retryable) == ("normalized_read_unavailable", True)

    invalid_payload = b"not-parquet"
    repository.context = replace(
        repository.context,
        artifact_sha256=hashlib.sha256(invalid_payload).hexdigest(),
    )
    invalid = DatasetValidationHandler(FakeValidationStorage(invalid_payload), repository, clock=lambda: NOW)
    with pytest.raises(JobExecutionError) as parquet_error:
        invalid.execute(_claim(fingerprint))
    assert parquet_error.value.code == "invalid_normalized_parquet"

    handler, repository, fingerprint = _setup(b"Customer ID,Date,Amount,Defaulted\nC-1,2026-08-01,100,0\n")
    repository.context = replace(repository.context, artifact_row_count=2)
    with pytest.raises(JobExecutionError) as dimension_error:
        handler.execute(_claim(fingerprint))
    assert dimension_error.value.code == "normalized_schema_mismatch"


def test_validation_context_and_run_contracts_reject_incoherent_lineage() -> None:
    handler, repository, fingerprint = _setup(b"Customer ID,Date,Amount,Defaulted\nC-1,2026-08-01,100,0\n")
    context = repository.context
    for changes in (
        {"dataset_revision": 0},
        {"artifact_row_count": 0},
        {"artifact_sha256": "invalid"},
        {"organization_id": "different-org"},
    ):
        with pytest.raises(ValueError):
            replace(context, **changes)

    handler.execute(_claim(fingerprint))
    run = repository.runs[0][0]
    with pytest.raises(ValueError):
        replace(run, completed_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError):
        replace(run, verdict=ValidationVerdict.BLOCKED)


def test_target_type_validity_and_boolean_canonicalization_are_explicit() -> None:
    values = pd.Series(["1", "1.5", "true", "2026-08-25", "bad"], dtype="string")

    assert DatasetValidationHandler._valid_values(values, TargetType.STRING).tolist() == [True] * 5
    assert DatasetValidationHandler._valid_values(values, TargetType.DECIMAL).tolist() == [
        True,
        True,
        False,
        False,
        False,
    ]
    assert DatasetValidationHandler._valid_values(values, TargetType.INTEGER).tolist() == [
        True,
        False,
        False,
        False,
        False,
    ]
    assert DatasetValidationHandler._valid_values(values, TargetType.BOOLEAN).tolist() == [
        True,
        False,
        True,
        False,
        False,
    ]
    assert DatasetValidationHandler._valid_values(values, TargetType.DATE).tolist() == [
        False,
        False,
        False,
        True,
        False,
    ]
    boolean_values = pd.Series(["0", "1", "false", "true"], dtype="string")
    assert DatasetValidationHandler._canonical_values(boolean_values, TargetType.BOOLEAN).tolist() == [0, 1, 0, 1]
