"""`Grid` — the sole spatial authority (plan §3.1)."""

from __future__ import annotations

import numpy as np
import pytest

from nanofab_v3 import Grid


def test_grid_maps_cell_indices_to_positions(grid_2d: Grid) -> None:
    """Cell `(i, j)` sits at `origin + index * spacing`, per axis."""
    grid = Grid(origin=(-100.0, 20.0), spacing=0.25, shape=(40, 60), axes=("y", "x"))

    assert grid.position((0, 0)) == (-100.0, 20.0)
    assert grid.position((4, 8)) == (-99.0, 22.0)
    assert grid.extent("y") == (-100.0, -100.0 + 0.25 * 39)
    assert np.allclose(grid.coordinates("x"), 20.0 + 0.25 * np.arange(60))


def test_grid_reports_its_shape(grid_2d: Grid) -> None:
    assert grid_2d.ndim == 2
    assert grid_2d.size == 200 * 300
    assert grid_2d.cell_measure == 1.0


def test_axes_are_named_not_positional(grid_3d: Grid) -> None:
    """Kernel code addresses axes by name; 3D just adds one."""
    assert grid_3d.ndim == 3
    assert grid_3d.axis_index("x") == 2
    assert grid_3d.axis_index("z") == 0
    assert grid_3d.cell_measure == 8.0
    with pytest.raises(ValueError, match="unknown axis"):
        grid_3d.axis_index("theta")


def test_mesh_broadcasts_over_the_grid(grid_3d: Grid) -> None:
    """The open mesh is what every constructor samples on."""
    mesh = grid_3d.mesh()

    assert len(mesh) == 3
    assert np.broadcast_shapes(*[m.shape for m in mesh]) == grid_3d.shape
    assert mesh[1][0, 3, 0] == grid_3d.position((0, 3, 0))[1]


def test_grid_rejects_inconsistent_definitions() -> None:
    with pytest.raises(ValueError, match="same length"):
        Grid(origin=(0.0,), spacing=1.0, shape=(10, 10), axes=("y", "x"))
    with pytest.raises(ValueError, match="positive finite"):
        Grid(origin=(0.0, 0.0), spacing=0.0, shape=(10, 10), axes=("y", "x"))
    with pytest.raises(ValueError, match="at least one cell"):
        Grid(origin=(0.0, 0.0), spacing=1.0, shape=(10, 0), axes=("y", "x"))
    with pytest.raises(ValueError, match="unique"):
        Grid(origin=(0.0, 0.0), spacing=1.0, shape=(10, 10), axes=("x", "x"))


def test_as_field_validates_against_the_grid(grid_2d: Grid) -> None:
    """Nothing enters a `Structure` without being checked against the grid."""
    values = np.zeros(grid_2d.shape, dtype=np.float64)

    assert grid_2d.as_field(values).dtype == np.float32
    with pytest.raises(ValueError, match="does not match grid shape"):
        grid_2d.as_field(np.zeros((3, 3)))


def test_grid_is_a_frozen_value(grid_2d: Grid) -> None:
    """Two grids with the same definition are the same grid."""
    same = Grid(origin=(0.0, 0.0), spacing=1.0, shape=(200, 300), axes=("y", "x"))

    assert same == grid_2d
    grid_2d.check_same_grid([same])
    with pytest.raises(ValueError, match="same Grid"):
        grid_2d.check_same_grid([Grid((0.0, 0.0), 2.0, (200, 300), ("y", "x"))])
