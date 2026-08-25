"""Cheap field invariants on a `Structure` (plan §3.2, §4.5).

The plan lists three field invariants: sign correct everywhere, `|grad(phi)| ~ 1`
within a narrow band around each zero level, and pairwise-disjoint material
interiors ("guaranteed by construction, verified cheaply"). They are measurements,
not assertions — each function returns a number or a report and lets the caller
decide. M0's kernel-invariant tests are the first caller; the commit gate of
milestone M1 (plan §4.5) is the next one and reuses exactly these functions.

All of them are N-D generic.
"""

from __future__ import annotations

import numpy as np

from nanofab_v3.materials import MaterialId
from nanofab_v3.model.grid import Grid
from nanofab_v3.model.structure import Structure


def overlap_depth(phi_a: np.ndarray, phi_b: np.ndarray) -> float:
    """How deep two regions overlap, in nm; `0.0` when their interiors are disjoint.

    The depth of the worst cell that is inside both regions — `min(-phi_a, -phi_b)`
    at its maximum, clipped at zero.
    """
    both_inside = np.minimum(-np.asarray(phi_a), -np.asarray(phi_b))
    return float(max(0.0, np.max(both_inside, initial=0.0)))


def pairwise_overlap(structure: Structure) -> dict[tuple[MaterialId, MaterialId], int]:
    """Cells shared by two material interiors, per pair; empty when disjoint.

    Constructors carve new material against the existing solid (plan §3.2), so a
    non-empty result means an invariant was broken, not that a scene is unusual.
    """
    materials = structure.materials
    report: dict[tuple[MaterialId, MaterialId], int] = {}
    for index, first in enumerate(materials):
        inside_first = structure.inside(first)
        for second in materials[index + 1 :]:
            shared = int(np.count_nonzero(inside_first & structure.inside(second)))
            if shared:
                report[(first, second)] = shared
    return report


def max_overlap_depth(structure: Structure) -> float:
    """The deepest interior overlap over all material pairs, in nm (`0.0` = disjoint)."""
    materials = structure.materials
    worst = 0.0
    for index, first in enumerate(materials):
        for second in materials[index + 1 :]:
            worst = max(worst, overlap_depth(structure.phi_of(first), structure.phi_of(second)))
    return worst


def gradient_magnitude(grid: Grid, phi: np.ndarray) -> np.ndarray:
    """`|grad(phi)|` per cell, central differences on the grid spacing."""
    values = np.asarray(phi, dtype=np.float64)
    gradients = np.gradient(values, grid.spacing, edge_order=1)
    if grid.ndim == 1:
        gradients = [gradients]
    return np.sqrt(sum(g**2 for g in gradients))


def band_gradient_error(
    grid: Grid, phi: np.ndarray, band: float | None = None, quantile: float = 1.0
) -> float:
    """Deviation of `|grad(phi)|` from 1 inside a narrow band around `phi = 0`.

    The band defaults to two cells. A true signed-distance field scores ~0; the
    number grows as set operations and advection distort the distance property,
    which is the trigger the reinitialisation policy (plan §4.2) runs on.

    `quantile` defaults to 1.0, the worst cell. A **concave crease** — where two
    surfaces meet, e.g. the union of two overlapping disks — is a point where a
    correct distance field is genuinely not differentiable, so the worst cell
    there never converges to 1 no matter how well the field is normalised.
    Callers that judge a whole field (the distortion trigger, the commit gate)
    therefore read a high quantile instead, which sees real distortion but not
    the handful of crease cells.
    """
    width = 2.0 * grid.spacing if band is None else float(band)
    values = np.asarray(phi, dtype=np.float64)
    in_band = np.abs(values) <= width
    if not np.any(in_band):
        return 0.0
    deviation = np.abs(gradient_magnitude(grid, values)[in_band] - 1.0)
    if quantile >= 1.0:
        return float(np.max(deviation))
    return float(np.quantile(deviation, quantile))


def every_face(grid: Grid) -> tuple[tuple[str, str], ...]:
    """Every domain face as `(axis_name, "min" | "max")`."""
    return tuple((axis, side) for axis in grid.axes for side in ("min", "max"))


def boundary_contact(structure: Structure) -> tuple[tuple[str, str], ...]:
    """The domain faces the solid touches, as `(axis_name, "min" | "max")` pairs.

    The raw measurement behind the headroom guard (plan §3.1). It states no
    policy: a substrate resting on the bottom face is normal ("solid continues"
    by boundary condition), a front reaching a lateral or top face is not — which
    face is acceptable is M1's commit-gate decision, not this function's.
    """
    solid = structure.solid_mask
    grid = structure.grid
    faces: list[tuple[str, str]] = []
    for axis in range(grid.ndim):
        if bool(np.any(np.take(solid, 0, axis=axis))):
            faces.append((grid.axes[axis], "min"))
        if bool(np.any(np.take(solid, grid.shape[axis] - 1, axis=axis))):
            faces.append((grid.axes[axis], "max"))
    return tuple(faces)
