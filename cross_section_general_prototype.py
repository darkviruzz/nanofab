from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPainterPathStroker, QPen, QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
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
    name: str
    category: str
    composition: str
    crystallinity: str
    morphology: str
    optical_constants: dict[str, float]
    fill_hex: str
    stroke_hex: str


@dataclass
class ProcessInteractionModel:
    process_id: str
    name: str
    etch_rate_by_material_nm_min: dict[str, float] = field(default_factory=dict)
    notes: str = ""

    def etch_rate_nm_min(self, material: MaterialDef) -> float:
        # Explicit process lookup first; fallback can be derived from material properties.
        if material.material_id in self.etch_rate_by_material_nm_min:
            return float(self.etch_rate_by_material_nm_min[material.material_id])
        if material.category == "metal":
            return 8.0
        if material.category == "semiconductor":
            return 35.0
        return 18.0


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
class RayCastHit:
    x: float
    y: float
    material_id: str


@dataclass
class RayCastResult:
    x: float
    y_start: float
    y_stop: float
    hit: RayCastHit | None

    @property
    def open_to_bottom(self) -> bool:
        return self.hit is None


@dataclass
class CrossSectionState:
    schema_version: str
    extent: tuple[float, float, float, float]
    materials: dict[str, MaterialDef]
    process_models: dict[str, ProcessInteractionModel]
    active_process_id: str
    regions: list[Region2D]
    scalar_fields: dict[str, ScalarField2D] = field(default_factory=dict)
    operation_log: list[str] = field(default_factory=list)


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


def path_from_polygon(points: list[Vec2]) -> QPainterPath:
    path = QPainterPath()
    clean = ensure_ccw(points)
    if len(clean) < 3:
        return path
    path.moveTo(clean[0].x, clean[0].y)
    for point in clean[1:]:
        path.lineTo(point.x, point.y)
    path.closeSubpath()
    return path


def path_from_regions(regions: list[Region2D]) -> QPainterPath:
    union = QPainterPath()
    for region in regions:
        union = union.united(path_from_polygon(region.points))
    return union


def rect_path(x0: float, y0: float, x1: float, y1: float) -> QPainterPath:
    path = QPainterPath()
    left = min(x0, x1)
    right = max(x0, x1)
    bottom = min(y0, y1)
    top = max(y0, y1)
    path.addRect(left, bottom, right - left, top - bottom)
    return path


def path_to_regions(
    path: QPainterPath,
    *,
    region_prefix: str,
    material_id: str,
    tags: set[str],
    props: dict[str, Any] | None = None,
) -> list[Region2D]:
    regions: list[Region2D] = []
    props_map = dict(props or {})
    polygons = path.toSubpathPolygons()
    for idx, poly in enumerate(polygons):
        points = [Vec2(float(point.x()), float(point.y())) for point in poly]
        if len(points) > 1 and points[0] == points[-1]:
            points = points[:-1]
        points = ensure_ccw(points)
        if len(points) < 3:
            continue
        if abs(polygon_area(points)) < 1e-8:
            continue
        regions.append(
            Region2D(
                region_id=f"{region_prefix}_{idx:03d}",
                material_id=material_id,
                points=points,
                tags=set(tags),
                props=dict(props_map),
            )
        )
    return regions


def vertical_ray_first_hit(
    regions: list[Region2D],
    x: float,
    y_start: float,
    y_stop: float,
) -> tuple[float, str] | None:
    hits: list[tuple[float, str]] = []
    for region in regions:
        if "solid" not in region.tags:
            continue
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


def raycast_scan(
    state: CrossSectionState,
    *,
    sample_count: int = 31,
    x_margin: float = 0.6,
) -> list[RayCastResult]:
    xmin, xmax, ymin, ymax = state.extent
    if sample_count <= 0:
        return []
    span = max(1e-9, (xmax - xmin) - 2.0 * x_margin)
    results: list[RayCastResult] = []
    for idx in range(sample_count):
        x = xmin + x_margin + (span * idx / max(1, sample_count - 1))
        hit = vertical_ray_first_hit(state.regions, x=x, y_start=ymax, y_stop=ymin)
        if hit is None:
            results.append(RayCastResult(x=x, y_start=ymax, y_stop=ymin, hit=None))
        else:
            results.append(
                RayCastResult(
                    x=x,
                    y_start=ymax,
                    y_stop=ymin,
                    hit=RayCastHit(x=x, y=float(hit[0]), material_id=str(hit[1])),
                )
            )
    return results


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
            name="Si Substrate",
            category="semiconductor",
            composition="Si",
            crystallinity="single_crystal",
            morphology="planar",
            optical_constants={"n_550nm": 3.88, "k_550nm": 0.02},
            fill_hex="#1f9bd1",
            stroke_hex="#1375a2",
        ),
        "grating": MaterialDef(
            material_id="grating",
            name="Resist Core",
            category="polymer",
            composition="Organic resist",
            crystallinity="amorphous",
            morphology="dense",
            optical_constants={"n_550nm": 1.63, "k_550nm": 0.01},
            fill_hex="#f53b3b",
            stroke_hex="#a61717",
        ),
        "metal": MaterialDef(
            material_id="metal",
            name="Conformal Metal",
            category="metal",
            composition="TiN-like",
            crystallinity="nanocrystalline",
            morphology="columnar_thinfilm",
            optical_constants={"n_550nm": 2.1, "k_550nm": 3.9},
            fill_hex="#8b929b",
            stroke_hex="#5a6168",
        ),
    }

    process_models = {
        "ion_beam_demo": ProcessInteractionModel(
            process_id="ion_beam_demo",
            name="Ion Beam Etch Demo",
            etch_rate_by_material_nm_min={
                "substrate": 46.0,
                "grating": 22.0,
                "metal": 7.0,
            },
            notes=(
                "Process-layer model. Rates can come from explicit material table or "
                "fallback property-based model in ProcessInteractionModel.etch_rate_nm_min(...)."
            ),
        )
    }

    # Stepped top boundary models slight overetch into substrate in open windows.
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
        process_models=process_models,
        active_process_id="ion_beam_demo",
        regions=regions,
        scalar_fields={
            "exposure_dose": ScalarField2D(
                field_id="exposure_dose",
                unit="mJ/cm^2",
                description="Field layer placeholder for gradient-based resist and optical modeling.",
            )
        },
        operation_log=[
            "init: substrate + two-period T-grating + slight overetch profile",
            "material properties in material DB only",
            "process/material interaction moved to ProcessInteractionModel",
        ],
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
            # Ignore far-below cut boundary and side wall limits.
            if mid.y < -0.45:
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


def build_iterative_conformal_metal_regions(
    base_state: CrossSectionState,
    thickness_nm: int,
    max_iterations: int = 8,
) -> tuple[list[Region2D], int]:
    base_solids = [region for region in base_state.regions if "solid" in region.tags and region.material_id != "metal"]
    base_solid_path = path_from_regions(base_solids)

    xmin, xmax, _, ymax = base_state.extent
    # Process window: only top-connected region (prevents backside/bottom growth in this prototype).
    deposition_domain = rect_path(xmin + 0.08, -0.45, xmax - 0.08, ymax + 0.10)

    metal_path = QPainterPath()
    previous_shell = QPainterPath()
    target_nm = max(0, int(thickness_nm))
    if target_nm <= 0:
        return [], 0
    steps = max(1, min(max_iterations, int(math.ceil(target_nm / 5.0))))
    target_um = float(target_nm) / 1000.0
    performed = 0

    for step_idx in range(steps):
        radius_um = target_um * float(step_idx + 1) / float(steps)
        stroker = QPainterPathStroker()
        # Iterative shell growth from base interfaces. Later shells are built on prior shells.
        stroker.setWidth(2.0 * radius_um)
        stroker.setJoinStyle(Qt.RoundJoin)
        stroker.setCapStyle(Qt.RoundCap)
        stroker.setMiterLimit(2.0)

        shell = stroker.createStroke(base_solid_path)
        shell = shell.subtracted(base_solid_path)
        shell = shell.intersected(deposition_domain)
        shell = shell.subtracted(base_solid_path)
        increment = shell.subtracted(previous_shell)

        if increment.isEmpty():
            break

        previous_shell = previous_shell.united(increment)
        metal_path = previous_shell
        performed += 1

    metal_regions = path_to_regions(
        metal_path,
        region_prefix="metal",
        material_id="metal",
        tags={"solid", "metal", "deposited", "deposition_target"},
        props={
            "growth_model": "iterative_normal_offset",
            "target_thickness_nm": thickness_nm,
            "step_nm_effective": (target_nm / max(1, performed)) if performed > 0 else 0.0,
            "performed_steps": performed,
        },
    )
    return metal_regions, performed


def build_state_with_conformal(thickness_nm: int) -> CrossSectionState:
    base_state = build_base_state()
    metal_regions, performed_steps = build_iterative_conformal_metal_regions(base_state, thickness_nm=thickness_nm)
    return CrossSectionState(
        schema_version=base_state.schema_version,
        extent=base_state.extent,
        materials=base_state.materials,
        process_models=base_state.process_models,
        active_process_id=base_state.active_process_id,
        regions=[*base_state.regions, *metal_regions],
        scalar_fields=base_state.scalar_fields,
        operation_log=[
            *base_state.operation_log,
            (
                f"deposit_conformal_iterative: target={thickness_nm} nm, "
                f"iterations={performed_steps}, regions={len(metal_regions)}"
            ),
        ],
    )


class CrossSectionCanvas(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._state = build_state_with_conformal(70)
        self._show_exposed_interfaces = True
        self._show_ray_cast = True
        self._cached_interfaces: list[InterfaceSegment] = []
        self._cached_rays: list[RayCastResult] = []
        self.setMinimumSize(860, 520)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._rebuild_overlays()

    def set_state(self, state: CrossSectionState) -> None:
        self._state = state
        self._rebuild_overlays()
        self.update()

    def set_overlay_flags(self, *, show_exposed_interfaces: bool, show_ray_cast: bool) -> None:
        self._show_exposed_interfaces = bool(show_exposed_interfaces)
        self._show_ray_cast = bool(show_ray_cast)
        self._rebuild_overlays()
        self.update()

    def _rebuild_overlays(self) -> None:
        if self._show_exposed_interfaces:
            self._cached_interfaces = extract_exposed_interfaces(self._state)
        else:
            self._cached_interfaces = []
        if self._show_ray_cast:
            self._cached_rays = raycast_scan(self._state, sample_count=31)
        else:
            self._cached_rays = []

    @property
    def exposed_count(self) -> int:
        return len(self._cached_interfaces)

    @property
    def ray_open_count(self) -> int:
        return sum(1 for ray in self._cached_rays if ray.open_to_bottom)

    @property
    def ray_total_count(self) -> int:
        return len(self._cached_rays)

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
            painter.setPen(QPen(stroke, 1.45))
            painter.drawPolygon(qpoly)

        if self._show_exposed_interfaces:
            pen_interface = QPen(QColor("#16a34a"), 2.0)
            pen_normal = QPen(QColor("#22c55e"), 1.1, Qt.DashLine)
            painter.setBrush(Qt.NoBrush)
            for interface in self._cached_interfaces:
                p0 = map_point(interface.start)
                p1 = map_point(interface.end)
                painter.setPen(pen_interface)
                painter.drawLine(p0, p1)
                mid = edge_midpoint(interface.start, interface.end)
                tip = mid.offset(interface.normal_outward.x * 0.12, interface.normal_outward.y * 0.12)
                painter.setPen(pen_normal)
                painter.drawLine(map_point(mid), map_point(tip))

        if self._show_ray_cast:
            for ray in self._cached_rays:
                start = map_point(Vec2(ray.x, ray.y_start))
                if ray.hit is None:
                    end = map_point(Vec2(ray.x, ray.y_stop))
                    color = QColor("#16a34a")
                else:
                    end = map_point(Vec2(ray.hit.x, ray.hit.y))
                    color = QColor("#dc2626")
                painter.setPen(QPen(color, 1.0, Qt.DashLine))
                painter.drawLine(start, end)
                if ray.hit is not None:
                    painter.setPen(QPen(color, 1.0))
                    painter.setBrush(color)
                    painter.drawEllipse(end, 2.4, 2.4)

        last_op = self._state.operation_log[-1] if self._state.operation_log else "no-op"
        painter.setPen(QPen(QColor("#4b5563"), 1))
        painter.drawText(
            plot.adjusted(4, 4, -4, -4),
            Qt.AlignLeft | Qt.AlignBottom,
            f"{last_op}",
        )
        painter.end()


class CrossSectionCardWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Cross Section Prototype - General Region/Interface Model")
        self.resize(1120, 790)
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

        title = QLabel("Two-Period T-Grating + Overetch + Iterative Conformal Metal Growth")
        title.setObjectName("Title")
        subtitle = QLabel(
            "Data model: material DB + process/material interaction model + polygon regions + fields + operation log"
        )
        subtitle.setObjectName("SubTitle")

        self.canvas = CrossSectionCanvas()

        row1 = QHBoxLayout()
        row1.setSpacing(10)
        self.thickness_label = QLabel("")
        self.thickness_label.setObjectName("Meta")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(20, 260)
        self.slider.setValue(self._thickness_nm)
        self.slider.valueChanged.connect(self._on_slider_value_changed)
        row1.addWidget(self.thickness_label, 0)
        row1.addWidget(self.slider, 1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.btn_show_exposed = QPushButton("Exposed Interfaces")
        self.btn_show_exposed.setObjectName("ToggleBtn")
        self.btn_show_exposed.setCheckable(True)
        self.btn_show_exposed.setChecked(True)
        self.btn_show_exposed.toggled.connect(self._on_overlay_flags_changed)

        self.btn_show_rays = QPushButton("Ray Casting")
        self.btn_show_rays.setObjectName("ToggleBtn")
        self.btn_show_rays.setCheckable(True)
        self.btn_show_rays.setChecked(True)
        self.btn_show_rays.toggled.connect(self._on_overlay_flags_changed)

        self.analysis_label = QLabel("")
        self.analysis_label.setObjectName("Meta")
        self.analysis_label.setMinimumWidth(420)

        row2.addWidget(self.btn_show_exposed)
        row2.addWidget(self.btn_show_rays)
        row2.addWidget(self.analysis_label, 1)

        self.process_label = QLabel("")
        self.process_label.setObjectName("Meta")

        card_layout.addWidget(title)
        card_layout.addWidget(subtitle)
        card_layout.addWidget(self.canvas, 1)
        card_layout.addLayout(row1)
        card_layout.addLayout(row2)
        card_layout.addWidget(self.process_label)
        root_layout.addWidget(card, 1)
        self.setCentralWidget(root)

        self._apply_style()
        self._refresh_state()

    def _on_slider_value_changed(self, value: int) -> None:
        self._thickness_nm = int(value)
        self._refresh_state()

    def _on_overlay_flags_changed(self) -> None:
        self.canvas.set_overlay_flags(
            show_exposed_interfaces=self.btn_show_exposed.isChecked(),
            show_ray_cast=self.btn_show_rays.isChecked(),
        )
        self._refresh_analysis_text()

    def _refresh_analysis_text(self) -> None:
        self.analysis_label.setText(
            (
                f"Exposed segments: {self.canvas.exposed_count} | "
                f"Open rays: {self.canvas.ray_open_count}/{self.canvas.ray_total_count}"
            )
        )

    def _refresh_state(self) -> None:
        state = build_state_with_conformal(self._thickness_nm)
        self.canvas.set_state(state)
        self.canvas.set_overlay_flags(
            show_exposed_interfaces=self.btn_show_exposed.isChecked(),
            show_ray_cast=self.btn_show_rays.isChecked(),
        )

        self.thickness_label.setText(
            (
                f"Conformal thickness: {self._thickness_nm} nm "
                f"(iterative orthonormal growth, bounded passes)"
            )
        )
        self._refresh_analysis_text()

        process = state.process_models[state.active_process_id]
        rate_chunks: list[str] = []
        for material_id in ("substrate", "grating", "metal"):
            material = state.materials[material_id]
            rate = process.etch_rate_nm_min(material)
            rate_chunks.append(f"{material.name}: {rate:.1f} nm/min")
        self.process_label.setText(
            f"Process interaction ({process.name}) -> " + " | ".join(rate_chunks)
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
            #SubTitle {
                color: #334155;
                font-size: 13px;
                margin-bottom: 4px;
            }
            #Meta {
                color: #334155;
                font-size: 13px;
            }
            #ToggleBtn {
                border-radius: 9px;
                border: 1px solid #94a3b8;
                background: #e2e8f0;
                color: #0f172a;
                padding: 5px 10px;
                font-weight: 600;
            }
            #ToggleBtn:checked {
                background: #0f172a;
                border: 1px solid #0f172a;
                color: #f8fafc;
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
