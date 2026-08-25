"""Occurrences and their lineage: connected components, matched by overlap.

ADR-0003: a **Materialvorkommen (occurrence)** is a connected region of one
material, derived per revision — never stored. Identity across revisions is
*reconstructed* by overlapping the child's components with the parent's, which
turns a topology change into a finding ("#7 split into #7a/#7b") instead of the
arbitrary bookkeeping choice a stored per-occurrence id would force at exactly
the moment it matters: an etch cutting a film in two, a pinch-off merging two.

Connectivity is face connectivity (4-connected in 2D): two regions touching only
at a corner are not one piece of material.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

from nanofab_v3.materials import MaterialId
from nanofab_v3.model.grid import Grid
from nanofab_v3.model.occurrence import (
    LineageEntry,
    LineageKind,
    LineageReport,
    Occurrence,
    OccurrenceMap,
)
from nanofab_v3.model.structure import Structure


def label_region(grid: Grid, mask: np.ndarray) -> tuple[np.ndarray, int]:
    """Label the connected components of a boolean mask (face connectivity)."""
    connectivity = ndimage.generate_binary_structure(grid.ndim, 1)
    labels, count = ndimage.label(mask, structure=connectivity)
    return labels, int(count)


def label_occurrences(structure: Structure) -> OccurrenceMap:
    """The occurrences of every material in one revision (plan §3.5)."""
    grid = structure.grid
    found: list[Occurrence] = []
    labels: dict[MaterialId, np.ndarray] = {}
    for material in structure.materials:
        label_array, count = label_region(grid, structure.inside(material))
        labels[material] = label_array
        if count == 0:
            continue
        indices = list(range(1, count + 1))
        cells = np.bincount(label_array.ravel(), minlength=count + 1)[1:]
        centres = ndimage.center_of_mass(label_array > 0, label_array, indices)
        for label, centre in zip(indices, centres):
            found.append(
                Occurrence(
                    material=material,
                    label=label,
                    cells=int(cells[label - 1]),
                    measure=float(cells[label - 1]) * grid.cell_measure,
                    centroid=tuple(
                        origin + grid.spacing * float(index)
                        for origin, index in zip(grid.origin, centre)
                    ),
                )
            )
    return OccurrenceMap(occurrences=tuple(found), labels=labels)


def _overlap_matrix(
    parent: np.ndarray, child: np.ndarray, parents: int, children: int
) -> np.ndarray:
    """Cells shared by each parent label and each child label (label 0 excluded)."""
    flat = parent.ravel().astype(np.int64) * (children + 1) + child.ravel().astype(np.int64)
    counts = np.bincount(flat, minlength=(parents + 1) * (children + 1))
    return counts.reshape(parents + 1, children + 1)[1:, 1:]


def _components(links: np.ndarray) -> list[tuple[list[int], list[int]]]:
    """Connected groups of the bipartite parent/child overlap graph."""
    parents, children = links.shape
    seen_parent = [False] * parents
    seen_child = [False] * children
    groups: list[tuple[list[int], list[int]]] = []
    for start in range(parents):
        if seen_parent[start]:
            continue
        parent_group, child_group = [start], []
        seen_parent[start] = True
        queue = [("p", start)]
        while queue:
            side, node = queue.pop()
            neighbours = np.flatnonzero(links[node] if side == "p" else links[:, node])
            for other in neighbours.tolist():
                if side == "p" and not seen_child[other]:
                    seen_child[other] = True
                    child_group.append(other)
                    queue.append(("c", other))
                elif side == "c" and not seen_parent[other]:
                    seen_parent[other] = True
                    parent_group.append(other)
                    queue.append(("p", other))
        groups.append((sorted(parent_group), sorted(child_group)))
    for child in range(children):
        if not seen_child[child]:
            groups.append(([], [child]))
    return groups


def _classify(parents: list[int], children: list[int]) -> LineageKind:
    """ADR-0003's vocabulary for what happened to a group of occurrences."""
    if not parents:
        return "new"
    if not children:
        return "vanished"
    if len(parents) > 1:
        return "merged"
    return "unchanged" if len(children) == 1 else "split"


def match_lineage(parent: OccurrenceMap, child: OccurrenceMap) -> LineageReport:
    """Reconstruct occurrence identity between two revisions by overlap matching.

    Two occurrences are related when they share at least one cell. Everything
    else follows from the shape of that relation: one-to-one is unchanged,
    one-to-many a split, many-to-one a merge, and an unmatched occurrence on
    either side appeared or vanished.
    """
    entries: list[LineageEntry] = []
    materials = list(parent.labels) + [m for m in child.labels if m not in parent.labels]
    for material in materials:
        parent_labels = parent.labels.get(material)
        child_labels = child.labels.get(material)
        parents = parent.count(material)
        children = child.count(material)
        if parents == 0 and children == 0:
            continue
        if parents == 0 or children == 0:
            kind: LineageKind = "new" if parents == 0 else "vanished"
            entries.append(
                LineageEntry(
                    material=material,
                    kind=kind,
                    parents=tuple(range(1, parents + 1)),
                    children=tuple(range(1, children + 1)),
                )
            )
            continue
        links = _overlap_matrix(parent_labels, child_labels, parents, children) > 0
        for parent_group, child_group in _components(links):
            entries.append(
                LineageEntry(
                    material=material,
                    kind=_classify(parent_group, child_group),
                    parents=tuple(label + 1 for label in parent_group),
                    children=tuple(label + 1 for label in child_group),
                )
            )
    return LineageReport(entries=tuple(entries))
