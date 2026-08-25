"""Narrow-band reinitialisation — plan §4.2.

Two things have to hold at once, and they pull against each other: the field must
come back to `|grad(phi)| ~ 1`, and the zero level must **not move** while it
does. A scheme that only did the first would walk the interface a fraction of a
cell every pass, and with reinitialisation running many times per chain step that
is exactly the silent drift the commit gate exists to catch.
"""

from __future__ import annotations

import numpy as np
import pytest

from nanofab_v3 import Grid
from nanofab_v3.kernel import constructors as ctor
from nanofab_v3.kernel import csg, invariants, measures, reinit


@pytest.fixture
def disk_grid() -> Grid:
    return Grid(origin=(-100.0, -100.0), spacing=1.0, shape=(201, 201), axes=("y", "x"))


def test_an_exact_field_is_a_fixed_point(disk_grid: Grid) -> None:
    """Renormalising a field that is already a distance function changes nothing."""
    plane = ctor.half_space(disk_grid, normal=(0.6, 0.8), point=(0.0, 0.0))

    outcome = reinit.reinitialise(disk_grid, plane)

    assert np.array_equal(outcome.phi, plane)
    assert outcome.displacement == 0.0


def test_a_steepened_field_is_brought_back(disk_grid: Grid) -> None:
    """Twice the slope everywhere — the interface stays, the gradient recovers."""
    exact = ctor.ball(disk_grid, center=(0.0, 0.0), radius=50.0)
    steep = (exact * 2.0).astype(np.float32)

    outcome = reinit.reinitialise(disk_grid, steep)

    assert outcome.gradient_error_before == pytest.approx(1.0, abs=0.01)
    assert outcome.gradient_error_after < 0.15
    assert outcome.displacement < 0.05  # nm: the zero level barely moved


def test_a_flattened_field_is_brought_back(disk_grid: Grid) -> None:
    exact = ctor.ball(disk_grid, center=(0.0, 0.0), radius=50.0)
    flat = (exact * 0.5).astype(np.float32)

    outcome = reinit.reinitialise(disk_grid, flat)

    assert outcome.gradient_error_after < 0.15
    assert outcome.displacement < 0.05


def test_the_interface_stays_put_over_many_passes(disk_grid: Grid) -> None:
    """Repeated renormalisation must not walk the front — the drift risk of §15.

    It does not walk it *away*: the residual is curvature, not accumulation.
    The sub-cell distance `phi / |grad(phi)|` is a first-order estimate, so on a
    curved front each pass biases outward by a small fraction of a cell — flat
    fronts are a fixed point exactly. Bounded, measured, and reported per commit
    is the contract; zero is not on offer.
    """
    phi = ctor.ball(disk_grid, center=(0.0, 0.0), radius=40.0)
    before = measures.enclosed_measure(disk_grid, phi)
    passes = 20
    displacements = []

    for _ in range(passes):
        outcome = reinit.reinitialise(disk_grid, phi)
        phi = outcome.phi
        displacements.append(outcome.displacement)

    after = measures.enclosed_measure(disk_grid, phi)
    assert abs(after - before) / before < 0.01  # one percent over 20 passes
    assert max(displacements) < 0.01 * disk_grid.spacing  # a hundredth of a cell each


def test_a_field_without_a_zero_level_is_left_alone(disk_grid: Grid) -> None:
    empty = disk_grid.full(5.0)

    outcome = reinit.reinitialise(disk_grid, empty)

    assert outcome.sweeps == 0
    assert np.array_equal(outcome.phi, empty)


def test_the_band_reaches_values_that_lie_about_their_distance(disk_grid: Grid) -> None:
    """A small value far from any interface is a lie, and gets corrected.

    This is the shape a clipped field leaves behind where another material's
    surface was nearer, and the shape of a buried seam between two touching
    materials. A band read off `|phi|` alone would keep such a cell; a band grown
    from the interface alone would never reach it. Both criteria are needed.
    """
    phi = ctor.ball(disk_grid, center=(0.0, 0.0), radius=50.0).copy()
    lie = (slice(10, 15), slice(10, 15))  # far outside the disk, ~65 nm away
    assert np.all(phi[lie] > 60.0)
    phi[lie] = 2.0  # ... but claiming the surface is two cells away

    outcome = reinit.reinitialise(disk_grid, phi)

    # The sign never changes here, so this is a value error and not a second
    # interface: one pass walks it back by at most `sweeps * dtau`, towards the
    # truth rather than all the way to it.
    assert np.all(outcome.phi[lie] > 5.0)


def test_reinit_reports_what_it_moved(disk_grid: Grid) -> None:
    """The gate stores these numbers; a silent renormalisation is not allowed."""
    ring = csg.difference(
        ctor.ball(disk_grid, center=(0.0, 0.0), radius=50.0),
        ctor.ball(disk_grid, center=(0.0, 0.0), radius=20.0),
    )

    outcome = reinit.reinitialise(disk_grid, (ring * 1.5).astype(np.float32))

    assert outcome.sweeps > 0
    assert outcome.measure_moved >= 0.0
    assert outcome.displacement == pytest.approx(
        outcome.measure_moved / measures.front_integral(disk_grid, (ring * 1.5).astype(np.float32)),
        rel=1e-6,
    )


def test_the_policy_scales_with_the_grid(disk_grid: Grid) -> None:
    fine = Grid(origin=(0.0, 0.0), spacing=0.25, shape=(40, 40), axes=("y", "x"))
    policy = reinit.ReinitPolicy()

    assert policy.band_width(disk_grid) == 5.0
    assert policy.band_width(fine) == 1.25
    assert policy.sweep_count(disk_grid) == 10
    assert reinit.ReinitPolicy(band=8.0, iterations=3).sweep_count(disk_grid) == 3


def test_reinitialisation_is_n_d_generic() -> None:
    """Nothing in the scheme knows how many axes there are."""
    grid = Grid(origin=(0.0, 0.0, 0.0), spacing=1.0, shape=(30, 30, 30), axes=("z", "y", "x"))
    sphere = (ctor.ball(grid, center=(15.0, 15.0, 15.0), radius=8.0) * 2.0).astype(np.float32)

    outcome = reinit.reinitialise(grid, sphere)

    assert outcome.gradient_error_after < outcome.gradient_error_before
    assert invariants.band_gradient_error(grid, outcome.phi, quantile=0.99) < 0.2
