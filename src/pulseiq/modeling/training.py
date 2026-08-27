"""Leakage-reduced demonstration training, evaluation, lineage, and scoring."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from importlib.metadata import version
from typing import Any

import numpy as np
import pandas as pd

from .contracts import (
    EligibilityStatus,
    ModelBundle,
    ModelEligibilityError,
    ModelInputError,
    ModelRunProvenance,
)
from .eligibility import (
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
    NUMERIC_FEATURES,
    assess_model_eligibility,
    map_model_target,
)

MODEL_CODE_VERSION = "model-exploration/2.0.0"
FEATURE_DEFINITION_VERSION = "credit-demo-features/1.0.0"


def _dataset_reference(dataframe: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    digest.update("|".join(map(str, dataframe.columns)).encode())
    digest.update("|".join(map(str, dataframe.dtypes)).encode())
    digest.update(pd.util.hash_pandas_object(dataframe, index=True).to_numpy().tobytes())
    return f"dataframe:sha256:{digest.hexdigest()}"


def _model_frame(dataframe: pd.DataFrame, target: pd.Series) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    eligible = target.notna()
    source = dataframe.loc[eligible].copy().reset_index(drop=True)
    features = pd.DataFrame(index=source.index)
    for column in NUMERIC_FEATURES:
        features[column] = pd.to_numeric(source[column], errors="coerce")
    for column in CATEGORICAL_FEATURES:
        normalized = source[column].astype("string").str.strip()
        normalized = normalized.mask(normalized.eq(""), pd.NA)
        categorical = normalized.astype(object)
        categorical.loc[normalized.isna()] = np.nan
        features[column] = categorical
    return features, target.loc[eligible].astype(int).reset_index(drop=True), source


def _split_indices(
    source: pd.DataFrame,
    target: pd.Series,
    random_state: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, str, int]:
    from sklearn.model_selection import GroupShuffleSplit, train_test_split

    indices = np.arange(len(source))
    if "customer_id" in source.columns:
        groups = source["customer_id"].astype("string").str.strip()
        if groups.notna().all() and groups.ne("").all() and groups.nunique() >= 5:
            first = GroupShuffleSplit(n_splits=1, test_size=0.40, random_state=random_state)
            train_position, remaining_position = next(first.split(indices, target, groups=groups))
            remaining_groups = groups.iloc[remaining_position]
            second = GroupShuffleSplit(n_splits=1, test_size=0.50, random_state=random_state + 1)
            validation_relative, test_relative = next(
                second.split(remaining_position, target.iloc[remaining_position], groups=remaining_groups)
            )
            train_indices = indices[train_position]
            validation_indices = indices[remaining_position[validation_relative]]
            test_indices = indices[remaining_position[test_relative]]
            group_sets = [
                set(groups.iloc[split].astype(str)) for split in (train_indices, validation_indices, test_indices)
            ]
            overlap = sum(len(group_sets[left] & group_sets[right]) for left, right in ((0, 1), (0, 2), (1, 2)))
            return train_indices, validation_indices, test_indices, "group_holdout/customer_id/1.0.0", overlap

    train_indices, remaining_indices = train_test_split(
        indices,
        test_size=0.40,
        random_state=random_state,
        stratify=target,
    )
    validation_indices, test_indices = train_test_split(
        remaining_indices,
        test_size=0.50,
        random_state=random_state + 1,
        stratify=target.iloc[remaining_indices],
    )
    return train_indices, validation_indices, test_indices, "stratified_random_holdout/1.0.0", 0


def _preprocessor() -> Any:
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    numeric = Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler())])
    categorical = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("encoder", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]
    )
    return ColumnTransformer(
        [("numeric", numeric, list(NUMERIC_FEATURES)), ("categorical", categorical, list(CATEGORICAL_FEATURES))]
    )


def _metrics(y_true: pd.Series, predictions: np.ndarray, scores: np.ndarray) -> dict[str, float]:
    from sklearn.metrics import (
        accuracy_score,
        average_precision_score,
        brier_score_loss,
        f1_score,
        log_loss,
        precision_score,
        recall_score,
        roc_auc_score,
    )

    values = {
        "accuracy": accuracy_score(y_true, predictions),
        "precision": precision_score(y_true, predictions, zero_division=0),
        "recall": recall_score(y_true, predictions, zero_division=0),
        "f1_score": f1_score(y_true, predictions, zero_division=0),
        "roc_auc": roc_auc_score(y_true, scores),
        "pr_auc": average_precision_score(y_true, scores),
        "brier_score": brier_score_loss(y_true, scores),
        "log_loss": log_loss(y_true, scores, labels=[0, 1]),
    }
    return {key: round(float(value), 4) for key, value in values.items()}


def train_models(dataframe: pd.DataFrame, random_state: int = 42) -> ModelBundle:
    """Select on validation data and report final metrics on an untouched holdout."""

    from sklearn.base import clone
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import confusion_matrix
    from sklearn.pipeline import Pipeline
    from sklearn.tree import DecisionTreeClassifier

    eligibility = assess_model_eligibility(dataframe)
    if eligibility.status is EligibilityStatus.BLOCKED:
        details = " ".join(issue.message for issue in eligibility.issues if issue.severity.value == "block")
        raise ModelEligibilityError(f"Model exploration is blocked: {details}")

    target, _, target_definition = map_model_target(dataframe)
    if target_definition is None:
        raise ModelEligibilityError("Model exploration is blocked: no approved target definition was resolved.")
    features, eligible_target, source = _model_frame(dataframe, target)
    train_indices, validation_indices, test_indices, split_strategy, overlap = _split_indices(
        source, eligible_target, random_state
    )
    for split_name, split_indices in (
        ("training", train_indices),
        ("validation", validation_indices),
        ("holdout", test_indices),
    ):
        if eligible_target.iloc[split_indices].nunique() < 2:
            raise ModelEligibilityError(
                f"Model exploration is blocked: the {split_name} split does not contain both outcome classes."
            )

    candidates = {
        "Logistic Regression": LogisticRegression(max_iter=1500, class_weight="balanced", random_state=random_state),
        "Random Forest": RandomForestClassifier(
            n_estimators=120,
            max_depth=9,
            min_samples_leaf=4,
            class_weight="balanced",
            random_state=random_state,
        ),
        "Decision Tree": DecisionTreeClassifier(max_depth=5, class_weight="balanced", random_state=random_state),
    }
    leaderboard: list[dict[str, float | str]] = []
    for name, estimator in candidates.items():
        pipeline = Pipeline([("preprocessor", _preprocessor()), ("model", clone(estimator))])
        pipeline.fit(features.iloc[train_indices], eligible_target.iloc[train_indices])
        predictions = pipeline.predict(features.iloc[validation_indices])
        scores = pipeline.predict_proba(features.iloc[validation_indices])[:, 1]
        leaderboard.append(
            {
                "model": name,
                "evaluation_split": "validation",
                **_metrics(eligible_target.iloc[validation_indices], predictions, scores),
            }
        )

    leaderboard.sort(key=lambda row: (float(row["f1_score"]), float(row["pr_auc"])), reverse=True)
    best_name = str(leaderboard[0]["model"])
    combined_indices = np.concatenate([train_indices, validation_indices])
    final_pipeline = Pipeline([("preprocessor", _preprocessor()), ("model", clone(candidates[best_name]))])
    final_pipeline.fit(features.iloc[combined_indices], eligible_target.iloc[combined_indices])
    holdout_predictions = final_pipeline.predict(features.iloc[test_indices])
    holdout_scores = final_pipeline.predict_proba(features.iloc[test_indices])[:, 1]
    final_metrics = _metrics(eligible_target.iloc[test_indices], holdout_predictions, holdout_scores)
    matrix = (
        confusion_matrix(eligible_target.iloc[test_indices], holdout_predictions, labels=[0, 1]).astype(int).tolist()
    )

    dataset_reference = _dataset_reference(dataframe)
    run_material = f"{dataset_reference}|{target_definition}|{random_state}|{MODEL_CODE_VERSION}|{best_name}"
    run_id = f"model-run:sha256:{hashlib.sha256(run_material.encode()).hexdigest()}"
    provenance = ModelRunProvenance(
        run_id=run_id,
        generated_at=datetime.now(UTC),
        dataset_reference=dataset_reference,
        target_definition=target_definition,
        feature_definition=FEATURE_DEFINITION_VERSION,
        split_strategy=split_strategy,
        selection_split="validation",
        final_evaluation_split="holdout",
        random_state=random_state,
        train_rows=len(train_indices),
        validation_rows=len(validation_indices),
        test_rows=len(test_indices),
        group_overlap_count=overlap,
        dependency_versions=tuple((package, version(package)) for package in ("numpy", "pandas", "scikit-learn")),
        code_version=MODEL_CODE_VERSION,
    )
    return ModelBundle(
        name=best_name,
        pipeline=final_pipeline,
        metrics=final_metrics,
        confusion_matrix=matrix,
        leaderboard=leaderboard,
        feature_columns=list(FEATURE_COLUMNS),
        eligibility=eligibility,
        provenance=provenance,
    )


def score_customer(bundle: ModelBundle, form_values: dict[str, Any]) -> dict[str, Any]:
    """Return an uncalibrated demonstration score with mandatory review routing."""

    missing = [column for column in bundle.feature_columns if form_values.get(column) is None]
    if missing:
        raise ModelInputError(f"Model scoring is blocked because inputs are missing: {', '.join(missing)}.")
    row = pd.DataFrame([{column: form_values[column] for column in bundle.feature_columns}])
    score = float(bundle.pipeline.predict_proba(row)[0][1])
    return {
        "model_score_percent": round(score * 100, 1),
        "score_semantics": "Uncalibrated demonstration model output; not a probability of default.",
        "routing": "Manual review required",
        "explanation_status": "unavailable",
        "explanation": "No validated model-faithful local explanation is implemented.",
        "run_id": bundle.provenance.run_id,
    }
