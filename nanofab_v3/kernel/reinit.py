"""Narrow-band reinitialisation of a signed-distance field (plan §4.2).

Under advection `phi` stops being a distance function: `|grad(phi)| ~ 1` drifts,
and every exact fast path (offsetting, the balance check's front integral)
depends on it. The repair is the reinitialisation equation

    phi_tau + sign(phi0) * (|grad(phi)| - 1) = 0

run to steady state, which drives `|grad(phi)| -> 1` while leaving the zero level
where it was. Two properties of the plan are honoured literally:

- **Narrow band only.** A full-field solve costs what plan §4.2 measured
  (34 ms at 1 nm, 1016 ms at 0.25 nm); the iteration here runs on the band
  around the zero level and on its bounding box, so the cost follows the front,
  not the domain.
- **Interface preserving.** Cells adjacent to the interface use the
  Russo-Smereka sub-cell update: their target is the sub-cell distance `D`
  computed from the *original* field, so the zero level cannot drift a cell per
  reinitialisation the way a naive upwind scheme lets it.

The residual move is small but not zero, so it is measured and reported
(`ReinitOutcome`) rather than assumed away — the commit gate (plan §4.5) puts it
on the revision.

Policy: the trigger is sub-step count and distortion (`ReinitPolicy`), **never**
a user step boundary — otherwise `3 x 10 s` and `1 x 30 s` would diverge. The
commit gate additionally normalises once per chain step so the fast paths can
rely on the band invariant; that pass is interface-preserving and reported.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from nanofab_v3.kernel import invariants, measures, stencil
from nanofab_v3.model.grid import PHI_DTYPE, Grid

_MARGIN_CELLS = 2
"""Cells kept around the band's bounding box so the stencil reads real values."""


@dataclass(frozen=True)
class ReinitPolicy:
    """When and how far to renormalise a field.

    Attributes:
        band: Half-width of the narrow band in nm; `None` means 5 cells.
        iterations: Sweeps to run; `None` means twice the band width in cells,
            enough for information to cross the band at `dtau = 0.4 * spacing`.
        every_sub_steps: How often the motion solver checks the distortion.
        max_gradient_error: The distortion trigger — a band gradient error above
            this value renormalises mid-motion.
    """

    band: float | None = None
    iterations: int | None = None
    every_sub_steps: int = 10
    max_gradient_error: float = 0.25

    def band_width(self, grid: Grid) -> float:
        """The band half-width in nm for this grid."""
        return 5.0 * grid.spacing if self.band is None else float(self.band)

    def sweep_count(self, grid: Grid) -> int:
        """How many sweeps this policy runs on this grid."""
        if self.iterations is not None:
            return int(self.iterations)
        return max(1, int(math.ceil(2.0 * self.band_width(grid) / grid.spacing)))


@dataclass(frozen=True)
class ReinitOutcome:
    """The result of one reinitialisation, with what it cost the interface.

    Attributes:
        phi: The renormalised field.
        displacement: Mean normal shift of the zero level, in nm — the moved
            measure spread over the front. This is the number plan §4.2 asks to
            be reported rather than assumed small.
        measure_moved: Change of the enclosed measure, in nm^ndim.
        gradient_error_before / gradient_error_after: `| |grad(phi)| - 1 |` in the
            two-cell invariant band, i.e. what the fast paths actually rely on.
        sweeps: Sweeps actually run (0 when the field had no zero level).
    """

    phi: np.ndarray
    displacement: float
    measure_moved: float
    gradient_error_before: float
    gradient_error_after: float
    sweeps: int


def _band_slices(band: np.ndarray, shape: tuple[int, ...]) -> tuple[slice, ...] | None:
    """Bounding box of the band, widened by the stencil margin."""
    occupied = np.argwhere(band)
    if occupied.size == 0:
        return None
    low = occupied.min(axis=0)
    high = occupied.max(axis=0)
    return tuple(
        slice(max(0, int(lo) - _MARGIN_CELLS), min(int(n), int(hi) + 1 + _MARGIN_CELLS))
        for lo, hi, n in zip(low, high, shape)
    )


def reinitialise(
    grid: Grid, phi: np.ndarray, policy: ReinitPolicy = ReinitPolicy()
) -> ReinitOutcome:
    """Renormalise `phi` to a signed-distance field in a narrow band around zero."""
    original = grid.as_field(phi, dtype=PHI_DTYPE)
    band_width = policy.band_width(grid)
    error_before = invariants.band_gradient_error(grid, original)

    # The band is **geometric**: the cells within so many cells of the interface,
    # grown from the interface itself rather than read off `|phi|`. A field that
    # needs renormalising is exactly a field whose values cannot be trusted to say
    # how far the zero level is — a value band would then exclude the cells that
    # are furthest off, which are precisely the ones that need repairing.
    at_interface = stencil.has_opposite_sign_neighbour(original)
    if not at_interface.any():
        # No zero level in this field: nothing to normalise against.
        return ReinitOutcome(original, 0.0, 0.0, error_before, error_before, 0)
    band = ndimage.binary_dilation(
        at_interface,
        ndimage.generate_binary_structure(grid.ndim, 1),
        iterations=max(1, int(math.ceil(band_width / grid.spacing))),
    )
    # Plus every cell whose value merely *claims* to be near the zero level. Such
    # a cell is either near it — in which case the geometric band already has it —
    # or it is lying, and a lie of exactly this shape is what a buried seam
    # between two touching materials looks like, and what a clip leaves behind
    # where another material's surface was nearer. Both need correcting.
    band |= np.abs(original) <= band_width
    window = _band_slices(band, grid.shape)
    assert window is not None  # an interface exists, so the band is never empty

    start = original[window]
    values = start.copy()
    band_window = band[window]
    interface = at_interface[window]
    outward = start > 0.0
    # Two-valued sign, zeros counting as inside: `np.sign` would freeze a cell
    # that happens to sample exactly zero, and a buried seam between two touching
    # materials is made of exactly such cells (see `has_opposite_sign_neighbour`).
    sign = np.where(outward, PHI_DTYPE(1.0), PHI_DTYPE(-1.0))

    # Russo-Smereka sub-cell distance of the interface cells, from the *initial*
    # field: `phi0 / |grad(phi0)|` is the first-order distance to the zero level,
    # and it is the target the interface cells relax onto — which is what keeps
    # the zero level in place instead of letting it drift a cell per pass.
    slope = stencil.one_sided_gradient_magnitude(start, grid.spacing)
    sub_cell = start / np.maximum(slope, PHI_DTYPE(1e-6))

    dtau = PHI_DTYPE(0.4 * grid.spacing)
    sweeps = policy.sweep_count(grid)
    for _ in range(sweeps):
        gradient = stencil.godunov_norm(values, grid.spacing, outward)
        relaxed = values - dtau * sign * (gradient - PHI_DTYPE(1.0))
        corrected = values - (dtau / PHI_DTYPE(grid.spacing)) * (
            sign * np.abs(values) - sub_cell
        )
        updated = np.where(interface, corrected, relaxed)
        values = np.where(band_window, updated, values)

    if np.array_equal(values, start):
        # The sweep was a fixed point: the field was already a distance function
        # in its band, so the renormalised field *is* the input. Handing back the
        # input array rather than a bit-identical copy is what lets consecutive
        # revisions share it — `Structure`'s "arrays are shared cheaply between
        # revisions" is otherwise a docstring and not a fact (measured on the S1
        # chain: 6 of 9 consecutive material/revision pairs were bit-identical
        # and none shared an object). Callers already treat these arrays as
        # immutable, which is the contract that makes it safe, and the
        # no-zero-level path above has always returned the input this way.
        return ReinitOutcome(original, 0.0, 0.0, error_before, error_before, sweeps)

    result = original.copy()
    result[window] = values
    measure_moved = abs(
        measures.enclosed_measure(grid, result) - measures.enclosed_measure(grid, original)
    )
    front = measures.front_integral(grid, original)
    displacement = measure_moved / front if front > 0.0 else 0.0
    return ReinitOutcome(
        phi=result,
        displacement=displacement,
        measure_moved=measure_moved,
        gradient_error_before=error_before,
        gradient_error_after=invariants.band_gradient_error(grid, result),
        sweeps=sweeps,
    )
