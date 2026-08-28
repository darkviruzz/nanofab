"""Measures of a region and of its front, taken from the field itself.

Counting cells is only accurate to the perimeter times the cell size, which is
far too coarse for the commit gate's balance check (plan §4.5.4). The standard
level-set answer is used instead: a smoothed Heaviside `H_eps` integrates the
enclosed measure sub-cell accurately, and its derivative — the smoothed Dirac
`delta_eps` — turns a volume sum into an integral **along the front**:

    measure(region) = sum_cells H_eps(-phi) * cell_measure
    integral_front(f) = sum_cells f * delta_eps(phi) * cell_measure

Both are N-D generic and assume `|grad(phi)| ~ 1` near the zero level, which is
what the reinitialisation of plan §4.2 maintains.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from nanofab_v3.model.grid import Grid

if TYPE_CHECKING:  # pragma: no cover - import cycle only exists for type checkers
    from nanofab_v3.model.structure import Structure


def smoothed_heaviside(phi: np.ndarray, epsilon: float) -> np.ndarray:
    """`H_eps(phi)`: 0 well below zero, 1 well above, smooth across `2*epsilon`."""
    values = np.asarray(phi, dtype=np.float64)
    scaled = np.clip(values / epsilon, -1.0, 1.0)
    return 0.5 * (1.0 + scaled + np.sin(np.pi * scaled) / np.pi)


def smoothed_dirac(phi: np.ndarray, epsilon: float) -> np.ndarray:
    """`delta_eps(phi)`: the derivative of `smoothed_heaviside`, zero outside the band."""
    values = np.asarray(phi, dtype=np.float64)
    inside_band = np.abs(values) < epsilon
    return np.where(inside_band, (1.0 + np.cos(np.pi * values / epsilon)) / (2.0 * epsilon), 0.0)


def _band_width(grid: Grid, epsilon: float | None) -> float:
    return grid.spacing if epsilon is None else float(epsilon)


def enclosed_measure(grid: Grid, phi: np.ndarray, epsilon: float | None = None) -> float:
    """Area (2D) / volume (3D) of `phi < 0`, in nm^ndim, sub-cell accurate.

    The quantity the balance check compares against, and the honest way to ask
    "how much material is there" — cell counting quantises at the perimeter.

    `H_eps` is 1 well inside and 0 well outside, so only the band around the zero
    level needs evaluating; the rest is a cell count. That is what keeps this
    affordable to call per material on every commit.
    """
    values = np.asarray(phi)
    width = _band_width(grid, epsilon)
    band = np.abs(values) < width
    filled = float(np.count_nonzero(values <= -width))
    if band.any():
        filled += float(np.sum(smoothed_heaviside(-values[band], width)))
    return filled * grid.cell_measure


def solid_measure(structure: "Structure", epsilon: float | None = None) -> float:
    """How much material a `Structure` holds, in nm^ndim.

    Summed **per material** rather than taken from `solid_phi`, because where two
    materials touch, the union field is exactly zero along their shared interface
    and a single `H_eps` evaluation would count those cells as half empty. Since
    material interiors are disjoint, adding their measures is exact: at a shared
    interface each side contributes half a cell, which is the whole cell.
    """
    return sum(
        enclosed_measure(structure.grid, structure.phi_of(material), epsilon)
        for material in structure.materials
    )


def front_integral(
    grid: Grid, phi: np.ndarray, values: np.ndarray | float = 1.0, epsilon: float | None = None
) -> float:
    """Integral of `values` along the zero level of `phi`, in nm^(ndim-1) * unit.

    With `values = 1` this is the front's length (2D) / area (3D); with a speed
    field it is `∫ F dS`, the rate at which the enclosed measure changes — which
    is exactly what the balance check integrates over time.

    `delta_eps` is zero outside a band one cell wide, so the sum runs over the
    front's own cells rather than over the domain — the motion solver evaluates
    this once per sub-step, and a full-field pass there would cost more than the
    advection it is measuring.
    """
    field = np.asarray(phi)
    width = _band_width(grid, epsilon)
    band = np.abs(field) < width
    if not band.any():
        return 0.0
    dirac = smoothed_dirac(field[band], width)
    weights = values if np.isscalar(values) else np.asarray(values)[band]
    return float(np.sum(weights * dirac)) * grid.cell_measure


def surface_normals(grid: Grid, phi: np.ndarray) -> np.ndarray:
    """Outward unit normals `grad(phi) / |grad(phi)|`, shape `(ndim, *grid.shape)`.

    The kernel's answer to "which way does this piece of surface face" — used by
    the inspect overlays of plan §10 and, from M2 on, by the angle-dependent
    yield of the flux solver. Degenerate cells (no gradient) get a zero vector.
    """
    values = np.asarray(phi, dtype=np.float64)
    gradients = np.gradient(values, grid.spacing, edge_order=1)
    if grid.ndim == 1:
        gradients = [gradients]
    stacked = np.stack(gradients)
    magnitude = np.sqrt(np.sum(stacked**2, axis=0))
    return np.divide(stacked, magnitude, out=np.zeros_like(stacked), where=magnitude > 0.0)
