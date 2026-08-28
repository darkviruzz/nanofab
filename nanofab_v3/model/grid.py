"""The `Grid` — sole spatial authority of a v2 `Structure`.

`CONTEXT.md` / plan §3.1: origin, cell spacing, shape and axis names live here and
nowhere else. No other object stores coordinates, extents or spacings, and no
kernel code hard-codes an axis pair — 3D adds an axis to `shape`/`axes`, nothing
else changes.

Cell `(i0, i1, ...)` is sampled at `origin[a] + i_a * spacing` along axis `a`; the
array index order is the axis order in `axes`. Units are plain float nm
(plan §3.1: `Quantity` appears at API boundaries, not inside the kernel).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
import numpy.typing as npt

PHI_DTYPE = np.float32
"""Storage dtype of every signed-distance field (plan §3.2: dense float32)."""


@dataclass(frozen=True)
class Grid:
    """The sample's discretisation: where every cell of every field sits.

    Attributes:
        origin: Position of cell index 0 per axis, in nm.
        spacing: Isotropic cell spacing in nm. A visible model parameter
            (plan §3.1), not an implementation detail.
        shape: Number of cells per axis, e.g. `(ny, nx)`.
        axes: Axis names in array-index order, e.g. `("y", "x")` — names, never
            positional assumptions.
    """

    origin: tuple[float, ...]
    spacing: float
    shape: tuple[int, ...]
    axes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "origin", tuple(float(v) for v in self.origin))
        object.__setattr__(self, "shape", tuple(int(v) for v in self.shape))
        object.__setattr__(self, "axes", tuple(str(v) for v in self.axes))
        object.__setattr__(self, "spacing", float(self.spacing))

        if not self.shape:
            raise ValueError("Grid needs at least one axis")
        if len(self.origin) != len(self.shape) or len(self.axes) != len(self.shape):
            raise ValueError(
                "origin, shape and axes must have the same length "
                f"(got {len(self.origin)}, {len(self.shape)}, {len(self.axes)})"
            )
        if not math.isfinite(self.spacing) or self.spacing <= 0.0:
            raise ValueError(f"spacing must be a positive finite length, got {self.spacing!r}")
        if any(n < 1 for n in self.shape):
            raise ValueError(f"every axis needs at least one cell, got shape {self.shape}")
        if any(not math.isfinite(v) for v in self.origin):
            raise ValueError(f"origin must be finite, got {self.origin}")
        if len(set(self.axes)) != len(self.axes):
            raise ValueError(f"axis names must be unique, got {self.axes}")
        if any(not name.strip() for name in self.axes):
            raise ValueError(f"axis names must be non-empty, got {self.axes}")

    # -- shape ---------------------------------------------------------------

    @property
    def ndim(self) -> int:
        """Number of spatial axes (2 for the v2 core, 3 later)."""
        return len(self.shape)

    @property
    def size(self) -> int:
        """Total number of cells."""
        return int(np.prod(self.shape))

    @property
    def cell_measure(self) -> float:
        """Area (2D) / volume (3D) of one cell in nm^ndim."""
        return self.spacing**self.ndim

    def axis_index(self, axis: str | int) -> int:
        """Resolve an axis name (or index) to its array-index position."""
        if isinstance(axis, (int, np.integer)):
            index = int(axis)
            if not -self.ndim <= index < self.ndim:
                raise ValueError(f"axis index {axis} out of range for {self.ndim} axes")
            return index % self.ndim
        try:
            return self.axes.index(axis)
        except ValueError:
            raise ValueError(f"unknown axis {axis!r}, grid has {self.axes}") from None

    # -- positions -----------------------------------------------------------

    def coordinates(self, axis: str | int) -> np.ndarray:
        """1-D array of cell positions along `axis`, in nm (float64)."""
        index = self.axis_index(axis)
        return self.origin[index] + self.spacing * np.arange(self.shape[index], dtype=np.float64)

    def mesh(self, *, sparse: bool = True) -> tuple[np.ndarray, ...]:
        """Coordinate arrays per axis, broadcastable over the grid (float64).

        `sparse=True` (the default) returns open-mesh arrays — enough for every
        pointwise constructor and cheap in memory.
        """
        coords = [self.coordinates(a) for a in range(self.ndim)]
        return tuple(np.meshgrid(*coords, indexing="ij", sparse=sparse))

    def position(self, index: Sequence[int]) -> tuple[float, ...]:
        """Position in nm of the cell at `index` (one entry per axis)."""
        index = tuple(int(i) for i in index)
        if len(index) != self.ndim:
            raise ValueError(f"index needs {self.ndim} entries, got {len(index)}")
        return tuple(o + self.spacing * i for o, i in zip(self.origin, index))

    def extent(self, axis: str | int) -> tuple[float, float]:
        """`(first, last)` cell position along `axis`, in nm."""
        i = self.axis_index(axis)
        return self.origin[i], self.origin[i] + self.spacing * (self.shape[i] - 1)

    # -- arrays --------------------------------------------------------------

    def zeros(self, dtype: npt.DTypeLike = PHI_DTYPE) -> np.ndarray:
        """A zero-filled array shaped like the grid."""
        return np.zeros(self.shape, dtype=dtype)

    def full(self, value: float, dtype: npt.DTypeLike = PHI_DTYPE) -> np.ndarray:
        """A constant array shaped like the grid."""
        return np.full(self.shape, value, dtype=dtype)

    def as_field(self, values: np.ndarray, dtype: npt.DTypeLike = PHI_DTYPE) -> np.ndarray:
        """Validate `values` against the grid and return it in the storage dtype."""
        array = np.asarray(values, dtype=dtype)
        if array.shape != self.shape:
            raise ValueError(f"field shape {array.shape} does not match grid shape {self.shape}")
        return array

    def check_same_grid(self, others: Iterable["Grid"]) -> None:
        """Raise unless every grid in `others` is this grid (single-authority rule)."""
        for other in others:
            if other != self:
                raise ValueError("all fields of one Structure must live on the same Grid")
