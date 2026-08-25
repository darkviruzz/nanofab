"""NanoFab structure model v2 (working title `nanofab_v3`).

Successor of `nanofab_modular`, implementing `docs/plans/v2-structure-model.md`.
The sample's geometry is one signed-distance field per material on one shared
`Grid` (ADR-0002) — the single stored truth. Analytic primitives exist only as
constructors; set operations are pointwise min/max; everything else (solid union,
material index map, contours, `Occurrence`s) is derived per revision.

Package layout (plan §14):

- `model/` — `Grid`, `Structure`, `Field` types
- `kernel/` — set operations, constructors, marching squares, invariants
- `materials/` — the `MaterialType` library
- `processes/` — the process set (M3)
- `runtime/` — revisions, runs, materialization (M4)
- `io/` — persistence and exchange format (M4)

v1 (`cross_section_general_prototype.py`) stays untouched next to this package
until the S1-S4 acceptance tests pass (plan §14, AGENTS.md §7).
"""

from __future__ import annotations

from nanofab_v3.materials import MaterialId, MaterialType
from nanofab_v3.model import EMPTY, PHI_DTYPE, FieldKey, FieldSpec, Grid, Structure

__version__ = "0.3.0.dev0"

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
