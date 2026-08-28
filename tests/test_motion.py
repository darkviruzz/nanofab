"""Front motion — plan §4.2, the core of milestone M1.

Two paths that have to agree with each other and with themselves: the isotropic
fast path must be exact, the advected path must reproduce it on a plane, and
**splitting a dose must not change the result** — the failure that made v1's
iterative workflow untrustworthy (ADR-0001 F2/F4: `1 x 4.0 s` and `20 x 0.2 s`
removed different amounts, and neither was right).
"""

from __future__ import annotations

import numpy as np
import pytest

from nanofab_v3 import Grid, Structure
from nanofab_v3.kernel import constructors as ctor
from nanofab_v3.kernel import measures, motion


@pytest.fixture
def substrate(grid_2d: Grid) -> Structure:
    """A blanket substrate whose surface sits exactly on a grid row."""
    return ctor.add_material(
        Structure(grid_2d),
        "silicon",
        ctor.half_space(grid_2d, normal=(1.0, 0.0), point=(60.0, 0.0)),
    )


@pytest.fixture
def masked(substrate: Structure, grid_2d: Grid) -> Structure:
    """Substrate with a hard mask stripe on top of it."""
    return ctor.add_material(
        substrate, "mask", ctor.box(grid_2d, lower=(55.0, 100.0), upper=(75.0, 200.0))
    )


def _top_row(structure: Structure, material: str, column: int) -> int:
    """The first row above `material` in one column, or -1 if it is not there."""
    inside = structure.inside(material)[:, column]
    return int(np.flatnonzero(inside).max()) + 1 if inside.any() else -1


# -- the isotropic fast path -------------------------------------------------


def test_offset_moves_the_front_by_exactly_the_distance(substrate: Structure) -> None:
    etched = motion.offset_solid(substrate, -12.0).structure

    assert _top_row(etched, "silicon", 150) == 48
    assert np.array_equal(etched.phi_of("silicon"), substrate.phi_of("silicon") + np.float32(12.0))


def test_offset_dose_splitting_is_exact(substrate: Structure) -> None:
    """`1 x 20 nm` and `4 x 5 nm` agree to the last bit (plan §4.2, measured)."""
    once = motion.offset_solid(substrate, -20.0).structure
    split = substrate
    for _ in range(4):
        split = motion.offset_solid(split, -5.0).structure

    assert np.max(np.abs(once.phi_of("silicon") - split.phi_of("silicon"))) == 0.0


def test_offset_deposits_a_conformal_shell(substrate: Structure, grid_2d: Grid) -> None:
    """Growth needs a material to own the new shell; the substrate keeps its own."""
    grown = motion.offset_solid(substrate, 8.0, deposit_material="ald").structure

    assert grown.materials == ("silicon", "ald")
    assert _top_row(grown, "ald", 150) == 68
    assert np.array_equal(grown.phi_of("silicon"), substrate.phi_of("silicon"))
    # Measured sub-cell: cell counting would drop the two boundary rows, which
    # are exactly half full each.
    deposited = measures.enclosed_measure(grid_2d, grown.phi_of("ald"))
    assert deposited == pytest.approx(8.0 * grid_2d.shape[1], rel=0.02)


def test_offset_rejects_a_contradictory_direction(substrate: Structure) -> None:
    with pytest.raises(ValueError, match="needs a deposit_material"):
        motion.offset_solid(substrate, 5.0)
    with pytest.raises(ValueError, match="takes no deposit_material"):
        motion.offset_solid(substrate, -5.0, deposit_material="ald")


# -- the general path --------------------------------------------------------


def test_advection_reproduces_the_fast_path_on_a_plane(substrate: Structure) -> None:
    """A planar front is exactly where the upwind stencil is exact."""
    advected = motion.advect_front(substrate, motion.SurfaceRates(default=2.0), 5.0)
    offset = motion.offset_solid(substrate, -10.0)

    assert advected.sub_steps == 20
    difference = advected.structure.phi_of("silicon") - offset.structure.phi_of("silicon")
    assert np.max(np.abs(difference)) == 0.0


def test_advection_sub_steps_follow_the_cfl_condition(substrate: Structure) -> None:
    """`dt <= cfl * spacing / max|F|`, and the user never sees the sub-steps."""
    outcome = motion.advect_front(substrate, motion.SurfaceRates(default=4.0), 10.0, cfl=0.5)

    assert outcome.dt <= 0.5 * substrate.grid.spacing / 4.0 + 1e-9
    assert outcome.sub_steps == 80
    assert outcome.max_speed == 4.0


def test_advection_dose_splitting_agrees_within_tolerance(substrate: Structure) -> None:
    """`N x (t/N)` and `1 x t` agree — the consistency obligation of plan §4.2."""
    rates = motion.SurfaceRates(default=2.0)
    once = motion.advect_front(substrate, rates, 12.0).structure
    split = substrate
    for _ in range(4):
        split = motion.advect_front(split, rates, 3.0).structure

    difference = np.abs(once.phi_of("silicon") - split.phi_of("silicon"))
    assert float(np.max(difference)) < 0.05 * substrate.grid.spacing


def test_a_zero_rate_material_stalls_the_front(masked: Structure) -> None:
    """Mask behaviour emerges from rates; nothing in the kernel knows about masks."""
    outcome = motion.advect_front(masked, motion.SurfaceRates({"silicon": 2.0, "mask": 0.0}), 10.0)
    etched = outcome.structure

    assert _top_row(etched, "silicon", 20) == 40  # open field: 20 nm gone
    assert _top_row(etched, "silicon", 150) == 60  # under the mask: untouched
    assert etched.measure(etched.inside("mask")) == pytest.approx(
        masked.measure(masked.inside("mask"))
    )


def test_an_isotropic_etch_undercuts_its_mask(masked: Structure) -> None:
    """The undercut reaches about as far sideways as the etch goes down."""
    outcome = motion.advect_front(masked, motion.SurfaceRates({"silicon": 2.0, "mask": 0.0}), 10.0)
    silicon = outcome.structure.phi_of("silicon")

    just_below_the_mask = int(np.argmax(silicon[59] < 0.0))
    assert just_below_the_mask - 100 == pytest.approx(20, abs=3)


def test_the_front_switches_rate_when_it_reaches_the_next_material(grid_2d: Grid) -> None:
    """Etching through a slow film into a fast substrate needs no special case."""
    stack = ctor.add_material(
        Structure(grid_2d),
        "silicon",
        ctor.half_space(grid_2d, normal=(1.0, 0.0), point=(60.0, 0.0)),
    )
    stack = ctor.add_material(
        stack, "film", ctor.box(grid_2d, lower=(55.0, None), upper=(70.0, None))
    )
    rates = motion.SurfaceRates({"film": 1.0, "silicon": 5.0})

    # The film is 10 nm thick and etches at 1 nm/s, the substrate below at 5.
    in_the_film = motion.advect_front(stack, rates, 8.0).structure
    through_it = motion.advect_front(stack, rates, 12.0).structure

    assert _top_row(in_the_film, "film", 150) == 62  # 8 nm of film gone
    assert _top_row(in_the_film, "silicon", 150) == 60  # substrate untouched
    assert not through_it.inside("film").any()  # film consumed after 10 s
    # ... and the remaining ~2 s ran at the substrate's own rate, not the film's:
    # 10 nm, against the 2 nm the film's rate would have given. The switch itself
    # is a cell wide, so with a rate ratio of 5 the depth carries a few nm of
    # resolution error — which is what the grid spacing is a visible parameter for.
    depth = 60 - _top_row(through_it, "silicon", 150)
    assert 6.0 <= depth <= 16.0


def test_deposition_grows_a_new_material(substrate: Structure) -> None:
    outcome = motion.advect_front(
        substrate, motion.SurfaceRates(default=1.0), 6.0, deposit_material="metal"
    )

    assert outcome.structure.materials == ("silicon", "metal")
    assert _top_row(outcome.structure, "metal", 150) == 66
    assert outcome.swept > 0.0


def test_motion_leaves_its_input_untouched(substrate: Structure) -> None:
    """Every motion is a new revision; revisions are append-only."""
    before = substrate.phi_of("silicon").copy()
    motion.advect_front(substrate, motion.SurfaceRates(default=3.0), 4.0)
    motion.offset_solid(substrate, -7.0)

    assert np.array_equal(substrate.phi_of("silicon"), before)


def test_nothing_moves_without_a_rate(substrate: Structure) -> None:
    outcome = motion.advect_front(substrate, motion.SurfaceRates(), 10.0)

    assert outcome.sub_steps == 0
    assert outcome.swept == 0.0
    assert outcome.structure is substrate


# -- the union front ---------------------------------------------------------


def test_touching_materials_do_not_leave_a_seam_in_the_front(masked: Structure) -> None:
    """`min_m phi[m]` is zero along a shared interface; that is not a front.

    Without the repair the buried seam would be advected like a real surface and
    an etch would punch a void along a perfectly continuous interface.
    """
    grid = masked.grid
    raw = masked.solid_phi
    repaired = motion.union_front(masked)

    assert raw[60, 150] == pytest.approx(0.0)  # the seam, exactly on a grid row
    assert repaired[60, 150] < -3.0  # buried, and now says so
    # The front integral counts only the real solid/empty interface.
    assert measures.front_integral(grid, repaired) < 0.85 * measures.front_integral(grid, raw)


def test_a_single_material_needs_no_repair(substrate: Structure) -> None:
    """One material cannot have a seam, so the fast path stays exact."""
    assert np.array_equal(motion.union_front(substrate), substrate.solid_phi)
