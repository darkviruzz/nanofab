"""`Field` types: named per-cell quantities on the `Grid` (plan §3.3).

A `Field` is a named per-cell quantity — `dose`, `damage`, `exposed`,
`temperature_history` — with one of two scopes:

- **global**, meaningful everywhere (rare), keyed `FieldKey(name, None)`;
- **material-scoped**, meaningful only where its material exists, keyed
  `FieldKey(name, material_id)`.

The scoping rule (plan §3.3) says material-scoped fields are reset to their
default wherever the owning material was removed or newly created during a step —
which is why `FieldSpec` carries the default: the commit gate (§4.5, milestone M1)
needs it. M0 only stores and validates fields; nothing resets them yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

import numpy as np
import numpy.typing as npt

from nanofab_v3.materials import MaterialId
from nanofab_v3.model.grid import Grid


class FieldKey(NamedTuple):
    """Identity of one `Field` in a `Structure`: its name and its scope.

    `material is None` marks a global field; otherwise the field is scoped to
    that material.
    """

    name: str
    material: MaterialId | None = None

    @property
    def is_material_scoped(self) -> bool:
        """True for a field that only means something inside its material."""
        return self.material is not None


@dataclass(frozen=True)
class FieldSpec:
    """Declaration of a `Field` kind: dtype, default and scope.

    Attributes:
        name: Field name, e.g. `"dose"`.
        dtype: Storage dtype — `float32` for `dose`, `int8` for `exposed`.
        default: Value a fresh (or reset) cell carries.
        material_scoped: Whether keys of this field name a material.
        unit: Unit string for the API boundary, e.g. `"mJ/cm^2"`. The kernel
            itself works in plain floats (plan §3.1).
    """

    name: str
    dtype: npt.DTypeLike = np.float32
    default: float = 0.0
    material_scoped: bool = True
    unit: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("field name must be a non-empty string")

    def key(self, material: MaterialId | None = None) -> FieldKey:
        """Build the `FieldKey` for this spec, checking the declared scope."""
        if self.material_scoped and material is None:
            raise ValueError(f"field {self.name!r} is material-scoped and needs a material")
        if not self.material_scoped and material is not None:
            raise ValueError(f"field {self.name!r} is global and takes no material")
        return FieldKey(self.name, material)

    def new(self, grid: Grid) -> np.ndarray:
        """A default-filled array of this field on `grid`."""
        return np.full(grid.shape, self.default, dtype=self.dtype)
