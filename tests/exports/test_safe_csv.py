"""Tests for spreadsheet-safe CSV exports."""

from __future__ import annotations

from io import BytesIO

import pandas as pd

from pulseiq.exports import safe_csv_bytes


def test_safe_csv_neutralizes_formula_like_user_strings() -> None:
    dataframe = pd.DataFrame(
        {
            "value": ["=2+3", "+cmd", "-formula", "@SUM(A1:A2)", "\tformula", "  =hidden", "safe"],
            "number": [-42, 5, 6, 7, 8, 9, 10],
        }
    )

    exported = safe_csv_bytes(dataframe)
    restored = pd.read_csv(BytesIO(exported), keep_default_na=False)

    assert restored["value"].tolist() == [
        "'=2+3",
        "'+cmd",
        "'-formula",
        "'@SUM(A1:A2)",
        "'\tformula",
        "'  =hidden",
        "safe",
    ]
    assert restored["number"].tolist() == [-42, 5, 6, 7, 8, 9, 10]


def test_safe_csv_does_not_mutate_the_source_dataframe() -> None:
    dataframe = pd.DataFrame({"value": ["=unsafe"]})

    safe_csv_bytes(dataframe)

    assert dataframe.loc[0, "value"] == "=unsafe"


def test_safe_csv_includes_utf8_bom_for_spreadsheet_interoperability() -> None:
    exported = safe_csv_bytes(pd.DataFrame({"city": ["Kigali"]}))

    assert exported.startswith(b"\xef\xbb\xbf")
