"""The domain edge: material cut by a wall, and a union field valid in the volume.

Milestone M9, and a bug that took a real project to find. `docs/plans/
m6-m9-roadmap.md` §M9 diagnosed it on `structure.v2` (241x301 @ 1 nm, a
`develop_at_rate` with 200 sub-steps and 19 mid-motion reinitialisations): a
speck of contamination sitting against the left wall, and after half a minute of
development the resist was in pieces, the speck had holes in it, and the commit
gate reported `band |grad(phi)| - 1 is 0.353, above 0.35`.

The roadmap named four links in the chain. Only the first is a defect:

1. **`min_m phi[m]` is not a distance function in the volume.** At a buried
   material seam it reads zero, and *below* the seam it reproduces the lower
   material's own depth — so a cell 30 nm inside a stack can read -5 because an
   interface passes 5 nm away.
2. Every mid-motion reinitialisation marched that kink deeper, because a
   narrow-band pass is a five-cell tool and the defect is domain-wide.
3. At the wall it tipped positive, which is where the sign flips were seen.
4. `motion._clipped` writes the union into every material, so the broken field
   was punched into materials the step never touched.

Links 2-4 are consequences. `union_front` now *builds* a distance function
instead of repairing one (`motion.seeded_distance`), and they go with it — which
is the claim these tests make, at the level the bug was found: a whole process
step through the public API, not a hand-built field.

Two things the roadmap proposed and the measurements did **not** support are
recorded here rather than in a commit message, because the next person to read
§M9 will otherwise try them again:

- **Neumann/ghost cells in `kernel.stencil`.** Zeroing the one-sided differences
  at a domain face breaks `test_an_exact_field_is_a_fixed_point` and
  `test_advection_reproduces_the_fast_path_on_a_plane` — the stencil's linear
  continuation is load-bearing, and its module docstring says why. Measured on a
  synthetic wall-cut disk over 286 reinitialisation passes, the wall column is
  *stable* on its own (`max ||grad| - 1| = 0.05`, solid cell count constant, no
  sign flip); what grew was the band error at `phi ~ 0` in the domain interior,
  which is link 1. The wall never needed a boundary condition — it needed a
  union field that was a distance function when it got there.
- **Narrowing `_clipped` to the cells the union emptied.** `max` is also what
  keeps a material's field continuous as the front approaches; clipping only the
  emptied cells leaves a gradient of five across the front and fails the gate at
  every duration. See the note in `motion._clipped`.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy import ndimage

from nanofab_v3 import Structure
from nanofab_v3.kernel import constructors as ctor
from nanofab_v3.kernel import gate as commit_gate
from nanofab_v3.kernel import motion
from nanofab_v3.materials import PARTICLE, RESIST, SILICON, MaterialLibrary, didactic_library
from nanofab_v3.processes import lithography, substrate


@pytest.fixture
def library() -> MaterialLibrary:
    return didactic_library()


@pytest.fixture
def speck(library: MaterialLibrary) -> Structure:
    """The reproduction case: a wall-cut particle under exposed resist.

    The roadmap's own geometry — 241x301 at 1 nm, 40 nm of silicon, 80 nm of
    resist, a 14 nm speck of contamination whose centre sits *outside* the
    domain so the left wall cuts it, and a 100 nm exposure window over it. The
    speck against the wall is the whole point: it is the one piece of solid with
    no front in x, which is what made link 3 visible.
    """
    grid = substrate.cross_section_grid(width=300.0, thickness=40.0, headroom=200.0)
    wafer = substrate.select_substrate(grid, SILICON, surface=40.0)
    coated = lithography.spin_coat(wafer, RESIST, thickness=80.0)
    speckled = commit_gate.commit(
        ctor.add_material(coated, PARTICLE, ctor.ball(grid, center=(120.0, -4.0), radius=14.0))
    ).structure
    return lithography.expose_dose(
        speckled,
        RESIST,
        lithography.windows(grid, [(100.0, 200.0)]),
        dose=150.0,
        blur=8.0,
        library=library,
    )


def _developed(speck: Structure, library: MaterialLibrary, duration: float):
    """Develop for `duration` and close the step through the commit gate."""
    moved = lithography.develop_at_rate(speck, RESIST, duration=duration, library=library)
    return commit_gate.commit(moved.structure, parent=speck, swept=moved.swept), moved


@pytest.mark.parametrize("duration", [4.0, 16.0, 30.0, 60.0])
def test_the_reproduction_case_develops_without_a_gate_failure(
    speck: Structure, library: MaterialLibrary, duration: float
) -> None:
    """§M9's DoD, at four durations because the bug was cumulative.

    Before the fix, 4 s and 16 s passed and 30 s and 60 s failed with band
    gradient errors of 0.353 and 0.355 against a 0.35 tolerance — the distortion
    grew with the number of reinitialisations, which is what "marched deeper"
    means. After it, the same runs report 0.117 and 0.108 and the error stops
    growing: 119 passes are no worse than 15.
    """
    committed, _ = _developed(speck, library, duration)

    assert committed.report.failures == ()
    assert committed.report.band_gradient_error < 0.25
    assert committed.report.max_overlap_depth == pytest.approx(0.0)


def test_the_wall_cut_particle_survives_in_one_piece(
    speck: Structure, library: MaterialLibrary
) -> None:
    """No holes punched into a material the develop never touched (link 4).

    The particle is not attacked by the developer at any rate, so after 30 s it
    must be exactly the speck it was: same cells, one connected component, and
    every one of them still negative. A positive value *inside* it is the
    signature of the broken union being written through `_clipped`.
    """
    before = np.asarray(speck.phi_of(PARTICLE))
    committed, _ = _developed(speck, library, 30.0)
    after = np.asarray(committed.structure.phi_of(PARTICLE))

    assert int((after < 0.0).sum()) == int((before < 0.0).sum())
    assert ndimage.label(after < 0.0)[1] == 1
    # The speck reaches the wall, and its deepest cell is a real distance from
    # the surface rather than a flat plateau the reinitialisation left behind.
    at_wall = after[:, 0]
    assert at_wall.min() < -5.0
    assert len(np.unique(np.round(at_wall[at_wall < 0.0], 3))) > 3


def test_the_union_front_is_a_distance_function_at_the_wall(speck: Structure) -> None:
    """What link 1 looked like, measured where it did the damage.

    Along the row through the speck's centre the union used to read a flat
    `-4.0` across six columns — the particle's own field, reproduced because the
    seam with the resist above it reads zero. It now ramps a nanometre per cell,
    which is what `|grad(phi)| = 1` means when you write it out.
    """
    front = np.asarray(motion.union_front(speck))
    row = front[120, :8]

    assert np.all(np.diff(row) > 0.5)  # monotonic, and no plateau
    assert row[0] < -8.0  # eight cells from the surface, and it says so


def test_building_the_union_keeps_the_interface_to_the_last_bit(speck: Structure) -> None:
    """The volume is bought with the volume, not with the surface.

    Every measurement in this package — a linewidth, an undercut, a remaining
    thickness — reads the field within a cell of the zero level. A repair that
    improved the volume by moving the surface would be a bad trade, so the cells
    straddling the interface keep `min_m phi[m]` exactly.
    """
    raw = np.asarray(speck.solid_phi)
    front = np.asarray(motion.union_front(speck))
    interface = motion.interface_cells(np.asarray(speck.solid_mask))

    assert interface.any()
    assert np.array_equal(front[interface], raw[interface])


def test_the_wall_is_not_an_interface(speck: Structure) -> None:
    """A domain face is where the model stops, not where the material does.

    `predicates.open_faces` already says so for reachability; the front field has
    to agree, or solid cut by the wall grows a surface it does not have. Read on
    the deepest row of the substrate, which spans the full width: the field must
    keep getting *more* negative towards the wall, never turn back up.
    """
    front = np.asarray(motion.union_front(speck))
    bottom = front[0, :6]

    assert np.all(bottom < 0.0)
    assert bottom[0] <= bottom[-1]
