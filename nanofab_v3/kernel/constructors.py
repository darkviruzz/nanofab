"""Constructors: analytic primitives sampled onto the `Grid`, once (plan §4.1).

ADR-0002's central rule: **analytics is only a constructor — afterwards only the
sampled field counts.** Each function here evaluates an exact signed-distance
function on the grid points and returns a dense float32 array; the primitive is
then forgotten. Nothing in the kernel ever consults it again. v1's permanent
analytic/`QPainterPath` dual truth was the root cause of its iteration stall
(ADR-0001 F2) — there is no second representation here to fall out of sync.

Accuracy: a half-space is exactly representable (a linear function is reproduced
exactly by the grid's linear reconstruction, so the zero level sits exactly where
the analytic plane does). Corners are exact to the ~½-cell corner rounding the
grid resolution implies (plan §15).

All constructors are N-D generic: they iterate over `grid.axes`, never over a
hard-coded axis pair.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from nanofab_v3.kernel import csg
from nanofab_v3.materials import MaterialId
from nanofab_v3.model.grid import PHI_DTYPE, Grid
from nanofab_v3.model.structure import Structure


def _check_length(grid: Grid, values: Sequence[float | None], what: str) -> None:
    if len(values) != grid.ndim:
        raise ValueError(f"{what} needs {grid.ndim} entries (one per axis), got {len(values)}")


def half_space(grid: Grid, normal: Sequence[float], point: Sequence[float]) -> np.ndarray:
    """Everything on the far side of a plane through `point`, sampled on `grid`.

    The plan's "half-plane" (§4.1) in its N-D form: a half-plane in 2D, a
    half-space in 3D. `normal` points **out of** the material, matching the
    outward `grad(phi)` convention of every signed-distance field here, so

        phi(x) = dot(normal_hat, x - point)

    is exact everywhere — and where the plane passes through grid points, the
    sampled zero crossing lies exactly on them.
    """
    _check_length(grid, normal, "normal")
    _check_length(grid, point, "point")
    direction = np.asarray(normal, dtype=np.float64)
    length = float(np.linalg.norm(direction))
    if not math.isfinite(length) or length == 0.0:
        raise ValueError(f"normal must be a non-zero finite vector, got {tuple(normal)}")
    direction = direction / length
    origin = np.asarray(point, dtype=np.float64)

    mesh = grid.mesh()
    phi = np.zeros(grid.shape, dtype=np.float64)
    for axis in range(grid.ndim):
        phi = phi + direction[axis] * (mesh[axis] - origin[axis])
    return phi.astype(PHI_DTYPE)


def box(
    grid: Grid,
    lower: Sequence[float | None],
    upper: Sequence[float | None],
) -> np.ndarray:
    """An axis-aligned box, sampled on `grid`; `None` means unbounded on that side.

    The exact signed distance of a box: the Euclidean distance to the surface
    outside, and the distance to the nearest face inside. Unbounded sides turn
    the box into a slab or half-space, which is what stack constructors need.
    """
    _check_length(grid, lower, "lower")
    _check_length(grid, upper, "upper")
    lo = [-np.inf if v is None else float(v) for v in lower]
    hi = [np.inf if v is None else float(v) for v in upper]
    if all(not math.isfinite(a) and not math.isfinite(b) for a, b in zip(lo, hi)):
        raise ValueError("box needs at least one finite bound")
    for axis, (a, b) in enumerate(zip(lo, hi)):
        if a > b:
            raise ValueError(f"box bounds inverted on axis {grid.axes[axis]!r}: {a} > {b}")

    mesh = grid.mesh()
    outside_sq = np.zeros(grid.shape, dtype=np.float64)
    inside = np.full(grid.shape, -np.inf, dtype=np.float64)
    for axis in range(grid.ndim):
        # q > 0 outside the slab of this axis, q < 0 inside it.
        q = np.maximum(lo[axis] - mesh[axis], mesh[axis] - hi[axis])
        outside_sq = outside_sq + np.maximum(q, 0.0) ** 2
        inside = np.maximum(inside, q)
    phi = np.sqrt(outside_sq) + np.minimum(inside, 0.0)
    return phi.astype(PHI_DTYPE)


def rounded_box(
    grid: Grid,
    lower: Sequence[float | None],
    upper: Sequence[float | None],
    radius: float,
) -> np.ndarray:
    """A box with corners rounded by `radius` nm, sampled on `grid`.

    Built as the exact offset of the box shrunk by `radius` — still an exact
    signed-distance field, and the primitive for realistic (non-ideal) corners.
    """
    radius = float(radius)
    if not math.isfinite(radius) or radius < 0.0:
        raise ValueError(f"radius must be a non-negative finite length, got {radius}")
    if radius == 0.0:
        return box(grid, lower, upper)
    _check_length(grid, lower, "lower")
    _check_length(grid, upper, "upper")

    shrunk_lower: list[float | None] = []
    shrunk_upper: list[float | None] = []
    for axis, (a, b) in enumerate(zip(lower, upper)):
        if a is not None and b is not None and float(b) - float(a) < 2.0 * radius:
            raise ValueError(
                f"radius {radius} does not fit into axis {grid.axes[axis]!r} "
                f"of width {float(b) - float(a)}"
            )
        shrunk_lower.append(None if a is None else float(a) + radius)
        shrunk_upper.append(None if b is None else float(b) - radius)
    return csg.offset(box(grid, shrunk_lower, shrunk_upper), radius)


def ball(grid: Grid, center: Sequence[float], radius: float) -> np.ndarray:
    """A ball of `radius` nm around `center` (a disk in 2D), sampled on `grid`.

    Exact everywhere; the primitive behind seeded particles and roughness.
    """
    _check_length(grid, center, "center")
    radius = float(radius)
    if not math.isfinite(radius) or radius <= 0.0:
        raise ValueError(f"radius must be a positive finite length, got {radius}")

    mesh = grid.mesh()
    distance_sq = np.zeros(grid.shape, dtype=np.float64)
    for axis in range(grid.ndim):
        distance_sq = distance_sq + (mesh[axis] - float(center[axis])) ** 2
    return (np.sqrt(distance_sq) - radius).astype(PHI_DTYPE)


def add_material(
    structure: Structure,
    material: MaterialId,
    phi: np.ndarray,
    *,
    carve: bool = True,
) -> Structure:
    """Place a sampled constructor field as `material`, returning a new `Structure`.

    With `carve=True` (the default) the new region is intersected with the empty
    space of the **other** materials, so material interiors stay pairwise
    disjoint by construction (plan §3.2) — occupancy already there wins. If
    `material` is already present, the new region is unioned onto it, which is
    how one material is built from several primitives.

    `carve=False` is for callers that have already established disjointness
    themselves; nothing here then guards it.
    """
    region = structure.grid.as_field(phi, dtype=PHI_DTYPE)
    if carve:
        others = [p for m, p in structure.phi.items() if m != material]
        if others:
            region = csg.difference(region, csg.union(*others))
    existing = structure.phi.get(material)
    if existing is not None:
        region = csg.union(existing, region)
    return structure.with_material(material, region)
