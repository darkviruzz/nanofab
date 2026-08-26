"""The dialog an unknown material raises, and the form behind it (roadmap E15).

The second half of `materials.unknown`. That module decides *what* is missing and
what would have to be answered; this one asks. The split is ADR-0001's rule
applied to a dialog: `MaterialDescription` below holds and validates the answers
and imports no Qt, `MaterialDialog` renders it and decides nothing.

Only two things are asked for by default — a name and a rate per process class —
because the point is not to author a full library entry through a form. It is to
turn "this behaves like a perfect mask and nobody said so" into "this etches at
0.4 nm/s in a fluorine ICP, and here is the file that says so". Everything else a
`MaterialType` can carry has a default, and the file it writes is an ordinary one
that can be opened and finished by hand — which is the answer to every field this
form does not have.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from nanofab_v3.materials.material import MaterialType
from nanofab_v3.materials.unknown import MissingMaterial


@dataclass
class MaterialDescription:
    """The answers, before they become a `MaterialType` — Qt-free and testable.

    A mutable holder rather than a frozen value because a form fills it field by
    field. `build()` is where it stops being answers and becomes a library entry,
    and the `MaterialType` constructor is what validates it — the same validator
    `schema.from_dict` leans on, so a rate typed into this dialog and a rate typed
    into the file are refused for the same reasons.
    """

    missing: MissingMaterial
    name: str = ""
    display_color: str = "#808080"
    rates: dict[str, float] = field(default_factory=dict)

    def build(self) -> MaterialType:
        """The `MaterialType` these answers describe; raises if they do not add up.

        Zero rates are dropped rather than stored. "No entry" already means "does
        not move" (`MaterialType.rate_for`), so writing `0.0` for every class an
        operator left blank would put thirteen deliberate-looking statements in a
        file where the operator made none.
        """
        return self.missing.draft(
            name=self.name.strip() or None,
            display_color=self.display_color,
            rates={key: value for key, value in self.rates.items() if value > 0.0},
        )


class MaterialDialog(QDialog):
    """Ask for the missing material's name, colour and rates, once per material."""

    def __init__(self, missing: MissingMaterial, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Unknown material: {missing.material_id}")
        self.description = MaterialDescription(missing=missing)

        explanation = QLabel(missing.question())
        explanation.setWordWrap(True)

        self._name = QLineEdit(str(missing.material_id).replace("_", " ").capitalize())
        self._color = QPushButton(self.description.display_color)
        self._color.clicked.connect(self._pick_color)

        form = QFormLayout()
        form.addRow("Name", self._name)
        form.addRow("Colour", self._color)
        self._rates: dict[str, QDoubleSpinBox] = {}
        for process_class in missing.process_classes:
            box = QDoubleSpinBox()
            box.setDecimals(4)
            box.setRange(0.0, 10_000.0)
            box.setSuffix(" nm/s")
            # Left at zero on purpose: an unanswered class stays unanswered
            # rather than becoming a stated zero (see `MaterialDescription.build`).
            box.setValue(0.0)
            form.addRow(process_class, box)
            self._rates[process_class] = box

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(explanation)
        layout.addLayout(form)
        layout.addWidget(
            QLabel(
                "Saved to your own material directory as an ordinary JSON file — "
                "uncalibrated, and marked as such."
            )
        )
        layout.addWidget(buttons)

    def _pick_color(self) -> None:
        chosen = QColorDialog.getColor(parent=self)
        if chosen.isValid():
            self.description.display_color = chosen.name()
            self._color.setText(chosen.name())

    def values(self) -> MaterialDescription:
        """The answers as they stand — read after `exec()` returns `Accepted`."""
        self.description.name = self._name.text()
        self.description.rates = {
            process_class: box.value() for process_class, box in self._rates.items()
        }
        return self.description

    def described(self) -> MaterialType:
        """The `MaterialType` the operator described."""
        return self.values().build()


def ask_about(missing: Sequence[MissingMaterial], parent: QWidget | None = None):
    """Run one dialog per unknown material; yield the ones that were described.

    A generator so the caller decides what to do with each answer — the session
    saves it and rebinds its library — and so cancelling one material does not
    abandon the rest.
    """
    for entry in tuple(missing):
        dialog = MaterialDialog(entry, parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            yield dialog.described()
