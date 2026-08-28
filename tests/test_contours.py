"""Marching squares: the rendering/debug consumer of the kernel (plan §10)."""

from __future__ import annotations

import numpy as np
import pytest

from nanofab_v3 import Grid, Structure
from nanofab_v3.kernel import constructors as ctor
from nanofab_v3.kernel import contours, csg


@pytest.fixture
def disk_grid() -> Grid:
    return Grid(origin=(-100.0, -100.0), spacing=1.0, shape=(201, 201), axes=("y", "x"))


def _signed_area(polyline: np.ndarray) -> float:
    """Shoelace area with the first grid axis up and the second to the right."""
    y, x = polyline[:, 0], polyline[:, 1]
    return 0.5 * float(np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))


def test_disk_contour_is_one_closed_loop_on_the_circle(disk_grid: Grid) -> None:
    """Sub-cell accurate: linear interpolation puts every point on the circle."""
    radius = 50.0
    phi = ctor.ball(disk_grid, center=(0.0, 0.0), radius=radius)

    lines = contours.marching_squares(disk_grid, phi)
    assert len(lines) == 1
    loop = lines[0]
    assert np.array_equal(loop[0], loop[-1])  # closed loops repeat their first point

    distance = np.linalg.norm(loop, axis=1)
    assert np.max(np.abs(distance - radius)) < 0.02
    assert contours.contour_length(lines) == pytest.approx(2 * np.pi * radius, rel=1e-3)
    assert _signed_area(loop) == pytest.approx(np.pi * radius**2, rel=1e-3)


def test_contours_put_the_material_on_the_left(disk_grid: Grid) -> None:
    """An enclosed void runs the other way round than the outer surface.

    Orientation is the property that lets a renderer fill a ring correctly, and
    the one that makes stitching unambiguous.
    """
    ring = csg.difference(
        ctor.ball(disk_grid, center=(0.0, 0.0), radius=50.0),
        ctor.ball(disk_grid, center=(0.0, 0.0), radius=20.0),
    )

    lines = contours.marching_squares(disk_grid, ring)
    assert len(lines) == 2
    areas = sorted(_signed_area(line) for line in lines)
    assert areas[1] == pytest.approx(np.pi * 50.0**2, rel=1e-3)  # outer, positive
    assert areas[0] == pytest.approx(-np.pi * 20.0**2, rel=1e-3)  # inner, negative
    assert sum(areas) == pytest.approx(np.pi * (50.0**2 - 20.0**2), rel=1e-3)


def test_separate_regions_give_separate_contours(disk_grid: Grid) -> None:
    two_disks = csg.union(
        ctor.ball(disk_grid, center=(0.0, -50.0), radius=20.0),
        ctor.ball(disk_grid, center=(0.0, 50.0), radius=20.0),
    )

    assert len(contours.marching_squares(disk_grid, two_disks)) == 2


def test_plane_contour_is_an_open_polyline_on_the_exact_row(grid_2d: Grid) -> None:
    """A contour that leaves the domain stays open and is not closed up."""
    phi = ctor.half_space(grid_2d, normal=(1.0, 0.0), point=(60.0, 0.0))

    lines = contours.marching_squares(grid_2d, phi)
    assert len(lines) == 1
    points = lines[0]
    assert len(points) == grid_2d.shape[1]
    assert np.all(points[:, 0] == 60.0)
    assert not np.array_equal(points[0], points[-1])


def test_contour_points_are_in_grid_axis_order(grid_2d: Grid) -> None:
    """Points are `(axis0, axis1)` in nm — the renderer decides what is drawn where."""
    phi = ctor.box(grid_2d, lower=(50.0, 100.0), upper=(90.0, 200.0))

    points = contours.marching_squares(grid_2d, phi)[0]
    assert points.shape[1] == grid_2d.ndim
    assert points[:, 0].min() == pytest.approx(50.0)
    assert points[:, 1].max() == pytest.approx(200.0)


def test_level_other_than_zero(disk_grid: Grid) -> None:
    """Any level works — useful for debugging a narrow band."""
    phi = ctor.ball(disk_grid, center=(0.0, 0.0), radius=50.0)

    lines = contours.marching_squares(disk_grid, phi, level=10.0)
    assert contours.contour_length(lines) == pytest.approx(2 * np.pi * 60.0, rel=1e-3)


def test_saddle_cells_separate_the_connected_corners() -> None:
    """The ambiguous case is resolved by the cell centre, not by luck."""
    grid = Grid(origin=(0.0, 0.0), spacing=1.0, shape=(2, 2), axes=("y", "x"))

    # Centre outside: the two inside corners are separate islands.
    separate = contours.marching_squares(grid, np.array([[-1.0, 2.0], [2.0, -1.0]]))
    # Centre inside: the inside corners are connected, the outside ones are cut off.
    connected = contours.marching_squares(grid, np.array([[-2.0, 1.0], [1.0, -2.0]]))

    assert len(separate) == len(connected) == 2
    # Each segment cuts off the corner it sits closest to.
    separate_corners = {tuple(np.round(np.mean(line, axis=0))) for line in separate}
    connected_corners = {tuple(np.round(np.mean(line, axis=0))) for line in connected}
    assert separate_corners == {(0.0, 0.0), (1.0, 1.0)}  # the two inside corners
    assert connected_corners == {(0.0, 1.0), (1.0, 0.0)}  # the two outside corners


def test_uniform_field_has_no_contour(grid_2d: Grid) -> None:
    assert contours.marching_squares(grid_2d, grid_2d.full(1.0)) == []
    assert contours.contour_length([]) == 0.0


def test_material_contours_cover_every_material(grid_2d: Grid) -> None:
    structure = Structure(grid_2d)
    structure = ctor.add_material(
        structure, "silicon", ctor.half_space(grid_2d, normal=(1.0, 0.0), point=(60.0, 0.0))
    )
    structure = ctor.add_material(
        structure, "metal", ctor.box(grid_2d, lower=(55.0, 100.0), upper=(80.0, 200.0))
    )

    per_material = contours.material_contours(structure)
    assert set(per_material) == {"silicon", "metal"}
    assert all(lines for lines in per_material.values())


def test_marching_squares_is_2d_only(grid_3d: Grid) -> None:
    """One of the two named 2D seams of the v2 core (plan §4.3, Q7)."""
    with pytest.raises(ValueError, match="2D-only"):
        contours.marching_squares(grid_3d, grid_3d.zeros())
