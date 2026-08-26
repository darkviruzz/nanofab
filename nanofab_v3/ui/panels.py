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

from PySide6.QtCore import Qt, Signal
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
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from nanofab_v3.processes.contract import ParamSpec
from nanofab_v3.processes.registry import ProcessRegistry
from nanofab_v3.runtime.revision import RevisionChain

_RUNNABLE = QColor("#5ac87a")
_BLOCKED = QColor("#8a949e")


class StepListPanel(QWidget):
    """Every registered process, grouped by technique, gated on capabilities.

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
        layout.addWidget(self.list, 1)
        layout.addWidget(self.reason)
        layout.addWidget(self.run_button)
        self.refresh(frozenset())

    def refresh(self, capabilities: Iterable[str]) -> None:
        """Re-gate every row against what the current revision promises."""
        self._capabilities = frozenset(capabilities)
        selected = self.selected_step_id()
        self.list.clear()
        for technique, steps in self._registry.by_technique().items():
            header = QListWidgetItem(technique)
            header.setFlags(Qt.NoItemFlags)
            header.setFont(_bold(header.font()))
            self.list.addItem(header)
            for step in steps:
                reason = self._registry.blocked_reason(step.step_id, self._capabilities)
                item = QListWidgetItem(f"   {step.display_name}  ·  {step.fidelity}")
                item.setData(Qt.UserRole, step.step_id)
                item.setForeground(_RUNNABLE if reason is None else _BLOCKED)
                # The tooltip is the whole difference from v1's gating: it names
                # the missing promise about the sample, not the step that has
                # not run yet.
                item.setToolTip(reason or f"{step.step_id}: ready")
                self.list.addItem(item)
                if step.step_id == selected:
                    self.list.setCurrentItem(item)
        self._on_selection(self.list.currentItem(), None)

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
    """A typed form generated from a step's `ParamSpec`s (plan §5.1)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._widgets: dict[str, QWidget] = {}
        self._specs: tuple[ParamSpec, ...] = ()
        self.title = QLabel("No step selected")
        self.title.setFont(_bold(self.title.font()))
        self.form = QFormLayout()
        self.form.setLabelAlignment(Qt.AlignRight)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.title)
        layout.addLayout(self.form)
        layout.addStretch(1)

    def set_step(self, step_id: str, display_name: str, specs: Sequence[ParamSpec]) -> None:
        """Rebuild the form for one step."""
        self._clear()
        self._specs = tuple(specs)
        self.title.setText(f"{display_name}   ({step_id})")
        for spec in self._specs:
            widget = _widget_for(spec)
            self._widgets[spec.name] = widget
            label = spec.name if not spec.unit else f"{spec.name} [{spec.unit}]"
            widget.setToolTip(spec.description)
            self.form.addRow(QLabel(label), widget)

    def values(self) -> dict[str, Any]:
        """What the form currently says, ready for `validate_params`.

        Not validated here on purpose: the engine validates, once, at the
        boundary it owns (`contract.validate_params`). A second validator in the
        UI is a second definition of what a legal recipe is.
        """
        collected: dict[str, Any] = {}
        for spec in self._specs:
            widget = self._widgets[spec.name]
            if isinstance(widget, QComboBox):
                collected[spec.name] = widget.currentText()
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
            if isinstance(widget, QComboBox):
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

    def _clear(self) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        self._widgets.clear()
        self._specs = ()


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

    Signals:
        revision_chosen: `(index)` when the selection changes.
    """

    revision_chosen = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._on_row)
        heading = QLabel("Revisions")
        heading.setFont(_bold(heading.font()))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(heading)
        layout.addWidget(self.list, 1)

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
