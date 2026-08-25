from __future__ import annotations

from typing import Any

from ..domain import ArtifactRef, HistoryEntry, SampleState, utc_now_iso


def make_artifact(
    run_id: str,
    step_id: str,
    kind: str,
    filename: str,
    summary: str,
    tags: list[str] | None = None,
) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=f"{run_id}-{step_id}-{kind}",
        kind=kind,
        uri=f"file:runs/{run_id}/{filename}",
        created_at=utc_now_iso(),
        summary=summary,
        tags=tags or [],
    )


def append_history(
    state: SampleState,
    step_id: str,
    step_name: str,
    params: dict[str, Any],
    artifacts: list[ArtifactRef],
    notes: str = "",
    status: str = "done",
) -> None:
    timestamp = utc_now_iso()
    state.history.append(
        HistoryEntry(
            step_id=step_id,
            step_name=step_name,
            started_at=timestamp,
            finished_at=timestamp,
            status=status,
            parameter_snapshot=dict(params),
            produced_artifacts=[artifact.uri for artifact in artifacts],
            notes=notes,
        )
    )
