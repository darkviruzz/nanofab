"""Mechanism tests — plan §13.2, layer 2 of the acceptance pyramid.

These are the measured probes of the design phase turned into standing tests:
scenes small enough to reason about analytically, asserted against the number the
geometry says they must produce. They are the layer that catches a kernel that is
internally consistent but physically wrong.

Two mechanisms live here so far:

- **T-profile ALD** (this file's first half) — conformal growth over a re-entrant
  profile seals an enclosed void at `t >= half the opening`. It needs no flux at
  all, which is what makes it the honest smoke test for the M1 building blocks
  the flux solver is about to be stacked on.
- **Shadow wedge** (second half) — a directional source behind a mask edge, with
  the shadow boundary asserted against `h * tan(theta)`.

The undercut mechanism (isotropic etch under a mask) lives in `test_motion.py`,
next to the motion it is a property of.
"""

from __future__ import annotations

import numpy as np
import pytest

from nanofab_v3 import Grid, Structure
from nanofab_v3.kernel import constructors as ctor
from nanofab_v3.kernel import csg, motion, occurrences

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


def test_the_sealed_void_keeps_shrinking_and_finally_disappears(t_profile: Structure) -> None:
    """Geometric deposition keeps growing *inside* a sealed cavity — by design, for now.

    This is correct for the M1/M2 kernel and wrong as physics: once the mouth is
    closed, no precursor reaches the cavity and the void must stop shrinking. The
    missing piece is plan §4.4's reachability gate, which arrives with the process
    contract in M3 — S3 (lift-off broken by ALD) is exactly this mechanism at
    scenario scale. It is asserted here so the behaviour is documented rather than
    rediscovered as a bug.
    """
    sizes = [
        _empty_components(motion.offset_solid(t_profile, t, deposit_material="ald").structure)[1]
        for t in (10.0, 12.0, 15.0)
    ]

    assert sizes == sorted(sizes, reverse=True)  # the sealed void keeps shrinking
    assert _empty_components(
        motion.offset_solid(t_profile, 20.0, deposit_material="ald").structure
    ) == (1, 0)


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
