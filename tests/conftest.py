"""Shared fixtures for the `nanofab_v3` tests."""

from __future__ import annotations

import pytest

from nanofab_v3 import Grid


@pytest.fixture
def grid_2d() -> Grid:
    """A plain 2D cross-section grid at 1 nm/cell (the plan's default resolution)."""
    return Grid(origin=(0.0, 0.0), spacing=1.0, shape=(200, 300), axes=("y", "x"))


@pytest.fixture
def grid_3d() -> Grid:
    """A 3D grid — used to hold the kernel to its N-D genericity (plan §3.1)."""
    return Grid(origin=(0.0, 0.0, 0.0), spacing=2.0, shape=(20, 30, 40), axes=("z", "y", "x"))


@pytest.fixture
def mirror_grid() -> Grid:
    """A 2D grid with an odd x extent, so a scene can be mirrored cell-exactly."""
    return Grid(origin=(0.0, 0.0), spacing=1.0, shape=(160, 201), axes=("y", "x"))
