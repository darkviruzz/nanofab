"""Mechanism tests — plan §13.2, layer 2 of the acceptance pyramid.

These are the measured probes of the design phase turned into standing tests:
scenes small enough to reason about analytically, asserted against the number the
geometry says they must produce. They are the layer that catches a kernel that is
internally consistent but physically wrong.

Two mechanisms live here so far:

- **T-profile ALD** (this file's first half) — conformal growth over a re-entrant
  profile seals an enclosed void at `t >= half the opening`. It needs no flux at
  all, which is what makes it the honest smoke test for the M1 building blocks
  the flux solver is about to be stacked on. From M3 on it carries the second
  half of the mechanism too: once the growth is reachability-gated, the sealed
  void has to **stop shrinking**, which is scenario S3 at its smallest scale.
- **Shadow wedge** (second half) — a directional source behind a mask edge, with
  the shadow boundary asserted against `h * tan(theta)`.

The undercut mechanism (isotropic etch under a mask) lives in `test_motion.py`,
next to the motion it is a property of.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from nanofab_v3 import Grid, Structure
from nanofab_v3.kernel import constructors as ctor
from nanofab_v3.kernel import csg, flux, motion, occurrences
from nanofab_v3.processes import deposition

# -- T-profile ALD: conformal growth seals a re-entrant cavity ----------------


@pytest.fixture
def t_profile() -> Structure:
    """Substrate under a resist with a re-entrant (mushroom) opening.

    A 20 nm mouth through the top of the resist widening into a 60 nm cavity
    below it — the lift-off profile of scenarios S1/S3, and the shape whose
    topology a conformal process changes.

    The void is built as **one** union of two overlapping boxes rather than as two
    abutting ones. Two boxes that share a face leave the difference exactly zero
    along it, and `solid_mask` counts a zero as solid (§17.1), so an abutting
    construction would wall the cavity off from its own mouth before anything is
    deposited at all.
    """
    grid = Grid(origin=(0.0, 0.0), spacing=1.0, shape=(140, 200), axes=("y", "x"))
    structure = ctor.add_material(
        Structure(grid), "silicon", ctor.half_space(grid, normal=(1.0, 0.0), point=(40.0, 0.0))
    )
    slab = ctor.box(grid, lower=(40.0, None), upper=(90.0, None))
    mouth = ctor.box(grid, lower=(30.0, 90.0), upper=(120.0, 110.0))
    cavity = ctor.box(grid, lower=(30.0, 70.0), upper=(80.0, 130.0))
    return ctor.add_material(structure, "resist", csg.difference(slab, csg.union(mouth, cavity)))


def _empty_components(structure: Structure) -> tuple[int, int]:
    """`(components of empty space, cells enclosed by the solid)`.

    "Enclosed" means: not part of a component that reaches the top row of the
    domain. That is plan §4.4's reachability query in miniature — and in M3 it
    becomes the gate a wet process runs behind.
    """
    grid = structure.grid
    labels, count = occurrences.label_region(grid, ~structure.solid_mask)
    open_to_the_top = list(set(np.unique(labels[-1, :])) - {0})
    sealed = (labels > 0) & np.isin(labels, open_to_the_top, invert=True)
    return count, int(np.count_nonzero(sealed))


def test_the_open_profile_starts_with_one_empty_space(t_profile: Structure) -> None:
    """Before anything is deposited, the cavity is reachable through its mouth."""
    assert _empty_components(t_profile) == (1, 0)


def test_conformal_growth_seals_the_cavity_at_half_the_opening(t_profile: Structure) -> None:
    """ALD pinches the 20 nm mouth off at `t = 10 nm` — the plan §13.2 mechanism.

    Both walls of the mouth advance by `t`, so the gap closes when `2t` reaches
    the opening. Nothing in the kernel knows about mouths or cavities: the change
    of topology is `ndimage.label` counting one more component than before.
    """
    still_open = motion.offset_solid(t_profile, 9.0, deposit_material="ald").structure
    just_sealed = motion.offset_solid(t_profile, 10.0, deposit_material="ald").structure

    assert _empty_components(still_open) == (1, 0)
    components, enclosed = _empty_components(just_sealed)
    assert components == 2
    assert enclosed == 741  # the cavity, minus the 10 nm shell grown into it


def test_a_sealed_void_stops_shrinking_once_the_precursor_cannot_reach_it(
    t_profile: Structure,
) -> None:
    """The smallest possible S3: the reachability gate, proving itself.

    Two processes, one technique, one difference (plan §5.4). Both grow the front
    conformally by `t`:

    - `conformal_offset` is the exact **geometric** answer — one array operation,
      dose splitting bit-exact — and it keeps growing inside a cavity it has
      already sealed, because nothing in an offset knows where the precursor came
      from. Measured here: 741 -> 525 -> 261 -> 0 cells. That was M2's behaviour,
      correct for the question it asks and wrong as physics.
    - `atomic_layer_deposition` runs the same growth behind
      `predicates.ReachableFront`. Once the mouth closes, the cavity's own front
      is handed a speed of zero and the void **stops**: 586 cells at t = 13 nm and
      the same 586 at t = 40 nm, three times the dose that closed it geometrically.

    The residual between sealing and freezing is the gate's rebuild interval
    (`motion._FLUX_REFRESH = 5` sub-steps at half a cell each), which is why the
    void loses a few cells between t = 12 and t = 13 and none afterwards. Plan
    §18.1's argument applies unchanged: `K` is a cost knob, and what it costs is
    inside the cell the grid owes anyway.
    """
    geometric = [
        _empty_components(motion.offset_solid(t_profile, t, deposit_material="ald").structure)[1]
        for t in (10.0, 12.0, 15.0, 20.0)
    ]
    gated = [
        _empty_components(
            deposition.atomic_layer_deposition(t_profile, "ald", thickness=t).structure
        )[1]
        for t in (13.0, 15.0, 20.0, 40.0)
    ]

    assert geometric == sorted(geometric, reverse=True)
    assert geometric[-1] == 0  # the void is grown shut
    assert min(gated) > 0  # the gated one never is
    assert len(set(gated)) == 1  # and it does not move at all


def test_the_gated_deposition_still_grows_everywhere_it_can_reach(
    t_profile: Structure,
) -> None:
    """The gate must stop the void without stopping the process.

    The other half of the assertion above, and the one that would catch a gate
    that simply returned zero: on the open surface above the profile the two
    tiers agree cell for cell, because there the reachability multiplier is 1 and
    the motion is the same conformal growth.
    """
    offset = motion.offset_solid(t_profile, 15.0, deposit_material="ald").structure
    gated = deposition.atomic_layer_deposition(t_profile, "ald", thickness=15.0).structure

    for structure in (offset, gated):
        top = int(np.flatnonzero(structure.inside("ald")[:, 10]).max())
        assert top == pytest.approx(104, abs=1)  # resist top at 90 nm, plus 15 nm


def test_a_straight_gap_fills_without_enclosing_anything(t_profile: Structure) -> None:
    """The control case: a gap with no overhang fills from the bottom, seamed.

    Same opening, same deposition — only the re-entrance removed. Nothing is ever
    enclosed, which is what makes the T-profile's void a property of the *shape*
    and not of the process.
    """
    grid = t_profile.grid
    straight = ctor.add_material(
        ctor.add_material(
            Structure(grid), "silicon", ctor.half_space(grid, normal=(1.0, 0.0), point=(40.0, 0.0))
        ),
        "resist",
        csg.difference(
            ctor.box(grid, lower=(40.0, None), upper=(90.0, None)),
            ctor.box(grid, lower=(30.0, 90.0), upper=(120.0, 110.0)),
        ),
    )

    for t in (5.0, 10.0, 15.0, 20.0):
        grown = motion.offset_solid(straight, t, deposit_material="ald").structure
        assert _empty_components(grown) == (1, 0)


# -- shadow wedge: a mask edge against `h * tan(theta)` ----------------------

MASK_EDGE = 120.0
MASK_HEIGHT = 40.0
SURFACE = 60.0


@pytest.fixture
def masked_substrate() -> Structure:
    """A blanket substrate with a 40 nm mask stripe whose left edge is at x = 120.

    The whole shadow-wedge geometry: a source tilted by `theta` towards `+x` is
    occluded by the mask for every surface point within `h * tan(theta)` to the
    left of its edge. Nothing else in the scene can cast a shadow, so the
    analytic answer is exact and the test measures the solver, not the setup.
    """
    grid = Grid(origin=(0.0, 0.0), spacing=1.0, shape=(180, 260), axes=("y", "x"))
    structure = ctor.add_material(
        Structure(grid), "silicon", ctor.half_space(grid, normal=(1.0, 0.0), point=(SURFACE, 0.0))
    )
    return ctor.add_material(
        structure,
        "mask",
        ctor.box(
            grid,
            lower=(SURFACE, MASK_EDGE),
            upper=(SURFACE + MASK_HEIGHT, MASK_EDGE + 60.0),
        ),
    )


def _shadow_edge(arrival: np.ndarray) -> float:
    """Where the arrival on the substrate falls to half, left of the mask, in nm.

    The crossing sits between the last lit cell and the first dark one, so the
    boundary is reported half a cell before the first dark column.
    """
    profile = arrival[int(SURFACE), : int(MASK_EDGE)]
    dark = np.flatnonzero(profile < 0.5 * float(np.median(profile[:40])))
    return float(dark.min()) - 0.5


@pytest.mark.parametrize("degrees", [15.0, 30.0, 45.0, 60.0])
def test_the_shadow_wedge_lands_where_the_geometry_says(
    masked_substrate: Structure, degrees: float
) -> None:
    """The shadow boundary sits at `edge - h * tan(theta)` — plan §13.2.

    The tolerance comes from the geometry, not from hope (plan §17.3): the
    arrival is a per-cell quantity and the march samples a ray at finite steps,
    so a ray that clips the mask corner by less than half a cell of path can miss
    it. Both effects are one cell, and one cell is the accuracy the grid owes.
    Measured here: 0.2 to 0.8 nm at 1 nm/cell, all four angles, with the 60
    degree case casting a 69 nm shadow — so the error is not growing with the
    lever arm, which is the property that actually matters.
    """
    theta = math.radians(degrees)
    outcome = flux.evaporation(angle=theta).on_structure(masked_substrate)

    analytic = MASK_EDGE - MASK_HEIGHT * math.tan(theta)
    assert _shadow_edge(outcome.arrival) == pytest.approx(analytic, abs=1.5)
    assert outcome.unresolved == 0


def test_the_visibility_grid_is_a_speed_knob_and_not_an_accuracy_one(
    masked_substrate: Structure,
) -> None:
    """Coarsening the occupancy must not move the shadow boundary.

    The march steps on a coarsened distance transform but decides hits on the
    fine field, so the coarse grid only sets how many steps a ray takes. Plan
    §4.3 expected this knob to trade accuracy for speed; it does not, and that is
    worth a standing test because it is the fallback plan §15 names first.
    """
    model = flux.evaporation(angle=math.radians(30.0))
    edges = {
        spacing: _shadow_edge(
            flux.FluxModel2D(
                distribution=model.distribution, visibility_spacing=spacing
            ).on_structure(masked_substrate).arrival
        )
        for spacing in (1.0, 2.0, 4.0)
    }

    assert len(set(edges.values())) == 1, edges


def test_an_unobstructed_flat_surface_receives_exactly_one(masked_substrate: Structure) -> None:
    """The normalisation that makes the arrival a multiplier on a blanket rate."""
    arrival = flux.evaporation(angle=math.radians(30.0)).on_structure(masked_substrate).arrival

    assert arrival[int(SURFACE), 40] == pytest.approx(1.0, abs=1e-6)
    assert float(arrival.min()) >= 0.0


def test_a_wider_source_blurs_the_shadow_into_a_penumbra(masked_substrate: Structure) -> None:
    """A lobe has no sharp edge — which is why the shadow is called a *wedge*.

    A point source gives a shadow one cell wide; a source of finite angular width
    gives a transition as wide as the mask height times the spread in angle.
    """
    sharp = flux.evaporation(angle=math.radians(30.0)).on_structure(masked_substrate).arrival
    soft = (
        flux.evaporation(angle=math.radians(30.0), divergence=math.radians(8.0))
        .on_structure(masked_substrate)
        .arrival
    )

    def transition(arrival: np.ndarray) -> int:
        profile = arrival[int(SURFACE), : int(MASK_EDGE)]
        open_field = float(np.median(profile[:40]))
        partial = np.flatnonzero((profile < 0.95 * open_field) & (profile > 0.05 * open_field))
        return int(partial.max() - partial.min() + 1) if partial.size else 0

    assert transition(sharp) <= 2
    assert transition(soft) >= 8
