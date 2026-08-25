"""`FluxModel2D` — plan §4.3, the core of milestone M2.

The mechanism tests (`test_mechanisms.py`) assert where a shadow lands. This
file asserts the pieces that produce it: that the angular distributions are
normalised the way the rest of the model assumes, that a surface's response to
an angle is what the technique says, that visibility is computed from the
repaired union front and not from `solid_phi`, and that the arrival stays inside
the bound the CFL condition was given before the first sub-step.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from nanofab_v3 import Grid, Structure
from nanofab_v3.kernel import constructors as ctor
from nanofab_v3.kernel import csg, flux, measures, motion


@pytest.fixture
def flat(grid_2d: Grid) -> Structure:
    """A blanket substrate — the reference every normalisation is defined against."""
    return ctor.add_material(
        Structure(grid_2d),
        "silicon",
        ctor.half_space(grid_2d, normal=(1.0, 0.0), point=(60.0, 0.0)),
    )


@pytest.fixture
def stepped(grid_2d: Grid) -> Structure:
    """Substrate with a 40 nm mask stripe: one flat field, two sidewalls, one top."""
    return ctor.add_material(
        ctor.add_material(
            Structure(grid_2d),
            "silicon",
            ctor.half_space(grid_2d, normal=(1.0, 0.0), point=(60.0, 0.0)),
        ),
        "mask",
        ctor.box(grid_2d, lower=(60.0, 120.0), upper=(100.0, 180.0)),
    )


# -- angular distributions ---------------------------------------------------


@pytest.mark.parametrize(
    "distribution",
    [
        flux.Delta(0.0),
        flux.Delta(math.radians(40.0)),
        flux.Lobe(math.radians(20.0), math.radians(6.0)),
        flux.CosinePower(1.0),
        flux.CosinePower(4.0, math.radians(15.0)),
        flux.Isotropic(),
        flux.Mixture(((0.7, flux.Lobe(0.0, math.radians(4.0))), (0.3, flux.Isotropic()))),
    ],
)
def test_every_distribution_delivers_exactly_one_to_a_flat_surface(
    distribution: flux.AngularDistribution,
) -> None:
    """`sum_k w_k cos(theta_k) = 1` — the contract the rate models rest on.

    Without it, changing the source's angular width would silently change the
    blanket rate, and "10 nm/s" would mean something different per technique.
    """
    angles, weights = distribution.quadrature()

    assert float(np.sum(weights * np.cos(angles))) == pytest.approx(1.0)
    assert np.all(weights >= 0.0)


def test_a_source_below_the_horizon_is_refused() -> None:
    """A source at 90 degrees delivers nothing to a wafer; it is not a rescale."""
    with pytest.raises(ValueError, match="inside"):
        flux.Delta(math.radians(90.0)).quadrature()


def test_mixture_fractions_split_one_flux_rather_than_adding_two() -> None:
    """Fractions are a decomposition, so they are rescaled to sum to 1."""
    tilted = math.radians(45.0)
    angles, weights = flux.Mixture(
        ((3.0, flux.Delta(0.0)), (1.0, flux.Delta(tilted)))
    ).quadrature()
    response = weights * np.cos(angles)

    assert float(np.sum(response)) == pytest.approx(1.0)
    assert float(response[np.isclose(angles, 0.0)].sum()) == pytest.approx(0.75)
    assert float(response[np.isclose(angles, tilted)].sum()) == pytest.approx(0.25)


def test_a_scaled_source_deliberately_delivers_less() -> None:
    """`Scaled` is the counterpart of the isotropic floor and must not renormalise."""
    angles, weights = flux.Scaled(flux.Delta(0.0), 0.8).quadrature()

    assert float(np.sum(weights * np.cos(angles))) == pytest.approx(0.8)


# -- how a surface responds --------------------------------------------------


def test_a_delta_source_at_normal_incidence_leaves_sidewalls_bare(stepped: Structure) -> None:
    """S1's premise: evaporation coats the field and the mask top, not the walls."""
    arrival = flux.evaporation().on_structure(stepped).arrival

    assert arrival[60, 40] == pytest.approx(1.0, abs=1e-6)  # open substrate
    assert arrival[100, 150] == pytest.approx(1.0, abs=1e-6)  # mask top
    assert arrival[80, 119] < 0.02  # mask sidewall, one cell out
    assert arrival[80, 181] < 0.02


def test_a_broad_lobe_reaches_the_sidewall_an_evaporation_misses(stepped: Structure) -> None:
    """S4's premise: a cos^n source is what puts metal on a wall at all."""
    sharp = flux.evaporation().on_structure(stepped).arrival
    broad = flux.sputter_deposition(exponent=1.0).on_structure(stepped).arrival

    assert sharp[80, 119] < 0.02
    assert broad[80, 119] > 0.25


def test_a_narrower_sputter_lobe_puts_less_on_the_sidewall(stepped: Structure) -> None:
    """The exponent is the knob between conformal-ish and directional."""
    wide = flux.sputter_deposition(exponent=1.0).on_structure(stepped).arrival
    narrow = flux.sputter_deposition(exponent=5.0).on_structure(stepped).arrival

    assert narrow[80, 119] < wide[80, 119]
    assert narrow[60, 40] == pytest.approx(wide[60, 40], rel=0.15)  # the open field is unchanged


def test_surface_mobility_moves_flux_towards_the_starved_sidewall(stepped: Structure) -> None:
    """The mobility kernel is a smear along the front, and it conserves the maximum.

    An adatom that lands where coverage is high and diffuses to where it is low
    is what makes S4's fences continuous instead of beaded. It is a smear, not a
    conservative transport — but being a local weighted mean, it can never invent
    more arrival than the front already had, which is what keeps the CFL bound
    honest.
    """
    still = flux.sputter_deposition(exponent=1.0).on_structure(stepped).arrival
    mobile = flux.sputter_deposition(exponent=1.0, mobility_length=10.0).on_structure(
        stepped
    ).arrival

    assert mobile[80, 119] > still[80, 119]
    assert float(mobile.max()) <= float(still.max()) + 1e-9


def test_the_chemical_fraction_is_what_lets_rie_reach_a_shadowed_wall(
    stepped: Structure,
) -> None:
    """RIE against IBE: the same lobe, plus a component with no direction at all."""
    beam = flux.ion_beam_etch().on_structure(stepped).arrival
    plasma = flux.reactive_ion_etch(chemical_fraction=0.25).on_structure(stepped).arrival

    assert beam[80, 119] < 0.02
    # The floor, plus the little the lobe's own wings reach a vertical wall with.
    assert 0.25 <= plasma[80, 119] < 0.32
    # Both still remove a flat open surface at the nominal rate.
    assert beam[60, 40] == pytest.approx(1.0, abs=0.02)
    assert plasma[60, 40] == pytest.approx(1.0, abs=0.02)


def test_the_sputter_yield_peaks_off_normal_incidence() -> None:
    """The mechanism that facets an ion-milled corner instead of copying the mask."""
    yields = flux.SputterYield()
    angles = np.radians(np.arange(0.0, 90.0, 1.0))
    relative = yields.relative(np.cos(angles))

    assert relative[0] == pytest.approx(1.0)
    assert math.degrees(angles[int(np.argmax(relative))]) == pytest.approx(60.0, abs=2.0)
    assert float(relative.max()) == pytest.approx(1.47, abs=0.05)
    assert relative[-1] < 0.05  # grazing ions reflect


# -- visibility --------------------------------------------------------------


def test_visibility_is_taken_from_the_repaired_union_and_not_from_solid_phi(
    stepped: Structure,
) -> None:
    """A buried seam is not a wall (plan §17.1).

    Where the mask sits on the substrate, `min_m phi[m]` is exactly zero along
    their shared interface, so the raw field reports a *front* running through
    the middle of continuous material. Every front cell there is one the flux
    solver evaluates, extends from, and — in a scene where the seam is not
    shadowed from above — hands an arrival to. `motion.union_front` relaxes the
    seam away first, which is why `on_structure` is the entry point and
    `structure.solid_phi` is not.
    """
    seam = (60, 150)  # under the middle of the mask, on the shared interface
    assert abs(float(stepped.solid_phi[seam])) < stepped.grid.spacing  # raw: a front
    assert abs(float(motion.union_front(stepped)[seam])) > stepped.grid.spacing  # repaired: buried

    repaired = flux.evaporation().on_structure(stepped)
    raw = flux.evaporation().evaluate(stepped.grid, stepped.solid_phi)

    assert raw.front_cells > repaired.front_cells
    assert repaired.arrival[100, 150] == pytest.approx(1.0, abs=1e-6)


def test_nothing_receives_more_than_the_bound_the_cfl_condition_was_given(
    stepped: Structure,
) -> None:
    """`max_arrival` is derived, not measured — so it has to actually bound.

    The sub-step count is fixed before the first sub-step from this number. If a
    front cell could exceed it, the motion would silently violate its own CFL
    condition, and a split dose would stop matching an unsplit one.
    """
    for model in (
        flux.evaporation(angle=math.radians(45.0)),
        flux.ion_beam_etch(),
        flux.reactive_ion_etch(chemical_fraction=0.3),
        flux.sputter_deposition(exponent=2.0),
    ):
        arrival = model.on_structure(stepped).arrival
        assert float(arrival.max()) <= model.max_arrival + 1e-9
        assert float(arrival.min()) >= 0.0


def test_the_arrival_is_zero_far_from_the_front(stepped: Structure) -> None:
    """The collar is a narrow band: cells it does not reach must not move at all."""
    arrival = flux.evaporation().on_structure(stepped).arrival

    assert arrival[10, 40] == 0.0  # deep in the substrate
    assert arrival[190, 40] == 0.0  # high in the headroom


def test_a_deep_trench_shadows_its_own_sidewalls(grid_2d: Grid) -> None:
    """Reverse marching is what makes aspect ratio matter at all."""
    structure = ctor.add_material(
        Structure(grid_2d),
        "silicon",
        csg.difference(
            ctor.half_space(grid_2d, normal=(1.0, 0.0), point=(160.0, 0.0)),
            ctor.box(grid_2d, lower=(60.0, 140.0), upper=(200.0, 160.0)),
        ),
    )
    arrival = flux.sputter_deposition(exponent=1.0).on_structure(structure).arrival

    near_the_top = float(arrival[155, 139])
    deep_inside = float(arrival[70, 139])
    assert near_the_top > deep_inside * 2.0
    assert deep_inside >= 0.0


# -- redeposition ------------------------------------------------------------


@pytest.fixture
def open_trench(grid_2d: Grid) -> Structure:
    """A 20 nm wide, 100 nm deep trench cut into a substrate."""
    return ctor.add_material(
        Structure(grid_2d),
        "silicon",
        csg.difference(
            ctor.half_space(grid_2d, normal=(1.0, 0.0), point=(160.0, 0.0)),
            ctor.box(grid_2d, lower=(60.0, 140.0), upper=(200.0, 160.0)),
        ),
    )


def test_the_bounce_puts_material_from_the_floor_onto_the_sidewalls(
    open_trench: Structure,
) -> None:
    """Plan §4.3's one bounce: what leaves the floor lands on what can see it."""
    outcome = flux.ion_beam_etch(redeposition_yield=0.3).on_structure(open_trench)

    assert outcome.redeposited is not None
    sidewall = outcome.redeposited[80:140, 139]
    assert float(sidewall.mean()) > 0.01
    # An open field sees nothing but sky, so nothing bounces back onto it.
    assert outcome.redeposited[160, 40] == pytest.approx(0.0, abs=1e-9)


def test_redeposition_never_exceeds_the_yield_times_what_was_removed(
    open_trench: Structure,
) -> None:
    """The bound the one-bounce approximation deserves, and the CFL's safety net."""
    outcome = flux.ion_beam_etch(redeposition_yield=0.4).on_structure(open_trench)

    assert outcome.redeposited is not None
    assert float(outcome.redeposited.max()) <= 0.4 * float(outcome.arrival.max()) + 1e-9
    assert float(outcome.redeposited.min()) >= 0.0


def test_a_site_that_is_not_being_etched_does_not_redeposit(open_trench: Structure) -> None:
    """`release` is where material knowledge enters a geometry-only module.

    Without it, a hard mask standing in an ion beam sprays material it is not
    losing. The model cannot know that on its own — the rates live in the process
    — so the caller says so with a per-cell weight.
    """
    model = flux.ion_beam_etch(redeposition_yield=0.3)
    geometry_only = model.on_structure(open_trench)
    nothing_releases = model.on_structure(
        open_trench, release=np.zeros(open_trench.grid.shape, dtype=np.float64)
    )

    assert float(geometry_only.redeposited.max()) > 0.0
    assert float(nothing_releases.redeposited.max()) == pytest.approx(0.0, abs=1e-12)


def test_no_redeposition_array_without_a_redeposition_yield(open_trench: Structure) -> None:
    assert flux.ion_beam_etch().on_structure(open_trench).redeposited is None


# -- the seam into the motion solver -----------------------------------------


def test_the_solver_accepts_a_model_and_rebuilds_it_as_the_front_moves(
    stepped: Structure,
) -> None:
    """A directional etch has to re-ask what the front can see as it digs."""
    rates = motion.SurfaceRates({"silicon": 1.0, "mask": 0.0})
    outcome = motion.advect_front(stepped, rates, 20.0, flux=flux.ion_beam_etch())

    assert outcome.flux_rebuilds == math.ceil(outcome.sub_steps / motion._FLUX_REFRESH)
    assert outcome.max_speed == pytest.approx(flux.ion_beam_etch().max_arrival)


def test_a_static_flux_array_still_works_unchanged(stepped: Structure) -> None:
    """The M1 seam: `flux` as a plain per-cell multiplier, held for the whole motion."""
    rates = motion.SurfaceRates({"silicon": 2.0, "mask": 0.0})
    halved = motion.advect_front(stepped, rates, 5.0, flux=stepped.grid.full(0.5))
    plain = motion.advect_front(stepped, motion.SurfaceRates({"silicon": 1.0, "mask": 0.0}), 5.0)

    assert halved.flux_rebuilds == 0
    difference = halved.structure.phi_of("silicon") - plain.structure.phi_of("silicon")
    assert float(np.max(np.abs(difference))) < 0.05 * stepped.grid.spacing


def test_a_directional_etch_holds_the_mask_edge(grid_2d: Grid) -> None:
    """The whole point of M2: an ion beam etches down, not sideways.

    A 40 nm window in a hard mask, 30 nm of etching. With a narrow lobe the walls
    stand where the mask edge is; adding a chemical fraction is what makes the
    same etch undercut — which is scenario S2's contrast, in miniature.
    """
    structure = ctor.add_material(
        ctor.add_material(
            Structure(grid_2d),
            "silicon",
            ctor.half_space(grid_2d, normal=(1.0, 0.0), point=(120.0, 0.0)),
        ),
        "mask",
        csg.difference(
            ctor.box(grid_2d, lower=(120.0, None), upper=(150.0, None)),
            ctor.box(grid_2d, lower=(110.0, 130.0), upper=(220.0, 170.0)),
        ),
    )
    rates = motion.SurfaceRates({"silicon": 1.0, "mask": 0.0})

    def widest_opening(etched: Structure) -> float:
        empty = ~etched.solid_mask
        return max(
            float(130 - int(np.flatnonzero(empty[row]).min()))
            for row in range(95, 120)
            if np.flatnonzero(empty[row]).size
        )

    beam = motion.advect_front(structure, rates, 30.0, flux=flux.ion_beam_etch()).structure
    plasma = motion.advect_front(
        structure, rates, 30.0, flux=flux.reactive_ion_etch(chemical_fraction=0.3)
    ).structure

    depth = 120 - (int(np.flatnonzero(beam.inside("silicon")[:, 150]).max()) + 1)
    assert depth == pytest.approx(30, abs=3)
    assert widest_opening(beam) <= 2.0  # vertical walls, to the cell
    assert widest_opening(plasma) >= 5.0  # the chemical fraction undercuts
    assert beam.measure(beam.inside("mask")) == pytest.approx(
        structure.measure(structure.inside("mask"))
    )


# -- the named 2D seam -------------------------------------------------------


def test_the_flux_solver_refuses_a_three_dimensional_grid(grid_3d: Grid) -> None:
    """Plan Q7: the seam is named and checked, not silently assumed."""
    structure = ctor.add_material(
        Structure(grid_3d), "silicon", ctor.half_space(grid_3d, (1.0, 0.0, 0.0), (20.0, 0.0, 0.0))
    )
    with pytest.raises(ValueError, match="2D-only"):
        flux.evaporation().on_structure(structure)


# -- what a shadowed deposition leaves behind --------------------------------


def test_a_shadowed_deposition_leaves_no_phantom_material(stepped: Structure) -> None:
    """Where nothing was deposited, the deposit's field must say so.

    `max(solid_now, -solid_start)` is the right set and, on its own, the wrong
    field: where the front did not move it collapses to `|solid_start|`, which is
    exactly zero all along the old surface. Nothing is *inside* that zero level,
    but every measure taken off the field reads those cells as half full — the
    phantom the sub-cell measures of plan §4.5 exist to avoid, arriving through
    the back door. Measured before the fix on the reference grid: 1849 cells at
    exactly zero and ~600 nm^2 of metal that was never deposited.
    """
    grid = stepped.grid
    grown = motion.advect_front(
        stepped,
        motion.SurfaceRates(default=1.0),
        6.0,
        deposit_material="metal",
        flux=flux.evaporation(),
    ).structure
    metal = grown.phi_of("metal")

    # At normal incidence the metal is 6 nm on every horizontal surface and
    # nothing on the two sidewalls, so it covers the full width exactly once.
    assert measures.enclosed_measure(grid, metal) == pytest.approx(6.0 * grid.shape[1], rel=0.01)
    # Beside the bare mask sidewall the field is a distance to the metal that
    # *was* deposited — not a zero level standing where the surface used to be.
    beside_the_wall = metal[70:99, 119]
    assert float(beside_the_wall.min()) > 0.0
