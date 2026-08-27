"""Defense-in-depth tests for direct analytical service calls."""

from __future__ import annotations

import pandas as pd
import pytest

from pulseiq.anomaly import detect_anomalies
from pulseiq.data import generate_demo_data
from pulseiq.model import train_models


def test_direct_rule_evaluation_rejects_missing_evidence() -> None:
    """Calling the service directly cannot bypass dataset readiness."""

    with pytest.raises(ValueError, match="Risk rule evaluation is blocked"):
        detect_anomalies(pd.DataFrame({"transaction_amount": [1200]}))


def test_direct_model_training_rejects_silent_default_inputs() -> None:
    """Direct model training cannot construct generic financial features or targets."""

    with pytest.raises(ValueError, match="Model exploration is blocked"):
        train_models(pd.DataFrame({"income": [100_000], "loan_amount": [50_000]}))


def test_direct_model_training_never_replaces_a_single_class_target() -> None:
    dataframe = generate_demo_data(rows=300).assign(defaulted=0, repayment_status="Repaid")

    with pytest.raises(ValueError, match="only one outcome class"):
        train_models(dataframe)
