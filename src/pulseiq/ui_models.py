"""Typed view models shared by the governed workspace UI."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class JobState(StrEnum):
    """Truthful lifecycle states for long-running workspace operations."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """A selectable item whose source evidence can be inspected."""

    identifier: str
    label: str
    status: str
    summary: str
    fields: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class InspectorState:
    """Current filtered and selected state for an evidence inspector."""

    title: str
    filtered_count: int
    total_count: int
    selected_identifier: str | None


@dataclass(frozen=True, slots=True)
class ChartViewModel:
    """Chart metadata that keeps visual and tabular evidence paired."""

    title: str
    narrative: str
    table_caption: str
    export_name: str


@dataclass(frozen=True, slots=True)
class JobProgress:
    """Portable progress contract for local prototype and production workers."""

    job_id: str
    phase: str
    percent: int
    state: JobState
    heartbeat: str | None = None
    error: str | None = None
    artifact_reference: str | None = None
