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
from scipy import ndimage

from nanofab_v3.kernel import stencil
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


_TURNING_SLOPE = 0.5
"""How steep the steeper side of a reversal must be before it counts as one.

Low enough to catch a medial axis whose two sides are lopsided — inside a film
only a few cells thick the axis rarely lands on a cell centre, so one side can be
almost flat while the other falls a full cell. High enough to ignore an axis that
merely runs across the gradient, where both differences are curvature-sized
(`h^2 / 2R`, a hundredth of a cell on anything this model draws) and their sign
is noise.
"""


def turning_points(grid: Grid, phi: np.ndarray) -> np.ndarray:
    """Cells where `phi` reverses direction along an axis — a **medial axis**.

    A correct distance field has one: halfway through a slab, the distance to the
    surface above stops growing and the distance to the surface below takes over,
    so the field has a genuine local extremum there. `|grad(phi)|` is 0 at such a
    cell however perfectly the field is normalised — because it *is* normalised,
    and the derivative simply does not exist.

    That matters more than it sounds. The medial axis of a film sits half its
    thickness in, so for any film thinner than twice the invariant band the axis
    lies **inside the band** — and a 2 nm ALD film is the most ordinary object in
    this domain. The two one-sided differences there point in opposite
    directions, which is what this detects; `_TURNING_SLOPE` asks the steeper
    of them to be a real slope, which keeps out the axes that merely run
    across the gradient, where both differences are ~0 and their sign is noise.

    The result is **dilated by one cell**, because a central difference reads a
    three-cell stencil and is therefore contaminated one cell away from any point
    where the derivative does not exist — not just on it.

    Not to be confused with a **concave crease**, where the field is flat on one
    side rather than reversed. That one is not detected here (the same test
    cannot tell it from real distortion) and is handled by the gate's tolerance —
    see `kernel.gate.GateTolerances.band_gradient_error`.
    """
    values = np.asarray(phi, dtype=np.float64)
    turning = np.zeros(values.shape, dtype=bool)
    for backward, forward in stencil.one_sided_differences(values, grid.spacing):
        reversed_here = np.signbit(backward) != np.signbit(forward)
        steep = np.maximum(np.abs(backward), np.abs(forward)) > _TURNING_SLOPE
        turning |= reversed_here & steep
    return ndimage.binary_dilation(turning, ndimage.generate_binary_structure(values.ndim, 1))


def _bounding_box(
    mask: np.ndarray, shape: tuple[int, ...], margin: int
) -> tuple[slice, ...]:
    """The box `mask` occupies, widened by `margin` cells and clipped to `shape`."""
    occupied = np.argwhere(mask)
    low = occupied.min(axis=0) - margin
    high = occupied.max(axis=0) + margin + 1
    return tuple(
        slice(max(0, int(a)), min(int(size), int(b))) for a, b, size in zip(low, high, shape)
    )


def band_gradient_error(
    grid: Grid, phi: np.ndarray, band: float | None = None, quantile: float = 1.0
) -> float:
    """Deviation of `|grad(phi)|` from 1 inside a narrow band around `phi = 0`.

    The band defaults to two cells. A true signed-distance field scores ~0; the
    number grows as set operations and advection distort the distance property,
    which is the trigger the reinitialisation policy (plan §4.2) runs on.

    Two sets where a *correct* distance field is not differentiable are kept from
    dominating the answer, because on both no amount of renormalisation moves the
    number:

    - **medial axes** are removed from the band outright (`turning_points`);
      without that, every film thinner than twice the band fails on its own
      centre line, which says nothing about the solver;
    - **concave creases** stay in — at a right angle they read exactly
      `1 - 1/sqrt(2) = 0.293`, which is why `quantile` exists and why the gate's
      tolerance sits above that value.

    `quantile` defaults to 1.0, the worst cell — right for constructor-exactness
    tests, which run on smooth fields. Callers judging a whole scene (the
    distortion trigger, the commit gate) read a high quantile instead.
    """
    width = 2.0 * grid.spacing if band is None else float(band)
    values = np.asarray(phi, dtype=np.float64)
    near = np.abs(values) <= width
    if not np.any(near):
        return 0.0
    # Both passes below are stencils, so they cost the domain while the question
    # is about a curve. Cropping to the band's bounding box plus the two cells
    # the stencils reach is what keeps the commit gate proportional to the front.
    window = _bounding_box(near, values.shape, margin=2)
    values = values[window]
    in_band = near[window] & ~turning_points(grid, values)
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
