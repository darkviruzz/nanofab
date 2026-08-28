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
from nanofab_v3.kernel import flux, gate, motion, predicates
from nanofab_v3.processes import lithography

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


# -- M3: what the predicates and the reachability gate add -------------------


def test_connectivity_costs_a_fraction_of_a_motion_sub_step(small_grid: Grid) -> None:
    """Plan §4.4's queries are cheap enough to run every few sub-steps.

    The M3 handoff's budget rests on this: "connectivity is nearly free, so a
    reachability gate rebuilt every few sub-steps costs less than the flux does".
    Measured at the plan's reference grid (540x1200 at 1 nm): `label_region`
    2.7 ms, `reachable_empty` 4.9 ms, `supported` 3.6 ms, `enclosed_voids`
    11.5 ms — against ~50 ms for one complete advection sub-step (§17.7).

    Asserted here as a ratio on a small grid, for the reason the file's own
    docstring gives: a wall time would be a statement about this machine.
    """
    structure = ctor.add_material(
        Structure(small_grid),
        "silicon",
        ctor.half_space(small_grid, normal=(1.0, 0.0), point=(100.0, 0.0)),
    )
    rates = motion.SurfaceRates({"silicon": 2.0})

    started = time.perf_counter()
    motion.advect_front(structure, rates, 0.2)
    sub_step = time.perf_counter() - started

    started = time.perf_counter()
    for _ in range(4):
        predicates.reachable_empty(small_grid, structure.solid_phi)
        predicates.supported(structure)
        predicates.enclosed_voids(structure)
    queries = (time.perf_counter() - started) / 4.0

    assert queries < sub_step, f"connectivity cost {queries / sub_step:.1f} sub-steps"


def test_gating_a_directional_process_is_paid_for_by_the_flux(small_grid: Grid) -> None:
    """The gate rides the flux's rebuild cadence, so it costs next to nothing.

    `motion._FLUX_REFRESH` refreshes every factor of a `ProductFlux` on the same
    sub-steps, and both answer the same question — "where are the walls". Measured
    at the reference grid: a 4 nm RIE costs 1.28 s gated and 1.28 s ungated, i.e.
    the difference is below the noise; a heavy 60 s ion-beam etch costs 9.9 s
    gated against 9.0 s ungated, **+10 %**.

    Windowing the collar is what bought that: the gate rebuild went from 48 ms to
    20 ms at the reference grid when its distance transform stopped running over
    the headroom and the bulk of the wafer (`predicates._front_window`).
    """
    structure = ctor.add_material(
        Structure(small_grid),
        "silicon",
        ctor.half_space(small_grid, normal=(1.0, 0.0), point=(100.0, 0.0)),
    )
    rates = motion.SurfaceRates({"silicon": 2.0})
    model = flux.reactive_ion_etch(chemical_fraction=0.2)

    started = time.perf_counter()
    motion.advect_front(structure, rates, 2.0, flux=model)
    ungated = time.perf_counter() - started

    started = time.perf_counter()
    motion.advect_front(
        structure, rates, 2.0, flux=motion.gated(model, predicates.ReachableFront())
    )
    gated = time.perf_counter() - started

    assert gated < 2.0 * ungated, f"the gate cost {gated / ungated:.1f}x the flux"


def test_the_ideal_tier_costs_less_than_one_advection(small_grid: Grid) -> None:
    """A region operation is a set operation: no sub-stepping, no CFL, no time.

    That is the whole reason plan §3.3's ideal tier exists as a separate *kind* of
    process rather than as a flag. Measured at the reference grid: the complete
    spin-coat + ideal exposure + ideal development sequence is 0.30 s and an ideal
    lift-off 0.19 s, against 0.74 s for a single 4 nm directional deposition.
    """
    structure = ctor.add_material(
        Structure(small_grid),
        "silicon",
        ctor.half_space(small_grid, normal=(1.0, 0.0), point=(60.0, 0.0)),
    )
    coated = lithography.spin_coat(structure, "resist", thickness=40.0)
    exposed = lithography.expose_ideal(
        coated, "resist", lithography.windows(small_grid, [(60.0, 140.0)])
    )

    started = time.perf_counter()
    lithography.develop_ideal(exposed, "resist")
    ideal = time.perf_counter() - started

    started = time.perf_counter()
    motion.advect_front(coated, motion.SurfaceRates({"resist": 2.0}), 2.0)
    advection = time.perf_counter() - started

    assert ideal < advection, f"the ideal tier cost {ideal / advection:.1f} advections"
