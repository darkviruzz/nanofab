"""`MaterialType` library entries and the `MaterialId` that keys them.

Plan `docs/plans/v2-structure-model.md` §3.4: a `MaterialType` is pure data — a
library entry with no geometry. A *material in a `Structure`* is nothing but a
`MaterialId` owning one signed-distance field and, optionally, material-scoped
`Field`s (ADR-0003: no other per-material state is stored).

M0 keeps this deliberately thin. Rate/yield models, optical constants,
crystallographic anisotropy and develop/dissolve models arrive with the process
set in M3; they belong here, not in the geometry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NewType

MaterialId = NewType("MaterialId", str)
"""Key of one material inside a `Structure` (and of its `MaterialType`)."""


@dataclass(frozen=True)
class MaterialType:
    """A material library entry: identity and display data, never geometry.

    Attributes:
        material_id: Stable key, used as the `Structure.phi` key.
        name: Human-readable name for the UI.
        display_color: `#rrggbb` used by rendering (plan §10); not physics.
    """

    material_id: MaterialId
    name: str
    display_color: str = "#808080"

    def __post_init__(self) -> None:
        if not str(self.material_id).strip():
            raise ValueError("material_id must be a non-empty string")
        if not self.name.strip():
            raise ValueError("name must be a non-empty string")
