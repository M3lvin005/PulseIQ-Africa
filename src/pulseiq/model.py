"""Machine-learning utilities for loan/default risk prediction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


NUMERIC_FEATURES = [
    "income",
    "loan_amount",
    "repayment_history_score",
    "existing_debt",
    "transaction_frequency",
    "account_age_months",
]

CATEGORICAL_FEATURES = ["employment_status", "segment", "business_type", "region"]


@dataclass
class ModelBundle:
    name: str
    pipeline: Any
    metrics: dict[str, float]
    confusion_matrix: list[list[int]]
    leaderboard: list[dict[str, float | str]]
    feature_columns: list[str]


def _coerce_numeric(df: pd.DataFrame, column: str, default: float) -> pd.Series:
    if column in df.columns:
        values = pd.to_numeric(df[column], errors="coerce")
        if values.notna().any():
            return values.fillna(values.median()).astype(float)
    return pd.Series(default, index=df.index, dtype="float64")


def prepare_model_frame(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Build a model-ready feature frame and target from flexible uploaded data."""

    working = df.copy().reset_index(drop=True)
    features = pd.DataFrame(index=working.index)

    defaults = {
        "income": 180000.0,
        "loan_amount": 120000.0,
        "repayment_history_score": 70.0,
        "existing_debt": 25000.0,
        "transaction_frequency": 18.0,
        "account_age_months": 24.0,
    }
    for column, default in defaults.items():
        features[column] = _coerce_numeric(working, column, default)

    for column in CATEGORICAL_FEATURES:
        if column in working.columns:
            features[column] = working[column].fillna("Unknown").astype(str)
        else:
            features[column] = "Unknown"

    if "defaulted" in working.columns:
        target = pd.to_numeric(working["defaulted"], errors="coerce").fillna(0).clip(0, 1).astype(int)
    elif "repayment_status" in working.columns:
        status = working["repayment_status"].fillna("").astype(str).str.lower()
        target = status.str.contains("default|late|failed|missed").astype(int)
    else:
        loan_ratio = features["loan_amount"] / np.maximum(features["income"], 1)
        debt_ratio = features["existing_debt"] / np.maximum(features["income"], 1)
        target = ((features["repayment_history_score"] < 48) | (loan_ratio > 1.65) | (debt_ratio > 0.72)).astype(int)

    return features, target


def _one_hot_encoder() -> Any:
    from sklearn.preprocessing import OneHotEncoder

    try:
        return OneHotEncoder(handle_unknown="ignore", sparse_output=False)
    except TypeError:
        return OneHotEncoder(handle_unknown="ignore", sparse=False)


def train_models(df: pd.DataFrame, random_state: int = 42) -> ModelBundle:
    """Train three beginner-friendly classifiers and return the strongest one."""

    from sklearn.compose import ColumnTransformer
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.tree import DecisionTreeClassifier

    features, target = prepare_model_frame(df)
    if target.nunique() < 2:
        target = _fallback_target(features)

    stratify = target if target.value_counts().min() >= 2 else None
    test_size = 0.25 if len(features) >= 80 else 0.35
    x_train, x_test, y_train, y_test = train_test_split(
        features,
        target,
        test_size=test_size,
        random_state=random_state,
        stratify=stratify,
    )

    preprocessor = ColumnTransformer(
        transformers=[
            ("numeric", StandardScaler(), NUMERIC_FEATURES),
            ("categorical", _one_hot_encoder(), CATEGORICAL_FEATURES),
        ]
    )

    candidates = {
        "Logistic Regression": LogisticRegression(max_iter=1500, class_weight="balanced", random_state=random_state),
        "Random Forest": RandomForestClassifier(
            n_estimators=180,
            max_depth=9,
            min_samples_leaf=4,
            class_weight="balanced",
            random_state=random_state,
        ),
        "Decision Tree": DecisionTreeClassifier(max_depth=5, class_weight="balanced", random_state=random_state),
    }

    leaderboard: list[dict[str, float | str]] = []
    fitted: dict[str, Pipeline] = {}
    matrices: dict[str, list[list[int]]] = {}

    for name, estimator in candidates.items():
        pipeline = Pipeline(steps=[("preprocessor", preprocessor), ("model", estimator)])
        pipeline.fit(x_train, y_train)
        predictions = pipeline.predict(x_test)
        probabilities = pipeline.predict_proba(x_test)[:, 1] if hasattr(pipeline, "predict_proba") else predictions
        metrics = _metrics(y_test, predictions, probabilities)
        leaderboard.append({"model": name, **metrics})
        fitted[name] = pipeline
        matrices[name] = confusion_matrix(y_test, predictions, labels=[0, 1]).astype(int).tolist()

    leaderboard = sorted(leaderboard, key=lambda row: (float(row["f1_score"]), float(row["roc_auc"])), reverse=True)
    best_name = str(leaderboard[0]["model"])
    best_metrics = {key: float(value) for key, value in leaderboard[0].items() if key != "model"}

    return ModelBundle(
        name=best_name,
        pipeline=fitted[best_name],
        metrics=best_metrics,
        confusion_matrix=matrices[best_name],
        leaderboard=leaderboard,
        feature_columns=NUMERIC_FEATURES + CATEGORICAL_FEATURES,
    )


def _fallback_target(features: pd.DataFrame) -> pd.Series:
    loan_ratio = features["loan_amount"] / np.maximum(features["income"], 1)
    debt_ratio = features["existing_debt"] / np.maximum(features["income"], 1)
    score = features["repayment_history_score"]
    return ((loan_ratio > 1.55) | (debt_ratio > 0.62) | (score < 45)).astype(int)


def _metrics(y_true: pd.Series, predictions: np.ndarray, probabilities: np.ndarray) -> dict[str, float]:
    from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score

    values = {
        "accuracy": accuracy_score(y_true, predictions),
        "precision": precision_score(y_true, predictions, zero_division=0),
        "recall": recall_score(y_true, predictions, zero_division=0),
        "f1_score": f1_score(y_true, predictions, zero_division=0),
    }
    try:
        values["roc_auc"] = roc_auc_score(y_true, probabilities)
    except ValueError:
        values["roc_auc"] = 0.0
    return {key: round(float(value), 3) for key, value in values.items()}


def score_customer(bundle: ModelBundle, form_values: dict[str, Any]) -> dict[str, Any]:
    """Score one customer record and explain the risk decision."""

    row = pd.DataFrame([{column: form_values.get(column) for column in bundle.feature_columns}])
    probability = float(bundle.pipeline.predict_proba(row)[0][1])
    risk_score = round(probability * 100, 1)

    if risk_score >= 70:
        decision = "Review manually"
        action = "Request stronger documentation, reduce loan size, or add a guarantor."
    elif risk_score >= 45:
        decision = "Approve with conditions"
        action = "Consider a smaller facility, closer monitoring, or a shorter repayment cycle."
    else:
        decision = "Likely approve"
        action = "Proceed if identity and affordability checks are complete."

    reasons = []
    income = float(form_values.get("income") or 1)
    loan_amount = float(form_values.get("loan_amount") or 0)
    existing_debt = float(form_values.get("existing_debt") or 0)
    repayment_score = float(form_values.get("repayment_history_score") or 70)
    if loan_amount > income * 1.4:
        reasons.append("high loan-to-income ratio")
    if existing_debt > income * 0.55:
        reasons.append("existing debt pressure")
    if repayment_score < 50:
        reasons.append("weak repayment history")
    if str(form_values.get("employment_status", "")).lower() in {"informal", "unemployed"}:
        reasons.append("less stable employment profile")

    return {
        "risk_score": risk_score,
        "decision": decision,
        "reason": ", ".join(reasons) if reasons else "balanced affordability and repayment profile",
        "suggested_action": action,
    }

