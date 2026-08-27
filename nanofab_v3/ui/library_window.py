"""The library window: what is loaded, where it came from, and how to change it (E37).

One window with two tabs, because materials and demos raise the same question —
*what is loaded and from where* — and answering it in two places would mean two
answers the first time a root moved.

## Why this is a reference work before it is an editor

The library is eleven JSON files with a rate table in them, and until now the only
way to see what a build had actually loaded was `--version` in a terminal. That is
the wrong place: the person who wants to know whether their chromium is the
delivered chromium is looking at a cross-section, not at a shell. So the left half
is a list, the right half is **every** field including `rate_notes` — which is
where "assumed, not measured" lives — and the bottom names the file it came from
and lists the ones that did not parse, with the reason each gave.

The failures matter as much as the successes. A material that failed to load is
invisible everywhere else by design (`load_library` is lenient so one stray comma
cannot empty the library), which means this window is the only place it is
visible at all.

## And the editor half, with the two rules E37 attaches to it

- **Canonical and atomic**, through `materials.schema.write_material`: an edit to
  one rate must not reformat the eleven fields nobody touched, and a half-written
  file must not be readable. A test pins the encoding byte for byte.
- **The provenance is carried forward, never dropped.** Editing a rate turns
  "student process table, row 1" into a claim that is no longer true, so
  `materials.editing.carry_provenance` rewrites the note to say what the number
  was and what its note said. Only for the rates that actually changed.

"Reset" reads `data/materials/.original/`, the one extra copy the build leaves —
unmodified, never loaded, and read only when somebody asks for the delivered
number back.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from nanofab_v3.materials import MaterialType, application_library, invalidate_cache
from nanofab_v3.materials.material import MATERIAL_TAGS, PROCESS_CLASSES
from nanofab_v3.materials import editing
from nanofab_v3.ui import demos as demo_module


def _mono(font: QFont) -> QFont:
    mono = QFont(font)
    mono.setStyleHint(QFont.Monospace)
    mono.setFamily("monospace")
    return mono


class MaterialTab(QWidget):
    """The materials half: a list, every field of one entry, and the failures."""

    library_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._entries: dict[str, MaterialType] = {}
        self._files: dict[str, Path] = {}
        self._rates: dict[str, QDoubleSpinBox] = {}
        self._notes: dict[str, QLineEdit] = {}
        self._current = ""

        self.list = QListWidget()
        self.list.currentItemChanged.connect(lambda *_: self._show_selected())

        self.title = QLabel("")
        title_font = QFont(self.title.font())
        title_font.setBold(True)
        self.title.setFont(title_font)
        self.name = QLineEdit()
        self.color = QLineEdit()
        self.tags = QLineEdit()
        self.tags.setToolTip("Substance classes (E21), comma separated: " + ", ".join(MATERIAL_TAGS))
        self.notes = QPlainTextEdit()
        self.notes.setMaximumHeight(80)

        self.source = QLabel("")
        self.source.setWordWrap(True)
        self.source.setFont(_mono(self.source.font()))
        self.failures = QLabel("")
        self.failures.setWordWrap(True)
        self.failures.setStyleSheet("color: #ff6b6b;")

        self.save_button = QPushButton("Save")
        self.save_button.setToolTip(
            "Write this material back to its file — canonical encoding, atomic "
            "replace, and the note of every rate you changed is rewritten to say "
            "what it was (E37)"
        )
        self.save_button.clicked.connect(self._save)
        self.reset_button = QPushButton("Reset to delivered")
        self.reset_button.setToolTip(
            "Copy the file back from data/materials/.original/, the unmodified "
            "copy the build left behind"
        )
        self.reset_button.clicked.connect(self._reset)
        self.reload_button = QPushButton("Reload from disk")
        self.reload_button.clicked.connect(self.reload)

        self.setLayout(self._build())
        self.reload()

    # -- layout ---------------------------------------------------------------

    def _build(self) -> QVBoxLayout:
        form = QFormLayout()
        form.addRow(QLabel("name"), self.name)
        form.addRow(QLabel("display colour"), self.color)
        form.addRow(QLabel("tags"), self.tags)
        for process_class in PROCESS_CLASSES:
            spin = QDoubleSpinBox()
            spin.setDecimals(4)
            spin.setRange(0.0, 1_000_000.0)
            spin.setSuffix(" nm/s")
            note = QLineEdit()
            note.setPlaceholderText("where this number came from")
            row = QHBoxLayout()
            row.addWidget(spin, 1)
            row.addWidget(note, 2)
            holder = QWidget()
            holder.setLayout(row)
            self._rates[process_class] = spin
            self._notes[process_class] = note
            form.addRow(QLabel(process_class), holder)
        form.addRow(QLabel("notes"), self.notes)

        fields = QWidget()
        fields.setLayout(form)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(fields)

        buttons = QHBoxLayout()
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.reset_button)
        buttons.addWidget(self.reload_button)
        buttons.addStretch(1)

        right = QVBoxLayout()
        right.addWidget(self.title)
        right.addWidget(scroll, 1)
        right.addLayout(buttons)
        right.addWidget(self.source)
        right_panel = QWidget()
        right_panel.setLayout(right)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.list)
        splitter.addWidget(right_panel)
        splitter.setSizes([220, 640])

        layout = QVBoxLayout()
        layout.addWidget(splitter, 1)
        layout.addWidget(self.failures)
        return layout

    # -- reading --------------------------------------------------------------

    def reload(self) -> None:
        """Read the library again — after an edit here, or one in a text editor."""
        invalidate_cache()
        library, report = application_library()
        self._entries = dict(library.entries)
        self._files = dict(report.loaded)
        wanted = self._current or (sorted(self._entries)[0] if self._entries else "")

        self.list.blockSignals(True)
        self.list.clear()
        for material in sorted(self._entries):
            item = QListWidgetItem(f"{material} — {self._entries[material].name}")
            item.setData(Qt.UserRole, material)
            self.list.addItem(item)
        self.list.blockSignals(False)

        self.failures.setText(
            ""
            if not report.failures
            else "did not load:  "
            + "   ".join(f"{path.name} ({reason})" for path, reason in report.failures)
        )
        self._select(wanted)

    def _select(self, material: str) -> None:
        for row in range(self.list.count()):
            if self.list.item(row).data(Qt.UserRole) == material:
                self.list.setCurrentRow(row)
                return
        if self.list.count():
            self.list.setCurrentRow(0)

    def _show_selected(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        material = str(item.data(Qt.UserRole))
        entry = self._entries.get(material)
        if entry is None:
            return
        self._current = material
        self.title.setText(f"{entry.name}   ({material})")
        self.name.setText(entry.name)
        self.color.setText(entry.display_color)
        self.tags.setText(", ".join(entry.tags))
        self.notes.setPlainText(entry.notes)
        for process_class in PROCESS_CLASSES:
            self._rates[process_class].setValue(entry.rate_for(process_class))
            self._notes[process_class].setText(entry.rate_note(process_class))
        path = self._files.get(material)
        self.source.setText(f"from {path}" if path else "not on disk")
        self.reset_button.setEnabled(bool(editing.original_of(material)))

    # -- writing --------------------------------------------------------------

    def edited_entry(self) -> MaterialType | None:
        """What the form says, as a `MaterialType` — the constructor validates."""
        entry = self._entries.get(self._current)
        if entry is None:
            return None
        rates: dict[str, float] = {}
        notes: dict[str, str] = {}
        for process_class in PROCESS_CLASSES:
            value = float(self._rates[process_class].value())
            note = self._notes[process_class].text().strip()
            # A rate of zero is *absence*, not "does not move": the library's own
            # convention (handoff §3.3 — "absent beats invented"), so a zeroed
            # field drops out of the file rather than claiming a measurement.
            if value > 0.0:
                rates[process_class] = value
            if note:
                notes[process_class] = note
        tags = tuple(part.strip() for part in self.tags.text().split(",") if part.strip())
        return replace(
            entry,
            name=self.name.text().strip() or entry.name,
            display_color=self.color.text().strip() or entry.display_color,
            tags=tags,
            notes=self.notes.toPlainText(),
            rates=rates,
            rate_notes=notes,
        )

    def _save(self) -> None:
        try:
            entry = self.edited_entry()
        except (TypeError, ValueError) as error:
            QMessageBox.warning(self, "Not a valid material", str(error))
            return
        if entry is None:
            return
        previous = self._entries.get(self._current)
        try:
            path = editing.save_edit(entry, previous=previous)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Could not write", str(error))
            return
        self.reload()
        self.library_changed.emit()
        self.source.setText(f"saved to {path}")

    def _reset(self) -> None:
        material = self._current
        if not material:
            return
        answer = QMessageBox.question(
            self,
            "Reset to the delivered file?",
            f"Replace {material}.json with the copy this build was delivered with.\n\n"
            "What you changed is gone rather than kept beside it.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if editing.reset_material(material) is None:
            QMessageBox.information(
                self, "Nothing to reset to", "This build carries no delivered copy."
            )
            return
        self.reload()
        self.library_changed.emit()


class DemoTab(QWidget):
    """The demos half: the same question, and read-only.

    Read-only on purpose. A demo is a recipe, and this application already has a
    way to change one — open it, adjust the step, save it. A second editor for
    the same thing would be a second definition of what a recipe is, which is the
    drift this repository keeps refusing. What this tab is *for* is the other
    half of E37's question: which demo files loaded, from where, and which of
    them did not parse.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.list = QListWidget()
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setFont(_mono(self.detail.font()))
        self.source = QLabel("")
        self.source.setWordWrap(True)
        self.source.setFont(_mono(self.source.font()))
        self.failures = QLabel("")
        self.failures.setWordWrap(True)
        self.failures.setStyleSheet("color: #ff6b6b;")
        self.reload_button = QPushButton("Reload from disk")
        self.reload_button.clicked.connect(self.reload)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.list)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(self.detail, 1)
        right_layout.addWidget(self.source)
        splitter.addWidget(right)
        splitter.setSizes([220, 640])

        layout = QVBoxLayout(self)
        layout.addWidget(splitter, 1)
        layout.addWidget(self.failures)
        layout.addWidget(self.reload_button)

        self.list.currentItemChanged.connect(lambda *_: self._show_selected())
        self._demos: dict[str, Any] = {}
        self._files: dict[str, Path] = {}
        self.reload()

    def reload(self) -> None:
        demo_module.invalidate_cache()
        entries, report = demo_module.load_demos()
        self._demos = {entry.key: entry for entry in entries}
        self._files = dict(report.loaded)
        self.list.blockSignals(True)
        self.list.clear()
        for entry in entries:
            item = QListWidgetItem(entry.title)
            item.setData(Qt.UserRole, entry.key)
            self.list.addItem(item)
        self.list.blockSignals(False)
        self.failures.setText(
            ""
            if not report.failures
            else "did not load:  "
            + "   ".join(f"{path.name} ({reason})" for path, reason in report.failures)
        )
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self.detail.setPlainText(
                "No demos loaded.\n\nA delivered build reads them from data/demos/ "
                "beside the executable; an empty menu means that folder is missing "
                "(roadmap E19 — the library stops the program, the demos do not)."
            )

    def _show_selected(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        entry = self._demos.get(str(item.data(Qt.UserRole)))
        if entry is None:
            return
        lines = [entry.title, entry.summary, "", entry.watch_for, ""]
        for index, step in enumerate(entry.steps):
            lines.append(f"{index + 1:2d}. {step.step_id}")
            for name, value in sorted(step.params.items()):
                lines.append(f"      {name} = {value}")
            note = entry.note(index)
            if note:
                lines.append(f"      # {note}")
        self.detail.setPlainText("\n".join(lines))
        path = self._files.get(entry.key)
        self.source.setText(f"from {path}" if path else "not on disk")


class LibraryWindow(QWidget):
    """The two tabs, in one window (roadmap E37)."""

    library_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Library and demos")
        self.resize(900, 620)
        self.materials = MaterialTab()
        self.demos = DemoTab()
        self.tabs = QTabWidget()
        self.tabs.addTab(self.materials, "Materials")
        self.tabs.addTab(self.demos, "Demos")
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        self.materials.library_changed.connect(self.library_changed)


__all__ = ["DemoTab", "LibraryWindow", "MaterialTab"]
