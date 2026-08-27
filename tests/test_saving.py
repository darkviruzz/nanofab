"""Saving a recipe and saving a build are two different acts (post-M9 follow-up).

They used to be one menu entry, and keeping them one meant paying the expensive
price for the cheap thing. Measured on the lift-off demo, six steps on a 241x301
domain:

    the recipe          893 bytes, one JSON file
    the build       122 644 bytes in a folder, plus that same file

The ratio is what makes the split worth a menu entry rather than an option: a
recipe is text a person can read, diff, mail and edit, and on the etch-stop demo
a build is hundreds of megabytes and half a minute of writing. Two acts, two
names, two prices.

**Loading a recipe does not run it**, which is the second half of the same
argument. The etch-stop demo is 25 s of solver and the chromium grating 11; a
load that computed what it read would make opening a file a commitment rather
than a look. So `load_recipe` fills the recipe and leaves the chain empty, and
`run_recipe` is a separate, resumable act.
"""

from __future__ import annotations

import json

import pytest

from nanofab_v3.ui.demos import demo
from nanofab_v3.ui.session import RECIPE_SUFFIX, SESSION_MANIFEST, Session


@pytest.fixture
def ran() -> Session:
    """A finished lift-off: six revisions and the recipe that made them."""
    entry = demo("lift_off")
    session = Session(entry.grid)
    for step in entry.steps:
        session.run(step.step_id, step.params)
    return session


# -- the recipe: text, and only text ------------------------------------------


def test_a_saved_recipe_is_one_readable_file(ran: Session, tmp_path) -> None:
    written = ran.save_recipe(tmp_path / "flow")

    assert written.name == "flow" + RECIPE_SUFFIX  # the suffix is supplied
    assert [path.name for path in tmp_path.iterdir()] == [written.name]  # nothing else
    data = json.loads(written.read_text(encoding="utf-8"))
    assert [step["step_id"] for step in data["steps"]] == [
        step.step_id for step in ran.recipe.steps
    ]


def test_a_recipe_is_orders_of_magnitude_smaller_than_a_build(ran: Session, tmp_path) -> None:
    """The measurement the split is for, asserted rather than remembered."""
    recipe_file, directory = ran.save_build(tmp_path / "run")

    build_bytes = sum(path.stat().st_size for path in directory.rglob("*"))
    assert recipe_file.stat().st_size * 20 < build_bytes


def test_a_name_that_already_says_recipe_is_not_doubled(ran: Session, tmp_path) -> None:
    written = ran.save_recipe(tmp_path / ("flow" + RECIPE_SUFFIX))

    assert written.name == "flow" + RECIPE_SUFFIX


# -- the build: the recipe, and a folder beside it ----------------------------


def test_a_build_writes_the_recipe_and_a_folder_of_the_same_name(ran: Session, tmp_path) -> None:
    recipe_file, directory = ran.save_build(tmp_path / "run")

    assert recipe_file == tmp_path / ("run" + RECIPE_SUFFIX)
    assert directory == tmp_path / "run"
    assert directory.is_dir()
    # One file pair per step, and the folder's own copy of the recipe.
    assert len(list(directory.glob("rev-*.npz"))) == len(ran.chain)
    assert (directory / SESSION_MANIFEST).is_file()


def test_the_build_folder_stays_loadable_on_its_own(ran: Session, tmp_path) -> None:
    """Two copies of one recipe, on purpose: a folder moved away is still a session."""
    _recipe_file, directory = ran.save_build(tmp_path / "run")
    moved = tmp_path / "elsewhere"
    directory.rename(moved)

    reopened = Session.load(moved)

    assert len(reopened.chain) == len(ran.chain)
    assert reopened.structure.materials == ran.structure.materials


def test_saving_a_build_under_a_recipe_name_does_not_nest_the_suffix(
    ran: Session, tmp_path
) -> None:
    """A file dialog hands back whatever was typed, including a full recipe name."""
    recipe_file, directory = ran.save_build(tmp_path / ("run" + RECIPE_SUFFIX))

    assert recipe_file.name == "run" + RECIPE_SUFFIX
    assert directory.name == "run"


# -- loading a recipe computes nothing ----------------------------------------


def test_loading_a_recipe_does_not_run_it(ran: Session, tmp_path) -> None:
    written = ran.save_recipe(tmp_path / "flow")
    fresh = Session(demo("lift_off").grid)

    steps = fresh.load_recipe(written)

    assert len(steps) == len(ran.recipe.steps)
    assert len(fresh.chain) == 0  # nothing computed
    assert len(fresh.pending) == len(steps)


def test_running_a_loaded_recipe_reproduces_the_build(ran: Session, tmp_path) -> None:
    fresh = Session(demo("lift_off").grid)
    fresh.load_recipe(ran.save_recipe(tmp_path / "flow"))

    produced = fresh.run_recipe()

    assert len(produced) == len(ran.chain)
    assert fresh.pending == ()
    assert len(fresh.recipe.steps) == len(ran.recipe.steps)  # not duplicated
    assert fresh.structure.materials == ran.structure.materials


def test_run_recipe_reports_progress_before_each_step(ran: Session, tmp_path) -> None:
    """The hook the window's status bar and wait cursor hang off."""
    fresh = Session(demo("lift_off").grid)
    fresh.load_recipe(ran.save_recipe(tmp_path / "flow"))
    seen: list[tuple[int, int, str]] = []

    fresh.run_recipe(on_step=lambda index, total, step: seen.append((index, total, step.step_id)))

    assert seen[0] == (0, len(ran.recipe.steps), "substrate.select")
    assert [entry[0] for entry in seen] == list(range(len(ran.recipe.steps)))


def test_run_recipe_resumes_where_a_failure_left_it(tmp_path) -> None:
    """A step that cannot run stops the loop and leaves the rest of the recipe intact.

    The reason `run_recipe` starts at `len(self.chain)` rather than at zero: a
    recipe whose fourth step names a material nobody coated should be fixable and
    continued, not restarted. What must **not** happen is the recipe being
    truncated to whatever ran — which is what a `finally` around the step swap is
    there to prevent.
    """
    entry = demo("lift_off")
    session = Session(entry.grid)
    session.load_recipe(_recipe_with_a_bad_step(session, entry, tmp_path))

    with pytest.raises(Exception):
        session.run_recipe()

    assert len(session.chain) == 2  # the two that could run
    assert len(session.recipe.steps) == len(entry.steps) + 1  # nothing lost
    assert len(session.pending) == len(entry.steps) - 1


def _recipe_with_a_bad_step(session: Session, entry, tmp_path):
    """The lift-off with a develop wedged in before anything has been exposed."""
    from nanofab_v3.runtime.run import RecipeStep

    session.recipe = session.recipe.__class__(
        grid=entry.grid,
        steps=entry.steps[:2]
        + (RecipeStep("develop.ideal", {"material": "resist"}),)
        + entry.steps[2:],
        recipe_id="broken",
    )
    return session.save_recipe(tmp_path / "broken")


# -- the menu says the same thing the API does --------------------------------


@pytest.fixture
def qt_app():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _session_actions(window) -> list[str]:
    for menu in window.menuBar().findChildren(type(window.menuBar().actions()[0].menu())):
        if menu.title() == "&Session":
            return [action.text() for action in menu.actions() if action.text()]
    raise AssertionError("no Session menu")


def test_the_session_menu_names_the_two_saves_separately(qt_app) -> None:
    from nanofab_v3.ui.window import MainWindow

    actions = _session_actions(MainWindow())

    assert "&Save recipe…" in actions
    assert "Save &build…" in actions
    assert "&Open recipe…" in actions
    assert "Open &build…" in actions


def test_the_session_menu_no_longer_runs_a_demo(qt_app) -> None:
    """The picker replaced it in M8; the old single-demo entry stayed behind.

    It offered one of four demos from the wrong menu — the sort of leftover that
    is invisible to a test asserting the Demos menu is complete, because it was.
    """
    from nanofab_v3.ui.demos import demos
    from nanofab_v3.ui.window import MainWindow

    actions = _session_actions(MainWindow())

    assert not any("demo" in text.lower() for text in actions)
    assert not any(entry.title in actions for entry in demos())


def test_running_a_loaded_recipe_is_offered_only_when_there_is_something_to_run(
    qt_app, ran: Session, tmp_path
) -> None:
    from nanofab_v3.ui.window import MainWindow

    window = MainWindow()
    assert window._run_recipe_action.isEnabled() is False

    written = ran.save_recipe(tmp_path / "flow")
    window.session.load_recipe(written)
    window._refresh_all()

    assert window._run_recipe_action.isEnabled() is True
    assert "(6)" in window._run_recipe_action.text()  # how many are waiting

    window._on_run_recipe()

    assert len(window.session.chain) == len(ran.chain)
    assert window._run_recipe_action.isEnabled() is False


def test_a_demo_logs_the_note_that_explains_its_numbers(qt_app) -> None:
    """`note` moved out of the Python comments and into the file; it is shown."""
    from nanofab_v3.ui.window import MainWindow

    window = MainWindow()
    window._on_demo("black_silicon")

    log = window.log.view.toPlainText()
    assert "After, not before" in log
