"""The bugs and the wording M10 owed (roadmap §4 "M10" item 5).

Every one of these was measured before it was fixed, which is why they are one
file: the roadmap's §0 named four findings that turned a decision, and three of
them land here.
"""

from __future__ import annotations

import pytest

from nanofab_v3.processes.contract import sub_cell_warning

qt = pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qt_app():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


# -- §0.1: the adjust bug, and it is not the filter ---------------------------


def test_selecting_a_foreign_revision_no_longer_writes_into_the_visible_form(qt_app):
    """The measurement, reproduced: `material` and `thickness` collide by name.

    `substrate.select` has both, and so does `resist.spin_coat`. Selecting
    revision #0 while the spin coat's form is open used to write `silicon` /
    `0.0` over `resist` / `90.0`, because the write was by parameter name into
    whatever form was on screen.
    """
    from nanofab_v3.ui.window import MainWindow

    window = MainWindow()
    window.session.run("substrate.select", {"material": "silicon", "surface": 40.0})
    window.session.run("resist.spin_coat", {"material": "resist", "thickness": 90.0})

    window.steps.select_step("resist.spin_coat")
    window._on_step_chosen("resist.spin_coat")
    window.form.apply_values({"material": "resist", "thickness": 90.0})

    window._on_revision_chosen(0)  # the substrate revision, a different step

    assert window.form.values()["material"] == "resist"
    assert window.form.values()["thickness"] == pytest.approx(90.0)


def test_selecting_the_revision_of_the_shown_step_still_fills_the_form(qt_app):
    """The feature the bug was hiding inside: same step, so the values belong."""
    from nanofab_v3.ui.window import MainWindow

    window = MainWindow()
    window.session.run("substrate.select", {"material": "fused_silica", "surface": 40.0})
    window.steps.select_step("substrate.select")
    window._on_step_chosen("substrate.select")

    window._on_revision_chosen(0)
    assert window.form.values()["material"] == "fused_silica"


def test_adjust_loads_the_values_that_ran_even_when_the_filter_would_hide_them(qt_app):
    """The DoD's sentence. A typed material is still the material that ran."""
    from nanofab_v3.materials import MaterialType
    from nanofab_v3.ui.window import MainWindow

    window = MainWindow()
    window.session.library = window.session.library.with_entry(
        MaterialType(material_id="unobtainium", name="Unobtainium")
    )
    window.session.run("substrate.select", {"material": "silicon", "surface": 40.0})
    window.session.run("resist.spin_coat", {"material": "unobtainium", "thickness": 80.0})

    window._on_adjust(1)

    assert window.form.step_id == "resist.spin_coat"
    assert window.form.values()["material"] == "unobtainium"
    assert window.form.values()["thickness"] == pytest.approx(80.0)


def test_the_picture_is_a_pair_of_alternatives_not_a_tick_box(qt_app):
    """Contours and the index map are two pictures of one revision, not a stack."""
    from nanofab_v3.ui.window import MainWindow

    window = MainWindow()
    assert window.contour_radio.isChecked() and not window.index_map_radio.isChecked()
    window.index_map_radio.setChecked(True)
    assert not window.contour_radio.isChecked()
    assert window.canvas._show_index_map is True


# -- E35: the ellipsometer is gone, the SEM says what it shows ----------------


def test_the_ellipsometer_is_gone_from_the_registry_and_the_module():
    from nanofab_v3.processes import inspection
    from nanofab_v3.processes.registry import builtin_registry

    assert "inspect.ellipsometer" not in builtin_registry().steps
    assert not hasattr(inspection, "ELLIPSOMETER")


def test_the_sem_is_named_for_the_section_it_shows():
    """E35: this view is what a FIB cut exposes, and the name should say so."""
    from nanofab_v3.processes.registry import builtin_registry

    registry = builtin_registry()
    assert registry.display_name("inspect.sem") == "SEM (cross-section)"
    assert "cross-section" in registry.describe("inspect.sem")


def test_film_thickness_survives_the_ellipsometer_because_it_has_other_callers():
    """§0.7's correction: the profilometer reads it, so removing the step is safe."""
    from nanofab_v3.kernel import predicates

    assert callable(predicates.film_thickness)


# -- §0.5: a layer thinner than a cell ----------------------------------------


def test_a_thickness_below_one_cell_warns_and_says_what_to_do():
    """Measured: 0.2 nm of chromium on a 1 nm grid came out 0.51 nm, 153 % over."""
    assert sub_cell_warning(0.2, 1.0, "chrome").startswith("warning: 0.2 nm of chrome")
    assert "different number" in sub_cell_warning(0.2, 1.0)
    assert "overshoot" in sub_cell_warning(0.7, 1.0)
    assert sub_cell_warning(1.0, 1.0) == ""
    assert sub_cell_warning(90.0, 2.0) == ""


def test_a_deposition_thinner_than_a_cell_says_so_in_the_run_log(qt_app):
    """The warning reaches the operator at the step, not through a balance report."""
    from nanofab_v3.ui.session import Session

    session = Session()
    session.run("substrate.select", {"material": "silicon", "surface": 40.0})
    revision = session.run(
        "deposit.conformal_offset", {"material": "chrome", "thickness": 0.2}
    )
    assert any("below the" in line and "cell size" in line for line in revision.logs)
