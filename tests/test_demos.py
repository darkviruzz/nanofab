"""The demos run, and each one shows what its own sentence says it shows (M8).

Milestone M8's sixth item. Until now the application had one lift-off wired into
the window, which meant the only recipe anybody saw was the only recipe anybody
*could* see. There are four now, and each carries the prose that makes it worth
running: a demo that produces a shape teaches nothing on its own — what teaches
is knowing what the shape was supposed to show, and what would have happened
instead.

So these tests are not "does it crash". Each one asserts the *mechanism the demo
exists to demonstrate*, which is also what would break first if a rate or a step
drifted underneath it.
"""

from __future__ import annotations

import numpy as np
import pytest

from nanofab_v3.kernel import occurrences
from nanofab_v3.materials import (
    ALUMINA,
    CHROME,
    FUSED_SILICA,
    METAL,
    RESIST,
    SILICON,
    TITANIA,
)
from nanofab_v3.ui.demos import DEMOS, demo
from nanofab_v3.ui.session import Session, demo_recipe


def _run(key: str) -> Session:
    entry = demo(key)
    session = Session(entry.grid)
    for step in entry.steps:
        revision = session.run(step.step_id, step.params)
        assert revision.ok, (key, step.step_id, revision.validation.failures)
    return session


def _surface(session: Session, material: str) -> np.ndarray:
    """Topmost cell of `material` per column, in nm; `-inf` where it is absent."""
    structure = session.structure
    inside = structure.phi_of(material) <= 0.0
    grid = structure.grid
    rows = np.arange(grid.shape[0])[:, None]
    top = np.max(np.where(inside, rows, -1), axis=0)
    return np.where(top >= 0, grid.origin[0] + grid.spacing * top, -np.inf)


def _present(session: Session, material: str) -> bool:
    """Whether the material is really there, rather than a phantom zero (§20.5)."""
    structure = session.structure
    if material not in structure.phi:
        return False
    return occurrences.label_occurrences(structure).count(material) > 0


# -- every one of them --------------------------------------------------------


def test_every_demo_carries_the_sentence_that_makes_it_worth_running() -> None:
    """A screenshot would do as much as a demo without one."""
    assert len(DEMOS) == 5
    for entry in DEMOS:
        assert entry.summary and entry.watch_for
        assert len(entry.watch_for) > 120, entry.key
        assert entry.steps and entry.grid.ndim == 2
        assert entry.steps[0].step_id == "substrate.select"  # E4, in every recipe


def test_the_demo_keys_are_unique_and_findable() -> None:
    assert len({entry.key for entry in DEMOS}) == len(DEMOS)
    assert demo("black_silicon").title.startswith("Black silicon")
    with pytest.raises(ValueError, match="no demo"):
        demo("perpetual_motion")


def test_the_old_shorthand_delegates_rather_than_repeating_itself() -> None:
    """Two definitions of one recipe is the drift this repository keeps refusing."""
    grid, steps = demo_recipe()

    assert (grid, steps) == (demo("lift_off").grid, demo("lift_off").steps)


# -- 1. lift-off --------------------------------------------------------------


def test_the_lift_off_leaves_one_metal_pattern() -> None:
    """S1, and what the application has always opened with."""
    session = _run("lift_off")

    assert _present(session, METAL) and not _present(session, RESIST)
    assert session.structure.materials[0] == SILICON


# -- 2. the chromium hard mask ------------------------------------------------


def test_the_chromium_mask_holds_the_line_and_then_comes_off() -> None:
    """The photomask process, and the reason the chromium is there at all.

    A resist mask would be gone long before the grating was deep — fluorine takes
    resist thirty times faster than chromium — so what this asserts is the
    grating that only a hard mask makes possible, and the bath at the end that
    removes the mask and nothing else.
    """
    session = _run("chrome_grating")

    glass = _surface(session, FUSED_SILICA)
    assert np.isfinite(glass).all()  # the substrate is everywhere
    assert glass.max() - glass.min() > 150.0  # a deep grating, not a scratch
    # Steep: almost every column is either at the top or at the floor, with few
    # in between — which is what "vertical rate, no lateral one" looks like.
    top, floor = glass.max(), glass.min()
    flanks = np.count_nonzero((glass > floor + 20.0) & (glass < top - 20.0))
    assert flanks < 0.25 * glass.size

    assert not _present(session, CHROME)  # the wet etchant took the mask
    assert not _present(session, RESIST)  # the oxygen plasma took the resist


# -- 3. the etch stop ---------------------------------------------------------


def test_the_alumina_stops_a_deliberately_long_etch() -> None:
    """The floor of the grating sits on the alumina although nothing says when to stop.

    That is the whole demo: the etch runs 350 s against a 120 nm film on purpose,
    and what ends it is a 25:1 selectivity rather than the clock. Take the
    alumina out and the same recipe cuts into the substrate.
    """
    session = _run("titania_stop")

    assert _present(session, TITANIA)  # the grating lines survive
    assert _present(session, ALUMINA)  # ... and so does the stop, everywhere
    alumina = _surface(session, ALUMINA)
    assert np.isfinite(alumina).all()

    glass = _surface(session, FUSED_SILICA)
    assert glass.max() - glass.min() < 6.0  # the substrate is essentially untouched

    titania = _surface(session, TITANIA)
    covered = np.count_nonzero(np.isfinite(titania))
    assert 0.3 * titania.size < covered < 0.7 * titania.size  # patterned, not blanket

    assert not _present(session, RESIST)  # and the mask is gone


def test_the_oxygen_strip_takes_forty_seconds_and_not_four_hundred() -> None:
    """The last step of the etch-stop demo used to run ten times longer than it needs.

    "Deliberately long" is the *fluorine* step's argument — the alumina ends the
    etch and not the clock — and it had been copied onto the oxygen strip that
    follows, where it means nothing: there is no selectivity lesson in removing
    resist that is already gone.

    And by then it nearly is. The fluorine step takes resist at 1 nm/s for 350 s,
    so what reaches the oxygen plasma is a remnant of a 400 nm coat. Measured on
    this recipe: 35 s already leaves no resist cell, and 400 s left exactly the
    same nothing — six minutes of solving it. 40 s, with the margin visible.
    """
    entry = demo("titania_stop")
    strip = entry.steps[-1]

    assert strip.step_id == "etch.rie_oxygen"
    assert strip.params["duration"] == 40.0
    assert "40 s, not 400" in entry.note(len(entry.steps) - 1)

    session = _run("titania_stop")

    # `_present`, not `in materials`: an etch that consumes a material leaves its
    # key behind with an all-positive field (§20.5's phantom), and the question
    # here is whether any resist is *there*.
    assert not _present(session, RESIST)  # 40 s was enough
    assert int((session.structure.phi_of(RESIST) < 0.0).sum()) == 0
    assert _present(session, TITANIA) and _present(session, ALUMINA)  # and took nothing else


# -- 4. black silicon ---------------------------------------------------------


def test_micromasking_makes_a_surface_rather_than_a_defect() -> None:
    """Nothing in the recipe says "make pillars".

    Particles land, the etch cannot remove what they cover, and a forest is what
    is left — the S5 mechanism at a scale where it stops being a defect. The
    pillars stay connected to the wafer, which is what distinguishes a rough
    surface from a pile of debris.
    """
    session = _run("black_silicon")

    silicon = _surface(session, SILICON)
    assert np.isfinite(silicon).all()
    assert silicon.max() - silicon.min() > 30.0  # real relief
    peaks = np.count_nonzero((silicon[1:-1] > silicon[:-2]) & (silicon[1:-1] >= silicon[2:]))
    assert peaks > 8  # a forest, not one bump
    assert occurrences.label_occurrences(session.structure).count(SILICON) == 1
    assert not _present(session, "particle")  # the clean took what it could reach


def test_cleaning_before_the_etch_instead_of_after_leaves_a_flat_surface() -> None:
    """The control the demo's own text points at, and the reason it is a
    *reachability* finding: the same particles, removed while they can still be
    reached, mask nothing at all."""
    entry = demo("black_silicon")
    session = Session(entry.grid)
    reordered = (entry.steps[0], entry.steps[1], entry.steps[3], entry.steps[2])
    for step in reordered:
        session.run(step.step_id, step.params)

    inside = session.structure.phi_of(SILICON) <= 0.0
    grid = session.structure.grid
    rows = np.arange(grid.shape[0])[:, None]
    top = grid.origin[0] + grid.spacing * np.max(np.where(inside, rows, -1), axis=0)

    assert top.max() - top.min() < 5.0


# -- the picker ---------------------------------------------------------------


@pytest.fixture(scope="module")
def qt_app():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_the_shell_offers_every_demo_and_says_what_to_watch_for(qt_app) -> None:
    from nanofab_v3.ui.window import MainWindow

    window = MainWindow()
    titles = {
        action.text()
        for menu in window.menuBar().findChildren(type(window.menuBar().actions()[0].menu()))
        for action in menu.actions()
    }

    assert {entry.title for entry in DEMOS} <= titles

    window._on_demo("lift_off")

    assert len(window.session.chain) == len(demo("lift_off").steps)
    # The explanation goes into the log *before* the first step: afterwards it is
    # a shape somebody has to interpret.
    log = window.log.view.toPlainText()
    assert demo("lift_off").watch_for.split(".")[0] in log
    assert log.index("Naive lift-off") < log.index("substrate")
