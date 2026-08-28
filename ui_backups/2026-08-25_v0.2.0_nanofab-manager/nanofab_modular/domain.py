from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ProcStatus(str, Enum):
    PENDING = "Pending"
    BLOCKED = "Blocked"
    READY = "Ready"
    RUNNING = "Running"
    DONE = "Done"
    WARNING = "Warning"
    FAILED = "Failed"
    ABORTED = "Aborted"
    SKIPPED = "Skipped"


@dataclass
class Quantity:
    value: float
    unit: str
    source: str = "nominal"


@dataclass
class ArtifactRef:
    artifact_id: str
    kind: str
    uri: str
    created_at: str
    mime_type: str = ""
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    metrics: dict[str, Quantity] = field(default_factory=dict)


@dataclass
class Substrate:
    material: str
    form_factor: str
    geometry: dict[str, Any]
    surface_finish: str = "unknown"
    orientation: str = ""
    lot_id: str = ""
    notes: str = ""


@dataclass
class Layer:
    layer_id: str
    name: str
    role: str
    material: str
    status: str
    thickness: Quantity
    coverage: str = "blanket"
    properties: dict[str, Any] = field(default_factory=dict)
    facets: dict[str, Any] = field(default_factory=dict)


@dataclass
class HistoryEntry:
    step_id: str
    step_name: str
    started_at: str
    finished_at: str
    status: str
    parameter_snapshot: dict[str, Any]
    produced_artifacts: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class SampleState:
    revision: int = 0
    schema_id: str = "sample_state.v0"
    substrate: Substrate | None = None
    layers: list[Layer] = field(default_factory=list)
    artifacts: list[ArtifactRef] = field(default_factory=list)
    history: list[HistoryEntry] = field(default_factory=list)
    facets: dict[str, Any] = field(default_factory=dict)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clone_state(state: SampleState) -> SampleState:
    return copy.deepcopy(state)
