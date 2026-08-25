"""Marching squares: contours of a field for rendering and debug (plan §10).

Rendering is a **consumer** of the kernel, never the other way round (plan §4):
this module turns a sampled field into polylines; it has no say in the physics.
No scikit-image dependency — the marching-squares case analysis is generated from
the corner signs instead of a 16-entry table.

This is one of the two deliberately 2D-only seams of the v2 core (plan §4.3, Q7);
it raises on any grid that is not 2-D rather than pretending to be N-D generic.

Output convention:

- points are `(N, ndim)` float64 arrays in **nm**, in the grid's axis order
  (`grid.axes`) — the renderer decides which axis is drawn where;
- closed loops repeat their first point at the end; open polylines (contours that
  leave the domain) do not;
- segments are oriented so that the region `field < level` lies to the **left**
  of the direction of travel when the first grid axis is drawn upwards and the
  second to the right.
"""

from __future__ import annotations

import numpy as np

from nanofab_v3.materials import MaterialId
from nanofab_v3.model.grid import Grid
from nanofab_v3.model.structure import Structure

# An edge of the cell lattice, used as the identity a contour is stitched on:
# (0, i, j) is the edge from cell (i, j) to (i, j+1), (1, i, j) the one to (i+1, j).
EdgeKey = tuple[int, int, int]


def _edge_point(field: np.ndarray, spacing: float, origin, edge: EdgeKey, level: float) -> tuple:
    """Interpolate the level crossing on one lattice edge, in nm.

    Always evaluated from the lower-index corner towards the higher-index one, so
    the two cells sharing an edge produce a bit-identical point.
    """
    kind, i, j = edge
    a = float(field[i, j])
    b = float(field[i, j + 1]) if kind == 0 else float(field[i + 1, j])
    t = (level - a) / (b - a)
    if kind == 0:
        return (origin[0] + spacing * i, origin[1] + spacing * (j + t))
    return (origin[0] + spacing * (i + t), origin[1] + spacing * j)


def marching_squares(grid: Grid, field: np.ndarray, level: float = 0.0) -> list[np.ndarray]:
    """Contours of `field` at `level`, as polylines in nm (see module docstring)."""
    if grid.ndim != 2:
        raise ValueError(f"marching squares is 2D-only, grid has {grid.ndim} axes")
    values = grid.as_field(field, dtype=np.float64)
    level = float(level)

    inside = values < level
    ny, nx = values.shape
    if ny < 2 or nx < 2:
        return []

    # Corners of every cell, going counter-clockwise: (i,j) (i,j+1) (i+1,j+1) (i+1,j).
    corners = (inside[:-1, :-1], inside[:-1, 1:], inside[1:, 1:], inside[1:, :-1])
    edges_of_cell = (  # the lattice edge between corner k and corner k+1
        lambda i, j: (0, i, j),  # (i,j) -> (i,j+1)
        lambda i, j: (1, i, j + 1),  # (i,j+1) -> (i+1,j+1)
        lambda i, j: (0, i + 1, j),  # (i+1,j+1) -> (i+1,j)
        lambda i, j: (1, i, j),  # (i+1,j) -> (i,j)
    )
    crossing = np.zeros(corners[0].shape, dtype=bool)
    for k in range(4):
        crossing |= corners[k] != corners[(k + 1) % 4]

    segments: list[tuple[EdgeKey, EdgeKey]] = []
    for i, j in np.argwhere(crossing):
        i, j = int(i), int(j)
        side = [bool(corners[k][i, j]) for k in range(4)]
        # Walking the cell boundary counter-clockwise, the contour runs from an
        # inside->outside crossing to an outside->inside one; that orientation is
        # what puts `field < level` on the left.
        starts = [k for k in range(4) if side[k] and not side[(k + 1) % 4]]
        ends = [k for k in range(4) if not side[k] and side[(k + 1) % 4]]
        if len(starts) == 2:
            # Saddle: the cell centre decides which pair of corners is connected.
            centre = 0.25 * float(
                values[i, j] + values[i, j + 1] + values[i + 1, j + 1] + values[i + 1, j]
            )
            step = -1 if centre >= level else 1
        else:
            step = 1
        for start in starts:
            candidates = ((start + step * n) % 4 for n in range(1, 4))
            end = next(k for k in candidates if k in ends)
            segments.append((edges_of_cell[start](i, j), edges_of_cell[end](i, j)))

    return _stitch(segments, values, grid, level)


def _stitch(
    segments: list[tuple[EdgeKey, EdgeKey]],
    values: np.ndarray,
    grid: Grid,
    level: float,
) -> list[np.ndarray]:
    """Chain oriented segments into open polylines and closed loops."""
    if not segments:
        return []
    successor = {start: end for start, end in segments}
    if len(successor) != len(segments):  # pragma: no cover - guarded by orientation
        raise AssertionError("marching squares produced two segments starting on one edge")
    incoming = {end for _, end in segments}

    point_cache: dict[EdgeKey, tuple] = {}

    def point(edge: EdgeKey) -> tuple:
        if edge not in point_cache:
            point_cache[edge] = _edge_point(values, grid.spacing, grid.origin, edge, level)
        return point_cache[edge]

    def walk(first: EdgeKey) -> np.ndarray:
        chain = [first]
        edge = first
        while True:
            edge = successor[edge]
            chain.append(edge)
            visited.add(edge)
            if edge == first or edge not in successor:
                break
        return np.array([point(e) for e in chain], dtype=np.float64)

    visited: set[EdgeKey] = set()
    contours: list[np.ndarray] = []
    # Open contours first: they start on an edge nothing leads into.
    for start in successor:
        if start not in incoming and start not in visited:
            visited.add(start)
            contours.append(walk(start))
    # Whatever is left is a closed loop.
    for start in successor:
        if start not in visited:
            visited.add(start)
            contours.append(walk(start))
    return contours


def material_contours(
    structure: Structure, level: float = 0.0
) -> dict[MaterialId, list[np.ndarray]]:
    """Contours of every material's signed-distance field — the render input."""
    return {
        material: marching_squares(structure.grid, phi, level)
        for material, phi in structure.phi.items()
    }


def contour_length(contours: list[np.ndarray]) -> float:
    """Total polyline length in nm — a cheap check on a contour set."""
    steps = (np.linalg.norm(np.diff(c, axis=0), axis=1) for c in contours if len(c) > 1)
    return float(sum(np.sum(s) for s in steps))
