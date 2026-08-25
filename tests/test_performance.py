"""Performance floors — plan §13, layer 4, and the point of the whole rewrite.

ADR-0001 F3 measured v1 iterating an isotropic etch 60 times: the vertex count
grew from 58 to 2602, per-step cost from ~0.02 s to ~3.7 s (about 200x), and at
step 50 the shape transiently fell apart into eight fragments. That was not an
implementation bug — it was the representation, and this is the test that says
the representation changed.

On a grid the cost of a step is set by the grid, not by the history: a step is
the same number of array operations on the same number of cells whether it is
the first or the sixtieth. The assertion is therefore a *ratio*, not a wall
time, so it stays meaningful on a machine slower or faster than this one.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from nanofab_v3 import Grid, Structure
from nanofab_v3.kernel import constructors as ctor
from nanofab_v3.kernel import gate, motion

CHAIN_LENGTH = 60


@pytest.fixture
def small_grid() -> Grid:
    """Small enough for a 60-step chain in a test run, at the default 1 nm/cell."""
    return Grid(origin=(0.0, 0.0), spacing=1.0, shape=(120, 200), axes=("y", "x"))


def _chain_step(structure: Structure, seconds: float) -> Structure:
    """One user-visible step: move the front, then commit — sub-steps invisible."""
    outcome = motion.advect_front(structure, motion.SurfaceRates({"silicon": 2.0}), seconds)
    return gate.commit(outcome.structure, parent=structure, swept=outcome.swept).structure


def test_per_step_cost_is_flat_across_a_sixty_step_chain(small_grid: Grid) -> None:
    """The cost of step 60 is the cost of step 1 — v1's blow-up cannot occur here."""
    structure = ctor.add_material(
        Structure(small_grid),
        "silicon",
        ctor.half_space(small_grid, normal=(1.0, 0.0), point=(100.0, 0.0)),
    )
    timings = []

    for _ in range(CHAIN_LENGTH):
        started = time.perf_counter()
        structure = _chain_step(structure, 0.2)
        timings.append(time.perf_counter() - started)

    first_ten = float(np.median(timings[:10]))
    last_ten = float(np.median(timings[-10:]))
    assert last_ten < 2.0 * first_ten, f"per-step cost grew {last_ten / first_ten:.1f}x"
    # 60 steps of 0.2 s at 2 nm/s remove 24 nm; the front is still in the domain.
    assert structure.inside("silicon").any()


def test_state_size_is_constant_across_a_chain(small_grid: Grid) -> None:
    """No representation grows with history: same arrays, same dtype, same cells.

    This is the structural half of the argument the timing test makes
    statistically — v1 accumulated ~43 vertices per step with nothing to bound it.
    """
    structure = ctor.add_material(
        Structure(small_grid),
        "silicon",
        ctor.half_space(small_grid, normal=(1.0, 0.0), point=(100.0, 0.0)),
    )
    footprint = structure.phi_of("silicon").nbytes

    for _ in range(20):
        structure = _chain_step(structure, 0.2)

    assert structure.materials == ("silicon",)
    assert structure.phi_of("silicon").nbytes == footprint
    assert structure.phi_of("silicon").dtype == np.float32


def test_a_split_dose_costs_what_the_work_costs(small_grid: Grid) -> None:
    """Ten steps of 1 s cost about what one step of 10 s costs, plus ten gates.

    v1 inverted this: 20 x 0.2 s took 54 s where 1 x 4.0 s took 0.01 s, because
    each step paid for the mess the previous one left. Here the sub-step count is
    the same either way — that is what makes "etch, inspect, etch again" usable.
    """
    structure = ctor.add_material(
        Structure(small_grid),
        "silicon",
        ctor.half_space(small_grid, normal=(1.0, 0.0), point=(100.0, 0.0)),
    )
    rates = motion.SurfaceRates({"silicon": 2.0})

    started = time.perf_counter()
    motion.advect_front(structure, rates, 10.0)
    one_shot = time.perf_counter() - started

    started = time.perf_counter()
    split = structure
    for _ in range(10):
        split = motion.advect_front(split, rates, 1.0).structure
    ten_steps = time.perf_counter() - started

    assert ten_steps < 3.0 * one_shot, f"splitting cost {ten_steps / one_shot:.1f}x"
