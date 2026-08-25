"""`Structure` — the single stored geometry truth (plan §3.2, §3.3)."""

from __future__ import annotations

import numpy as np
import pytest

from nanofab_v3 import EMPTY, FieldKey, FieldSpec, Grid, Structure
from nanofab_v3.kernel import constructors as ctor


def _two_material_structure(grid: Grid) -> Structure:
    structure = Structure(grid)
    structure = ctor.add_material(
        structure, "silicon", ctor.half_space(grid, normal=(1.0, 0.0), point=(60.0, 0.0))
    )
    return ctor.add_material(
        structure, "metal", ctor.box(grid, lower=(55.0, 100.0), upper=(80.0, 200.0))
    )


def test_structure_stores_one_field_per_material(grid_2d: Grid) -> None:
    structure = _two_material_structure(grid_2d)

    assert structure.materials == ("silicon", "metal")
    assert structure.phi_of("silicon").dtype == np.float32
    assert structure.phi_of("silicon").shape == grid_2d.shape
    with pytest.raises(KeyError, match="no material"):
        structure.phi_of("resist")


def test_structure_is_a_value_object(grid_2d: Grid) -> None:
    """Every mutator returns a new revision; the stored mapping is read-only."""
    structure = _two_material_structure(grid_2d)
    without = structure.without_material("metal")

    assert structure.materials == ("silicon", "metal")
    assert without.materials == ("silicon",)
    with pytest.raises(TypeError):
        structure.phi["metal"] = np.zeros(grid_2d.shape, dtype=np.float32)


def test_derived_views_follow_the_materials(grid_2d: Grid) -> None:
    """Solid union, empty space and index map are derived per revision."""
    structure = _two_material_structure(grid_2d)

    expected_solid = np.minimum(structure.phi_of("silicon"), structure.phi_of("metal"))
    assert np.array_equal(structure.solid_phi, expected_solid)
    assert np.array_equal(structure.empty_phi, -structure.solid_phi)
    assert np.array_equal(structure.solid_mask, structure.solid_phi < 0.0)
    assert structure.material_at(0) == "silicon"
    assert structure.material_at(EMPTY) is None
    assert structure.material_index[199, 0] == EMPTY


def test_empty_structure_has_no_solid(grid_2d: Grid) -> None:
    structure = Structure(grid_2d)

    assert structure.materials == ()
    assert np.all(np.isinf(structure.solid_phi))
    assert not structure.solid_mask.any()
    assert np.all(structure.material_index == EMPTY)


def test_measure_counts_area_in_nm(grid_2d: Grid) -> None:
    structure = _two_material_structure(grid_2d)
    metal = structure.inside("metal")

    # Cells strictly inside: y = 61..79 (the substrate owns everything up to
    # y = 60), x = 101..199 — the faces themselves sit exactly on `phi = 0`.
    assert structure.measure(metal) == pytest.approx(19 * 99 * grid_2d.cell_measure)


def test_fields_carry_named_per_cell_state(grid_2d: Grid) -> None:
    """A `Field` is global or scoped to a material (plan §3.3)."""
    dose = FieldSpec("dose", dtype=np.float32, default=0.0, unit="mJ/cm^2")
    structure = _two_material_structure(grid_2d)
    structure = structure.with_field(dose.key("metal"), dose.new(grid_2d))

    assert structure.has_field(FieldKey("dose", "metal"))
    assert structure.field(FieldKey("dose", "metal")).shape == grid_2d.shape
    assert list(structure.fields_of("metal")) == [FieldKey("dose", "metal")]
    assert structure.fields_of(None) == {}


def test_material_scoped_fields_need_their_material(grid_2d: Grid) -> None:
    """A field cannot be scoped to a material the `Structure` does not have."""
    structure = _two_material_structure(grid_2d)

    with pytest.raises(ValueError, match="scoped to a material not in this Structure"):
        structure.with_field(FieldKey("dose", "resist"), grid_2d.zeros())


def test_dropping_a_material_drops_its_fields(grid_2d: Grid) -> None:
    """Material-scoped state has no meaning without its material."""
    structure = _two_material_structure(grid_2d)
    structure = structure.with_field(FieldKey("dose", "metal"), grid_2d.zeros())

    assert structure.without_material("metal").fields == {}


def test_field_spec_enforces_its_scope(grid_2d: Grid) -> None:
    material_scoped = FieldSpec("dose", material_scoped=True)
    global_field = FieldSpec("temperature", material_scoped=False)

    assert global_field.key() == FieldKey("temperature", None)
    assert not FieldKey("temperature", None).is_material_scoped
    with pytest.raises(ValueError, match="needs a material"):
        material_scoped.key()
    with pytest.raises(ValueError, match="takes no material"):
        global_field.key("metal")


def test_structure_validates_against_its_grid(grid_2d: Grid) -> None:
    with pytest.raises(ValueError, match="does not match grid shape"):
        Structure(grid_2d, {"silicon": np.zeros((5, 5), dtype=np.float32)})
