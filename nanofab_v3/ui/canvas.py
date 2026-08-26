"""The cross-section canvas, rewritten against `SceneSnapshot` v2 (plan §10, ADR-0001).

v1's canvas *was* the geometry: `material_paths: dict[material_id, QPainterPath]`
was the working truth, every process took and returned paths, and there was no
way back to the analytic model (ADR-0001 F1–F4). This one is the opposite by
construction — it receives a `SceneSnapshot`, which is numpy and nm, and its only
job is an affine map from nm to pixels plus a fill rule.

**No `QPainterPath` in this file decides anything.** Paths are built from
polylines the kernel produced, painted, and thrown away; nothing reads a path
back, intersects two of them, or asks one where a surface is. The one direction
data flows is snapshot → pixels, which is what plan §4 means by "rendering is a
consumer".

Two paths to a picture, both from the same snapshot:

- **Outlines** — filled polygons from `marching_squares` over each `phi_m`.
  Sub-cell smooth, and the default.
- **Index map** — a `QImage` straight off `structure.material_index`, one pixel
  per cell. The fast fallback and the debug view plan §10 asks for; it is also
  the honest picture of what the model actually stores, which is why the toggle
  is in the UI rather than hidden.

The one rendering convention: **the first grid axis is drawn upwards, the second
to the right.** Same convention as the commit gate's headroom guard ("the max
face of the first axis"), so "up" means the same thing in a picture and in an
invariant.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QImage,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from nanofab_v3.ui.scene import EMPTY_COLOR, SceneSnapshot

_MARGIN = 12
"""Pixels of breathing room around the domain."""


class CrossSectionCanvas(QWidget):
    """Paints one `SceneSnapshot`; owns no geometry of its own.

    Signals:
        hovered: `(text)` — what is under the cursor, for a status bar.
    """

    hovered = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene: SceneSnapshot | None = None
        self._index_image: QImage | None = None
        self._show_index_map = False
        self._show_outlines = True
        self.setMinimumSize(320, 240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.setObjectName("CrossSectionCanvas")

    # -- what to paint -------------------------------------------------------

    def set_scene(self, scene: SceneSnapshot | None) -> None:
        """Show a snapshot. The widget keeps no other state about the sample."""
        self._scene = scene
        self._index_image = None if scene is None else _index_image(scene)
        self.update()

    @property
    def scene(self) -> SceneSnapshot | None:
        return self._scene

    def set_index_map_visible(self, visible: bool) -> None:
        """Switch to the raster view of `material_index` (plan §10's fast path)."""
        self._show_index_map = bool(visible)
        self.update()

    def set_outlines_visible(self, visible: bool) -> None:
        self._show_outlines = bool(visible)
        self.update()

    # -- the nm <-> pixel map ------------------------------------------------

    def _viewport(self) -> tuple[float, float, float, float] | None:
        """`(scale, x0, y0, height)` mapping nm to pixels, or `None` with no scene.

        Isotropic on purpose: a cross-section with a stretched vertical axis is
        the picture that makes a 20 nm film look like a 200 nm one, and every
        aspect-ratio judgement an operator makes off the screen would be wrong.
        """
        if self._scene is None:
            return None
        up0, up1, right0, right1 = self._scene.extent
        span_up = max(up1 - up0, self._scene.grid.spacing)
        span_right = max(right1 - right0, self._scene.grid.spacing)
        usable_w = max(1, self.width() - 2 * _MARGIN)
        usable_h = max(1, self.height() - 2 * _MARGIN)
        scale = min(usable_w / span_right, usable_h / span_up)
        x0 = _MARGIN + 0.5 * (usable_w - span_right * scale)
        y0 = _MARGIN + 0.5 * (usable_h - span_up * scale)
        return scale, x0, y0, span_up * scale

    def _to_pixels(self, points: np.ndarray) -> np.ndarray:
        """`(N, 2)` nm in grid-axis order to `(N, 2)` pixels in screen order."""
        view = self._viewport()
        assert view is not None and self._scene is not None
        scale, x0, y0, height = view
        up0, _, right0, _ = self._scene.extent
        screen_x = x0 + (points[:, 1] - right0) * scale
        screen_y = y0 + height - (points[:, 0] - up0) * scale
        return np.stack([screen_x, screen_y], axis=1)

    def _to_nm(self, x: float, y: float) -> tuple[float, float] | None:
        """Screen pixels back to nm in grid-axis order — the hit test's input."""
        view = self._viewport()
        if view is None or self._scene is None:
            return None
        scale, x0, y0, height = view
        up0, _, right0, _ = self._scene.extent
        return (up0 + (y0 + height - y) / scale, right0 + (x - x0) / scale)

    # -- painting ------------------------------------------------------------

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(EMPTY_COLOR))
        scene = self._scene
        if scene is None or self._viewport() is None:
            painter.setPen(QColor("#8a949e"))
            painter.drawText(self.rect(), Qt.AlignCenter, "No revision selected")
            painter.end()
            return

        scale, x0, y0, height = self._viewport()  # type: ignore[misc]
        up0, up1, right0, right1 = scene.extent
        domain = QRectF(x0, y0, (right1 - right0) * scale, height)
        painter.fillRect(domain, QColor(EMPTY_COLOR).lighter(115))

        if self._show_index_map and self._index_image is not None:
            painter.drawPixmap(
                domain.toRect(),
                QPixmap.fromImage(
                    self._index_image.scaled(
                        domain.toRect().size(), Qt.IgnoreAspectRatio, Qt.FastTransformation
                    )
                ),
            )
        if self._show_outlines:
            for shape in scene.shapes:
                path = self._path(shape.outlines)
                if path is None:
                    continue
                color = QColor(shape.color)
                painter.setPen(QPen(color.darker(150), 1.2))
                painter.fillPath(path, color if not self._show_index_map else Qt.NoBrush)
                painter.drawPath(path)

        for overlay in scene.overlays:
            color = QColor(overlay.color)
            painter.setPen(QPen(color, 1.6, Qt.DashLine))
            path = self._path(overlay.outlines)
            if path is not None:
                painter.drawPath(path)
            if overlay.segments is not None and len(overlay.segments):
                painter.setPen(QPen(color, 1.2))
                flat = self._to_pixels(overlay.segments.reshape(-1, 2)).reshape(-1, 2, 2)
                for start, end in flat:
                    painter.drawLine(
                        QPointF(start[0], start[1]), QPointF(end[0], end[1])
                    )

        painter.setPen(QPen(QColor("#3d444c"), 1))
        painter.drawRect(domain)
        painter.setPen(QColor("#c8ced4"))
        painter.drawText(
            domain.adjusted(6, 4, -6, -4),
            Qt.AlignLeft | Qt.AlignTop,
            scene.caption,
        )
        painter.drawText(
            domain.adjusted(6, 4, -6, -4),
            Qt.AlignRight | Qt.AlignBottom,
            f"{right1 - right0:.0f} x {up1 - up0:.0f} nm at {scene.grid.spacing:g} nm/cell",
        )
        painter.end()

    def _path(self, outlines) -> QPainterPath | None:
        """Build a throwaway path from polylines the kernel produced.

        Nothing reads this back. It exists for exactly as long as one
        `fillPath` call, which is the whole difference from v1 (ADR-0001 F1).
        """
        if not outlines:
            return None
        path = QPainterPath()
        path.setFillRule(Qt.OddEvenFill)
        for line in outlines:
            if len(line) < 2:
                continue
            pixels = self._to_pixels(np.asarray(line, dtype=float))
            path.moveTo(QPointF(pixels[0, 0], pixels[0, 1]))
            for point in pixels[1:]:
                path.lineTo(QPointF(point[0], point[1]))
            path.closeSubpath()
        return path

    # -- interaction ---------------------------------------------------------

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        scene = self._scene
        if scene is None:
            return
        point = self._to_nm(event.position().x(), event.position().y())
        if point is None:
            return
        # The hit test is `SceneSnapshot`'s, not this widget's: it reads the
        # index map, which is an exclusive partition. Asking a QPainterPath
        # `contains()` would be v1's mistake in miniature — two overlapping
        # filled paths both claim the point, and the answer would depend on
        # paint order.
        material = scene.material_at(point)
        self.hovered.emit(
            f"{point[1]:.0f}, {point[0]:.0f} nm — "
            + (material if material is not None else "empty")
        )

    def resizeEvent(self, event: QResizeEvent) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self.update()


def _index_image(scene: SceneSnapshot) -> QImage | None:
    """`material_index` as an RGB image — plan §10's raster fast path.

    One pixel per cell, built once per snapshot rather than per frame. Row 0 of
    the array is the *bottom* of the picture, so the array is flipped here and
    the convention stays in one place.
    """
    if scene.index_map is None:
        return None
    index = np.asarray(scene.index_map)
    colors = [QColor(shape.color) for shape in scene.shapes]
    table = np.zeros((len(colors) + 1, 3), dtype=np.uint8)
    empty = QColor(EMPTY_COLOR)
    table[0] = (empty.red(), empty.green(), empty.blue())
    for i, color in enumerate(colors):
        table[i + 1] = (color.red(), color.green(), color.blue())
    rgb = table[np.clip(index + 1, 0, len(colors))]
    rgb = np.flipud(rgb)
    rows, cols, _ = rgb.shape
    buffer = np.ascontiguousarray(rgb)
    image = QImage(buffer.data, cols, rows, 3 * cols, QImage.Format_RGB888)
    return image.copy()  # detach from the numpy buffer before it goes out of scope
