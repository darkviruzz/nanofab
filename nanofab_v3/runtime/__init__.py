"""Runtime: revisions, runs, wafer materialization (plan §3.6, §8).

Where the append-only `Revision` chain, the `Recipe`/`Run` pair and the
replay-based materialization of wafer positions (ADR-0004) live — the
`ProcessEngine` ideas worth keeping, carried over as concepts rather than as v1
code (plan §12, interview decision I5).

- `revision` — `Revision`, `HistoryEntry`, `ArtifactRef`, `RevisionChain`. Plan
  §3.6's object, wrapping `processes.engine.StepOutcome` rather than replacing
  it. **A revision stores its `Structure`; the chain is what is lazy** — the one
  design decision M4 had to make first, settled on measured grounds (see
  `revision`'s module docstring).
- `run` — `Recipe`, `RecipeStep`, wafer-parameterised values and
  `effective_params`. Plan §8's seam: a parameter may vary over the wafer up to
  this call and may not past it, which is what keeps the solver position-blind.
- `replay` — `run_recipe`, `materialize`, `Run`. Deterministic replay per plan
  §5.2 and ADR-0004, cached on (recipe hash, position, step, code version).

The direction of the dependency is deliberate: `runtime` declares the `RevisionStore`
and `ReplayStore` protocols and `nanofab_v3.io` implements them, so the runtime
knows about revisions and nothing about files.
"""

from __future__ import annotations

from nanofab_v3.runtime.replay import (
    Progress,
    Run,
    StepFailed,
    apply_step,
    materialize,
    run_recipe,
)
from nanofab_v3.runtime.revision import (
    CENTER,
    ArtifactRef,
    HistoryEntry,
    MemoryRevisionStore,
    Revision,
    RevisionChain,
    RevisionStore,
    RevisionSummary,
    Stopwatch,
    now_iso,
)
from nanofab_v3.runtime.run import (
    LinearTilt,
    Position,
    RadialProfile,
    Recipe,
    RecipeStep,
    ReplayStore,
    WaferParameter,
    as_positions,
    effective_params,
    positions_on_radius,
    positions_across_radius,
)

__all__ = [
    "ArtifactRef",
    "CENTER",
    "HistoryEntry",
    "LinearTilt",
    "MemoryRevisionStore",
    "Position",
    "Progress",
    "RadialProfile",
    "Recipe",
    "RecipeStep",
    "ReplayStore",
    "Revision",
    "RevisionChain",
    "RevisionStore",
    "RevisionSummary",
    "Run",
    "StepFailed",
    "Stopwatch",
    "WaferParameter",
    "apply_step",
    "as_positions",
    "effective_params",
    "materialize",
    "now_iso",
    "positions_on_radius",
    "positions_across_radius",
    "run_recipe",
]
