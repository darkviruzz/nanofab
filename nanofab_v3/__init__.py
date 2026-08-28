"""NanoFab structure model v2 (working title `nanofab_v3`).

Successor of `nanofab_modular`, implementing `docs/plans/v2-structure-model.md`.
The sample's geometry is one signed-distance field per material on one shared
`Grid` (ADR-0002) — the single stored truth. Analytic primitives exist only as
constructors; set operations are pointwise min/max; everything else (solid union,
material cell grid, contours, `Occurrence`s) is derived per revision.

Package layout (plan §14):

- `model/` — `Grid`, `Structure`, `Field` types
- `kernel/` — set operations, constructors, marching squares, invariants
- `materials/` — the `MaterialType` library
- `processes/` — the process set (M3)
- `runtime/` — revisions, runs, materialization (M4)
- `io/` — persistence and exchange format (M4)
- `ui/` — `SceneSnapshot`, the interactive `Session`, and the Qt shell (M4)

The dependency runs one way through those: `runtime` declares the store
protocols `io` implements, and `ui.scene`/`ui.session` decide everything about
geometry and about a run without importing Qt. That last one is ADR-0001's
finding turned into a rule a test can check — v1's defect was a renderer that
owned the geometry.

The S1-S4 acceptance tests passed on 2026-08-25, so v1 became a `ui_backups/`
snapshot as plan §14 and AGENTS.md §7 require: the cross-section prototype is in
`ui_backups/2026-08-25_v1.0.0_cross-section-prototype/` and the v0.2.0
application in `ui_backups/2026-08-25_v0.2.0_nanofab-manager/`. This package is
the only actively built code base at the repository root.
"""

from __future__ import annotations

from nanofab_v3.materials import MaterialId, MaterialType
from nanofab_v3.model import EMPTY, PHI_DTYPE, FieldKey, FieldSpec, Grid, Structure

__version__ = "0.5.0a2"

__all__ = [
    "EMPTY",
    "PHI_DTYPE",
    "FieldKey",
    "FieldSpec",
    "Grid",
    "MaterialId",
    "MaterialType",
    "Structure",
    "__version__",
]
