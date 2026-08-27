"""The shell's panels: step list, parameter form, run log (plan §10).

Carried over from the v0.2.0 `nanofab_manager` shell in
`ui_backups/2026-08-25_v0.2.0_nanofab-manager/` — read from there and rewritten
here, per `AGENTS.md` §7. What carries over is the *shape*: a list of steps on the
left with a status per row, a typed parameter form in the middle, a run log
underneath. What does not carry over is the thing that made the shape work in v1.

## Gating moved from step ids to capabilities

v1's `StepRuntime.status` came from `prerequisites: list[step_id]` — "development
is blocked until step #4 has run" — so the UI could only ever say *which step*
was missing. v2 gates on capabilities (plan §5.3): a step is runnable when the
current revision carries every promise it requires, and
`registry.blocked_reason(step_id, capabilities)` produces the sentence. The
difference is what the operator reads: **"needs resist.exposed, which this
revision does not provide"** names a fact about the sample, which is the thing
they can act on, instead of a fact about the recipe's order.

It is also what makes two fidelity tiers coexist without the UI knowing they
exist: `develop.ideal` needs `resist.exposed`, `develop.rate` needs
`resist.dose`, and whichever exposure ran unlocks its own developer.
`registry.by_technique()` is what groups the tiers under one heading.

## The parameter form is generated, never hand-written

Every widget comes from a `ParamSpec` — kind, unit, range, choices, default —
because that is the contract the engine validates against anyway
(`contract.validate_params`). A form built by hand drifts from the schema, and a
recipe whose UI accepts what the solver rejects is worse than no form.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from nanofab_v3.materials import MaterialLibrary, didactic_library
from nanofab_v3.materials.selection import filtered_choices
from nanofab_v3.processes.contract import FIDELITIES, ParamSpec
from nanofab_v3.ui import presets
from nanofab_v3.processes.registry import ProcessRegistry
from nanofab_v3.runtime.revision import RevisionChain

_RUNNABLE = QColor("#5ac87a")
_BLOCKED = QColor("#8a949e")


class StepListPanel(QWidget):
    """Every registered process, grouped by technique, gated on capabilities.

    Since M8 it is also **searchable** (roadmap E11): a text box over id, name and
    description, plus one checkbox per fidelity tier. The search reaches the
    descriptions because E10 put them there, which is why the two decisions are
    one feature — a list you can search for "undercut" or "hard mask" is only
    possible once the steps say what they do.

    Filtering and gating are different things and stay different: a filtered-out
    step is *hidden*, a blocked one is **shown in grey with a reason**. Hiding
    what the sample cannot run would answer "why can I not do this?" by removing
    the question.

    Signals:
        step_chosen: `(step_id)` when the selection changes.
        run_requested: `(step_id)` when the run button is pressed.
    """

    step_chosen = Signal(str)
    run_requested = Signal(str)

    def __init__(self, registry: ProcessRegistry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._registry = registry
        self._capabilities: frozenset[str] = frozenset()

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search steps — name, id or description")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _text: self.refresh(self._capabilities))
        self.tags: dict[str, QCheckBox] = {}
        tag_row = QHBoxLayout()
        tag_row.setContentsMargins(0, 0, 0, 0)
        for fidelity in FIDELITIES:
            box = QCheckBox(fidelity)
            box.setChecked(True)
            box.setToolTip(f"Show steps at the {fidelity} fidelity tier")
            box.toggled.connect(lambda _on: self.refresh(self._capabilities))
            tag_row.addWidget(box)
            self.tags[fidelity] = box
        tag_row.addStretch(1)

        self.list = QListWidget()
        self.list.setAlternatingRowColors(True)
        self.list.currentItemChanged.connect(self._on_selection)
        self.reason = QLabel("")
        self.reason.setWordWrap(True)
        self.reason.setStyleSheet("color: #8a949e;")
        self.run_button = QPushButton("Run step")
        self.run_button.setEnabled(False)
        self.run_button.clicked.connect(self._on_run)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        heading = QLabel("Process steps")
        heading.setFont(_bold(heading.font()))
        layout.addWidget(heading)
        layout.addWidget(self.search)
        layout.addLayout(tag_row)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.reason)
        layout.addWidget(self.run_button)
        self.refresh(frozenset())

    def selected_fidelities(self) -> tuple[str, ...]:
        """Which fidelity tags are ticked. All of them is the same as none of them."""
        return tuple(name for name, box in self.tags.items() if box.isChecked())

    def visible_step_ids(self) -> tuple[str, ...]:
        """The step ids the filter currently lets through, in list order."""
        return tuple(
            self.list.item(row).data(Qt.UserRole)
            for row in range(self.list.count())
            if self.list.item(row).data(Qt.UserRole)
        )

    def refresh(self, capabilities: Iterable[str]) -> None:
        """Re-gate every row against what the current revision promises."""
        self._capabilities = frozenset(capabilities)
        selected = self.selected_step_id()
        matching = {
            step.step_id
            for step in self._registry.matching(
                self.search.text(), self.selected_fidelities()
            )
        }
        self.list.clear()
        for technique, steps in self._registry.by_technique().items():
            shown = [step for step in steps if step.step_id in matching]
            if not shown:
                continue
            header = QListWidgetItem(technique)
            header.setFlags(Qt.NoItemFlags)
            header.setFont(_bold(header.font()))
            self.list.addItem(header)
            for step in shown:
                reason = self._registry.blocked_reason(step.step_id, self._capabilities)
                name = self._registry.display_name(step.step_id)
                item = QListWidgetItem(f"   {name}  ·  {step.fidelity}")
                item.setData(Qt.UserRole, step.step_id)
                item.setForeground(_RUNNABLE if reason is None else _BLOCKED)
                # The tooltip is the whole difference from v1's gating: it names
                # the missing promise about the sample, not the step that has
                # not run yet.
                item.setToolTip(reason or f"{step.step_id}: ready")
                self.list.addItem(item)
                if step.step_id == selected:
                    self.list.setCurrentItem(item)
        if not matching:
            empty = QListWidgetItem("   nothing matches this search")
            empty.setFlags(Qt.NoItemFlags)
            self.list.addItem(empty)
        self._on_selection(self.list.currentItem(), None)

    def select_step(self, step_id: str) -> bool:
        """Select a step by id, if the filter is currently letting it through.

        Returns whether it could. E12's "adjust" uses it, and a step hidden by
        the search box is a legitimate miss rather than an error — the caller
        loads the parameters either way.
        """
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item.data(Qt.UserRole) == step_id:
                self.list.setCurrentItem(item)
                return True
        return False

    def selected_step_id(self) -> str | None:
        item = self.list.currentItem()
        return None if item is None else item.data(Qt.UserRole)

    def blocked_reason(self, step_id: str) -> str | None:
        return self._registry.blocked_reason(step_id, self._capabilities)

    def _on_selection(self, current, _previous) -> None:
        step_id = None if current is None else current.data(Qt.UserRole)
        if step_id is None:
            self.reason.setText("")
            self.run_button.setEnabled(False)
            return
        reason = self._registry.blocked_reason(step_id, self._capabilities)
        self.reason.setText(reason or "")
        self.run_button.setEnabled(reason is None)
        self.step_chosen.emit(step_id)

    def _on_run(self) -> None:
        step_id = self.selected_step_id()
        if step_id is not None:
            self.run_requested.emit(step_id)


class ParameterForm(QWidget):
    """A typed form generated from a step's `ParamSpec`s (plan §5.1).

    Since M7 it also knows about **presets** (roadmap M7 item 2). A parameter
    that `ui.presets` has a source for gets a grouped dropdown instead of a text
    field, and choosing an entry fills in the fields it drives. What makes that
    bearable rather than annoying is the rule `presets.apply_preset` applies: a
    field the operator changed **by hand** is theirs and is only overwritten
    after a question; everything else is filled in silently.

    Which is why this form tracks `touched`. "Differs from the default" is not
    the same fact — a value that happens to equal what somebody typed is not a
    value they typed — so every editable widget reports user edits, and
    programmatic writes are made behind `_applying` so they do not count as one.
    """

    def __init__(
        self, parent: QWidget | None = None, library: MaterialLibrary | None = None
    ) -> None:
        super().__init__(parent)
        self._widgets: dict[str, QWidget] = {}
        self._library = library if library is not None else didactic_library()
        self._specs: tuple[ParamSpec, ...] = ()
        self._step_id = ""
        self._touched: set[str] = set()
        self._applying = False
        self.title = QLabel("No step selected")
        self.title.setFont(_bold(self.title.font()))
        # Roadmap E10: the step explains itself, here, where somebody is about to
        # run it — rather than in a manual they would have to know exists.
        self.description = QLabel("")
        self.description.setWordWrap(True)
        self.description.setTextFormat(Qt.MarkdownText)
        self.description.setStyleSheet("color: #b7c0c9;")
        self.form = QFormLayout()
        self.form.setLabelAlignment(Qt.AlignRight)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.title)
        layout.addWidget(self.description)
        layout.addLayout(self.form)
        layout.addStretch(1)

    def set_step(
        self,
        step_id: str,
        display_name: str,
        specs: Sequence[ParamSpec],
        description: str = "",
    ) -> None:
        """Rebuild the form for one step, with its long description above it."""
        self._clear()
        self._specs = tuple(specs)
        self._step_id = step_id
        self.title.setText(f"{display_name}   ({step_id})")
        self.description.setText(description)
        self.description.setVisible(bool(description.strip()))
        for spec in self._specs:
            options = presets.options_for(step_id, spec.name)
            if options:
                widget = _preset_box(options)
            elif spec.material is not None:
                widget = MaterialBox(spec, self._library)
            else:
                widget = _widget_for(spec)
            self._widgets[spec.name] = widget
            label = spec.name if not spec.unit else f"{spec.name} [{spec.unit}]"
            widget.setToolTip(spec.description)
            self.form.addRow(QLabel(label), widget)
            self._watch(spec.name, widget)
            if options:
                widget.currentIndexChanged.connect(  # type: ignore[union-attr]
                    lambda _index, name=spec.name: self._on_preset_chosen(name)
                )

    # -- presets (roadmap M7 item 2) -----------------------------------------

    @property
    def step_id(self) -> str:
        """Which step this form belongs to — `""` when none is selected.

        Public because a parameter set only means anything inside the step that
        declared it: `material` on a substrate and `material` on a spin coat are
        two different questions with one name, and writing one into the other by
        name is roadmap §0.1's bug.
        """
        return self._step_id

    def show_all_materials(self) -> None:
        """Turn off every material filter on this form (E22's escape, from code)."""
        for widget in self._widgets.values():
            if isinstance(widget, MaterialBox):
                widget.show_all.setChecked(True)

    def touched(self) -> frozenset[str]:
        """Parameters the operator edited by hand since this step was selected."""
        return frozenset(self._touched)

    def _watch(self, name: str, widget: QWidget) -> None:
        """Mark a parameter touched when a *person* changes it, never a program."""

        def mark(*_args: Any) -> None:
            if not self._applying:
                self._touched.add(name)

        if isinstance(widget, MaterialBox):
            widget.box.activated.connect(mark)
            widget.box.lineEdit().textEdited.connect(mark)
        elif isinstance(widget, QComboBox):
            widget.activated.connect(mark)  # user-driven; `currentIndexChanged` is not
        elif isinstance(widget, QCheckBox):
            widget.clicked.connect(mark)
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            widget.lineEdit().textEdited.connect(mark)
            widget.valueChanged.connect(mark)
        elif isinstance(widget, QLineEdit):
            widget.textEdited.connect(mark)

    def _on_preset_chosen(self, parameter: str) -> None:
        """Fill in what the chosen preset drives, asking before losing any typing."""
        widget = self._widgets[parameter]
        key = widget.currentData()  # type: ignore[union-attr]
        options = {option.key: option for option in presets.options_for(self._step_id, parameter)}
        option = options.get(key)
        if option is None:
            return
        plan = presets.apply_preset(option, self.values(), self._touched)
        agreed: list[str] = []
        if plan.needs_asking:
            answer = QMessageBox.question(
                self,
                "Overwrite what you changed?",
                f"{option.label}\n\n"
                + "\n".join(plan.describe())
                + "\n\nTake the preset's values for these?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                agreed = list(plan.conflicts)
        self.apply_values(plan.resolved(agreed))

    def apply_values(self, values: Mapping[str, Any]) -> None:
        """Write values without marking them as the operator's own typing."""
        self._applying = True
        try:
            self.set_values(values)
        finally:
            self._applying = False
        self._touched -= set(values)

    def values(self) -> dict[str, Any]:
        """What the form currently says, ready for `validate_params`.

        Not validated here on purpose: the engine validates, once, at the
        boundary it owns (`contract.validate_params`). A second validator in the
        UI is a second definition of what a legal recipe is.
        """
        collected: dict[str, Any] = {}
        for spec in self._specs:
            widget = self._widgets[spec.name]
            if isinstance(widget, MaterialBox):
                collected[spec.name] = widget.value()
            elif isinstance(widget, QComboBox):
                # A preset box carries the key as data and shows the label; a
                # `choices` box shows the value itself.
                data = widget.currentData()
                collected[spec.name] = widget.currentText() if data is None else str(data)
            elif isinstance(widget, QCheckBox):
                collected[spec.name] = widget.isChecked()
            elif isinstance(widget, QSpinBox):
                collected[spec.name] = int(widget.value())
            elif isinstance(widget, QDoubleSpinBox):
                collected[spec.name] = float(widget.value())
            else:
                collected[spec.name] = widget.text()  # type: ignore[attr-defined]
        return collected

    def set_values(self, params: Mapping[str, Any]) -> None:
        """Show a recorded parameter set — what a chain's history carries."""
        for name, value in params.items():
            widget = self._widgets.get(name)
            if widget is None:
                continue
            if isinstance(widget, MaterialBox):
                widget.setValue(str(value))
                continue
            if isinstance(widget, QComboBox):
                index = widget.findData(str(value))
                if index >= 0:
                    widget.setCurrentIndex(index)
                else:
                    widget.setCurrentText(str(value))
            elif isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                widget.setValue(type(widget.value())(value))
            elif isinstance(widget, QLineEdit):
                widget.setText(str(value))

    def set_enabled(self, enabled: bool) -> None:
        for widget in self._widgets.values():
            widget.setEnabled(enabled)

    def set_library(self, library: MaterialLibrary) -> None:
        """Use another library for the material dropdowns (E15 wrote an entry)."""
        self._library = library
        for widget in self._widgets.values():
            if isinstance(widget, MaterialBox):
                widget.setLibrary(library)

    def _clear(self) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        self._widgets.clear()
        self._specs = ()
        self._touched.clear()
        self.description.clear()


class MaterialBox(QWidget):
    """A material dropdown that filters hard, says why, and has a way out (E22).

    Three parts, and each is one clause of the decision:

    - An **editable** combo. The list is what the step's `MaterialFilter` admits;
      typing is what E15 needs, because a material the library has never heard of
      is the fastest way to try something uncalibrated and the unknown-material
      dialog is what catches it afterwards. An uneditable list would kill E15.
    - A **sentence** under it saying what it filtered by. A list that silently
      omits what somebody came for is worse than a long one: they conclude the
      material is missing from the library and go and add a second copy of it.
    - **Show all**, which turns the filter off. A didactic tool exists for
      experiments, and one that decided which experiments are legal would be
      teaching the wrong thing. The sentence changes with it, so the state is
      never ambiguous.

    The value already in the recipe is always offered, filter or no filter
    (`filtered_choices(keep=...)`). A step that ran on a material this filter now
    rejects — because somebody edited its rate to zero, or typed it — must still
    show that value, or "adjust" would silently substitute a different material.
    That is the `adjust` bug arriving from the other side.
    """

    def __init__(
        self,
        spec: ParamSpec,
        library: MaterialLibrary | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._spec = spec
        self._library = library if library is not None else didactic_library()
        self.box = QComboBox()
        self.box.setEditable(True)
        self.box.setInsertPolicy(QComboBox.NoInsert)
        self.show_all = QCheckBox("show all")
        self.show_all.setToolTip(
            "Offer every material in the library, including the ones this step has "
            "no data for. Typing a name the library does not know is always allowed."
        )
        self.reason = QLabel("")
        self.reason.setWordWrap(True)
        self.reason.setStyleSheet("color: #8b95a1;")
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.box, 1)
        row.addWidget(self.show_all)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        layout.addLayout(row)
        layout.addWidget(self.reason)
        self.show_all.toggled.connect(lambda _on: self._repopulate())
        self._repopulate()
        if spec.default:
            self.setValue(str(spec.default))

    def setLibrary(self, library: MaterialLibrary) -> None:
        """Point the list at another library — E15 wrote one, so the list moved."""
        self._library = library
        self._repopulate()

    def _repopulate(self) -> None:
        current = self.value()
        filter_ = None if self.show_all.isChecked() else self._spec.material
        ids, why = filtered_choices(filter_, self._library, keep=(current,))
        self.box.blockSignals(True)
        self.box.clear()
        self.box.addItems([str(key) for key in ids])
        self.box.setCurrentText(current)
        self.box.blockSignals(False)
        if self.show_all.isChecked():
            why = f"showing all {len(ids)} materials — the filter is off"
        self.reason.setText(why + ". Any name may be typed.")

    def value(self) -> str:
        return self.box.currentText().strip()

    def setValue(self, value: str) -> None:
        text = str(value)
        if text and self.box.findText(text) < 0:
            # The recipe's own value outranks the filter — see the class docstring.
            self.box.addItem(text)
        self.box.setCurrentText(text)


def _widget_for(spec: ParamSpec) -> QWidget:
    """One widget per `ParamSpec`, with the schema's own range and unit on it.

    The range is set from the spec rather than from a generous default, so a
    parameter the solver would reject cannot be typed in the first place — and
    where it still can (a free-text string), `validate_params` is the one that
    says no.
    """
    if spec.choices is not None:
        combo = QComboBox()
        combo.addItems([str(choice) for choice in spec.choices])
        if spec.default is not None:
            combo.setCurrentText(str(spec.default))
        return combo
    if spec.kind is bool:
        box = QCheckBox()
        box.setChecked(bool(spec.default))
        return box
    if spec.kind is int:
        spin = QSpinBox()
        spin.setRange(
            int(spec.minimum) if spec.minimum is not None else -1_000_000,
            int(spec.maximum) if spec.maximum is not None else 1_000_000,
        )
        if spec.unit:
            spin.setSuffix(f" {spec.unit}")
        if spec.default is not None:
            spin.setValue(int(spec.default))
        return spin
    if spec.kind is float:
        spin = QDoubleSpinBox()
        spin.setDecimals(3)
        spin.setRange(
            float(spec.minimum) if spec.minimum is not None else -1_000_000.0,
            float(spec.maximum) if spec.maximum is not None else 1_000_000.0,
        )
        spin.setSingleStep(1.0)
        if spec.unit:
            spin.setSuffix(f" {spec.unit}")
        if spec.default is not None:
            spin.setValue(float(spec.default))
        return spin
    line = QLineEdit()
    line.setText("" if spec.default is None else str(spec.default))
    return line


class RevisionListPanel(QWidget):
    """The chain, one row per revision — plan §3.6's append-only history.

    Reads `RevisionChain`'s **summaries**, never its revisions: a row is bytes,
    so scrubbing a 60-step chain does not fault 6 MB per row back off disk.

    Since M8 the three things E12 allows are reachable from a row: **repeat** the
    step that made it, **adjust** it, or **remove** it. All three are truncation
    or appending, never branching — `ui/window.py`'s first paragraph has said "a
    snapshot is a record, not a branch" since M4 and E12 keeps it. What that
    costs is stated where it is spent: adjusting throws away everything after the
    revision being adjusted, and the confirmation says how many.

    Signals:
        revision_chosen: `(index)` when the selection changes.
        repeat_requested / adjust_requested / remove_requested: `(index)`.
    """

    revision_chosen = Signal(int)
    repeat_requested = Signal(int)
    adjust_requested = Signal(int)
    remove_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._on_row)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._on_context_menu)
        self.list.installEventFilter(self)
        heading = QLabel("Revisions")
        heading.setFont(_bold(heading.font()))
        hint = QLabel("Right-click a revision, or press Del to remove it.")
        hint.setStyleSheet("color: #8a949e;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(heading)
        layout.addWidget(self.list, 1)
        layout.addWidget(hint)

    # -- E12: repeat, adjust, remove -----------------------------------------

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        """Del removes the selected revision — the shortcut E12 asks for."""
        if (
            watched is self.list
            and event.type() == QEvent.KeyPress
            and event.key() in (Qt.Key_Delete, Qt.Key_Backspace)
        ):
            index = self.selected_index()
            if index is not None:
                self.remove_requested.emit(index)
                return True
        return super().eventFilter(watched, event)

    def _on_context_menu(self, point) -> None:
        index = self.selected_index()
        item = self.list.itemAt(point)
        if item is not None:
            index = self.list.row(item)
        if index is None or index < 0:
            return
        menu = QMenu(self)
        repeat = menu.addAction("Repeat this step")
        repeat.setToolTip("Run it again at the head of the chain — appends, changes nothing")
        adjust = menu.addAction("Adjust this step…")
        adjust.setToolTip("Truncate back to before it and load its parameters into the form")
        menu.addSeparator()
        remove = menu.addAction("Remove this revision and everything after it")
        chosen = menu.exec(self.list.viewport().mapToGlobal(point))
        if chosen is repeat:
            self.repeat_requested.emit(index)
        elif chosen is adjust:
            self.adjust_requested.emit(index)
        elif chosen is remove:
            self.remove_requested.emit(index)

    def refresh(self, chain: RevisionChain, *, select_last: bool = True) -> None:
        blocked = self.list.blockSignals(True)
        self.list.clear()
        for entry in chain:
            mark = "!" if not entry.ok else ("~" if entry.warnings else " ")
            item = QListWidgetItem(f"{mark} #{entry.index}  {entry.display_name}")
            item.setToolTip(
                "\n".join(entry.failures + entry.warnings)
                or f"materials: {', '.join(entry.materials)}"
            )
            if not entry.ok:
                item.setForeground(QColor("#ff6b6b"))
            elif entry.warnings:
                item.setForeground(QColor("#ffd166"))
            self.list.addItem(item)
        self.list.blockSignals(blocked)
        if select_last and len(chain):
            self.list.setCurrentRow(len(chain) - 1)

    def selected_index(self) -> int | None:
        row = self.list.currentRow()
        return None if row < 0 else row

    def _on_row(self, row: int) -> None:
        if row >= 0:
            self.revision_chosen.emit(row)


class RunLogPanel(QWidget):
    """The run log: what each step did and what the commit gate said about it.

    Plan §4.5: "a suspicious step is visible, never silent". The gate's report is
    stored on the revision and appended here verbatim, warnings included — the
    balance check, the reinitialisation displacement, the lineage findings and
    the capabilities gained or lost.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(4000)
        self.view.setFont(_monospace(self.view.font()))
        heading = QLabel("Run log")
        heading.setFont(_bold(heading.font()))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(heading)
        row.addStretch(1)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.view.clear)
        row.addWidget(clear)
        layout.addLayout(row)
        layout.addWidget(self.view, 1)

    def append(self, lines: Iterable[str]) -> None:
        for line in lines:
            self.view.appendPlainText(line)
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())


def _bold(font: QFont) -> QFont:
    bold = QFont(font)
    bold.setBold(True)
    return bold


def _monospace(font: QFont) -> QFont:
    mono = QFont(font)
    mono.setStyleHint(QFont.Monospace)
    mono.setFamily("monospace")
    mono.setPointSizeF(max(8.0, font.pointSizeF() - 1.0))
    return mono


def _preset_box(options: Sequence[presets.PresetOption]) -> QComboBox:
    """A grouped preset dropdown: sections as disabled headings, keys as data.

    E3's "zweigeteilt und sortiert", rendered. The order is not decided here —
    `presets.options_for` hands them over already sorted, so the dropdown, a
    recipe file and a test cannot disagree about which entry is first.
    """
    box = QComboBox()
    box.addItem("(none — use the fields below)", "")
    for section, entries in presets.grouped(options).items():
        if section:
            box.insertSeparator(box.count())
            box.addItem(section, None)
            item = box.model().item(box.count() - 1)
            item.setEnabled(False)
            item.setFont(_bold(box.font()))
        for option in entries:
            box.addItem(option.label, option.key)
    return box
