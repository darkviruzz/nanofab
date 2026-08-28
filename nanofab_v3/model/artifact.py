"""`ArtifactRef` and the sink a step reaches a filesystem through (docs §4.2.2).

An artifact is a **file the revision points at**, never a payload inside it. A
SEM image, a profilometer trace, a mesh handed to an external solver: all of them
stay out of the `Structure` and out of the `Revision`, which is what keeps a
revision 5-320 KB on disk (plan §20.3) no matter what was measured on it.

## Why the sink exists, and why it is not a purity hole

A `ProcessStep` is a pure function of (input structure, params, position, step
index, code version) — plan §5.2, ADR-0004 — and a pure function cannot open a
file. So a step that wants to *produce* an artifact is handed somewhere to put
it: `StepContext.artifacts`, an `ArtifactSink`, which takes a payload and gives
back the `ArtifactRef` that names where it went.

The invariant survives, and the reason is worth stating once. What §5.2 makes
pure is the step's **outcome** — the structure it commits, the capabilities it
provides, the numbers it measured. An artifact is none of those: it is a record
of a run, in the same category as `HistoryEntry.started_at`, which replay has
never reproduced either. Two replays of a step write the same bytes to the same
relative name, so a re-materialized position points at a file with the same
content, and a cached revision points at one already written.

**A step with no sink emits no artifacts and still measures everything.** That is
the honest default rather than a degraded one: `inspect.profilometer` with
nowhere to write a trace has still measured the step height, and a ref to a file
nobody wrote would be worse than no ref at all. `MemoryArtifactSink` is here for
tests and for a session that wants the payloads without a directory;
`io.store.DirectoryArtifactSink` is the one that writes files.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class ArtifactRef:
    """A URI reference to a heavy output (docs §4.2.2, carried over unchanged).

    Attributes:
        kind: What sort of output it is — `"image"`, `"table"`, `"mesh"`, `"log"`.
        uri: Where it lives. A relative path is relative to the save file.
        label: What to call it in the UI.
        media_type: MIME type when it is known; `""` when it is not.
    """

    kind: str
    uri: str
    label: str = ""
    media_type: str = ""


class ArtifactSink(Protocol):
    """Somewhere a step can put a payload and get back a reference to it.

    Structural, like `ProcessStep` and `WaferParameter`: a session, a test or a
    plugin's own store is one by having this method, without importing anything
    from here.
    """

    def put(
        self,
        name: str,
        payload: np.ndarray,
        *,
        kind: str = "table",
        label: str = "",
    ) -> ArtifactRef:
        """Store `payload` under `name` and return the reference to it."""


class MemoryArtifactSink:
    """An `ArtifactSink` that keeps payloads in a dict — for tests and sessions.

    The `uri` it hands back is `memory:<name>`, which is deliberately not a path:
    a ref that looked like a file and was not would be the exact failure this
    module exists to avoid.
    """

    def __init__(self) -> None:
        self.payloads: dict[str, np.ndarray] = {}

    def put(
        self,
        name: str,
        payload: np.ndarray,
        *,
        kind: str = "table",
        label: str = "",
    ) -> ArtifactRef:
        array = np.asarray(payload)
        self.payloads[name] = array
        return ArtifactRef(kind=kind, uri=f"memory:{name}", label=label or name)

    def __len__(self) -> int:
        return len(self.payloads)

    def __contains__(self, name: object) -> bool:
        return name in self.payloads
