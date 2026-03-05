from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True)
class Vec2:
    x: float
    y: float

    def offset(self, dx: float, dy: float) -> Vec2:
        return Vec2(self.x + dx, self.y + dy)


@dataclass
class MaterialDef:
    material_id: str
    label: str
    fill_hex: str
    stroke_hex: str
    ion_etch_rate_nm_min: float


@dataclass
class Region2D:
    region_id: str
    material_id: str
    points: list[Vec2]
    tags: set[str] = field(default_factory=set)
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScalarField2D:
    field_id: str
    unit: str
    description: str
    samples: dict[tuple[int, int], float] = field(default_factory=dict)


@dataclass
class InterfaceSegment:
    interface_id: str
    owner_region_id: str
    owner_material_id: str
    start: Vec2
    end: Vec2
    normal_outward: Vec2


@dataclass
class CrossSectionState:
    schema_version: str
    extent: tuple[float, float, float, float]
    materials: dict[str, MaterialDef]
    regions: list[Region2D]
    scalar_fields: dict[str, ScalarField2D] = field(default_factory=dict)
    operation_log: list[str] = field(default_factory=list)


def rect(x0: float, y0: float, x1: float, y1: float) -> list[Vec2]:
    return [Vec2(x0, y0), Vec2(x1, y0), Vec2(x1, y1), Vec2(x0, y1)]


def polygon_area(points: list[Vec2]) -> float:
    area = 0.0
    count = len(points)
    for idx in range(count):
        p = points[idx]
        q = points[(idx + 1) % count]
        area += p.x * q.y - q.x * p.y
    return 0.5 * area


def ensure_ccw(points: list[Vec2]) -> list[Vec2]:
    if len(points) < 3:
        return points
    if polygon_area(points) < 0:
        return list(reversed(points))
    return points


def point_in_polygon(point: Vec2, polygon: list[Vec2]) -> bool:
    if len(polygon) < 3:
        return False
    inside = False
    x = point.x
    y = point.y
    prev = polygon[-1]
    for curr in polygon:
        if (curr.y > y) != (prev.y > y):
            denom = (prev.y - curr.y)
            if abs(denom) > 1e-12:
                x_intersect = ((prev.x - curr.x) * (y - curr.y) / denom) + curr.x
                if x < x_intersect:
                    inside = not inside
        prev = curr
    return inside


def edge_midpoint(a: Vec2, b: Vec2) -> Vec2:
    return Vec2(0.5 * (a.x + b.x), 0.5 * (a.y + b.y))


def edge_normal_outward_ccw(a: Vec2, b: Vec2) -> Vec2:
    dx = b.x - a.x
    dy = b.y - a.y
    length = math.hypot(dx, dy)
    if length <= 1e-12:
        return Vec2(0.0, 0.0)
    return Vec2(dy / length, -dx / length)


def vertical_ray_first_hit(
    regions: list[Region2D],
    x: float,
    y_start: float,
    y_stop: float,
) -> tuple[float, str] | None:
    hits: list[tuple[float, str]] = []
    for region in regions:
        points = ensure_ccw(region.points)
        count = len(points)
        for idx in range(count):
            a = points[idx]
            b = points[(idx + 1) % count]
            if abs(a.x - b.x) <= 1e-10:
                continue
            if x < min(a.x, b.x) or x > max(a.x, b.x):
                continue
            t = (x - a.x) / (b.x - a.x)
            if t < 0.0 or t > 1.0:
                continue
            y = a.y + t * (b.y - a.y)
            if y_stop <= y <= y_start:
                hits.append((y, region.material_id))
    if not hits:
        return None
    hits.sort(key=lambda item: item[0], reverse=True)
    return hits[0]


def build_t_pillar(
    region_id: str,
    material_id: str,
    center_x: float,
    base_y: float,
    stem_width: float,
    stem_height: float,
    cap_width: float,
    cap_height: float,
) -> Region2D:
    stem_half = 0.5 * stem_width
    cap_half = 0.5 * cap_width
    y1 = base_y + stem_height
    y2 = y1 + cap_height
    points = [
        Vec2(center_x - stem_half, base_y),
        Vec2(center_x + stem_half, base_y),
        Vec2(center_x + stem_half, y1),
        Vec2(center_x + cap_half, y1),
        Vec2(center_x + cap_half, y2),
        Vec2(center_x - cap_half, y2),
        Vec2(center_x - cap_half, y1),
        Vec2(center_x - stem_half, y1),
    ]
    return Region2D(
        region_id=region_id,
        material_id=material_id,
        points=ensure_ccw(points),
        tags={"solid", "deposition_target", "grating"},
    )


def build_base_state() -> CrossSectionState:
    materials = {
        "substrate": MaterialDef(
            material_id="substrate",
            label="Substrate",
            fill_hex="#1f9bd1",
            stroke_hex="#1375a2",
            ion_etch_rate_nm_min=45.0,
        ),
        "grating": MaterialDef(
            material_id="grating",
            label="T-Grating",
            fill_hex="#f53b3b",
            stroke_hex="#a61717",
            ion_etch_rate_nm_min=20.0,
        ),
        "metal": MaterialDef(
            material_id="metal",
            label="Conformal Metal",
            fill_hex="#8b929b",
            stroke_hex="#5a6168",
            ion_etch_rate_nm_min=5.0,
        ),
    }

    # Stepped top boundary models slight overetch into the substrate in open windows.
    substrate_points = ensure_ccw(
        [
            Vec2(0.0, -5.0),
            Vec2(20.0, -5.0),
            Vec2(20.0, -0.20),
            Vec2(16.0, -0.20),
            Vec2(16.0, 0.0),
            Vec2(12.0, 0.0),
            Vec2(12.0, -0.20),
            Vec2(8.0, -0.20),
            Vec2(8.0, 0.0),
            Vec2(4.0, 0.0),
            Vec2(4.0, -0.20),
            Vec2(0.0, -0.20),
        ]
    )

    regions = [
        Region2D(
            region_id="substrate",
            material_id="substrate",
            points=substrate_points,
            tags={"solid", "deposition_target"},
        ),
        build_t_pillar(
            region_id="grating_1",
            material_id="grating",
            center_x=6.0,
            base_y=0.0,
            stem_width=1.2,
            stem_height=2.2,
            cap_width=3.6,
            cap_height=0.8,
        ),
        build_t_pillar(
            region_id="grating_2",
            material_id="grating",
            center_x=14.0,
            base_y=0.0,
            stem_width=1.2,
            stem_height=2.2,
            cap_width=3.6,
            cap_height=0.8,
        ),
    ]

    return CrossSectionState(
        schema_version="cross_section_state.v0.2-prototype",
        extent=(0.0, 20.0, -5.2, 3.4),
        materials=materials,
        regions=regions,
        scalar_fields={
            "exposure_dose": ScalarField2D(
                field_id="exposure_dose",
                unit="mJ/cm^2",
                description="Reserved field layer for future gradient-based lithography simulation.",
            )
        },
        operation_log=["init: substrate + two-period T grating + slight overetch profile"],
    )


def extract_exposed_interfaces(state: CrossSectionState) -> list[InterfaceSegment]:
    interfaces: list[InterfaceSegment] = []
    xmin, xmax, _, _ = state.extent
    epsilon = 1e-3
    for region in state.regions:
        if "deposition_target" not in region.tags:
            continue
        points = ensure_ccw(region.points)
        count = len(points)
        for idx in range(count):
            a = points[idx]
            b = points[(idx + 1) % count]
            normal = edge_normal_outward_ccw(a, b)
            if abs(normal.x) <= 1e-10 and abs(normal.y) <= 1e-10:
                continue
            mid = edge_midpoint(a, b)
            # Keep focus on process-facing topography, not cut-plane side boundaries/backside.
            if mid.y < -0.35:
                continue
            if abs(mid.x - xmin) < 1e-6 or abs(mid.x - xmax) < 1e-6:
                continue
            sample = mid.offset(normal.x * epsilon, normal.y * epsilon)
            is_exposed = True
            for other in state.regions:
                if other.region_id == region.region_id:
                    continue
                if "solid" not in other.tags:
                    continue
                if point_in_polygon(sample, ensure_ccw(other.points)):
                    is_exposed = False
                    break
            if not is_exposed:
                continue
            interfaces.append(
                InterfaceSegment(
                    interface_id=f"{region.region_id}:edge:{idx}",
                    owner_region_id=region.region_id,
                    owner_material_id=region.material_id,
                    start=a,
                    end=b,
                    normal_outward=normal,
                )
            )
    return interfaces


def build_conformal_metal_regions(
    base_state: CrossSectionState,
    thickness_um: float,
) -> list[Region2D]:
    metal_regions: list[Region2D] = []
    interfaces = extract_exposed_interfaces(base_state)
    for idx, interface in enumerate(interfaces):
        start = interface.start
        end = interface.end
        normal = interface.normal_outward
        p0 = start
        p1 = end
        p2 = end.offset(normal.x * thickness_um, normal.y * thickness_um)
        p3 = start.offset(normal.x * thickness_um, normal.y * thickness_um)
        points = ensure_ccw([p0, p1, p2, p3])
        metal_regions.append(
            Region2D(
                region_id=f"metal_seg_{idx:03d}",
                material_id="metal",
                points=points,
                tags={"solid", "metal", "deposited"},
                props={
                    "thickness_um": thickness_um,
                    "source_interface": interface.interface_id,
                    "movement": "orthonormal",
                },
            )
        )
    return metal_regions


def build_state_with_conformal(thickness_nm: int) -> CrossSectionState:
    base_state = build_base_state()
    thickness_um = float(thickness_nm) / 1000.0
    metal_regions = build_conformal_metal_regions(base_state, thickness_um)
    new_state = CrossSectionState(
        schema_version=base_state.schema_version,
        extent=base_state.extent,
        materials=base_state.materials,
        regions=[*base_state.regions, *metal_regions],
        scalar_fields=base_state.scalar_fields,
        operation_log=[
            *base_state.operation_log,
            f"deposit_conformal: thickness_nm={thickness_nm}, interfaces={len(metal_regions)}",
        ],
    )
    return new_state


class CrossSectionCanvas(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._state = build_state_with_conformal(70)
        self.setMinimumSize(840, 520)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_state(self, state: CrossSectionState) -> None:
        self._state = state
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        area = self.rect().adjusted(10, 10, -10, -10)
        painter.fillRect(area, QColor("#f8fafc"))
        painter.setPen(QPen(QColor("#d2d7df"), 1))
        painter.drawRoundedRect(area, 10, 10)

        xmin, xmax, ymin, ymax = self._state.extent
        plot = area.adjusted(16, 14, -16, -24)
        if plot.width() <= 0 or plot.height() <= 0:
            painter.end()
            return

        def map_point(v: Vec2) -> QPointF:
            nx = (v.x - xmin) / max(1e-9, (xmax - xmin))
            ny = (v.y - ymin) / max(1e-9, (ymax - ymin))
            px = plot.left() + nx * plot.width()
            py = plot.bottom() - ny * plot.height()
            return QPointF(px, py)

        material_order = {"substrate": 0, "grating": 1, "metal": 2}
        regions = sorted(self._state.regions, key=lambda r: material_order.get(r.material_id, 99))
        for region in regions:
            material = self._state.materials[region.material_id]
            qpoly = QPolygonF([map_point(point) for point in ensure_ccw(region.points)])
            fill = QColor(material.fill_hex)
            stroke = QColor(material.stroke_hex)
            if region.material_id == "metal":
                fill.setAlpha(190)
                stroke.setAlpha(220)
            painter.setBrush(fill)
            painter.setPen(QPen(stroke, 1.6))
            painter.drawPolygon(qpoly)

        # Small ray-cast preview to show structural compatibility for top-down beam checks.
        ray_xs = [6.0, 10.0, 14.0]
        for ray_x in ray_xs:
            hit = vertical_ray_first_hit(self._state.regions, ray_x, y_start=ymax, y_stop=ymin)
            x0 = map_point(Vec2(ray_x, ymax)).x()
            if hit is None:
                y_hit = map_point(Vec2(ray_x, ymin)).y()
                color = QColor("#16a34a")
            else:
                y_hit = map_point(Vec2(ray_x, hit[0])).y()
                color = QColor("#dc2626") if hit[0] > 0.6 else QColor("#16a34a")
            pen = QPen(color, 1.0, Qt.DashLine)
            painter.setPen(pen)
            painter.drawLine(QPointF(x0, map_point(Vec2(ray_x, ymax)).y()), QPointF(x0, y_hit))

        painter.setPen(QPen(QColor("#4b5563"), 1))
        painter.drawText(
            plot.adjusted(4, 4, -4, -4),
            Qt.AlignLeft | Qt.AlignBottom,
            "General state: polygon regions + material metadata + operation log + field placeholders",
        )
        painter.end()


class CrossSectionCardWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Cross Section Prototype - General Region Model")
        self.resize(1100, 780)
        self._thickness_nm = 70

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(28, 26, 28, 26)
        root_layout.setSpacing(10)

        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(22, 18, 22, 18)
        card_layout.setSpacing(12)

        title = QLabel("Two-Period T-Grating on Substrate with Overetch + Conformal Metal")
        title.setObjectName("Title")

        self.canvas = CrossSectionCanvas()

        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.thickness_label = QLabel("")
        self.thickness_label.setObjectName("Meta")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(20, 260)
        self.slider.setValue(self._thickness_nm)
        self.slider.valueChanged.connect(self._on_slider_value_changed)
        controls.addWidget(self.thickness_label, 0)
        controls.addWidget(self.slider, 1)

        card_layout.addWidget(title)
        card_layout.addWidget(self.canvas, 1)
        card_layout.addLayout(controls)
        root_layout.addWidget(card, 1)
        self.setCentralWidget(root)

        self._apply_style()
        self._refresh_state()

    def _on_slider_value_changed(self, value: int) -> None:
        self._thickness_nm = int(value)
        self._refresh_state()

    def _refresh_state(self) -> None:
        state = build_state_with_conformal(self._thickness_nm)
        self.canvas.set_state(state)
        self.thickness_label.setText(
            f"Conformal thickness: {self._thickness_nm} nm (orthonormal interface offset)"
        )

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow {
                background: #e5e7eb;
            }
            #Card {
                background: #f3f4f6;
                border: 1px solid #cfd5dd;
                border-radius: 18px;
            }
            #Title {
                color: #111827;
                font-size: 18px;
                font-weight: 700;
            }
            #Meta {
                color: #334155;
                font-size: 13px;
                min-width: 340px;
            }
            QSlider::groove:horizontal {
                height: 8px;
                border-radius: 4px;
                background: #cbd5e1;
            }
            QSlider::sub-page:horizontal {
                border-radius: 4px;
                background: #64748b;
            }
            QSlider::handle:horizontal {
                background: #0f172a;
                width: 18px;
                margin: -5px 0;
                border-radius: 9px;
            }
            """
        )


def main() -> int:
    app = QApplication(sys.argv)
    window = CrossSectionCardWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
