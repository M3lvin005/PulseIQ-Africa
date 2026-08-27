"""Contracts for shared evidence, chart, and progress view models."""

from __future__ import annotations

from pulseiq.ui_models import ChartViewModel, EvidenceItem, InspectorState, JobProgress, JobState


def test_job_progress_clamps_at_render_boundary_and_exposes_worker_fields() -> None:
    progress = JobProgress(
        "report-package",
        "Prepare artifacts",
        100,
        JobState.SUCCEEDED,
        heartbeat="2026-08-27T04:00:00Z",
        artifact_reference="s3://reports/demo.html",
    )

    assert progress.state is JobState.SUCCEEDED
    assert progress.artifact_reference == "s3://reports/demo.html"


def test_evidence_and_chart_models_preserve_traceable_context() -> None:
    item = EvidenceItem("TXN-1", "TXN-1 · CUST-1", "High", "Rule triggered", (("Source", "demo"),))
    inspector = InspectorState("Flagged record", 1, 20, item.identifier)
    chart = ChartViewModel("Risk trend", "Flags rose", "Risk trend data", "risk-trend.csv")

    assert inspector.selected_identifier == "TXN-1"
    assert inspector.total_count == 20
    assert chart.table_caption == "Risk trend data"
