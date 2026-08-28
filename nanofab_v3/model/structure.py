"""The `Structure` — the single stored geometry truth of one revision.

`CONTEXT.md` / plan §3.2: material geometry and per-cell state of the sample at
one revision — one signed-distance field per material plus named `Field`s, all on
one `Grid`. `phi[m] < 0` means "inside material m".

Everything else is **derived, never stored as truth**:

- solid union `solid_phi = min_m phi[m]`,
- empty space `empty_phi = -solid_phi`,
- the material cell grid `argmin_m phi[m]`,
- contours (`nanofab_v3.kernel.contours`) and `Occurrence`s (M3).

Analytic primitives exist only as constructors (ADR-0002): once sampled onto the
grid, the field is the truth and the primitive is forgotten. A `Structure` is a
value object — every mutator returns a new `Structure`, and the arrays it holds
are treated as immutable (kernel functions never write in place), which is what
lets revisions share arrays cheaply.

**`metadata` is the one thing here that is not per cell** (M7, roadmap E7). A
wafer is 625 µm thick and the domain that shows it is a few hundred nanometres
deep — roadmap §1's arithmetic says a 625 µm domain at 1 nm would be 15 GB per
revision, so the thickness is *known* rather than *drawn*. It cannot be a
`Field`: a `Field` is one value per cell, and four bytes times the whole grid to
say "1 mm" is not a representation, it is a waste with a rounding error in it. It
cannot be a capability either — those are set membership, not numbers. And it
cannot live on the `Revision`, because a step sees only its `Structure` and the
step that must refuse to etch through the wafer is the one that needs the number.

So: a small mapping of JSON-native scalars, carried by every derivation and
serialised with the rest. Deliberately open rather than a typed `SubstrateSpec`
field, because the next thing that needs it (B2's back side, a chuck temperature,
a tool id) should not be a schema change — and deliberately *scalars only*, so
that "carried through the exchange format" needs no encoder of its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from functools import cached_property
from types import MappingProxyType
from typing import Mapping

import numpy as np

from nanofab_v3.materials import MaterialId
from nanofab_v3.model.field import FieldKey
from nanofab_v3.model.grid import PHI_DTYPE, Grid

METADATA_TYPES = float | int | str | bool
"""What `Structure.metadata` may hold: JSON scalars, so the format needs no encoder."""

EMPTY = -1
"""`material_index` value for a cell that belongs to no material (empty space)."""


@dataclass(frozen=True, eq=False)
class Structure:
    """Geometry and per-cell state of the sample at one revision.

    Attributes:
        grid: The `Grid` every field lives on — the sole spatial authority.
        phi: One signed-distance field per material, `phi[m] < 0` inside m,
            dense float32 on `grid`.
        fields: Named per-cell quantities, keyed by `FieldKey` (plan §3.3).
        metadata: Scalar facts about the sample that are not per cell — the
            substrate's real thickness above all (roadmap E7). See the module
            docstring for why this is neither a `Field` nor a capability.
    """

    grid: Grid
    phi: Mapping[MaterialId, np.ndarray] = dataclass_field(default_factory=dict)
    fields: Mapping[FieldKey, np.ndarray] = dataclass_field(default_factory=dict)
    metadata: Mapping[str, METADATA_TYPES] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        phi = {}
        for material, values in dict(self.phi).items():
            phi[material] = self.grid.as_field(values, dtype=PHI_DTYPE)
        fields = {}
        for key, values in dict(self.fields).items():
            key = FieldKey(*key)
            array = np.asarray(values)
            if array.shape != self.grid.shape:
                raise ValueError(
                    f"field {key} has shape {array.shape}, grid shape is {self.grid.shape}"
                )
            if key.material is not None and key.material not in phi:
                raise ValueError(f"field {key} is scoped to a material not in this Structure")
            fields[key] = array
        metadata = {}
        for key, value in dict(self.metadata).items():
            if not str(key).strip():
                raise ValueError("a metadata key must be a non-empty string")
            if not isinstance(value, (bool, int, float, str)):
                raise ValueError(
                    f"metadata {key!r} is {type(value).__name__}; only JSON scalars are "
                    "carried here, so that the exchange format needs no encoder for it"
                )
            metadata[str(key)] = value
        object.__setattr__(self, "phi", MappingProxyType(phi))
        object.__setattr__(self, "fields", MappingProxyType(fields))
        object.__setattr__(self, "metadata", MappingProxyType(metadata))

    # -- materials -----------------------------------------------------------

    @property
    def materials(self) -> tuple[MaterialId, ...]:
        """The materials present, in insertion order (stable per revision)."""
        return tuple(self.phi.keys())

    def phi_of(self, material: MaterialId) -> np.ndarray:
        """The signed-distance field of `material`."""
        try:
            return self.phi[material]
        except KeyError:
            raise KeyError(f"no material {material!r} in this Structure") from None

    def inside(self, material: MaterialId) -> np.ndarray:
        """Boolean mask of the cells in the interior of `material` (`phi < 0`).

        Strictly the interior, so interiors of different materials stay disjoint
        even where they touch. For "which material owns this cell", including the
        cells exactly on an interface, use `material_index`.
        """
        return self.phi_of(material) < 0.0

    def with_material(self, material: MaterialId, phi: np.ndarray) -> "Structure":
        """A new `Structure` with `material` set to `phi` (replacing any existing)."""
        updated = dict(self.phi)
        updated[material] = self.grid.as_field(phi, dtype=PHI_DTYPE)
        return Structure(self.grid, updated, dict(self.fields), dict(self.metadata))

    def without_material(self, material: MaterialId) -> "Structure":
        """A new `Structure` without `material` and without its scoped fields."""
        if material not in self.phi:
            raise KeyError(f"no material {material!r} in this Structure")
        updated = {m: p for m, p in self.phi.items() if m != material}
        fields = {k: v for k, v in self.fields.items() if k.material != material}
        return Structure(self.grid, updated, fields, dict(self.metadata))

    # -- fields --------------------------------------------------------------

    def field(self, key: FieldKey) -> np.ndarray:
        """The `Field` array stored under `key`."""
        try:
            return self.fields[FieldKey(*key)]
        except KeyError:
            raise KeyError(f"no field {key} in this Structure") from None

    def has_field(self, key: FieldKey) -> bool:
        """Whether a `Field` is stored under `key`."""
        return FieldKey(*key) in self.fields

    def fields_of(self, material: MaterialId | None) -> dict[FieldKey, np.ndarray]:
        """All fields scoped to `material` (`None` selects the global fields)."""
        return {k: v for k, v in self.fields.items() if k.material == material}

    def with_field(self, key: FieldKey, values: np.ndarray) -> "Structure":
        """A new `Structure` carrying `values` under `key`."""
        fields = dict(self.fields)
        fields[FieldKey(*key)] = values
        return Structure(self.grid, dict(self.phi), fields, dict(self.metadata))

    def without_field(self, key: FieldKey) -> "Structure":
        """A new `Structure` without the field stored under `key`."""
        key = FieldKey(*key)
        if key not in self.fields:
            raise KeyError(f"no field {key} in this Structure")
        fields = {k: v for k, v in self.fields.items() if k != key}
        return Structure(self.grid, dict(self.phi), fields, dict(self.metadata))

    # -- metadata ------------------------------------------------------------

    def meta(self, key: str, default: METADATA_TYPES | None = None) -> METADATA_TYPES | None:
        """One metadata value, or `default` — the read half of the module docstring."""
        return self.metadata.get(key, default)

    def with_metadata(self, **values: METADATA_TYPES) -> "Structure":
        """A new `Structure` with these metadata entries added or replaced."""
        merged = dict(self.metadata)
        merged.update(values)
        return Structure(self.grid, dict(self.phi), dict(self.fields), merged)

    # -- derived views (never stored as truth) -------------------------------

    @cached_property
    def solid_phi(self) -> np.ndarray:
        """Signed-distance field of the solid union, `min_m phi[m]`.

        Derived per revision, cached here only because rendering and queries ask
        for it repeatedly — it is not part of the stored truth. An empty
        `Structure` is `+inf` everywhere (no solid anywhere).
        """
        if not self.phi:
            return self.grid.full(np.inf)
        return np.minimum.reduce(list(self.phi.values()))

    @cached_property
    def empty_phi(self) -> np.ndarray:
        """Signed-distance field of empty space, `-solid_phi`."""
        return -self.solid_phi

    @cached_property
    def solid_mask(self) -> np.ndarray:
        """Boolean mask of cells occupied by any material.

        A cell sitting exactly on a zero level counts as solid. Where two
        materials touch, `solid_phi` is exactly zero along their shared
        interface, and a strict `< 0` would open a one-cell gap through the
        middle of continuous material — which would then read as a crack to
        every connectivity query. `material_index` gives such a cell to one
        material, so the partition stays exclusive.
        """
        return self.solid_phi <= 0.0

    @cached_property
    def nearest_material_index(self) -> np.ndarray:
        """Index into `materials` of the material closest to each cell, `argmin_m phi[m]`.

        Defined in empty space too, where it names the material whose surface is
        nearest — which is what the motion kernel asks for when it needs the
        material at the front (plan §4.2). `EMPTY` only when there is no material
        at all.
        """
        if not self.phi:
            return self.grid.full(EMPTY, dtype=np.int16)
        stack = np.stack(list(self.phi.values()))
        return np.argmin(stack, axis=0).astype(np.int16)

    @cached_property
    def material_index(self) -> np.ndarray:
        """Index into `materials` per cell, `EMPTY` where the cell is empty.

        `argmin_m phi[m]` masked to the solid (plan §3.2) — the map rendering and
        per-cell queries run on. Derived, cached per revision.
        """
        if not self.phi:
            return self.grid.full(EMPTY, dtype=np.int16)
        return np.where(self.solid_mask, self.nearest_material_index, np.int16(EMPTY)).astype(
            np.int16
        )

    def material_at(self, index: int) -> MaterialId | None:
        """The material an entry of `material_index` refers to (`None` = empty)."""
        if index == EMPTY:
            return None
        return self.materials[int(index)]

    def measure(self, mask: np.ndarray) -> float:
        """Area (2D) / volume (3D) covered by a boolean mask, in nm^ndim."""
        return float(np.count_nonzero(mask)) * self.grid.cell_measure

    def __repr__(self) -> str:  # pragma: no cover - debug convenience
        return (
            f"Structure(grid={self.grid.shape}@{self.grid.spacing}nm, "
            f"materials={list(self.materials)}, fields={[tuple(k) for k in self.fields]})"
        )
