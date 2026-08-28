"""Occurrences and lineage — ADR-0003, plan §3.5.

Identity is *reconstructed*, never stored. The test of that design is what it
does at the moments a stored id would have to guess: an etch cutting a film in
two, and a deposition merging two islands.
"""

from __future__ import annotations

import numpy as np
import pytest

from nanofab_v3 import Grid, Structure
from nanofab_v3.kernel import constructors as ctor
from nanofab_v3.kernel import csg, occurrences


def _two_islands(grid: Grid) -> Structure:
    islands = csg.union(
        ctor.ball(grid, center=(100.0, 80.0), radius=25.0),
        ctor.ball(grid, center=(100.0, 220.0), radius=25.0),
    )
    return ctor.add_material(Structure(grid), "metal", islands)


def _one_island(grid: Grid) -> Structure:
    return ctor.add_material(
        Structure(grid), "metal", ctor.box(grid, lower=(80.0, 60.0), upper=(120.0, 240.0))
    )


def test_occurrences_are_connected_components(grid_2d: Grid) -> None:
    found = occurrences.label_occurrences(_two_islands(grid_2d))

    assert found.count("metal") == 2
    first, second = found.of("metal")
    assert first.cells == pytest.approx(second.cells, rel=0.02)
    assert first.centroid[1] == pytest.approx(80.0, abs=1.0)
    assert second.centroid[1] == pytest.approx(220.0, abs=1.0)
    assert first.measure == first.cells * grid_2d.cell_measure


def test_occurrences_are_per_material(grid_2d: Grid) -> None:
    structure = ctor.add_material(
        _two_islands(grid_2d),
        "silicon",
        ctor.half_space(grid_2d, normal=(1.0, 0.0), point=(60.0, 0.0)),
    )

    found = occurrences.label_occurrences(structure)

    assert found.count("metal") == 2
    assert found.count("silicon") == 1
    assert found.count() == 3


def test_diagonal_contact_is_not_connection(grid_2d: Grid) -> None:
    """Face connectivity: two blocks meeting at a corner are two occurrences."""
    values = grid_2d.full(1.0)
    values[10:20, 10:20] = -1.0
    values[20:30, 20:30] = -1.0
    structure = Structure(grid_2d, {"metal": values})

    assert occurrences.label_occurrences(structure).count("metal") == 2


def test_a_split_is_reported_as_a_split(grid_2d: Grid) -> None:
    parent = occurrences.label_occurrences(_one_island(grid_2d))
    child = occurrences.label_occurrences(_two_islands(grid_2d))

    report = occurrences.match_lineage(parent, child)

    assert [entry.kind for entry in report.entries] == ["split"]
    assert report.entries[0].parents == (1,)
    assert report.entries[0].children == (1, 2)
    assert report.describe() == ("metal #1 split into #1, #2",)


def test_a_merge_is_reported_as_a_merge(grid_2d: Grid) -> None:
    parent = occurrences.label_occurrences(_two_islands(grid_2d))
    child = occurrences.label_occurrences(_one_island(grid_2d))

    report = occurrences.match_lineage(parent, child)

    assert [entry.kind for entry in report.entries] == ["merged"]
    assert report.entries[0].parents == (1, 2)
    assert report.describe() == ("metal #1, #2 merged into #1",)


def test_an_unchanged_occurrence_is_reported_as_unchanged(grid_2d: Grid) -> None:
    both = occurrences.label_occurrences(_two_islands(grid_2d))

    report = occurrences.match_lineage(both, both)

    assert [entry.kind for entry in report.entries] == ["unchanged", "unchanged"]
    assert not report.topology_changed
    assert report.describe() == ()


def test_a_new_material_appears_and_a_removed_one_vanishes(grid_2d: Grid) -> None:
    nothing = occurrences.label_occurrences(Structure(grid_2d))
    something = occurrences.label_occurrences(_one_island(grid_2d))

    assert occurrences.match_lineage(nothing, something).of_kind("new")
    assert occurrences.match_lineage(something, nothing).of_kind("vanished")
    assert occurrences.match_lineage(something, nothing).describe() == ("metal #1 vanished",)


def test_an_island_that_dissolves_vanishes(grid_2d: Grid) -> None:
    """One occurrence of a material goes; the other stays."""
    parent = occurrences.label_occurrences(_two_islands(grid_2d))
    remaining = ctor.add_material(
        Structure(grid_2d), "metal", ctor.ball(grid_2d, center=(100.0, 80.0), radius=25.0)
    )

    report = occurrences.match_lineage(parent, occurrences.label_occurrences(remaining))

    assert sorted(entry.kind for entry in report.entries) == ["unchanged", "vanished"]


def test_labelling_is_n_d_generic() -> None:
    grid = Grid(origin=(0.0, 0.0, 0.0), spacing=1.0, shape=(40, 40, 40), axes=("z", "y", "x"))
    two = csg.union(
        ctor.ball(grid, center=(20.0, 20.0, 10.0), radius=6.0),
        ctor.ball(grid, center=(20.0, 20.0, 30.0), radius=6.0),
    )
    structure = ctor.add_material(Structure(grid), "metal", two)

    found = occurrences.label_occurrences(structure)

    assert found.count("metal") == 2
    assert len(found.of("metal")[0].centroid) == 3


def test_occurrence_identity_is_not_stored(grid_2d: Grid) -> None:
    """The `Structure` carries geometry and fields, and nothing about occurrences."""
    structure = _two_islands(grid_2d)

    assert set(structure.phi) == {"metal"}
    assert structure.fields == {}
    assert not hasattr(structure, "occurrences")
    assert np.array_equal(
        occurrences.label_occurrences(structure).labels["metal"],
        occurrences.label_occurrences(structure).labels["metal"],
    )
