"""Fail CI when a detect-secrets JSON report contains repository findings."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pulseiq.security import load_secret_report, summarize_secret_findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="Path to detect-secrets JSON output")
    args = parser.parse_args()

    try:
        summaries = summarize_secret_findings(load_secret_report(args.report))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Secret scan could not be verified: {exc}")
        return 2

    if summaries:
        print("Potential secrets detected; values and hashes are intentionally omitted:")
        for summary in summaries:
            print(f"- {summary}")
        return 1

    print("No potential secrets detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
