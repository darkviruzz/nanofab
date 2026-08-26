"""Shared fixtures for the `nanofab_v3` tests, and the one bit of setup they need.

`QT_QPA_PLATFORM=offscreen` is set here, before anything imports Qt, so the
widget tests run on a machine with no display — which is every CI runner and this
repository's own container. `setdefault`, so a developer who wants to watch the
widgets can still export their own platform; and here rather than in
`pyproject.toml` because it has to happen at import time and needs no plugin.

Without it the Qt half of `test_ui.py` and `test_wafer.py` does not fail, it
**skips**, which is worse: a milestone about the UI would ship with every one of
its own tests quietly not running. That is not hypothetical — installing Qt in
this container immediately turned up an M7 regression in the step list that eight
skipped tests had been hiding.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
