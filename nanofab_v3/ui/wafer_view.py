"""The wafer view: a position fan you can click (plan §8, §14).

The Qt half of `ui.wafer`, and deliberately thin. Everything that decides
anything — which positions there are, what state each is in, what two of them
differ by — is in the Qt-free module; this paints a circle per position and
emits which one was clicked. That is ADR-0001's rule one level up from the
canvas: the wafer map is a *view* of a model that runs without it.

Three behaviours it exists for, all from handoff §5:

- **Partial results are shown, never waited for.** The fan reports `pending`,
  `running`, `done` and `failed` as four values of one field, so the map paints
  the same way a second after the run started as it does when it finished, and
  clicking a half-materialized position shows the revisions it already has.
- **A scene is built per selection, not per paint** (handoff §4, trap 4). A
  `SceneSnapshot` is 107 ms; nine positions repainted per frame would be a
  second a frame. Selecting a position emits its index; the window builds one
  scene from it, exactly as it does for the interactive session.
- **The fan and the session share one cache directory.** A warm replay is 68×,
  and two directories would mean paying for the same position twice.

The refresh timer polls `WaferFan.snapshot()` rather than taking a signal from
the worker thread — see `ui.wafer` for why the boundary goes there.
"""

from __future__ import annotations

import math
from typing import Mapping

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from nanofab_v3.runtime.run import Position
from nanofab_v3.ui.wafer import DONE, FAILED, PENDING, RUNNING, PositionStatus, WaferFan

STATE_COLORS = {
    PENDING: "#3a4048",
    RUNNING: "#d0a020",
    DONE: "#4c9a5a",
    FAILED: "#b4463c",
}
"""One colour per state — the whole legend, and the only thing the map encodes."""

WAFER_EDGE = "#5a626c"
DOT_RADIUS = 9.0
"""Radius of a position marker in pixels. Fixed, so a fan at 5 mm is readable."""


class WaferMapWidget(QWidget):
    """The wafer disc with a marker per position.

    Signals:
        position_chosen: The position the user clicked, in mm.
    """

    position_chosen = Signal(tuple)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._statuses: dict[Position, PositionStatus] = {}
        self._selected: Position | None = None
        self._radius_mm = 75.0
        self.setMinimumSize(220, 220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)

    def set_statuses(self, statuses: Mapping[Position, PositionStatus]) -> None:
        """Replace what is drawn. Cheap: no geometry, no scene, just a repaint."""
        self._statuses = dict(statuses)
        furthest = max((status.radius for status in self._statuses.values()), default=0.0)
        self._radius_mm = max(furthest * 1.25, 25.0)
        self.update()

    @property
    def selected(self) -> Position | None:
        return self._selected

    def select(self, position: Position | None) -> None:
        self._selected = position
        self.update()

    # -- painting ------------------------------------------------------------

    def _centre_and_scale(self) -> tuple[QPointF, float]:
        side = min(self.width(), self.height()) - 2 * DOT_RADIUS - 8
        return QPointF(self.width() / 2.0, self.height() / 2.0), (side / 2.0) / self._radius_mm

    def _to_pixels(self, position: Position) -> QPointF:
        centre, scale = self._centre_and_scale()
        # Wafer y points up, screen y points down.
        return QPointF(
            centre.x() + position[0] * scale, centre.y() - position[1] * scale
        )

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt's name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        centre, scale = self._centre_and_scale()
        disc = self._radius_mm * scale

        painter.setPen(QPen(QColor(WAFER_EDGE), 1.5))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(centre, disc, disc)
        painter.drawLine(QPointF(centre.x() - disc, centre.y()),
                         QPointF(centre.x() + disc, centre.y()))
        painter.drawLine(QPointF(centre.x(), centre.y() - disc),
                         QPointF(centre.x(), centre.y() + disc))

        for position, status in self._statuses.items():
            point = self._to_pixels(position)
            colour = QColor(STATE_COLORS.get(status.state, STATE_COLORS[PENDING]))
            painter.setBrush(QBrush(colour))
            painter.setPen(QPen(QColor("#0d0f12"), 1.0))
            painter.drawEllipse(point, DOT_RADIUS, DOT_RADIUS)
            if status.state == RUNNING and status.fraction > 0.0:
                # A wedge of the marker, so "how far" needs no second widget.
                painter.setBrush(QBrush(QColor(STATE_COLORS[DONE])))
                painter.setPen(Qt.NoPen)
                box = QRectF(
                    point.x() - DOT_RADIUS, point.y() - DOT_RADIUS,
                    2 * DOT_RADIUS, 2 * DOT_RADIUS,
                )
                painter.drawPie(box, 90 * 16, -int(360 * 16 * status.fraction))
            if position == self._selected:
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor("#e8e8e8"), 2.0))
                painter.drawEllipse(point, DOT_RADIUS + 4, DOT_RADIUS + 4)
        painter.end()

    # -- interaction ---------------------------------------------------------

    def _nearest(self, x: float, y: float) -> Position | None:
        best, distance = None, DOT_RADIUS + 6
        for position in self._statuses:
            point = self._to_pixels(position)
            reach = math.hypot(point.x() - x, point.y() - y)
            if reach <= distance:
                best, distance = position, reach
        return best

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt's name
        point = event.position()
        found = self._nearest(point.x(), point.y())
        if found is not None:
            self.select(found)
            self.position_chosen.emit(found)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt's name
        point = event.position()
        found = self._nearest(point.x(), point.y())
        self.setToolTip(self._statuses[found].describe() if found is not None else "")


class WaferPanel(QWidget):
    """The map, its legend and its controls — plan §14's position fan.

    Signals:
        position_chosen: A position was clicked; the window builds one scene
            from its chain. Emitted on selection, never on a repaint.
    """

    position_chosen = Signal(tuple)

    REFRESH_MS = 200
    """How often the map polls the fan. Slow on purpose: a position takes
    seconds, so a faster poll would repaint the same picture for nothing."""

    def __init__(self, fan: WaferFan | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.fan = fan
        self.map = WaferMapWidget()
        self.map.position_chosen.connect(self._on_position)

        self.summary = QLabel("no wafer run")
        self.summary.setWordWrap(True)
        self.start_button = QPushButton("Materialize")
        self.start_button.clicked.connect(self.start)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel)

        controls = QHBoxLayout()
        controls.addWidget(self.start_button)
        controls.addWidget(self.cancel_button)
        controls.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Wafer positions"))
        layout.addWidget(self.map, 1)
        layout.addWidget(self._legend())
        layout.addWidget(self.summary)
        layout.addLayout(controls)

        self._timer = QTimer(self)
        self._timer.setInterval(self.REFRESH_MS)
        self._timer.timeout.connect(self.refresh)
        self.refresh()

    def _legend(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        for state in (PENDING, RUNNING, DONE, FAILED):
            swatch = QLabel(f"● {state}")
            swatch.setStyleSheet(f"color: {STATE_COLORS[state]};")
            layout.addWidget(swatch)
        layout.addStretch(1)
        return row

    def set_fan(self, fan: WaferFan | None) -> None:
        """Point the panel at a fan (or at none), and show it immediately."""
        self.fan = fan
        self.map.select(None)
        self.refresh()

    def start(self) -> None:
        """Materialize the pending positions in the background."""
        if self.fan is None:
            return
        self.fan.start()
        self._timer.start()
        self.refresh()

    def cancel(self) -> None:
        if self.fan is not None:
            self.fan.cancel()

    def refresh(self) -> None:
        """Poll the fan and repaint. Called by the timer and after a click."""
        if self.fan is None:
            self.map.set_statuses({})
            self.summary.setText("no wafer run")
            self.start_button.setEnabled(False)
            self.cancel_button.setEnabled(False)
            return

        statuses = self.fan.snapshot()
        self.map.set_statuses(statuses)
        counts = {state: 0 for state in STATE_COLORS}
        for status in statuses.values():
            counts[status.state] = counts.get(status.state, 0) + 1
        running = self.fan.is_running
        self.summary.setText(
            f"{counts[DONE]} of {len(statuses)} materialized"
            + (f", {counts[FAILED]} failed" if counts[FAILED] else "")
            + (" — running" if running else "")
        )
        self.start_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        if not running:
            self._timer.stop()

    def _on_position(self, position: Position) -> None:
        self.position_chosen.emit(position)
        self.refresh()
