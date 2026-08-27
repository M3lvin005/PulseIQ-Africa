"""Small fail-closed helpers used by repository security gates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def summarize_secret_findings(document: dict[str, Any]) -> tuple[str, ...]:
    """Return safe finding summaries without exposing hashes or secret values."""
    results = document.get("results")
    if not isinstance(results, dict):
        raise ValueError("Secret-scan report does not contain a results object.")

    summaries: list[str] = []
    for filename, raw_findings in sorted(results.items()):
        if not isinstance(filename, str) or not isinstance(raw_findings, list):
            raise ValueError("Secret-scan report has an invalid results entry.")
        for finding in raw_findings:
            if not isinstance(finding, dict):
                raise ValueError("Secret-scan report contains an invalid finding.")
            finding_type = finding.get("type", "Unknown detector")
            line_number = finding.get("line_number", "unknown")
            summaries.append(f"{filename}:{line_number}: {finding_type}")
    return tuple(summaries)


def load_secret_report(path: Path) -> dict[str, Any]:
    """Load and validate the top-level JSON report shape."""
    with path.open(encoding="utf-8") as report_file:
        document = json.load(report_file)
    if not isinstance(document, dict):
        raise ValueError("Secret-scan report must be a JSON object.")
    return document
