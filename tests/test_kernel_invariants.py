"""Kernel invariants — plan §13, layer 1 (the definition of done for M0).

Three properties the whole v2 structure model rests on:

1. **Constructor exactness on planes** — a half-space is exactly representable,
   so its zero level lands exactly on the grid (ADR-0002).
2. **Pairwise disjointness** — constructed materials never share interior cells
   (plan §3.2, guaranteed by construction and verified cheaply here).
3. **Symmetric scenes stay symmetric** — no operation in the kernel introduces a
   handedness the scene did not have.
"""

from __future__ import annotations

import numpy as np
import pytest

from nanofab_v3 import Grid, Structure
from nanofab_v3.kernel import constructors as ctor
from nanofab_v3.kernel import contours, csg, invariants

# -- 1. constructor exactness on planes --------------------------------------


def test_half_space_zero_level_lies_exactly_on_a_grid_row(grid_2d: Grid) -> None:
    """A substrate surface placed on a grid row is sampled as exactly zero there.

    The measured reference from the v2 design probes (memory.md 2026-08-25):
    a half-plane SDF is exact on the grid — max |phi| on the surface row is 0.0,
    not "small".
    """
    surface_y = 60.0
    phi = ctor.half_space(grid_2d, normal=(1.0, 0.0), point=(surface_y, 0.0))
    row = int(surface_y / grid_2d.spacing)

    assert np.max(np.abs(phi[row])) == 0.0
    assert np.count_nonzero(phi[row]) == 0
    # ... and the sampled field *is* the analytic one, everywhere.
    y = grid_2d.mesh()[0]
    assert np.array_equal(phi, np.broadcast_to(y - surface_y, phi.shape).astype(phi.dtype))


def test_half_space_is_exact_for_a_tilted_plane(grid_2d: Grid) -> None:
    """Off-axis planes stay exact too: sampled phi equals the analytic distance."""
    normal = np.array([0.6, 0.8])
    point = np.array([80.0, 150.0])
    phi = ctor.half_space(grid_2d, normal=normal, point=point)

    y, x = grid_2d.mesh()
    analytic = normal[0] * (y - point[0]) + normal[1] * (x - point[1])
    assert np.max(np.abs(phi - analytic)) < 1e-4  # float32 storage, ~1e-7 relative


def test_plane_contour_reproduces_the_analytic_plane(grid_2d: Grid) -> None:
    """The reconstructed zero level of a plane sits on the analytic plane.

    This is the property that makes "analytics is only a constructor" (ADR-0002)
    affordable: the grid loses nothing on a plane.
    """
    normal = np.array([0.6, 0.8])
    point = np.array([80.0, 150.0])
    phi = ctor.half_space(grid_2d, normal=normal, point=point)

    lines = contours.marching_squares(grid_2d, phi)
    assert len(lines) == 1
    points = lines[0]
    distance = (points - point) @ normal
    assert np.max(np.abs(distance)) < 1e-4


def test_half_space_normal_points_out_of_the_material(grid_2d: Grid) -> None:
    """`phi < 0` is on the side the normal points away from."""
    phi = ctor.half_space(grid_2d, normal=(1.0, 0.0), point=(60.0, 0.0))
    assert phi[0, 0] < 0.0  # below the surface: material
    assert phi[-1, 0] > 0.0  # above it: empty


def test_plane_gradient_has_unit_magnitude(grid_2d: Grid) -> None:
    """A constructed plane satisfies the band invariant `|grad(phi)| = 1` (plan §3.2)."""
    phi = ctor.half_space(grid_2d, normal=(0.6, 0.8), point=(80.0, 150.0))
    assert invariants.band_gradient_error(grid_2d, phi) < 1e-5


# -- 2. pairwise disjointness of constructed materials -----------------------


def _stack(grid: Grid) -> Structure:
    """Substrate / film / resist, each primitive deliberately overlapping the last."""
    structure = Structure(grid)
    structure = ctor.add_material(
        structure, "silicon", ctor.half_space(grid, normal=(1.0, 0.0), point=(60.0, 0.0))
    )
    structure = ctor.add_material(
        structure, "metal", ctor.box(grid, lower=(55.0, None), upper=(80.0, None))
    )
    structure = ctor.add_material(
        structure, "resist", ctor.box(grid, lower=(70.0, 100.0), upper=(120.0, 200.0))
    )
    return structure


def test_constructed_materials_have_disjoint_interiors(grid_2d: Grid) -> None:
    """Overlapping primitives are carved against the existing solid on placement."""
    structure = _stack(grid_2d)

    assert invariants.pairwise_overlap(structure) == {}
    assert invariants.max_overlap_depth(structure) == 0.0


def test_carving_gives_the_existing_material_precedence(grid_2d: Grid) -> None:
    """The film starts where the substrate ends, not where its primitive did."""
    structure = _stack(grid_2d)
    metal = structure.inside("metal")

    assert not metal[:61].any()  # substrate owns everything up to y = 60
    assert metal[61:80].all()
    assert not structure.inside("resist")[:81].any()  # film owns up to y = 80


def test_without_carving_the_overlap_is_real(grid_2d: Grid) -> None:
    """The disjointness above is produced by `add_material`, not by the scene."""
    structure = Structure(grid_2d)
    structure = ctor.add_material(
        structure, "silicon", ctor.half_space(grid_2d, normal=(1.0, 0.0), point=(60.0, 0.0))
    )
    structure = ctor.add_material(
        structure,
        "metal",
        ctor.box(grid_2d, lower=(55.0, None), upper=(80.0, None)),
        carve=False,
    )

    assert invariants.pairwise_overlap(structure) != {}
    # The primitives overlap in a 5 nm band (y = 55..60); the deepest cell inside
    # both is 2 nm from either surface, the band's mid-plane falling between rows.
    assert invariants.max_overlap_depth(structure) == pytest.approx(2.0)


def test_material_index_partitions_the_solid(grid_2d: Grid) -> None:
    """The derived index map gives every solid cell to exactly one material.

    Ownership is a partition, interiors are strict: a cell sitting exactly on the
    interface between two materials is interior to neither but is owned by one,
    which is what keeps the solid free of one-cell cracks without letting two
    materials claim the same interior.
    """
    structure = _stack(grid_2d)
    index = structure.material_index

    owned = np.zeros(grid_2d.shape, dtype=bool)
    for position, material in enumerate(structure.materials):
        selected = index == position
        assert not np.any(selected & owned), "two materials own the same cell"
        assert np.all(structure.phi_of(material)[selected] <= 0.0)
        assert np.all(selected[structure.inside(material)]), "an interior cell went unowned"
        owned |= selected
    assert np.array_equal(owned, structure.solid_mask)
    assert np.array_equal(index < 0, ~structure.solid_mask)


def test_solid_union_is_the_pointwise_minimum(grid_2d: Grid) -> None:
    """`solid_phi` is derived, and derived exactly as the plan states."""
    structure = _stack(grid_2d)
    expected = csg.union(*[structure.phi_of(m) for m in structure.materials])

    assert np.array_equal(structure.solid_phi, expected)
    assert np.array_equal(structure.empty_phi, -expected)


# -- 3. symmetric scenes stay symmetric --------------------------------------


def _mirror(array: np.ndarray) -> np.ndarray:
    """Mirror an array on its last axis (`x` in the test grids)."""
    return array[..., ::-1]


def _symmetric_scene(grid: Grid) -> Structure:
    """A scene built symmetrically about the grid's x mid-plane."""
    structure = Structure(grid)
    structure = ctor.add_material(
        structure, "silicon", ctor.half_space(grid, normal=(1.0, 0.0), point=(40.0, 0.0))
    )
    structure = ctor.add_material(
        structure, "metal", ctor.box(grid, lower=(40.0, 80.0), upper=(90.0, 120.0))
    )
    # One material, two mirrored particles: the *scene* is symmetric, the
    # primitives are not.
    particles = csg.union(
        ctor.ball(grid, center=(100.0, 40.0), radius=15.0),
        ctor.ball(grid, center=(100.0, 160.0), radius=15.0),
    )
    return ctor.add_material(structure, "particle", particles)


def test_symmetric_scene_stays_symmetric(mirror_grid: Grid) -> None:
    """Every constructed field of a mirror-symmetric scene is mirror-symmetric.

    Bit-exact, not "within tolerance": the constructors and the set operations are
    pointwise, so a symmetric scene has no way to acquire a handedness.
    """
    structure = _symmetric_scene(mirror_grid)

    for material in structure.materials:
        phi = structure.phi_of(material)
        assert np.array_equal(phi, _mirror(phi)), f"{material} lost its symmetry"
    assert np.array_equal(structure.solid_phi, _mirror(structure.solid_phi))
    assert np.array_equal(structure.material_index, _mirror(structure.material_index))


def test_set_operations_preserve_symmetry(mirror_grid: Grid) -> None:
    """Union, difference and offset keep a symmetric scene symmetric."""
    structure = _symmetric_scene(mirror_grid)
    solid = structure.solid_phi

    grown = csg.offset(solid, 7.0)
    carved = csg.difference(grown, ctor.box(mirror_grid, lower=(95.0, 90.0), upper=(105.0, 110.0)))

    assert np.array_equal(grown, _mirror(grown))
    assert np.array_equal(carved, _mirror(carved))


def test_symmetric_scene_has_symmetric_contours(mirror_grid: Grid) -> None:
    """The rendering path inherits the symmetry, down to the contour points."""
    structure = _symmetric_scene(mirror_grid)
    lines = contours.marching_squares(mirror_grid, structure.solid_phi)

    points = np.concatenate(lines)
    x_min, x_max = mirror_grid.extent("x")
    mirrored = points.copy()
    mirrored[:, 1] = (x_min + x_max) - mirrored[:, 1]

    # As point sets: which point a closed loop happens to start on is bookkeeping,
    # not geometry (`np.unique` also sorts, so the two sets line up).
    assert np.allclose(np.unique(points, axis=0), np.unique(mirrored, axis=0), atol=1e-9)
