"""The commit gate — plan §4.5, the second half of milestone M1.

Every chain step ends here, and the point is that nothing about a step stays
silent: the renormalisation reports what it moved, the balance check compares the
measure that actually changed against what the motion claims it moved, the
field-scoping rule wipes state whose material is gone, and a topology change
comes back as a lineage finding rather than as a surprise three steps later.
"""

from __future__ import annotations

import numpy as np
import pytest

from nanofab_v3 import FieldKey, FieldSpec, Grid, Structure
from nanofab_v3.kernel import constructors as ctor
from nanofab_v3.kernel import csg, gate, motion


@pytest.fixture
def substrate(grid_2d: Grid) -> Structure:
    return ctor.add_material(
        Structure(grid_2d),
        "silicon",
        ctor.half_space(grid_2d, normal=(1.0, 0.0), point=(60.0, 0.0)),
    )


@pytest.fixture
def masked(substrate: Structure, grid_2d: Grid) -> Structure:
    return ctor.add_material(
        substrate, "mask", ctor.box(grid_2d, lower=(55.0, 100.0), upper=(75.0, 200.0))
    )


def _etch(structure: Structure, seconds: float, **rates: float) -> gate.CommitOutcome:
    """One chain step: move the front, then commit — the M1 composition."""
    outcome = motion.advect_front(structure, motion.SurfaceRates(rates), seconds)
    return gate.commit(outcome.structure, parent=structure, swept=outcome.swept)


# -- invariants --------------------------------------------------------------


def test_a_clean_scene_passes_the_gate(masked: Structure) -> None:
    committed = gate.commit(masked)

    assert committed.report.ok
    assert committed.report.failures == ()
    assert committed.report.max_overlap_depth == 0.0


def test_the_gate_renormalises_and_says_what_it_moved(grid_2d: Grid) -> None:
    """A step hands the gate a distorted field; the gate hands back a clean one."""
    distorted = ctor.add_material(
        Structure(grid_2d),
        "silicon",
        (ctor.ball(grid_2d, center=(100.0, 150.0), radius=40.0) * 2.0).astype(np.float32),
    )

    committed = gate.commit(distorted)

    assert committed.report.ok
    assert committed.report.band_gradient_error < 0.25
    assert committed.report.reinit_displacement > 0.0  # reported, not hidden
    assert committed.report.reinit_measure_moved > 0.0


def test_overlapping_materials_fail_the_gate(grid_2d: Grid) -> None:
    """Disjoint interiors are an invariant, not an aspiration."""
    overlapping = Structure(grid_2d)
    overlapping = ctor.add_material(
        overlapping, "a", ctor.box(grid_2d, lower=(40.0, 100.0), upper=(80.0, 200.0))
    )
    overlapping = ctor.add_material(
        overlapping, "b", ctor.box(grid_2d, lower=(60.0, 120.0), upper=(100.0, 180.0)), carve=False
    )

    report = gate.commit(overlapping).report

    assert not report.ok
    assert any("overlap" in failure for failure in report.failures)


def test_the_headroom_guard_catches_a_stack_leaving_the_domain(grid_2d: Grid) -> None:
    """Growth out of the top of the domain is a failed step (plan §3.1)."""
    tall = ctor.add_material(
        Structure(grid_2d),
        "silicon",
        ctor.half_space(grid_2d, normal=(1.0, 0.0), point=(60.0, 0.0)),
    )
    grown = motion.offset_solid(tall, 150.0, deposit_material="film").structure

    report = gate.commit(grown, parent=tall).report

    assert not report.ok
    assert any("headroom" in failure for failure in report.failures)
    assert ("y", "max") in report.boundary_faces


def test_a_blanket_layer_may_touch_the_lateral_faces(masked: Structure) -> None:
    """A cross-section continues sideways; failing on that would fail everything."""
    report = gate.commit(masked).report

    assert ("x", "min") in report.boundary_faces
    assert report.ok


# -- the balance check -------------------------------------------------------


def test_the_balance_check_closes_on_a_plain_etch(substrate: Structure) -> None:
    """What the front integral says was removed is what actually went missing."""
    committed = _etch(substrate, 10.0, silicon=2.0)

    assert committed.report.ok
    assert committed.report.balance is not None
    assert committed.report.balance.ok
    assert committed.report.balance.error < 0.02
    assert committed.report.balance.measured < 0.0  # material left


def test_the_balance_check_closes_on_a_masked_etch(masked: Structure) -> None:
    committed = _etch(masked, 10.0, silicon=2.0, mask=0.0)

    assert committed.report.ok
    assert committed.report.balance.ok


def test_the_balance_check_closes_on_deposition(substrate: Structure) -> None:
    outcome = motion.advect_front(
        substrate, motion.SurfaceRates(default=1.0), 8.0, deposit_material="film"
    )
    committed = gate.commit(outcome.structure, parent=substrate, swept=outcome.swept)

    assert committed.report.balance.expected > 0.0
    assert committed.report.balance.ok


def test_a_step_without_motion_has_no_balance(masked: Structure) -> None:
    """An inspection step returns its input; there is nothing to balance."""
    committed = gate.commit(masked, parent=masked)

    assert committed.report.balance is None
    assert committed.report.ok


def test_the_balance_check_warns_rather_than_fails(substrate: Structure) -> None:
    """A wrong claim is surfaced, not swallowed — and does not fail the step."""
    outcome = motion.advect_front(substrate, motion.SurfaceRates(default=2.0), 5.0)
    committed = gate.commit(outcome.structure, parent=substrate, swept=outcome.swept * 3.0)

    assert not committed.report.balance.ok
    assert any("balance" in warning for warning in committed.report.warnings)
    assert committed.report.ok  # invariants held; the claim did not


# -- field scoping -----------------------------------------------------------


def test_a_material_scoped_field_is_reset_where_its_material_changed(
    substrate: Structure, grid_2d: Grid
) -> None:
    """Without this, dose from a first lithography leaks into later resist."""
    dose = FieldSpec("dose", default=0.0, unit="mJ/cm^2")
    exposed = substrate.with_field(dose.key("silicon"), grid_2d.full(7.0, dtype=np.float32))
    outcome = motion.advect_front(exposed, motion.SurfaceRates(default=2.0), 10.0)

    committed = gate.commit(
        outcome.structure, parent=exposed, swept=outcome.swept, field_specs={"dose": dose}
    )

    values = committed.structure.field(FieldKey("dose", "silicon"))
    removed = exposed.inside("silicon") & ~committed.structure.inside("silicon")
    assert np.all(values[removed] == 0.0)  # the etched shell forgot its dose
    assert np.all(values[committed.structure.inside("silicon")] == 7.0)  # the rest kept it
    assert committed.report.field_resets["dose@silicon"] == int(np.count_nonzero(removed))


def test_a_global_field_is_never_reset(substrate: Structure, grid_2d: Grid) -> None:
    """Scoping is about material-scoped fields; a global one means something everywhere."""
    temperature = FieldSpec("temperature", material_scoped=False)
    with_field = substrate.with_field(temperature.key(), grid_2d.full(300.0, dtype=np.float32))
    outcome = motion.advect_front(with_field, motion.SurfaceRates(default=2.0), 10.0)

    committed = gate.commit(
        outcome.structure,
        parent=with_field,
        swept=outcome.swept,
        field_specs={"temperature": temperature},
    )

    assert committed.report.field_resets == {}
    assert np.all(committed.structure.field(FieldKey("temperature", None)) == 300.0)


def test_a_field_without_a_spec_falls_back_to_zero(substrate: Structure, grid_2d: Grid) -> None:
    with_field = substrate.with_field(FieldKey("damage", "silicon"), grid_2d.full(4.0))
    outcome = motion.advect_front(with_field, motion.SurfaceRates(default=2.0), 6.0)

    committed = gate.commit(outcome.structure, parent=with_field, swept=outcome.swept)

    assert "damage@silicon" in committed.report.field_resets


# -- lineage -----------------------------------------------------------------


def test_cutting_a_film_in_two_is_reported_as_a_split(grid_2d: Grid) -> None:
    """A topology change is a finding, not a bookkeeping corner case (ADR-0003)."""
    film = ctor.add_material(
        Structure(grid_2d), "metal", ctor.box(grid_2d, lower=(40.0, 20.0), upper=(60.0, 280.0))
    )
    cut = ctor.add_material(
        Structure(grid_2d),
        "metal",
        csg.difference(
            ctor.box(grid_2d, lower=(40.0, 20.0), upper=(60.0, 280.0)),
            ctor.box(grid_2d, lower=(35.0, 145.0), upper=(65.0, 155.0)),
        ),
    )

    committed = gate.commit(cut, parent=film)

    assert committed.lineage.topology_changed
    assert [entry.kind for entry in committed.lineage.entries] == ["split"]
    assert "split into" in committed.lineage.describe()[0]
    assert any("split" in warning for warning in committed.report.warnings)


def test_an_untouched_scene_reports_no_lineage_change(masked: Structure) -> None:
    committed = gate.commit(masked, parent=masked)

    assert not committed.lineage.topology_changed
    assert committed.lineage.describe() == ()


def test_the_first_revision_needs_no_parent(masked: Structure) -> None:
    committed = gate.commit(masked)

    assert committed.report.ok
    assert committed.lineage.entries == ()
    assert committed.report.field_resets == {}


def test_the_gate_leaves_its_input_untouched(masked: Structure) -> None:
    before = masked.phi_of("silicon").copy()

    committed = gate.commit(masked)

    assert np.array_equal(masked.phi_of("silicon"), before)
    assert committed.structure is not masked
