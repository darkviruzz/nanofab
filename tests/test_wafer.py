"""The wafer fan and its view (plan §8, §14) — milestone M5.

The engine under this was finished in M4 and is tested in `test_runtime.py`:
`Run` over an extensible position set, `positions_on_radius`, a cache keyed per
position, and the property ADR-0004 rejected eager fan-out for. What is new is
the *job runner* and the *view*, so what is tested here is what those can get
wrong:

- a position that is still solving must be **readable**, not a blocked call;
- a position that fails must cost its own result and nothing else's;
- a second look at a position must hit the cache, because 68× is the feature;
- the widget must decide nothing — it paints statuses and emits a click.

The heavy Qt half is `importorskip`ped exactly as `test_ui.py` does, so a
headless runner without PySide6 still checks everything above.
"""

from __future__ import annotations

import time

import pytest

from nanofab_v3.io import replay_cache_for
from nanofab_v3.materials import RESIST, SILICON, didactic_library
from nanofab_v3.processes import ProcessRegistry, builtin_registry
from nanofab_v3.processes.substrate import cross_section_grid
from nanofab_v3.runtime import RadialProfile, Recipe, RecipeStep, Run
from nanofab_v3.ui.wafer import (
    DONE,
    FAILED,
    PENDING,
    RUNNING,
    WaferFan,
    compare,
    default_cache_dir,
)

EDGE = (60.0, 0.0)


@pytest.fixture(scope="module")
def registry() -> ProcessRegistry:
    return builtin_registry()


@pytest.fixture(scope="module")
def library():
    return didactic_library()


@pytest.fixture
def graded() -> Recipe:
    """A recipe whose resist thickness falls off towards the wafer edge.

    A fan over a recipe with no wafer-parameterised value shows five identical
    samples, which is correct and proves nothing — so every comparison test here
    uses this one.
    """
    grid = cross_section_grid(width=160.0, thickness=30.0, headroom=100.0)
    return Recipe(
        grid,
        (
            RecipeStep("substrate.select", {"material": SILICON, "surface": 30.0}),
            RecipeStep(
                "resist.spin_coat",
                {
                    "material": RESIST,
                    "thickness": RadialProfile(radii=(0.0, 60.0), values=(50.0, 30.0)),
                },
            ),
        ),
        "graded",
    )


# -- 1. the job runner --------------------------------------------------------


def test_a_fan_on_a_radius_is_the_centre_plus_a_ring(graded, registry, library) -> None:
    fan = WaferFan.on_radius(graded, 60.0, 4, registry=registry, library=library)

    assert fan.positions[0] == (0.0, 0.0)
    assert len(fan.positions) == 5
    assert all(status.state == PENDING for status in fan.snapshot().values())
    assert all(status.steps_total == len(graded) for status in fan.snapshot().values())


def test_every_position_materializes_and_carries_its_own_chain(
    graded, registry, library
) -> None:
    fan = WaferFan.on_radius(graded, 60.0, 4, registry=registry, library=library)

    fan.run_blocking()

    statuses = fan.snapshot()
    assert {status.state for status in statuses.values()} == {DONE}
    assert len(fan.done) == 5
    for status in statuses.values():
        assert status.steps_done == len(graded)
        assert status.fraction == 1.0
        assert status.structure is not None


def test_the_edge_is_a_different_sample_from_the_centre(graded, registry, library) -> None:
    """What the fan exists to show, and the reason `compare` is not a diff of pictures.

    The resist is 50 nm at the centre and 30 at 60 mm out, so the edge carries
    less of it — resolved by `effective_params` before anything reached the
    solver, which never learned there was a wafer (ADR-0004).
    """
    fan = WaferFan.on_radius(graded, 60.0, 4, registry=registry, library=library)
    fan.run_blocking()

    difference = compare(fan, (0.0, 0.0), EDGE)

    assert difference["resist"] < 0.0
    assert difference["silicon"] == pytest.approx(0.0, abs=1.0)


def test_comparing_a_position_that_is_not_materialized_says_so(
    graded, registry, library
) -> None:
    fan = WaferFan.on_radius(graded, 60.0, 4, registry=registry, library=library)

    with pytest.raises(ValueError, match="materialized"):
        compare(fan, (0.0, 0.0), EDGE)


def test_partial_results_are_readable_while_the_run_is_going(
    graded, registry, library
) -> None:
    """Handoff §5: show partial results, do not block.

    The assertion is that a caller reading `snapshot()` mid-run gets an answer
    rather than waiting — and that the answer distinguishes the position being
    worked on from the ones queued behind it.
    """
    fan = WaferFan.on_radius(graded, 60.0, 4, registry=registry, library=library)
    seen: list[tuple[str, ...]] = []

    fan.start()
    deadline = time.time() + 60
    while fan.is_running and time.time() < deadline:
        states = tuple(status.state for status in fan.snapshot().values())
        if not seen or states != seen[-1]:
            seen.append(states)
        time.sleep(0.01)
    fan.join(30)

    assert seen, "the run finished without a single readable intermediate state"
    assert any(RUNNING in states or PENDING in states for states in seen)
    assert all(status.state == DONE for status in fan.snapshot().values())


def test_structures_answers_with_what_exists_rather_than_computing_more(
    graded, registry, library
) -> None:
    """Deliberately not `Run.structures()`, which materializes and blocks."""
    fan = WaferFan.on_radius(graded, 60.0, 4, registry=registry, library=library)

    assert fan.structures() == {}

    fan.run_blocking(positions=[(0.0, 0.0)])

    assert set(fan.structures()) == {(0.0, 0.0)}
    assert len(fan.positions) == 5  # the rest are still queued, not gone


def test_one_position_failing_costs_only_its_own_result(graded, registry, library) -> None:
    """A wafer map that aborted on one odd edge position would hide the finding.

    `strict=True` here so the gate's verdict propagates as an exception, which is
    the harshest version of the case; the default fan uses `strict=False` and a
    broken invariant becomes a marked revision instead.
    """
    # An out-of-range spin speed rather than a missing thickness: since M6 the
    # spin coat derives its thickness from the resist's curve, so leaving it out
    # is the *normal* call and no longer breaks anything (roadmap E17).
    broken = Recipe(
        graded.grid,
        graded.steps
        + (RecipeStep("resist.spin_coat", {"material": RESIST, "spin_speed": -1.0}),),
        "broken",
    )
    fan = WaferFan(
        Run(broken, registry=registry, library=library, positions=[(0.0, 0.0), EDGE])
    )

    fan.run_blocking()

    statuses = fan.snapshot()
    assert {status.state for status in statuses.values()} == {FAILED}
    assert all("ParameterError" in status.error for status in statuses.values())
    assert all(status.describe().startswith("(") for status in statuses.values())


def test_a_second_fan_over_the_same_cache_replays_instead_of_solving(
    graded, registry, library, tmp_path
) -> None:
    """The 68x the handoff calls "the whole feature", asserted as cache hits.

    The cache is built by `io.replay_cache_for`, so its key carries each step's
    implementation digest (plan §21.1) — which is what makes a warm hit a
    statement about the same code and not only the same parameters.
    """
    cache = replay_cache_for(tmp_path / "cache", graded, registry=registry)
    first = WaferFan.on_radius(graded, 60.0, 4, registry=registry, library=library, cache=cache)
    first.run_blocking()
    cold_writes = cache.writes

    second = WaferFan.on_radius(graded, 60.0, 4, registry=registry, library=library, cache=cache)
    hits_before = cache.hits
    second.run_blocking()

    assert cold_writes >= 5 * len(graded)
    assert cache.hits - hits_before == 5 * len(graded)
    assert cache.writes == cold_writes  # nothing was solved a second time
    assert len(second.done) == 5


def test_adding_a_position_later_is_the_ordinary_path(graded, registry, library) -> None:
    """ADR-0004's whole reason for rejecting eager fan-out, at the fan's level."""
    fan = WaferFan(Run(graded, registry=registry, library=library))
    fan.run_blocking()

    added = fan.add_position((30.0, 30.0))

    assert fan.status(added).state == PENDING
    fan.run_blocking()
    assert fan.status(added).state == DONE
    assert fan.status((0.0, 0.0)).state == DONE


def test_cancelling_stops_the_fan_between_positions(graded, registry, library) -> None:
    """Between positions, never between steps.

    A chain abandoned mid-step would still have written its earlier revisions to
    the cache and would be served as complete on the next look.
    """
    fan = WaferFan.on_radius(graded, 60.0, 8, registry=registry, library=library)

    fan.start()
    fan.cancel()
    fan.join(60)

    statuses = fan.snapshot()
    assert not fan.is_running
    assert any(status.state == PENDING for status in statuses.values())
    for status in statuses.values():
        # nothing half-finished: a position is queued or it is complete
        assert status.state != RUNNING
        if status.state == DONE:
            assert status.steps_done == len(graded)


def test_the_watcher_hears_about_every_change(graded, registry, library) -> None:
    heard: list[tuple[tuple[float, float], str]] = []
    fan = WaferFan(
        Run(graded, registry=registry, library=library, positions=[(0.0, 0.0)]),
        watcher=lambda status: heard.append((status.position, status.state)),
    )

    fan.run_blocking()

    assert (CENTER := (0.0, 0.0)) and heard[0] == (CENTER, RUNNING)
    assert heard[-1] == (CENTER, DONE)
    assert [state for _, state in heard].count(RUNNING) == len(graded) + 1


def test_the_cache_directory_is_decided_in_one_place(monkeypatch, tmp_path) -> None:
    """The fan and the session share a directory because there is only one.

    Since M10 (E38) `$NANOFAB_CACHE` names the **root** rather than the replay
    directory, because the ladder now has two rungs under it: `replay/` for the
    structures and `session/` for the autosaved recipe. They are siblings so that
    clearing the expensive one cannot take the irreplaceable one with it.
    """
    from nanofab_v3.ui.wafer import session_cache_dir

    monkeypatch.setenv("NANOFAB_CACHE", str(tmp_path / "elsewhere"))

    assert default_cache_dir() == tmp_path / "elsewhere" / "replay"
    assert session_cache_dir() == tmp_path / "elsewhere" / "session"

    monkeypatch.delenv("NANOFAB_CACHE")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    assert default_cache_dir() == tmp_path / "nanofab_v3" / "replay"


# -- 2. the view --------------------------------------------------------------


@pytest.fixture(scope="module")
def qt_app():
    pytest.importorskip("PySide6")
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_the_panel_paints_whatever_the_fan_has(qt_app, graded, registry, library) -> None:
    """A view of statuses: no scene, no geometry, no decision of its own."""
    from nanofab_v3.ui.wafer_view import WaferPanel

    fan = WaferFan.on_radius(graded, 60.0, 4, registry=registry, library=library)
    panel = WaferPanel(fan)

    assert "0 of 5 materialized" in panel.summary.text()

    fan.run_blocking()
    panel.refresh()

    assert "5 of 5 materialized" in panel.summary.text()
    assert len(panel.map._statuses) == 5


def test_clicking_a_position_emits_it_and_builds_no_scene(
    qt_app, graded, registry, library
) -> None:
    """Handoff §4, trap 4: one scene per selection, never one per position per paint.

    The widget's whole output is a position. Whoever wants a picture of it builds
    exactly one, which is what `MainWindow._on_wafer_position` does.
    """
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    from nanofab_v3.ui.wafer_view import WaferPanel

    fan = WaferFan.on_radius(graded, 60.0, 4, registry=registry, library=library)
    fan.run_blocking()
    panel = WaferPanel(fan)
    panel.resize(300, 300)
    chosen: list[tuple[float, float]] = []
    panel.position_chosen.connect(lambda position: chosen.append(position))

    target = panel.map._to_pixels(EDGE)
    panel.map.mousePressEvent(
        QMouseEvent(
            QMouseEvent.MouseButtonPress,
            QPointF(target),
            QPointF(target),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
    )

    assert chosen == [EDGE]
    assert panel.map.selected == EDGE


def test_a_panel_with_no_fan_says_so_rather_than_failing(qt_app) -> None:
    from nanofab_v3.ui.wafer_view import WaferPanel

    panel = WaferPanel()

    assert panel.summary.text() == "no wafer run"
    assert not panel.start_button.isEnabled()
    panel.start()  # a no-op, not an exception


def test_the_window_fans_out_and_shows_one_position(qt_app, monkeypatch, tmp_path) -> None:
    """The wiring, end to end: demo, fan out, click an edge, see its caption.

    Slow enough to be worth one test rather than several — it runs S1 six times.
    """
    monkeypatch.setenv("NANOFAB_CACHE", str(tmp_path / "cache"))
    from nanofab_v3.ui.window import MainWindow

    window = MainWindow()
    window.resize(1200, 800)
    window._on_demo()
    window._on_fan_out()

    deadline = time.time() + 300
    while window.wafer.fan.is_running and time.time() < deadline:
        qt_app.processEvents()
        time.sleep(0.05)
    window.wafer.fan.join(60)
    window.wafer.refresh()

    assert len(window.wafer.fan.done) == 5
    assert window.wafer.isVisible() or window._wafer_visible_action.isChecked()

    edge = window.wafer.fan.positions[1]
    window._on_wafer_position(edge)

    assert window.canvas._scene is not None
    assert window.canvas._scene.caption.startswith("(60, 0) mm")
    assert list((tmp_path / "cache").iterdir())  # the fan wrote to the shared directory
