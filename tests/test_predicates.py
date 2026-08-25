"""Predicates and region operations — plan §7 and §4.4.

The layer the acceptance scenarios are asserted *through*, so these tests are
where the predicates themselves have to be pinned against geometry simple enough
to check by hand: a slab, a trench, a sealed cavity, a mask with a window.

Two of them are also kernel steps (reachability and support), and both shapes are
exercised here — the region form a set operation consumes, and the
`motion.FrontFlux` form a rate-driven process multiplies onto its speed field.
"""

from __future__ import annotations

import numpy as np
import pytest

from nanofab_v3 import Grid, Structure
from nanofab_v3.kernel import constructors as ctor
from nanofab_v3.kernel import csg, motion, predicates, regions

# -- fixtures -----------------------------------------------------------------


@pytest.fixture
def cavity() -> Structure:
    """A substrate under a slab with a re-entrant cavity — one sealed, one open.

    The mushroom profile of a lift-off resist: a 20 nm mouth widening into a 60 nm
    cavity. Built as **one** union of overlapping boxes rather than as abutting
    ones, for the reason `test_mechanisms.t_profile` gives: two boxes that share a
    face leave the difference exactly zero along it, and `solid_mask` counts a
    zero as solid, so an abutting construction walls the cavity off from its own
    mouth before anything happens to it.
    """
    grid = Grid(origin=(0.0, 0.0), spacing=1.0, shape=(140, 200), axes=("y", "x"))
    structure = ctor.add_material(
        Structure(grid), "silicon", ctor.half_space(grid, normal=(1.0, 0.0), point=(40.0, 0.0))
    )
    slab = ctor.box(grid, lower=(40.0, None), upper=(90.0, None))
    mouth = ctor.box(grid, lower=(30.0, 90.0), upper=(120.0, 110.0))
    hollow = ctor.box(grid, lower=(30.0, 70.0), upper=(80.0, 130.0))
    return ctor.add_material(structure, "resist", csg.difference(slab, csg.union(mouth, hollow)))


@pytest.fixture
def masked() -> Structure:
    """An oxide layer on silicon under a resist mask with an 80 nm window.

    The resist is a **planarising** slab — unbounded downwards, carved against
    what is already there, exactly as `processes.lithography.spin_coat` builds it.
    That is not a detail: an unbounded slab is negative all the way down, so the
    carve `max(phi_slab, -phi_union)` lands on the buried silicon/oxide interface
    and leaves the phantom zero the first test below measures. A slab bounded at
    the oxide's top would hide it, and hiding it is how it survived M0 to M2.
    """
    grid = Grid(origin=(0.0, 0.0), spacing=1.0, shape=(220, 300), axes=("y", "x"))
    structure = ctor.add_material(
        Structure(grid), "silicon", ctor.half_space(grid, normal=(1.0, 0.0), point=(40.0, 0.0))
    )
    structure = ctor.add_material(
        structure, "oxide", ctor.box(grid, lower=(40.0, None), upper=(100.0, None))
    )
    return ctor.add_material(
        structure,
        "resist",
        csg.difference(
            ctor.box(grid, lower=(None, None), upper=(160.0, None)),
            ctor.box(grid, lower=(90.0, 110.0), upper=(200.0, 190.0)),
        ),
    )


# -- the closed region --------------------------------------------------------


def test_a_carved_field_reads_zero_on_other_materials_buried_seams(masked: Structure) -> None:
    """Why `cells_of` is not `phi <= 0` — the S2 stack measures it.

    `add_material` carves the new region against the union of the others, and
    `-phi_union` is exactly zero along every interface between two of *those* —
    interfaces the new material is nowhere near. Here `phi_resist` reads 0.0
    along the buried silicon/oxide interface at y = 40, sixty nanometres below the
    resist's own underside and in every column of the domain.
    """
    values = np.asarray(masked.phi_of("resist"))

    assert np.count_nonzero(values[40] <= 0.0) == masked.grid.shape[1]  # every column

    closed = predicates.cells_of(masked, "resist")

    assert not np.any(closed[40])  # the phantom seam is not the resist
    assert np.all(closed[101, :110])  # the mask itself is
    assert not np.any(closed[101, 111:189])  # and the window is not


def test_the_closed_region_is_the_interior_plus_its_own_boundary(masked: Structure) -> None:
    """One cell wider than `inside`, and the cell a bath touches first."""
    interior = masked.inside("resist")
    closed = predicates.cells_of(masked, "resist")

    assert np.all(closed[interior])
    assert np.count_nonzero(closed) > np.count_nonzero(interior)
    assert np.all(np.asarray(masked.phi_of("resist"))[closed] <= 0.0)


# -- reachability -------------------------------------------------------------


def test_an_open_cavity_leaves_its_resist_reachable(cavity: Structure) -> None:
    """Before anything seals it, the solvent gets in through the mouth."""
    assert predicates.is_reachable(cavity, "resist")
    assert predicates.enclosed_voids(cavity) == ()


def test_sealing_the_mouth_makes_the_resist_unreachable(cavity: Structure) -> None:
    """S3's mechanism, at its smallest: reachability is a topology query.

    Conformal growth closes the 20 nm mouth at half the opening. Nothing in the
    kernel knows what a mouth is — the query simply stops finding a path from the
    top of the domain to the cavity.
    """
    sealed = motion.offset_solid(cavity, 12.0, deposit_material="ald").structure

    assert not predicates.is_reachable(sealed, "resist")
    voids = predicates.enclosed_voids(sealed)
    assert len(voids) == 1
    assert voids[0].cells > 0
    assert voids[0].centroid[1] == pytest.approx(100.0, abs=2.0)  # the cavity, centred


def test_only_the_top_face_counts_as_the_outside(cavity: Structure) -> None:
    """A cross-section continues sideways, so a lateral face is not a bath.

    The convention the whole package runs on (the gate's headroom guard reads the
    same face, §17.5). Which faces are open has to be an *argument* rather than a
    guess, because guessing "connected" would make a sealed cavity reachable the
    moment it happened to reach the crop of the window — a property of where the
    cross-section was cut, not of the sample.
    """
    assert predicates.open_faces(cavity.grid) == (("y", "max"),)

    from_above = predicates.reachable_empty(cavity.grid, cavity.solid_phi)
    from_the_wafer = predicates.reachable_empty(
        cavity.grid, cavity.solid_phi, faces=(("y", "min"),)
    )

    assert from_above[100, 100]  # the mouth, open to the headroom
    assert not from_the_wafer.any()  # the wafer face is solid: nothing arrives there


def test_reachable_occurrences_takes_the_whole_piece_or_none_of_it(cavity: Structure) -> None:
    """A solvent that reaches one corner of a connected piece takes the piece."""
    reachable = predicates.reachable_occurrences(cavity, "resist")
    sealed = motion.offset_solid(cavity, 12.0, deposit_material="ald").structure

    assert np.array_equal(reachable, predicates.cells_of(cavity, "resist"))
    assert not predicates.reachable_occurrences(sealed, "resist").any()


# -- the gate a rate-driven process runs behind -------------------------------


def test_the_reachable_front_is_one_on_the_open_surface_and_zero_in_a_sealed_void(
    cavity: Structure,
) -> None:
    """`ReachableFront` in its `motion.FrontFlux` shape (plan §4.4).

    The same predicate as a per-cell multiplier: 1 where the bath is, 0 where it
    is not, extended into a collar so the upwind stencil sees a speed on both
    sides of the zero level rather than a step across it (§18.5).
    """
    sealed = motion.offset_solid(cavity, 12.0, deposit_material="ald").structure
    gate = predicates.ReachableFront()

    arrival = gate.on_front(sealed.grid, motion.union_front(sealed))

    assert gate.max_arrival == 1.0
    assert arrival.max() == 1.0
    assert arrival.min() == 0.0
    # The outer surface: 12 nm of growth puts it at y = 102, away from the mouth.
    assert arrival[98:107, 20].max() == pytest.approx(1.0)
    void = predicates.enclosed_voids(sealed)[0]
    assert arrival[int(void.centroid[0]), int(void.centroid[1])] == pytest.approx(0.0)
    # ... and so is the void's own front, which is what stops it shrinking.
    assert arrival[int(void.centroid[0]), 74:126].max() == pytest.approx(0.0)


def test_the_gate_is_frozen_beyond_its_collar(cavity: Structure) -> None:
    """A velocity extension is only valid near the front — §18.5, in this module.

    Extended over the whole domain the gate would hand a cell ten cells deep in a
    wall the speed of whatever front happens to be nearest, and `phi` there would
    climb until it crossed zero. Beyond the collar it is zero and the cell is
    frozen.
    """
    gate = predicates.ReachableFront(collar_cells=4)

    arrival = gate.on_front(cavity.grid, motion.union_front(cavity))

    assert arrival[10, 100] == 0.0  # deep inside the substrate
    assert arrival[135, 100] == 0.0  # far above the surface


def test_the_gate_is_n_dimensional(grid_3d: Grid) -> None:
    """Connectivity is N-D, so this is deliberately not a third 2D seam (plan Q7)."""
    structure = ctor.add_material(
        Structure(grid_3d), "silicon", ctor.half_space(grid_3d, (1.0, 0.0, 0.0), (20.0, 0.0, 0.0))
    )

    arrival = predicates.ReachableFront().on_front(grid_3d, motion.union_front(structure))

    assert arrival.shape == grid_3d.shape
    assert arrival.max() == pytest.approx(1.0)


# -- support ------------------------------------------------------------------


def test_a_floating_component_is_unsupported_and_the_wafer_is_not() -> None:
    """Support is "connected to the wafer", i.e. to the min face of the stacking axis."""
    grid = Grid(origin=(0.0, 0.0), spacing=1.0, shape=(120, 120), axes=("y", "x"))
    structure = ctor.add_material(
        Structure(grid), "silicon", ctor.half_space(grid, normal=(1.0, 0.0), point=(40.0, 0.0))
    )
    structure = ctor.add_material(
        structure, "metal", ctor.box(grid, lower=(70.0, 40.0), upper=(90.0, 80.0))
    )

    floating = predicates.unsupported(structure)

    assert np.all(floating[structure.inside("metal")])
    assert not np.any(floating & structure.inside("silicon"))
    assert np.all(predicates.supported(structure)[:41])


def test_a_component_touching_the_wafer_is_supported_however_thin_the_contact() -> None:
    """Support is topological: one shared cell is enough, and has to be.

    The fences of S4 hang on exactly this — a sidewall film touching the pattern
    at its foot is attached, and no thickness threshold gets to overrule that.
    """
    grid = Grid(origin=(0.0, 0.0), spacing=1.0, shape=(120, 120), axes=("y", "x"))
    structure = ctor.add_material(
        Structure(grid), "silicon", ctor.half_space(grid, normal=(1.0, 0.0), point=(40.0, 0.0))
    )
    structure = ctor.add_material(
        structure, "metal", ctor.box(grid, lower=(40.0, 40.0), upper=(90.0, 44.0))
    )

    assert not predicates.unsupported(structure).any()


# -- undercut -----------------------------------------------------------------


def test_a_bare_mask_has_no_undercut(masked: Structure) -> None:
    """The measurement starts at zero, so a nonzero one means the etch did it."""
    measured = predicates.undercut(masked, "resist")

    assert measured.lateral == 0.0
    assert measured.vertical == 0.0
    assert measured.ratio == 0.0


def test_the_undercut_ratio_reads_one_for_a_circular_front(masked: Structure) -> None:
    """An isotropic removal is a circle centred on the mask edge (`CONTEXT.md`).

    A circle's radius is the same sideways as downwards, so the ratio is 1 — which
    is the number scenario S2 asserts an isotropic wet etch against, and the
    reason the predicate is a *ratio* rather than two lengths.
    """
    etched = motion.advect_front(
        masked,
        motion.SurfaceRates({"oxide": 1.0, "silicon": 0.0, "resist": 0.0}),
        25.0,
        flux=predicates.ReachableFront(),
    ).structure

    measured = predicates.undercut(etched, "resist")

    assert measured.vertical == pytest.approx(25.0, abs=2.0)
    assert measured.lateral == pytest.approx(25.0, abs=4.0)
    assert measured.ratio == pytest.approx(1.0, abs=0.2)


# -- step coverage ------------------------------------------------------------


def test_a_conformal_film_covers_a_step_evenly() -> None:
    """`CONTEXT.md`: conformal means equal thickness on every reachable surface."""
    grid = Grid(origin=(0.0, 0.0), spacing=1.0, shape=(160, 200), axes=("y", "x"))
    structure = ctor.add_material(
        Structure(grid), "silicon", ctor.half_space(grid, normal=(1.0, 0.0), point=(40.0, 0.0))
    )
    structure = ctor.add_material(
        structure, "silicon", ctor.box(grid, lower=(40.0, 80.0), upper=(80.0, 200.0))
    )

    grown = motion.offset_solid(structure, 12.0, deposit_material="ald").structure
    coverage = predicates.step_coverage(grown, "ald")

    # Thickness is twice the depth at the film's medial axis, so a 12 nm offset
    # reads 12 nm — everywhere, over the step included, which is what conformal
    # means and what the ratio is 1 for.
    assert coverage.nominal == pytest.approx(12.0, abs=1.5)
    assert coverage.ratio > 0.9
    assert coverage.continuous


def test_step_coverage_reports_a_film_that_is_not_one_piece() -> None:
    """Discontinuity is the finding S1's lift-off and S4's fences both rest on."""
    grid = Grid(origin=(0.0, 0.0), spacing=1.0, shape=(120, 200), axes=("y", "x"))
    structure = ctor.add_material(
        Structure(grid), "silicon", ctor.half_space(grid, normal=(1.0, 0.0), point=(40.0, 0.0))
    )
    broken = ctor.add_material(
        ctor.add_material(
            structure, "metal", ctor.box(grid, lower=(40.0, 20.0), upper=(50.0, 80.0))
        ),
        "metal",
        ctor.box(grid, lower=(40.0, 120.0), upper=(50.0, 180.0)),
    )

    coverage = predicates.step_coverage(broken, "metal")

    assert not coverage.continuous
    assert predicates.step_coverage(structure, "metal").nominal == 0.0


# -- region operations --------------------------------------------------------


def test_the_mask_distance_field_puts_its_zero_level_between_the_cells() -> None:
    """`signed_distance_of` shifts by half a cell — without it a region grows.

    The outermost cell of a mask is half a cell from the boundary, not a whole
    one. A field that says otherwise makes every removed region half a cell too
    large in every direction, which on a 2 nm film is a 50 % error.
    """
    grid = Grid(origin=(0.0, 0.0), spacing=1.0, shape=(20, 20), axes=("y", "x"))
    mask = np.zeros(grid.shape, dtype=bool)
    mask[:10] = True

    phi = regions.signed_distance_of(grid, mask)

    assert phi[9, 5] == pytest.approx(-0.5)
    assert phi[10, 5] == pytest.approx(0.5)
    assert phi[0, 5] == pytest.approx(-9.5)


def test_removing_a_material_selectively_leaves_the_others_bit_identical(
    cavity: Structure,
) -> None:
    """Why `remove_region` takes `materials` — two touching materials share a cell.

    A mask covering the resist's closed region also covers the substrate's top
    row, because `phi` is exactly zero there for both (§17.1). Measured before
    this argument existed: dissolving the resist took half a nanometre of silicon
    with it, along every cell the two shared.
    """
    removed = predicates.reachable_occurrences(cavity, "resist")

    stripped = regions.remove_region(cavity, removed, materials=("resist",))

    assert stripped.materials == ("silicon",)
    assert np.array_equal(
        np.asarray(stripped.phi_of("silicon")), np.asarray(cavity.phi_of("silicon"))
    )


def test_a_material_that_loses_everything_is_dropped_with_its_fields(
    cavity: Structure,
) -> None:
    """The mechanism behind the gate's capability update (plan §5.3).

    `material:resist` disappears from the revision because the resist did — no
    step had to remember to retract it, and no all-positive ghost field is left
    for a later query to trip over.
    """
    with_field = cavity.with_field(("exposed", "resist"), np.ones(cavity.grid.shape, np.int8))

    stripped = regions.remove_region(
        with_field, predicates.cells_of(cavity, "resist"), materials=("resist",)
    )

    assert "resist" not in stripped.phi
    assert not stripped.has_field(("exposed", "resist"))


def test_removing_nothing_returns_the_very_same_structure(cavity: Structure) -> None:
    """A no-op must not cost a revision's worth of arrays, or a repair."""
    assert regions.remove_region(cavity, np.zeros(cavity.grid.shape, bool)) is cavity


def test_remove_region_refuses_a_material_that_is_not_there(cavity: Structure) -> None:
    """A typo'd material would silently remove nothing at all."""
    with pytest.raises(KeyError, match="no material"):
        regions.remove_region(cavity, cavity.solid_mask, materials=("photoresist",))
