"""The application shell (plan §10).

The v0.2.0 `nanofab_manager` layout, carried over: steps on the left, the sample
in the middle, the chain and the run log around it. Read out of
`ui_backups/2026-08-25_v0.2.0_nanofab-manager/` and rewritten here — a snapshot is
a record, not a branch (`AGENTS.md` §7).

What this file is allowed to contain is wiring: a widget knows about the
`Session` and the `Session` knows about the runtime. It holds **no** state about
the sample, because the sample's state is the revision chain and the picture of
it is a `SceneSnapshot` derived on demand. That is the rule ADR-0001's autopsy
came down to, applied one level up from the canvas.
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from nanofab_v3 import __version__
from nanofab_v3.io import replay_cache_for
from nanofab_v3.processes.contract import CapabilityError, ParameterError
from nanofab_v3.processes.lithography import pattern_from_params as lithography_pattern
from nanofab_v3.ui.canvas import CrossSectionCanvas
from nanofab_v3.ui.panels import (
    ParameterForm,
    RevisionListPanel,
    RunLogPanel,
    StepListPanel,
)
from nanofab_v3.ui.scene import ALWAYS_ON, OVERLAY_KINDS, light_preview
from nanofab_v3.ui.scene import build as build_scene
from nanofab_v3.ui.demos import demo, demos as all_demos
from nanofab_v3.ui.session import Session
from nanofab_v3.ui.wafer import WaferFan, default_cache_dir
from nanofab_v3.ui.wafer_view import WaferPanel

APP_NAME = "NanoFab Structure Model"
"""The v2 application's name. The v0.2.0 shell it descends from was "NanoFab Manager"."""


class MainWindow(QMainWindow):
    """Steps, sample, chain, log — the four panels of plan §10."""

    def __init__(self, session: Session | None = None) -> None:
        super().__init__()
        self.session = session or Session()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1280, 800)

        self.steps = StepListPanel(self.session.registry)
        self.form = ParameterForm()
        self.canvas = CrossSectionCanvas()
        self.revisions = RevisionListPanel()
        self.log = RunLogPanel()
        self.wafer = WaferPanel()
        self.wafer.setVisible(False)
        self._overlays: dict[str, QCheckBox] = {}

        self.setCentralWidget(self._build_layout())
        self.setStatusBar(QStatusBar())
        self._build_menu()

        self.steps.step_chosen.connect(self._on_step_chosen)
        self.steps.run_requested.connect(self._on_run)
        self.revisions.revision_chosen.connect(self._on_revision_chosen)
        self.revisions.repeat_requested.connect(self._on_repeat)
        self.revisions.adjust_requested.connect(self._on_adjust)
        self.revisions.remove_requested.connect(self._on_remove)
        self.canvas.hovered.connect(self.statusBar().showMessage)
        self.wafer.position_chosen.connect(self._on_wafer_position)

        self.log.append(self.session.plugins.describe())
        self._refresh_all()

    # -- layout --------------------------------------------------------------

    def _build_layout(self) -> QWidget:
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(self.steps, 3)
        left_layout.addWidget(self.form, 2)

        middle = QWidget()
        middle_layout = QVBoxLayout(middle)
        middle_layout.addWidget(self.canvas, 1)
        middle_layout.addLayout(self._build_view_controls())

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(self.revisions, 1)
        right_layout.addWidget(self.log, 2)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(middle)
        splitter.addWidget(right)
        # Hidden until asked for: a wafer fan is not what an operator looks at
        # while building a recipe, and nine positions is minutes of solver.
        splitter.addWidget(self.wafer)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([320, 640, 320, 300])
        return splitter

    def _build_view_controls(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("Overlays:"))
        for kind in OVERLAY_KINDS:
            box = QCheckBox(kind)
            if kind in ALWAYS_ON:
                # Roadmap E9: the exposure *result* colours without being asked,
                # because a latent image you have to remember to look for is a
                # latent image nobody looks at. Not free — the outline costs
                # about as much as a predicate (§24.7) — but a scene is rebuilt
                # when the revision changes, not per frame.
                box.setChecked(True)
                box.setToolTip(
                    f"Show the {kind} field the exposure wrote. On by default (roadmap "
                    "E9): the result of an exposure should not be something you have "
                    "to switch on."
                )
            else:
                # Off by default and computed only when ticked: a predicate is
                # 3-12 ms at the reference grid, which is cheap once and not cheap
                # every frame (handoff §4.3).
                box.setToolTip(f"Compute the {kind} predicate for the shown revision")
            box.stateChanged.connect(self._refresh_canvas)
            self._overlays[kind] = box
            row.addWidget(box)
        self.light_box = QCheckBox("light preview")
        self.light_box.setToolTip(
            "Draw where the light would fall, from the mask parameters in the form — "
            "geometry only, before the step runs. The difference from the exposed "
            "overlay is the aerial image."
        )
        self.light_box.stateChanged.connect(self._refresh_canvas)
        row.addWidget(self.light_box)
        row.addStretch(1)
        self.true_to_scale_box = QCheckBox("true to scale")
        self.true_to_scale_box.setToolTip(
            "Draw the domain 1:1 whatever its aspect ratio. Off by default: a very "
            "deep or very narrow domain is otherwise a sliver. The compression "
            "factor is shown in the picture either way — it is never silent."
        )
        self.true_to_scale_box.stateChanged.connect(
            lambda _state: self.canvas.set_true_to_scale(self.true_to_scale_box.isChecked())
        )
        self.index_map_box = QCheckBox("index map")
        self.index_map_box.setToolTip(
            "Paint material_index directly — one pixel per cell, the honest "
            "picture of what the model stores"
        )
        self.index_map_box.stateChanged.connect(
            lambda state: self.canvas.set_index_map_visible(bool(state))
        )
        row.addWidget(self.true_to_scale_box)
        row.addWidget(self.index_map_box)
        return row

    def _build_menu(self) -> None:
        """The menus, and the one distinction the Session menu now makes.

        **A recipe and a build are two different things to save**, and keeping
        them one action meant paying the expensive price for the cheap thing. A
        recipe is a few kilobytes of text — readable, diffable, mailable — and a
        build is every `phi` of every revision, hundreds of megabytes and half a
        minute for the etch-stop demo. So: `Save recipe…` on Ctrl+S, because it is
        the one worth doing often, and `Save build…` without a shortcut, because
        it is a decision.

        Opening a recipe does **not** run it (`Session.load_recipe`), which is why
        `Run the loaded recipe` exists as its own entry: a load that computed
        would make opening a file a twenty-five-second commitment. The revision
        list is empty until it runs, and the status bar and the log say so.

        The demos are their own menu, which is where the stray "Run the lift-off
        demo" that used to sit at the bottom of the Session menu went — it was the
        pre-M8 single demo, still there after the picker replaced it, offering
        entry one of four from the wrong menu.
        """
        session_menu = self.menuBar().addMenu("&Session")
        for text, shortcut, slot, tip in (
            ("&New", QKeySequence.New, self._on_new, "Start over on an empty domain"),
            (
                "&Open recipe…",
                QKeySequence.Open,
                self._on_open_recipe,
                "Read a recipe file. Nothing is computed — run it when you want it.",
            ),
            (
                "&Save recipe…",
                QKeySequence.Save,
                self._on_save_recipe,
                "Write the steps as one JSON file. Kilobytes, and no structures.",
            ),
        ):
            action = QAction(text, self)
            action.setShortcut(shortcut)
            action.setToolTip(tip)
            action.triggered.connect(slot)
            session_menu.addAction(action)
        session_menu.addSeparator()
        for text, slot, tip in (
            (
                "Open &build…",
                self._on_open_build,
                "Read a saved build back: the recipe and every computed revision.",
            ),
            (
                "Save &build…",
                self._on_save_build,
                "Write <name>.recipe.json and a <name>/ folder with every step in it.",
            ),
        ):
            action = QAction(text, self)
            action.setToolTip(tip)
            action.triggered.connect(slot)
            session_menu.addAction(action)
        session_menu.addSeparator()
        self._run_recipe_action = QAction("&Run the loaded recipe", self)
        self._run_recipe_action.setToolTip("Compute the steps that have no revision yet")
        self._run_recipe_action.triggered.connect(self._on_run_recipe)
        self._run_recipe_action.setEnabled(False)
        session_menu.addAction(self._run_recipe_action)

        demo_menu = self.menuBar().addMenu("&Demos")
        for entry in all_demos():
            action = QAction(entry.title, self)
            action.setToolTip(f"{entry.summary} — {len(entry.steps)} steps")
            action.triggered.connect(lambda _checked, key=entry.key: self._on_demo(key))
            demo_menu.addAction(action)

        wafer_menu = self.menuBar().addMenu("&Wafer")
        fan = QAction("&Fan this recipe over the wafer", self)
        fan.setToolTip(
            "Replay the current recipe at the centre and four edge positions "
            "(plan §8): each one is an independent chain, materialized in the "
            "background and cached per position."
        )
        fan.triggered.connect(self._on_fan_out)
        wafer_menu.addAction(fan)
        show = QAction("Show the wafer &map", self, checkable=True)
        show.toggled.connect(self.wafer.setVisible)
        wafer_menu.addAction(show)
        self._wafer_visible_action = show

    # -- reacting ------------------------------------------------------------

    def _refresh_all(self) -> None:
        self.steps.refresh(self.session.capabilities)
        self.revisions.refresh(self.session.chain)
        # Enabled exactly when there is something to run: a loaded recipe whose
        # steps have no revisions, or one a failing step stopped part way. Greyed
        # out otherwise, so the menu answers "is there anything left" by itself.
        action = getattr(self, "_run_recipe_action", None)
        if action is not None:
            pending = len(self.session.pending)
            action.setEnabled(bool(pending))
            action.setText(
                "&Run the loaded recipe" if not pending else f"&Run the loaded recipe ({pending})"
            )
        self._refresh_canvas()

    def _refresh_canvas(self) -> None:
        overlays = [kind for kind, box in self._overlays.items() if box.isChecked()]
        index = self.revisions.selected_index()
        scene = self.session.scene(index, overlays=overlays)
        preview = self._light_preview(index)
        self.canvas.set_scene(scene if preview is None else scene.with_light(preview))

    def _light_preview(self, index: int | None):
        """E9's preview, from the form's own values — never from the sample.

        Only while an exposure step is selected, because the mask parameters are
        that step's and asking any other step for them would be inventing a mask.
        Failures are swallowed on purpose: a half-typed period in a spin box is a
        normal state for a form to be in, and a preview is not worth a dialog.
        """
        if not self.light_box.isChecked():
            return None
        step_id = self.steps.selected_step_id() or ""
        if not step_id.startswith("litho."):
            return None
        structure = (
            self.session.structure
            if index is None or not len(self.session.chain)
            else self.session.chain[index].structure
        )
        try:
            pattern = lithography_pattern(structure.grid, self.form.values())
            return light_preview(structure, pattern)
        except (ValueError, KeyError, TypeError):
            return None

    def _on_step_chosen(self, step_id: str) -> None:
        registry = self.session.registry
        step = registry[step_id]
        self.form.set_step(
            step_id,
            registry.display_name(step_id),
            step.parameter_schema(),
            registry.describe(step_id),
        )

    def _on_revision_chosen(self, index: int) -> None:
        self._refresh_canvas()
        revision = self.session.chain[index]
        self.form.set_values(revision.history.params)

    def _on_run(self, step_id: str) -> None:
        # The engine's verdict is shown rather than second-guessed: the UI has no
        # separate idea of what a legal recipe is (see `panels`). `_run_and_show`
        # is where that happens, shared with E12's repeat.
        self._run_and_show(lambda: self.session.run(step_id, self.form.values()))

    def _ask_about_unknown_materials(self) -> None:
        """Roadmap E15: a material the library cannot answer for gets asked about.

        After the step rather than before it, because a material can arrive
        without any step naming it — a scattered particle, a plugin's own film —
        and that is the case the rule was written for. The step is not undone: it
        already ran at rate 0, which is what the run log says, and describing the
        material now means the *next* step knows it. Undoing it would be worse,
        because it would make the warning cost work rather than explain it.
        """
        unknown = self.session.unknown_materials()
        if not unknown:
            return
        from nanofab_v3.ui.material_dialog import ask_about

        for entry in ask_about(unknown.missing, self):
            path = self.session.describe_material(entry)
            self.log.append((f"described {entry.material_id} -> {path}",))
        self._refresh_all()

    def _offer_to_raise_the_domain_cap(self, revision) -> None:
        """Roadmap E5: at the cap, warn with an estimate and offer to raise it.

        The one place the domain is *not* autonomous, and deliberately: growing
        and shrinking are decisions the model can make (it knows where the sample
        is), and spending another gigabyte is a decision only the person paying
        for it can. So the estimate is shown before the choice, not after — plan
        §20.3's honest 6x-500x range for disk included, because a single number
        there would be a fiction.
        """
        change = revision.domain
        if not change.capped:
            return
        grid = revision.structure.grid
        wanted = (grid.shape[0] + change.wanted) * grid.spacing
        detail = "\n".join(change.describe(grid))
        answer = QMessageBox.question(
            self,
            "The domain is at its cap",
            f"{detail}\n\nRaise the cap to {wanted / 1000.0:.2f} um for this session?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.session.domain = replace(self.session.domain, cap=wanted)
        self.log.append(
            (
                f"domain cap raised to {wanted / 1000.0:.2f} um — rerun the step to use it",
            )
        )

    # -- E12: repeat, adjust, remove -----------------------------------------

    def _on_repeat(self, index: int) -> None:
        """Run the step that made this revision again, at the head.

        Appending, not replacing: a second 10 s etch really is 20 s of etching,
        and pretending otherwise would be the one thing a didactic tool must not
        do with a process time.
        """
        self._run_and_show(lambda: self.session.repeat(index))

    def _on_adjust(self, index: int) -> None:
        """Truncate to before this revision and put its parameters back in the form.

        E12's "anpassen", spelled out: there is no branching here, so adjusting a
        step is throwing away what came after it and running it again. The cost
        is asked about rather than assumed, because it is measured in work.
        """
        losing = len(self.session.chain) - index
        if losing > 1 and not self._confirm_truncate(index, losing):
            return
        entry = self.session.recipe[index]
        params = self.session.parameters_of(index)
        self.session.rewind(index)
        self.steps.select_step(entry.step_id)
        self._on_step_chosen(entry.step_id)
        self.form.apply_values(params)
        self._refresh_all()
        self.statusBar().showMessage(
            f"Adjusting {entry.step_id}: change the parameters and press Run", 8000
        )

    def _on_remove(self, index: int) -> None:
        """Drop this revision and everything after it."""
        losing = len(self.session.chain) - index
        if losing > 1 and not self._confirm_truncate(index, losing):
            return
        self.session.rewind(index)
        self._refresh_all()
        self.statusBar().showMessage(f"Removed {losing} revision(s)", 5000)

    def _confirm_truncate(self, index: int, losing: int) -> bool:
        """Ask before throwing away work — and say exactly how much of it."""
        answer = QMessageBox.question(
            self,
            "Remove revisions?",
            f"This drops revision #{index} and the {losing - 1} after it.\n\n"
            "A snapshot is a record, not a branch: what came after is gone rather "
            "than kept beside what comes next.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _run_and_show(self, action) -> None:
        """Run something that appends a revision, and show whatever it said."""
        try:
            revision = action()
        except (CapabilityError, ParameterError) as error:
            QMessageBox.warning(self, "Step not run", str(error))
            return
        self.log.append(self.session.log_lines(revision))
        self._refresh_all()
        self._ask_about_unknown_materials()
        self._offer_to_raise_the_domain_cap(revision)
        if not revision.ok:
            self.statusBar().showMessage(
                f"#{revision.index} {revision.step_id}: "
                + "; ".join(revision.validation.failures),
                10_000,
            )

    def _on_new(self) -> None:
        self.session.reset()
        self.log.view.clear()
        self._refresh_all()

    def _on_demo(self, key: str = "lift_off") -> None:
        """Run one demo end to end (roadmap M8): a real recipe, not a mock-up of one.

        The explanation goes into the run log **before** the first step, because
        what makes a demo teach anything is knowing what to watch for while it
        happens — afterwards it is a shape somebody has to interpret.

        Since the demos moved to JSON a step may also carry a `note` saying why
        its numbers are what they are, and that is logged as the step runs: the
        moment somebody wonders about a duration is the moment it is on screen.
        """
        entry = demo(key)
        self.session.reset(entry.grid)
        self.session.recipe = replace(self.session.recipe, steps=tuple(entry.steps))
        self.log.view.clear()
        self.log.append((entry.describe(),))
        self._run_pending(entry.title, notes=entry.notes)
        self.statusBar().showMessage(f"{entry.title}: {entry.watch_for}", 30_000)

    def _run_pending(self, title: str, *, notes: tuple[str, ...] = ()) -> None:
        """Compute the recipe steps that have no revision yet, visibly.

        The one runner behind both the Demos menu and `Run the loaded recipe`,
        because they are the same act: a recipe exists and its structures do not.
        Foreground with a wait cursor and the events pumped between steps, so the
        chain and the log fill in as it goes. The etch-stop demo is about 25 s of
        solver; backgrounding it the way the wafer fan does would be the better
        answer and is deliberately not done here, because the fan's runner is built
        around *positions* and one interactive chain is not that.
        """
        total = len(self.session.recipe.steps)

        def announce(index: int, _total: int, step) -> None:
            self.statusBar().showMessage(f"{title}: step {index + 1} of {total} — {step.step_id}")
            if index < len(notes) and notes[index]:
                self.log.append((f"  ({notes[index]})",))
            QApplication.processEvents()

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for revision in self.session.run_recipe(on_step=announce):
                self.log.append(self.session.log_lines(revision))
                self.revisions.refresh(self.session.chain)
                QApplication.processEvents()
        except (CapabilityError, ParameterError) as error:
            QMessageBox.warning(self, "The recipe stopped", str(error))
        finally:
            QApplication.restoreOverrideCursor()
        self._refresh_all()

    # -- the wafer fan (plan §8, §14) ----------------------------------------

    def _on_fan_out(self) -> None:
        """Materialize the current recipe at the centre and four edge positions.

        The engine has been able to do this since M4; what happens here is a
        `WaferFan` over the session's own recipe, sharing the one cache directory
        (`ui.wafer.default_cache_dir`) so a position the session already ran is
        a 0.11 s replay rather than a 7.6 s solve.
        """
        if not len(self.session.recipe):
            QMessageBox.information(
                self, "Nothing to fan out", "Run at least one step first."
            )
            return
        cache = replay_cache_for(
            default_cache_dir(), self.session.recipe, registry=self.session.registry
        )
        fan = WaferFan.on_radius(
            self.session.recipe,
            radius=60.0,
            count=4,
            registry=self.session.registry,
            library=self.session.library,
            cache=cache,
            sink=self.session.sink,
        )
        self.wafer.set_fan(fan)
        self.wafer.setVisible(True)
        self._wafer_visible_action.setChecked(True)
        self.wafer.start()
        self.log.append((f"wafer: materializing {len(fan.positions)} positions",))

    def _on_wafer_position(self, position) -> None:
        """Show one position's sample — one scene built per selection, not per paint.

        Handoff §4, trap 4: a `SceneSnapshot` is 107 ms, so nine of them per
        frame is a second a frame. This builds exactly one, for the position that
        was clicked, and a position that is still solving shows the revisions it
        already has rather than nothing.
        """
        if self.wafer.fan is None:
            return
        status = self.wafer.fan.status(position)
        structure = status.structure
        if structure is None:
            self.statusBar().showMessage(status.describe(), 5000)
            return
        overlays = [kind for kind, box in self._overlays.items() if box.isChecked()]
        self.canvas.set_scene(
            build_scene(
                structure,
                library=self.session.library,
                overlays=overlays,
                caption=status.describe(),
            )
        )
        self.statusBar().showMessage(status.describe(), 5000)

    def _on_save_recipe(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self, "Save the recipe as…", "recipe.recipe.json", "Recipe (*.recipe.json *.json)"
        )
        if not path:
            return
        written = self.session.save_recipe(Path(path))
        self.statusBar().showMessage(
            f"Wrote {written.name} — {len(self.session.recipe.steps)} steps, no structures", 8000
        )

    def _on_save_build(self) -> None:
        """`<name>.recipe.json` and a `<name>/` folder, from one chosen name.

        A save *file* dialog rather than a directory one, although the bigger half
        of what this writes is a directory: the name is what the two share, and
        asking for a folder would make the recipe file's name a thing this code
        invented rather than a thing somebody chose.
        """
        path, _filter = QFileDialog.getSaveFileName(
            self, "Save the build as…", "build", "Build (*)"
        )
        if not path:
            return
        recipe_file, directory = self.session.save_build(Path(path))
        self.statusBar().showMessage(
            f"Wrote {recipe_file.name} and {directory.name}/ "
            f"({len(self.session.chain)} revisions)",
            8000,
        )

    def _on_open_recipe(self) -> None:
        """Read a recipe and stop there — see `_build_menu` for why it does not run.

        The log gets the whole step list, because the revision panel has nothing
        to show yet and "I opened a file and the window did not change" is what
        this would otherwise look like.
        """
        path, _filter = QFileDialog.getOpenFileName(
            self, "Open a recipe", "", "Recipe (*.recipe.json *.json)"
        )
        if not path:
            return
        try:
            steps = self.session.load_recipe(Path(path))
        except (OSError, ValueError, KeyError) as error:
            QMessageBox.warning(self, "Could not open", str(error))
            return
        self.log.view.clear()
        self.log.append(
            (f"{Path(path).name} — {len(steps)} steps, not run yet:",)
            + tuple(f"  {index + 1}. {step.step_id}" for index, step in enumerate(steps))
            + ("Session -> Run the loaded recipe computes them.",)
        )
        self._refresh_all()
        self.statusBar().showMessage(
            f"{len(steps)} steps loaded — nothing computed yet", 15_000
        )

    def _on_run_recipe(self) -> None:
        pending = len(self.session.pending)
        if not pending:
            self.statusBar().showMessage("Every step of this recipe already has a revision", 5000)
            return
        self._run_pending(self.session.recipe.recipe_id)
        self.statusBar().showMessage(f"Ran {pending} step(s)", 8000)

    def _on_open_build(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Open a saved build")
        if not directory:
            return
        try:
            self.session = Session.load(
                Path(directory),
                registry=self.session.registry,
                library=self.session.library,
            )
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Could not open", str(error))
            return
        self.log.view.clear()
        self.log.append(self.session.chain.logs())
        self._refresh_all()


def run(argv: list[str] | None = None) -> int:
    """Start the application. The only function in this package that needs a display."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(argv or [])
    window = MainWindow()
    window.show()
    return int(app.exec())
