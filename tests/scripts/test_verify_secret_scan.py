from __future__ import annotations

import json
from pathlib import Path

import pytest

from pulseiq.security import load_secret_report, summarize_secret_findings


def test_summarize_findings_omits_secret_hashes() -> None:
    document = {
        "results": {
            "settings.py": [
                {
                    "type": "High Entropy String",
                    "line_number": 8,
                    "hashed_secret": "must-not-appear",  # pragma: allowlist secret
                }
            ]
        }
    }

    summaries = summarize_secret_findings(document)

    assert summaries == ("settings.py:8: High Entropy String",)
    assert "must-not-appear" not in summaries[0]


def test_summarize_findings_accepts_clean_report() -> None:
    assert summarize_secret_findings({"results": {}}) == ()


def test_load_report_rejects_non_object(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text(json.dumps([]), encoding="utf-8")

    with pytest.raises(ValueError, match="JSON object"):
        load_secret_report(report)
