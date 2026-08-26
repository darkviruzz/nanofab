"""Rendering and the interactive session — plan §10, ADR-0001, milestone M4.

ADR-0001's autopsy came down to one sentence: v1 let the renderer own the
geometry, so every process decision was made by a `QPainterPath`. The tests here
are what makes the v2 answer checkable rather than merely intended.

Two of them are structural and would fail on a rewrite that drifted back:
`SceneSnapshot` and `Session` must import with no Qt in the process at all, which
is only possible if nothing that decides geometry lives on the Qt side. The rest
are about the pictures themselves, and every one of them exists because the naive
version of that picture was measured and was wrong.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from nanofab_v3 import Grid, Structure
from nanofab_v3.kernel import constructors as ctor
from nanofab_v3.kernel import occurrences
from nanofab_v3.materials import (
    METAL,
    OXIDE,
    RESIST,
    SILICON,
    didactic_library,
)
from nanofab_v3.processes import builtin_registry
from nanofab_v3.processes.contract import CapabilityError
from nanofab_v3.kernel.domain import DomainPolicy
from nanofab_v3.model import capability
from nanofab_v3.processes.substrate import cross_section_grid
from nanofab_v3.runtime import CENTER, Recipe, RecipeStep, run_recipe
from nanofab_v3.ui import scene as scene_builder
from nanofab_v3.ui.session import Session, demo_recipe

EDGE = (60.0, 0.0)


@pytest.fixture(scope="module")
def registry():
    return builtin_registry()


@pytest.fixture(scope="module")
def library():
    return didactic_library()


@pytest.fixture(scope="module")
def lift_off(registry, library):
    """S1 run through the runtime — the chain the application opens with."""
    grid, steps = demo_recipe()
    return run_recipe(
        Recipe(grid=grid, recipe_id="s1", steps=steps), registry=registry, library=library
    )


@pytest.fixture(scope="module")
def buried(registry, library):
    """Silicon, 60 nm of oxide on it, resist spun over both — §19.2's stack.

    The one where `phi_resist` is exactly 0.0 along a buried interface it is
    nowhere near, in every column of the domain.
    """
    grid = cross_section_grid(width=300.0, thickness=40.0, headroom=200.0)
    return run_recipe(
        Recipe(
            grid=grid,
            recipe_id="buried",
            steps=(
                RecipeStep("substrate.select", {"material": SILICON, "surface": 40.0}),
                RecipeStep("deposit.conformal_offset", {"material": OXIDE, "thickness": 60.0}),
                RecipeStep("resist.spin_coat", {"material": RESIST, "thickness": 80.0}),
            ),
        ),
        registry=registry,
        library=library,
    )


def _signed_area(loop: np.ndarray) -> float:
    """Shoelace area of a closed loop, positive when it runs counter-clockwise."""
    up, right = loop[:, 0], loop[:, 1]
    return 0.5 * float(np.sum(right[:-1] * up[1:] - right[1:] * up[:-1]))


# -- 1. the structural rule ---------------------------------------------------


def test_the_render_model_needs_no_qt() -> None:
    """`scene`, `session` and `wafer` are Qt-free — the whole ADR-0001 answer.

    Not a portability nicety. If anything that decides geometry lived on the Qt
    side, this import would drag PySide6 in — so this test failing means the
    thing v2 exists to prevent has started happening again.

    `ui.wafer` joined the list in M5. A wafer fan *drives runs*, which is the
    other half of the same rule: the widget in `ui.wafer_view` paints a circle
    per position and decides nothing.
    """
    import subprocess
    import sys

    probe = (
        "import sys;"
        "import nanofab_v3.ui.scene, nanofab_v3.ui.session, nanofab_v3.ui.wafer;"
        "print('PySide6' in sys.modules or 'shiboken6' in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == "False"


def test_rendering_says_it_is_2d_rather_than_pretending(library) -> None:
    """The third 2D-only module is named and refuses a 3D grid (handoff §1)."""
    grid = Grid(origin=(0.0,) * 3, spacing=2.0, shape=(20, 30, 40), axes=("z", "y", "x"))
    built = ctor.add_material(
        Structure(grid), SILICON, ctor.half_space(grid, normal=(1.0, 0.0, 0.0), point=(20.0,) * 3)
    )

    with pytest.raises(ValueError, match="2D by decision"):
        scene_builder.build(built, library=library)


# -- 2. the pictures, and why the naive ones were wrong -----------------------


def test_a_blanket_layer_is_filled_rather_than_a_zero_area_chord(lift_off, library) -> None:
    """An outline that leaves the domain is not a polygon (see `scene`).

    Measured on this stack: the substrate contours as **one open polyline** from
    (40, 300) to (40, 0), and closing it with a chord between its own ends gives
    a horizontal line of zero area — the substrate simply did not appear. Every
    blanket layer has this shape, for the same reason §17.5 gives about the
    lateral faces.
    """
    snapshot = scene_builder.build(lift_off[0].structure, library=library)
    silicon = snapshot.shape_of(SILICON)

    assert silicon is not None
    assert len(silicon.outlines) == 1
    loop = silicon.outlines[0]
    assert np.allclose(loop[0], loop[-1])
    # 40 nm of substrate across 300 nm of domain, counter-clockwise.
    assert _signed_area(loop) == pytest.approx(12000.0, abs=1.0)


def test_a_slab_with_two_open_edges_is_stitched_to_itself(lift_off, library) -> None:
    """Two open contours, one slab: they close against *each other*, not each alone."""
    snapshot = scene_builder.build(lift_off[1].structure, library=library)
    resist = snapshot.shape_of(RESIST)

    assert resist is not None
    assert len(resist.outlines) == 1
    assert _signed_area(resist.outlines[0]) == pytest.approx(27000.0, abs=1.0)


def test_a_material_filling_the_whole_domain_is_the_domain(library) -> None:
    """No contour at all is two different pictures, and empty is only one of them."""
    grid = Grid(origin=(0.0, 0.0), spacing=1.0, shape=(40, 60), axes=("y", "x"))
    everywhere = Structure(grid, {SILICON: grid.full(-5.0)})

    snapshot = scene_builder.build(everywhere, library=library)
    silicon = snapshot.shape_of(SILICON)

    assert silicon is not None and len(silicon.outlines) == 1
    assert _signed_area(silicon.outlines[0]) == pytest.approx(39.0 * 59.0)


def test_every_shape_agrees_with_the_occurrence_labelling(lift_off, library) -> None:
    """The check handoff §4.1 asks for, made mechanical instead of visual.

    A picture whose loop count disagrees with `label_occurrences` is a picture to
    distrust — a phantom contour, or a fill that swallowed a hole. Asserted at
    every revision of S1, which is where the interesting counts are: the resist
    splits in two, the metal lands in three pieces, and one of them survives.
    """
    for index in range(len(lift_off)):
        structure = lift_off[index].structure
        snapshot = scene_builder.build(structure, library=library)
        labelled = occurrences.label_occurrences(structure)
        for shape in snapshot.shapes:
            assert shape.occurrences == labelled.count(shape.material)
            assert len(shape.outlines) == shape.occurrences, (
                f"revision {index}: {shape.material} draws {len(shape.outlines)} loops "
                f"for {shape.occurrences} occurrences"
            )


def test_a_phantom_zero_level_does_not_become_a_contour(buried, library) -> None:
    """§19.2's defect, at the place handoff §4.1 predicted it would surface next.

    On this stack `phi_resist` is exactly 0.0 along the buried silicon/oxide
    interface, 60 nm below the resist's own underside and in **every column**. A
    fill rule of `phi_m <= 0` therefore claims one whole extra row of the domain.
    Marching squares does not: it tests `field < level` strictly, and a phantom
    zero has no strictly-inside cell on either side, so it produces no sign
    change and no contour.
    """
    structure = buried.structure
    phi = np.asarray(structure.phi_of(RESIST))
    from nanofab_v3.kernel import regions

    naive = int(np.count_nonzero(phi <= 0.0))
    honest = int(np.count_nonzero(regions.closed_region(structure.grid, phi)))
    assert naive - honest == structure.grid.shape[1]  # one full row, every column

    snapshot = scene_builder.build(structure, library=library)
    resist = snapshot.shape_of(RESIST)

    assert resist is not None
    assert resist.occurrences == 1
    assert len(resist.outlines) == 1
    assert _signed_area(resist.outlines[0]) == pytest.approx(80.0 * 300.0, abs=200.0)


def test_the_hit_test_reads_the_partition_and_not_the_fields(lift_off, library) -> None:
    """`material_index` is exclusive; `phi_m <= 0` and a filled path are not."""
    snapshot = scene_builder.build(lift_off[4].structure, library=library)

    assert snapshot.material_at((20.0, 150.0)) == SILICON
    assert snapshot.material_at((50.0, 150.0)) == METAL  # in the window, on the wafer
    assert snapshot.material_at((100.0, 50.0)) == RESIST  # beside it, on the resist
    assert snapshot.material_at((230.0, 150.0)) is None  # headroom
    assert snapshot.material_at((-5.0, 10.0)) is None  # outside the domain


def test_overlays_are_computed_only_when_asked_for(lift_off, library) -> None:
    """Handoff §4.3: a predicate is 3-12 ms, which is cheap once and not per frame."""
    plain = scene_builder.build(lift_off[4].structure, library=library)
    asked = scene_builder.build(
        lift_off[4].structure, library=library, overlays=("reachable", "voids")
    )

    assert plain.overlays == ()
    assert [overlay.kind for overlay in asked.overlays] == ["reachable", "voids"]
    assert asked.overlays[0].outlines
    assert "cells a bath can touch" in asked.overlays[0].note


def test_normals_are_read_off_the_union_front_not_the_solid_field(buried, library) -> None:
    """Trap §17.1, third milestone running, at the place the handoff predicted.

    Where two materials touch, `solid_phi` is exactly zero along their buried
    seam, so its gradient there is a seam's gradient and the arrows would sprout
    from the middle of continuous material. This stack has such a seam at 40 nm
    (silicon/oxide) and another at 100 nm (oxide/resist); every normal has to
    start on the real surface at 180 nm.
    """
    segments = scene_builder.surface_normals(buried.structure)

    assert segments is not None and len(segments)
    starts = segments[:, 0, 0]
    assert float(np.min(starts)) > 150.0
    assert float(np.max(starts)) == pytest.approx(180.0, abs=1.0)


def test_the_index_map_is_the_partition_the_canvas_rasterises(lift_off, library) -> None:
    snapshot = scene_builder.build(lift_off[4].structure, library=library)

    assert snapshot.index_map is not None
    assert snapshot.index_map.shape == lift_off[4].structure.grid.shape
    assert set(np.unique(snapshot.index_map)) <= {-1, 0, 1, 2}
    assert set(snapshot.palette) == set(lift_off[4].structure.materials)


# -- 3. the interactive session, which needs no display -----------------------


def test_a_session_gates_on_capabilities_with_the_sentence(registry, library) -> None:
    """v1 could say "step 4 has not run"; v2 says what is missing about the sample.

    Two sentences, in the order an operator meets them: before anything exists,
    E4's — there is no domain, select a substrate — and after that, the
    capability the step actually wants.
    """
    session = Session(registry=registry, library=library)

    assert session.capabilities == frozenset()
    assert "substrate" in (session.blocked_reason("develop.ideal") or "")
    assert session.runnable_steps() == ("substrate.select",)

    session.run("substrate.select", {"material": SILICON, "surface": 40.0})
    assert "resist.exposed" in (session.blocked_reason("develop.ideal") or "")
    assert "develop.ideal" not in session.runnable_steps()
    session.run("resist.spin_coat", {"material": RESIST, "thickness": 90.0})

    assert session.blocked_reason("develop.ideal") is not None
    session.run(
        "litho.expose_ideal",
        {"material": RESIST, "pattern": "window", "center": 150.0, "width": 100.0},
    )
    assert session.blocked_reason("develop.ideal") is None


def test_a_session_refuses_a_step_before_anything_moves(registry, library) -> None:
    session = Session(registry=registry, library=library)

    with pytest.raises(CapabilityError, match="resist.exposed"):
        session.run("develop.ideal", {"material": RESIST})

    assert len(session.chain) == 0
    assert len(session.recipe) == 0


def test_a_session_grows_a_recipe_and_a_chain_together(registry, library) -> None:
    """What makes an interactive run replayable without anybody writing it down."""
    grid, steps = demo_recipe()
    session = Session(grid, registry=registry, library=library, recipe_id="demo")
    for step in steps:
        session.run(step.step_id, step.params)

    assert len(session.chain) == len(steps)
    assert [entry.step_id for entry in session.recipe] == [s.step_id for s in steps]
    assert session.structure.materials == (SILICON, METAL)


def test_a_session_shows_a_failing_gate_rather_than_raising(registry, library) -> None:
    """Plan §4.5: a suspicious step is visible, never silent. `strict` is a batch flag.

    The failing step is a coat that will not fit under a deliberately low domain
    cap. Since M7 a coat taller than the headroom simply grows the domain (E5);
    what a session still has to *show* rather than raise on is the cap, and the
    log line beside the failure says what raising it would cost.
    """
    grid = cross_section_grid(width=200.0, thickness=40.0, headroom=140.0)
    session = Session(
        grid, registry=registry, library=library, domain=DomainPolicy(cap=260.0)
    )
    session.run("substrate.select", {"material": SILICON, "surface": 40.0})

    revision = session.run("resist.spin_coat", {"material": RESIST, "thickness": 400.0})

    assert not revision.ok
    assert len(session.chain) == 2
    assert any("headroom" in message for message in revision.validation.failures)
    assert any("Raising the cap" in line and "MB of RAM" in line for line in revision.logs)
    assert not session.chain.summary(1).ok


def test_rewinding_a_session_truncates_the_recipe_too(registry, library) -> None:
    grid, steps = demo_recipe()
    session = Session(grid, registry=registry, library=library)
    for step in steps:
        session.run(step.step_id, step.params)

    session.rewind(3)

    assert len(session.chain) == 3
    assert len(session.recipe) == 3
    assert session.structure.materials == (SILICON, RESIST)


def test_a_session_round_trips_through_disk(registry, library, tmp_path) -> None:
    """The DoD's save/load half, at the level a person actually saves at."""
    grid, steps = demo_recipe()
    session = Session(grid, registry=registry, library=library, recipe_id="demo")
    for step in steps:
        session.run(step.step_id, step.params)

    session.save(tmp_path / "session")
    loaded = Session.load(tmp_path / "session", registry=registry, library=library)

    assert len(loaded.chain) == len(session.chain)
    assert loaded.capabilities == session.capabilities
    assert [e.step_id for e in loaded.recipe] == [e.step_id for e in session.recipe]
    assert loaded.recipe.grid == session.recipe.grid
    for material in session.structure.materials:
        assert np.array_equal(
            np.asarray(loaded.structure.phi_of(material)),
            np.asarray(session.structure.phi_of(material)),
        )


def test_a_loaded_session_can_be_continued(registry, library, tmp_path) -> None:
    """A saved session is a session, not a picture of one."""
    grid, steps = demo_recipe()
    session = Session(grid, registry=registry, library=library)
    for step in steps[:4]:
        session.run(step.step_id, step.params)
    session.save(tmp_path / "session")

    loaded = Session.load(tmp_path / "session", registry=registry, library=library)
    loaded.run("deposit.evaporate", {"material": METAL, "thickness": 20.0})

    assert len(loaded.chain) == 5
    assert METAL in loaded.structure.materials
    assert loaded.chain[4].parent == 3


def test_a_session_replays_at_another_wafer_position(registry, library) -> None:
    """Plan §8, reached from the UI: "what would the edge have done?"."""
    grid, steps = demo_recipe()
    session = Session(grid, registry=registry, library=library, recipe_id="demo")
    for step in steps:
        session.run(step.step_id, step.params)

    elsewhere = session.at_position(EDGE)

    assert elsewhere.position == EDGE
    assert len(elsewhere) == len(session.chain)
    assert elsewhere.capabilities == session.capabilities
    assert elsewhere[-1].history.position == EDGE
    assert session.chain[-1].history.position == CENTER


def test_a_scene_is_derived_and_the_v1_layer_list_does_not_come_back(
    registry, library
) -> None:
    """Plan §3.6: where the UI wants a stack summary, it is derived."""
    grid, steps = demo_recipe()
    session = Session(grid, registry=registry, library=library)
    for step in steps:
        session.run(step.step_id, step.params)

    early = session.scene(1)
    late = session.scene()

    assert [shape.material for shape in early.shapes] == [SILICON, RESIST]
    assert [shape.material for shape in late.shapes] == [SILICON, METAL]
    assert early.caption.startswith("#1")
    assert not hasattr(session, "layers")


# -- 4. the Qt half, headless -------------------------------------------------


@pytest.fixture(scope="module")
def qt_app():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_the_window_builds_and_runs_the_demo(qt_app, library) -> None:
    """The DoD's other half: an interactive session that is usable."""
    from nanofab_v3.ui.window import MainWindow

    window = MainWindow()
    window.resize(1280, 800)
    window._on_demo()

    assert window.revisions.list.count() == 6
    assert window.log.view.toPlainText()
    assert f"material:{METAL}" in window.session.capabilities
    assert f"material:{RESIST}" not in window.session.capabilities


def test_the_step_list_greys_out_what_the_revision_cannot_run(qt_app, library) -> None:
    from PySide6.QtCore import Qt

    from nanofab_v3.ui.panels import StepListPanel

    panel = StepListPanel(builtin_registry())
    # A sample that exists, so the sentence is about the *step's* requirement.
    # With nothing at all it is E4's instead — asserted just below, because both
    # are things the step list has to be able to say.
    panel.refresh(frozenset({capability.DOMAIN}))
    blocked = [
        panel.list.item(row).toolTip()
        for row in range(panel.list.count())
        if panel.list.item(row).data(Qt.UserRole) == "develop.ideal"
    ]

    assert blocked and "resist.exposed" in blocked[0]

    panel.refresh(frozenset())
    before_anything = [
        panel.list.item(row).toolTip()
        for row in range(panel.list.count())
        if panel.list.item(row).data(Qt.UserRole) == "develop.ideal"
    ]

    assert before_anything and "substrate is always the first step" in before_anything[0]

    panel.refresh(frozenset({capability.DOMAIN, f"material:{RESIST}", f"{RESIST}.exposed"}))
    ready = [
        panel.list.item(row).toolTip()
        for row in range(panel.list.count())
        if panel.list.item(row).data(Qt.UserRole) == "develop.ideal"
    ]

    assert ready == ["develop.ideal: ready"]


def test_the_canvas_paints_the_sample_and_the_index_map(qt_app, lift_off, library) -> None:
    """Both of plan §10's paths, rendered offscreen and checked for content."""
    from PySide6.QtGui import QImage

    from nanofab_v3.ui.canvas import CrossSectionCanvas

    canvas = CrossSectionCanvas()
    canvas.resize(600, 400)
    canvas.set_scene(
        scene_builder.build(lift_off[4].structure, library=library, overlays=("reachable",))
    )

    outlines = _render(canvas, QImage)
    canvas.set_index_map_visible(True)
    raster = _render(canvas, QImage)

    assert len(np.unique(outlines.reshape(-1, 4), axis=0)) > 8
    assert len(np.unique(raster.reshape(-1, 4), axis=0)) > 4
    assert not np.array_equal(outlines, raster)


def test_the_canvas_says_what_is_under_the_cursor(qt_app, lift_off, library) -> None:
    """The hit test goes through `SceneSnapshot`, never through a painted path."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    from nanofab_v3.ui.canvas import CrossSectionCanvas

    canvas = CrossSectionCanvas()
    canvas.resize(600, 400)
    canvas.set_scene(scene_builder.build(lift_off[4].structure, library=library))
    seen: list[str] = []
    canvas.hovered.connect(seen.append)

    canvas.mouseMoveEvent(
        QMouseEvent(
            QMouseEvent.MouseMove,
            QPointF(300.0, 380.0),
            QPointF(300.0, 380.0),
            Qt.NoButton,
            Qt.NoButton,
            Qt.NoModifier,
        )
    )

    assert seen and "nm" in seen[0]


def _render(widget, QImage) -> np.ndarray:
    """Paint a widget offscreen and return its pixels.

    The copy is not decoration: `constBits()` hands back a view into the
    `QImage`'s buffer, and the image is freed when this function returns — read
    afterwards, the array is whatever the allocator did with the memory since.
    Without it this helper reported five colours for a canvas that paints 831.
    """
    image = QImage(widget.size(), QImage.Format_ARGB32)
    image.fill(0)
    widget.render(image)
    pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(
        image.height(), image.width(), 4
    )
    return np.array(pixels, copy=True)
