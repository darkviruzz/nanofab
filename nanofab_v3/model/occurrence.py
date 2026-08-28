"""`Occurrence` (Materialvorkommen) and its lineage — derived, never stored.

`CONTEXT.md` / ADR-0003: an occurrence is a connected region of one material,
derived per revision by connected-component labelling. Identity across revisions
is **reconstructed** by overlap matching against the parent revision, never
stored — which is what turns an etch splitting a film, or a pinch-off merging
two, into a finding instead of an arbitrary bookkeeping choice.

The records here are pure data; `nanofab_v3.kernel.occurrences` computes them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from nanofab_v3.materials import MaterialId

LineageKind = Literal["unchanged", "split", "merged", "new", "vanished"]
"""How an occurrence relates to the parent revision (ADR-0003)."""


@dataclass(frozen=True)
class Occurrence:
    """One connected region of one material at one revision.

    Attributes:
        material: The material this region belongs to.
        label: Component label within that material, `1..n` — an index into the
            revision's labelling, not an identity that survives it.
        cells: Number of cells in the region.
        measure: Area (2D) / volume (3D) in nm^ndim.
        centroid: Centre of mass in nm, in the grid's axis order.
    """

    material: MaterialId
    label: int
    cells: int
    measure: float
    centroid: tuple[float, ...]


@dataclass(frozen=True)
class OccurrenceMap:
    """The occurrences of one revision, with the label array they came from.

    Attributes:
        occurrences: Every occurrence of every material.
        labels: Per material, the connected-component label array (0 = outside).
            Kept so lineage can be matched by overlap; it is a derived view of
            the revision, not part of the stored `Structure`.
    """

    occurrences: tuple[Occurrence, ...]
    labels: dict[MaterialId, np.ndarray]

    def of(self, material: MaterialId) -> tuple[Occurrence, ...]:
        """The occurrences of one material, in label order."""
        return tuple(o for o in self.occurrences if o.material == material)

    def count(self, material: MaterialId | None = None) -> int:
        """How many occurrences there are, in total or for one material."""
        if material is None:
            return len(self.occurrences)
        return len(self.of(material))


@dataclass(frozen=True)
class LineageEntry:
    """What became of one occurrence between two revisions.

    `parents` and `children` are labels within `material`; the wording of
    ADR-0003 ("#7 split into #7a/#7b") is what `describe()` renders.
    """

    material: MaterialId
    kind: LineageKind
    parents: tuple[int, ...]
    children: tuple[int, ...]

    def describe(self) -> str:
        """One human-readable line, as the UI surfaces it."""
        parents = ", ".join(f"#{label}" for label in self.parents)
        children = ", ".join(f"#{label}" for label in self.children)
        if self.kind == "unchanged":
            return f"{self.material} {parents} unchanged"
        if self.kind == "split":
            return f"{self.material} {parents} split into {children}"
        if self.kind == "merged":
            return f"{self.material} {parents} merged into {children}"
        if self.kind == "new":
            return f"{self.material} {children} appeared"
        return f"{self.material} {parents} vanished"


@dataclass(frozen=True)
class LineageReport:
    """The occurrence lineage of one step (plan §3.5, ADR-0003)."""

    entries: tuple[LineageEntry, ...] = ()

    def of_kind(self, kind: LineageKind) -> tuple[LineageEntry, ...]:
        """Every entry of one kind — `"split"` and `"merged"` are the findings."""
        return tuple(entry for entry in self.entries if entry.kind == kind)

    @property
    def topology_changed(self) -> bool:
        """Whether anything split, merged, appeared or vanished."""
        return any(entry.kind != "unchanged" for entry in self.entries)

    def describe(self) -> tuple[str, ...]:
        """The report as lines, skipping the occurrences that just stayed put."""
        return tuple(entry.describe() for entry in self.entries if entry.kind != "unchanged")
