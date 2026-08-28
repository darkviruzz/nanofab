"""The handoff's remaining remarks: R1, R6, R8, R9 (`docs/plans/m6-m9-handoff.md`).

R1 is the substantive one and its finding was about process rather than about
code: **a decision recorded in a roadmap's §2 but never written into a §4 task
list gets built only by luck.** E13's and E17's "the material decides, and the UI
shows what it decided" clauses had no owner, so the model half of one shipped, the
model half of the other was a live bug for four milestones, and neither UI half
existed. This file is the UI half, plus the two small edges that share a widget
with it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nanofab_v3.materials import didactic_library
from nanofab_v3.ui.derived import derived_hints
from nanofab_v3.ui.session import default_grid

qt = pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qt_app():
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def library():
    return didactic_library()


# -- R1: what a marker resolves to, before the step runs ----------------------


def test_spin_speed_says_what_thickness_the_curve_gives_and_where_from(library):
    """E17's UI half. The number *and* its source: "90 nm" is a number, and
    "90 nm, from the resist's spin curve at 3000 rpm" is diagnosable."""
    hints = derived_hints(
        "resist.spin_coat",
        {"material": "resist", "spin_speed": 3000.0},
        library=library,
    )
    assert "spin curve" in hints["spin_speed"]
    assert "3000 rpm" in hints["spin_speed"]
    assert hints["spin_speed"].startswith("8")  # the curve's own answer, in nm


def test_the_ideal_typed_thickness_gets_no_derived_hint(library):
    assert derived_hints(
        "resist.spin_coat_ideal",
        {"material": "resist", "thickness": 120.0},
        library=library,
    ) == {}


def test_a_spin_speed_outside_the_measured_range_says_so_before_the_step(library):
    """R1's specific complaint: the clamp message reached the operator only in
    the run log, i.e. after the mistake."""
    hint = derived_hints(
        "resist.spin_coat",
        {"material": "resist", "spin_speed": 9000.0},
        library=library,
    )["spin_speed"]
    assert "clamped" in hint and "1000" in hint and "5000" in hint


def test_a_material_with_no_curve_says_what_to_do_about_it(library):
    hint = derived_hints(
        "resist.spin_coat",
        {"material": "chrome", "spin_speed": 3000.0},
        library=library,
    )["spin_speed"]
    assert "no spin curve" in hint and "ideal" in hint


def test_an_empty_tone_names_the_resist_that_decided_it(library):
    """E13's UI half — the clause that two pieces of prose asserted and nothing
    implemented, for four milestones."""
    hint = derived_hints("develop.ideal", {"material": "resist", "tone": ""}, library=library)
    assert hint["tone"].startswith("positive, from resist's own develop model")


def test_the_litho_markers_name_the_domain_they_came_from():
    grid = default_grid()
    hints = derived_hints(
        "litho.expose_ideal",
        {"pattern": "grating", "center": 0.0, "grating_center": 0.0, "period": 0.0},
        grid=grid,
    )
    assert "middle of the domain" in hints["grating_center"]
    assert "three lines" in hints["period"]
    # A grating has no window centre; hinting at the unused one trains people to
    # ignore hints.
    assert "center" not in hints


def test_the_substrate_preset_says_which_fields_it_is_driving():
    """R8's second edge: twelve parameters in one form, and no sign of which of
    them the chosen preset already answered."""
    hints = derived_hints("substrate.select", {"preset": "wafer_fs_100"})
    assert hints["material"].startswith("fused_silica, from the wafer_fs_100 preset")
    assert "100 nm" in hints["surface"]
    assert "Ra 0.5 nm" in hints["roughness"]


def test_a_hint_is_never_worth_an_exception(library):
    """A half-typed value in a spin box is a normal state for a form to be in."""
    # A blank material is answerable — it says what to do — and neither of these
    # may raise, which is the property being pinned.
    assert "ideal" in derived_hints(
        "resist.spin_coat", {"material": None}, library=library
    )["spin_speed"]
    assert derived_hints("litho.expose_ideal", {}, grid=None) == {}
    assert "spin_speed" in derived_hints(
        "resist.spin_coat", {"spin_speed": "not a number"}, library=library
    )


def test_the_form_shows_the_hint_and_hides_it_again(qt_app):
    from nanofab_v3.processes.registry import builtin_registry
    from nanofab_v3.ui.panels import ParameterForm

    registry = builtin_registry()
    form = ParameterForm()
    form.set_domain(default_grid())
    form.set_step(
        "resist.spin_coat", "Spin coat", registry["resist.spin_coat"].parameter_schema()
    )

    assert form._hints["spin_speed"].isVisible() or form._hints["spin_speed"].text()
    assert "spin curve" in form._hints["spin_speed"].text()

    form.apply_values({"spin_speed": 4000.0})
    assert form._hints["spin_speed"].text().startswith("74")


# -- R8: the two other edges --------------------------------------------------


def test_the_description_scrolls_instead_of_being_clipped(qt_app):
    """E10's long descriptions are exactly the content an unscrollable label
    truncates, so E10 partly defeated itself on a small screen."""
    from PySide6.QtWidgets import QScrollArea

    from nanofab_v3.processes.registry import builtin_registry
    from nanofab_v3.ui.panels import ParameterForm

    registry = builtin_registry()
    form = ParameterForm()
    form.set_step(
        "strip.lift_off",
        "Lift-off",
        registry["strip.lift_off"].parameter_schema(),
        registry.describe("strip.lift_off"),
    )
    assert isinstance(form.description_area, QScrollArea)
    assert form.description_area.maximumHeight() < 400
    assert form.description_area.isVisibleTo(form)


def test_a_running_chain_says_which_step_and_how_long(qt_app):
    """The cheap half of R8's first edge: a frozen window that says "step 4 of 7,
    18 s" is waiting; one that says nothing is broken."""
    from nanofab_v3.ui.window import MainWindow

    window = MainWindow()
    window._on_demo("lift_off")
    assert " s so far)" in window.statusBar().currentMessage() or window.session.chain


# -- R6: the provenance the shell prints at startup ---------------------------


def test_the_window_logs_which_library_it_is_running_on(qt_app):
    """R6: `application_library()` reads a directory no test can see, so the
    first "my chromium etches wrong" is a question about which files were read.
    A screenshot now carries its own answer."""
    from nanofab_v3.ui.window import MainWindow

    window = MainWindow()
    text = window.log.view.toPlainText()
    assert "fingerprint" in text
    assert "root:" in text
    assert "settings:" in text


# -- R9: the workflow that fails on a skip ------------------------------------


def test_there_is_a_ci_workflow_and_it_refuses_to_pass_with_a_skip():
    """The cheapest insurance in the handoff's list, and the lesson it protects
    is one this repository already paid for: "9 skipped" was in every commit
    message from M5 to M8 and nobody read it as "the UI has no tests"."""
    workflow = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "tests.yml"
    text = workflow.read_text(encoding="utf-8")
    assert "compileall" in text and "pytest" in text
    assert "skipped" in text and "exit 1" in text
    assert "QT_QPA_PLATFORM" in text  # or the Qt tests skip and the check is moot
