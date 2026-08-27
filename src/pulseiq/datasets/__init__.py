"""Public dataset assessment interface.

Feature code should import dataset contracts from this module instead of reaching
into validation internals. This keeps the trust boundary small and replaceable.
"""

from .artifacts_postgres import PostgresNormalizedArtifactRepository
from .assessment import assess_dataset
from .contracts import (
    AssessmentStatus,
    CapabilityAssessment,
    DatasetAssessment,
    DatasetCapability,
    DatasetCapabilityError,
    IssueSeverity,
    QualityDimension,
    QualityDimensionScore,
    ValidationIssue,
)
from .malware import (
    ClamdInstreamScanner,
    MalwareScanError,
    MalwareScanResult,
    MalwareScanStatus,
)
from .mapping import (
    AmountDirection,
    ArtifactMappingContext,
    ConfirmedFieldMapping,
    ConfirmSchemaMapping,
    CurrencyMode,
    MappingConfirmationError,
    MappingConfirmationResult,
    PeriodSemantics,
    SchemaMappingService,
    SchemaMappingVersion,
    TargetType,
    TimeSemantics,
    UnitSemantics,
)
from .mapping_postgres import PostgresSchemaMappingRepository
from .normalization import (
    DatasetNormalizationHandler,
    DatasetNormalizationStorageError,
    DatasetScanPipelineHandler,
    NormalizedArtifactField,
    NormalizedDatasetArtifact,
)
from .postgres import PostgresDatasetUploadRepository
from .quality_overrides import (
    EffectiveQualityStatus,
    EffectiveValidationQuality,
    GetEffectiveValidationQuality,
    OverrideQualityWarning,
    QualityOverrideResult,
    QualityWarningContext,
    QualityWarningOverride,
    QualityWarningOverrideError,
    QualityWarningOverrideService,
    ValidationQualityQueryError,
    ValidationQualityQueryService,
)
from .quality_overrides_postgres import PostgresQualityWarningOverrideRepository
from .s3_normalization import S3DatasetNormalizationStorage
from .s3_storage import (
    QuarantineObjectStoreError,
    S3DatasetScanStorage,
    S3QuarantineObjectStore,
)
from .scanning import DatasetScanHandler, DatasetScanStorageError
from .upload_adapters import InMemoryDatasetUploadRepository, InMemoryQuarantineUploadSigner
from .upload_contracts import (
    BeginDatasetUpload,
    CompleteDatasetUpload,
    CompleteUploadResult,
    DatasetVersion,
    DatasetVersionStatus,
    ImportJob,
    ImportJobStatus,
    PresignedUpload,
    QuarantineUploadRequest,
    StoredObjectMetadata,
    UploadReservation,
)
from .uploads import DatasetUploadError, DatasetUploadService
from .validation import (
    DatasetValidationHandler,
    DatasetValidationStorageError,
    ValidationContext,
    ValidationRun,
    ValidationVerdict,
)
from .validation_postgres import PostgresDatasetValidationRepository

__all__ = [
    "AmountDirection",
    "ArtifactMappingContext",
    "AssessmentStatus",
    "BeginDatasetUpload",
    "CapabilityAssessment",
    "ClamdInstreamScanner",
    "CompleteDatasetUpload",
    "CompleteUploadResult",
    "ConfirmSchemaMapping",
    "ConfirmedFieldMapping",
    "CurrencyMode",
    "DatasetAssessment",
    "DatasetCapability",
    "DatasetCapabilityError",
    "DatasetNormalizationHandler",
    "DatasetNormalizationStorageError",
    "DatasetScanHandler",
    "DatasetScanPipelineHandler",
    "DatasetScanStorageError",
    "DatasetUploadError",
    "DatasetUploadService",
    "DatasetValidationHandler",
    "DatasetValidationStorageError",
    "DatasetVersion",
    "DatasetVersionStatus",
    "EffectiveQualityStatus",
    "EffectiveValidationQuality",
    "GetEffectiveValidationQuality",
    "ImportJob",
    "ImportJobStatus",
    "InMemoryDatasetUploadRepository",
    "InMemoryQuarantineUploadSigner",
    "IssueSeverity",
    "MalwareScanError",
    "MalwareScanResult",
    "MalwareScanStatus",
    "MappingConfirmationError",
    "MappingConfirmationResult",
    "NormalizedArtifactField",
    "NormalizedDatasetArtifact",
    "OverrideQualityWarning",
    "PeriodSemantics",
    "PostgresDatasetUploadRepository",
    "PostgresDatasetValidationRepository",
    "PostgresNormalizedArtifactRepository",
    "PostgresQualityWarningOverrideRepository",
    "PostgresSchemaMappingRepository",
    "PresignedUpload",
    "QualityDimension",
    "QualityDimensionScore",
    "QualityOverrideResult",
    "QualityWarningContext",
    "QualityWarningOverride",
    "QualityWarningOverrideError",
    "QualityWarningOverrideService",
    "QuarantineObjectStoreError",
    "QuarantineUploadRequest",
    "S3DatasetNormalizationStorage",
    "S3DatasetScanStorage",
    "S3QuarantineObjectStore",
    "SchemaMappingService",
    "SchemaMappingVersion",
    "StoredObjectMetadata",
    "TargetType",
    "TimeSemantics",
    "UnitSemantics",
    "UploadReservation",
    "ValidationContext",
    "ValidationIssue",
    "ValidationQualityQueryError",
    "ValidationQualityQueryService",
    "ValidationRun",
    "ValidationVerdict",
    "assess_dataset",
]
