"""Repeat, adjust, remove — the three things E12 allows, and the one it does not.

Milestone M8, roadmap E12. `ui/window.py`'s first paragraph has said since M4
that *a snapshot is a record, not a branch*, and E12 keeps it: everything here is
truncation or appending. Branching is backlog B8 and would be an architecture
decision with its own ADR, not a UI feature.

So the three operations are:

- **repeat** — run the same step again at the head. Appending, so a second 10 s
  etch really is 20 s of etching;
- **adjust** — truncate back to before the revision and put its parameters in
  the form, to be changed and run again;
- **remove** — truncate, and say how much that costs before doing it.
"""

from __future__ import annotations

import pytest

from nanofab_v3.materials import RESIST, SILICON, didactic_library
from nanofab_v3.processes import builtin_registry
from nanofab_v3.ui.session import Session


@pytest.fixture
def session() -> Session:
    session = Session(registry=builtin_registry(), library=didactic_library())
    session.run("substrate.select", {"material": str(SILICON), "surface": 40.0})
    session.run("resist.spin_coat", {"material": str(RESIST), "spin_speed": 3000.0})
    session.run("litho.expose_ideal", {"material": str(RESIST), "center": 150.0, "width": 100.0})
    return session


# -- the Qt-free half ---------------------------------------------------------


def test_repeating_a_step_appends_rather_than_replacing(session: Session) -> None:
    """A second exposure is a second exposure. Pretending otherwise would be a lie
    about a process time, which is the one thing a didactic tool must not tell."""
    before = len(session.chain)

    session.repeat(1)

    assert len(session.chain) == before + 1
    assert session.chain.summary(before).step_id == "resist.spin_coat"
    assert [step.step_id for step in session.recipe][-1] == "resist.spin_coat"


def test_the_parameters_come_from_the_recipe_and_not_from_the_history(
    session: Session,
) -> None:
    """A form wants what somebody typed, including what they left alone.

    The history records the *validated* values that actually ran — every default
    filled in, every `Quantity` unwrapped — which is what replay needs and not
    what a person is editing.
    """
    typed = session.parameters_of(1)

    assert typed == {"material": str(RESIST), "spin_speed": 3000.0}
    assert "spin_time" in session.chain[1].history.params  # the history has the defaults
    assert "spin_time" not in typed


def test_rewinding_truncates_the_chain_and_the_recipe_together(session: Session) -> None:
    """Half a truncation would be a recipe that no longer describes its own chain."""
    session.rewind(1)

    assert len(session.chain) == 1
    assert len(session.recipe) == 1
    assert session.structure.materials == (SILICON,)


def test_a_repeat_after_a_rewind_is_the_ordinary_path(session: Session) -> None:
    """Adjust is exactly this: truncate, then run the same step with new values."""
    params = session.parameters_of(1)
    session.rewind(1)

    session.run("resist.spin_coat", {**params, "spin_speed": 5000.0})

    assert len(session.chain) == 2
    assert session.chain[1].measurements["thickness"].value == 72.0  # 5000 rpm, not 3000


# -- the Qt half --------------------------------------------------------------


@pytest.fixture(scope="module")
def qt_app():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qt_app):
    from nanofab_v3.ui.window import MainWindow

    window = MainWindow()
    window.session.run("substrate.select", {"material": str(SILICON), "surface": 40.0})
    window.session.run("resist.spin_coat", {"material": str(RESIST), "spin_speed": 3000.0})
    window._refresh_all()
    return window


def test_the_delete_key_removes_the_selected_revision(window) -> None:
    """E12 asks for the key, so the key is what is tested."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    window.revisions.list.setCurrentRow(1)
    press = QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier)

    window.revisions.eventFilter(window.revisions.list, press)

    assert len(window.session.chain) == 1


def test_repeating_from_the_panel_runs_the_step_again(window) -> None:
    window._on_repeat(1)

    assert len(window.session.chain) == 3
    assert window.session.chain.summary(2).step_id == "resist.spin_coat"
    assert window.log.view.toPlainText()


def test_adjusting_truncates_and_loads_the_parameters_into_the_form(window) -> None:
    """The form is left holding what ran, ready to be changed — and *not* marked
    as the operator's own typing, so a preset could still fill it in silently."""
    window._on_adjust(1)

    assert len(window.session.chain) == 1
    assert window.form.values()["spin_speed"] == 3000.0
    assert window.steps.selected_step_id() == "resist.spin_coat"
    assert window.form.touched() == frozenset()


def test_removing_the_head_alone_does_not_ask(window) -> None:
    """The confirmation is about losing work; dropping one revision loses none but its own.

    A dialog on every deletion is a dialog people learn to dismiss, which would
    cost the one case where it matters.
    """
    window._on_remove(1)

    assert len(window.session.chain) == 1
