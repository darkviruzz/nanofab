"""Constructors: analytic primitives sampled onto the `Grid`, once (plan §4.1)."""

from __future__ import annotations

import numpy as np
import pytest

from nanofab_v3 import Grid, Structure
from nanofab_v3.kernel import constructors as ctor
from nanofab_v3.kernel import invariants


def test_box_is_an_exact_distance_field(grid_2d: Grid) -> None:
    """Distance to the nearest face inside, Euclidean distance outside."""
    phi = ctor.box(grid_2d, lower=(50.0, 100.0), upper=(90.0, 200.0))

    assert phi[70, 150] == pytest.approx(-20.0)  # nearest face is 20 nm up/down
    assert phi[100, 150] == pytest.approx(10.0)  # 10 nm above the top face
    assert phi[50, 100] == pytest.approx(0.0)  # exactly on the corner
    assert phi[93, 204] == pytest.approx(5.0)  # diagonal: sqrt(3^2 + 4^2)


def test_box_side_may_be_unbounded(grid_2d: Grid) -> None:
    """`None` turns the box into a slab — what stack constructors need."""
    slab = ctor.box(grid_2d, lower=(50.0, None), upper=(90.0, None))

    assert np.array_equal(slab, slab[:, :1].repeat(grid_2d.shape[1], axis=1))
    assert slab[70, 0] == pytest.approx(-20.0)
    with pytest.raises(ValueError, match="at least one finite bound"):
        ctor.box(grid_2d, lower=(None, None), upper=(None, None))


def test_box_rejects_inverted_bounds(grid_2d: Grid) -> None:
    with pytest.raises(ValueError, match="inverted"):
        ctor.box(grid_2d, lower=(90.0, 100.0), upper=(50.0, 200.0))


def test_rounded_box_rounds_only_the_corners(grid_2d: Grid) -> None:
    """Faces stay where they were; corners are pulled in by `radius`."""
    radius = 10.0
    sharp = ctor.box(grid_2d, lower=(50.0, 100.0), upper=(90.0, 200.0))
    rounded = ctor.rounded_box(grid_2d, lower=(50.0, 100.0), upper=(90.0, 200.0), radius=radius)

    assert rounded[70, 150] == pytest.approx(sharp[70, 150])  # mid-face unchanged
    # The sharp corner now lies outside, by the arc's sagitta.
    assert rounded[50, 100] == pytest.approx(radius * (np.sqrt(2.0) - 1.0), abs=1e-5)
    assert rounded[60, 110] == pytest.approx(-radius)  # centre of the corner arc
    assert np.count_nonzero(rounded < 0) < np.count_nonzero(sharp < 0)


def test_rounded_box_needs_a_radius_that_fits(grid_2d: Grid) -> None:
    with pytest.raises(ValueError, match="does not fit"):
        ctor.rounded_box(grid_2d, lower=(50.0, 100.0), upper=(60.0, 200.0), radius=20.0)


def test_ball_is_an_exact_distance_field(grid_2d: Grid) -> None:
    """The primitive behind particles: `|x - c| - r`, exact everywhere."""
    phi = ctor.ball(grid_2d, center=(100.0, 150.0), radius=30.0)

    assert phi[100, 150] == pytest.approx(-30.0)
    assert phi[100, 180] == pytest.approx(0.0)
    assert phi[140, 150] == pytest.approx(10.0)
    assert invariants.band_gradient_error(grid_2d, phi) < 0.01


def test_constructors_are_n_d_generic(grid_3d: Grid) -> None:
    """3D adds an axis to the `Grid` — the constructors do not change."""
    plane = ctor.half_space(grid_3d, normal=(0.0, 0.0, 1.0), point=(0.0, 0.0, 40.0))
    brick = ctor.box(grid_3d, lower=(10.0, 20.0, 30.0), upper=(20.0, 40.0, 50.0))
    sphere = ctor.ball(grid_3d, center=(20.0, 30.0, 40.0), radius=10.0)

    for phi in (plane, brick, sphere):
        assert phi.shape == grid_3d.shape
        assert phi.dtype == np.float32
    assert sphere[10, 15, 20] == pytest.approx(-10.0)


def test_constructors_check_their_arguments(grid_2d: Grid) -> None:
    with pytest.raises(ValueError, match="one per axis"):
        ctor.ball(grid_2d, center=(1.0, 2.0, 3.0), radius=5.0)
    with pytest.raises(ValueError, match="non-zero finite"):
        ctor.half_space(grid_2d, normal=(0.0, 0.0), point=(0.0, 0.0))
    with pytest.raises(ValueError, match="positive finite"):
        ctor.ball(grid_2d, center=(0.0, 0.0), radius=-1.0)


def test_add_material_unions_primitives_of_one_material(grid_2d: Grid) -> None:
    """A material may be built from several primitives."""
    structure = Structure(grid_2d)
    structure = ctor.add_material(
        structure, "particle", ctor.ball(grid_2d, center=(120.0, 100.0), radius=10.0)
    )
    structure = ctor.add_material(
        structure, "particle", ctor.ball(grid_2d, center=(120.0, 200.0), radius=10.0)
    )

    assert structure.materials == ("particle",)
    assert structure.inside("particle")[120, 100]
    assert structure.inside("particle")[120, 200]
    assert not structure.inside("particle")[120, 150]


def test_add_material_returns_a_new_structure(grid_2d: Grid) -> None:
    """Constructors are pure: the input revision is never mutated."""
    before = Structure(grid_2d)
    after = ctor.add_material(
        before, "silicon", ctor.half_space(grid_2d, normal=(1.0, 0.0), point=(60.0, 0.0))
    )

    assert before.materials == ()
    assert after.materials == ("silicon",)
