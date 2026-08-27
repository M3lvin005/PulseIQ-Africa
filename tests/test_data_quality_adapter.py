"""Compatibility tests for legacy data-quality callers."""

from __future__ import annotations

import pandas as pd

from pulseiq.data import data_quality


def test_legacy_quality_adapter_never_scores_empty_data_as_healthy() -> None:
    """Existing UI/report callers inherit REQ-QUAL-005 immediately."""

    quality = data_quality(pd.DataFrame())

    assert quality.score == 0.0
