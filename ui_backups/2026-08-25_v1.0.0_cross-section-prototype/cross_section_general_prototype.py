from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPainterPathStroker, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

EPSILON = 1e-6


@dataclass(frozen=True)
class Vec2:
    x: float
    y: float

    def add(self, other: Vec2) -> Vec2:
        return Vec2(self.x + other.x, self.y + other.y)

    def sub(self, other: Vec2) -> Vec2:
        return Vec2(self.x - other.x, self.y - other.y)

    def scaled(self, factor: float) -> Vec2:
        return Vec2(self.x * factor, self.y * factor)

    def dot(self, other: Vec2) -> float:
        return self.x * other.x + self.y * other.y

    def length(self) -> float:
        return math.hypot(self.x, self.y)

    def normalized(self) -> Vec2:
        length = self.length()
        if length <= EPSILON:
            return Vec2(0.0, 0.0)
        return Vec2(self.x / length, self.y / length)

    def distance_to(self, other: Vec2) -> float:
        return self.sub(other).length()

    def to_qpointf(self) -> QPointF:
        return QPointF(self.x, self.y)

    @staticmethod
    def from_qpointf(point: QPointF) -> Vec2:
        return Vec2(float(point.x()), float(point.y()))


class Segment2D:
    seg_id: str

    def start(self) -> Vec2:
        raise NotImplementedError

    def end(self) -> Vec2:
        raise NotImplementedError

    def length_nm(self) -> float:
        raise NotImplementedError

    def point_tangent(self, t: float) -> tuple[Vec2, Vec2]:
        raise NotImplementedError

    def sample_points(self, max_chord_nm: float) -> list[Vec2]:
        raise NotImplementedError

    def reversed(self) -> Segment2D:
        raise NotImplementedError


@dataclass(frozen=True)
class LineSegment(Segment2D):
    seg_id: str
    p0: Vec2
    p1: Vec2

    def start(self) -> Vec2:
        return self.p0

    def end(self) -> Vec2:
        return self.p1

    def length_nm(self) -> float:
        return self.p0.distance_to(self.p1)

    def point_tangent(self, t: float) -> tuple[Vec2, Vec2]:
        t_clamped = clamp(t, 0.0, 1.0)
        delta = self.p1.sub(self.p0)
        point = self.p0.add(delta.scaled(t_clamped))
        tangent = delta.normalized()
        return point, tangent

    def sample_points(self, max_chord_nm: float) -> list[Vec2]:
        count = max(2, int(math.ceil(self.length_nm() / max(max_chord_nm, 0.5))) + 1)
        points: list[Vec2] = []
        for index in range(count):
            t = index / max(1, count - 1)
            point, _ = self.point_tangent(t)
            points.append(point)
        return points

    def reversed(self) -> Segment2D:
        return LineSegment(seg_id=f"{self.seg_id}_rev", p0=self.p1, p1=self.p0)


@dataclass(frozen=True)
class ArcSegment(Segment2D):
    seg_id: str
    center: Vec2
    radius_nm: float
    start_deg: float
    sweep_deg: float

    def start(self) -> Vec2:
        return self._point_for_angle(self.start_deg)

    def end(self) -> Vec2:
        return self._point_for_angle(self.start_deg + self.sweep_deg)

    def length_nm(self) -> float:
        return abs(math.radians(self.sweep_deg) * self.radius_nm)

    def point_tangent(self, t: float) -> tuple[Vec2, Vec2]:
        t_clamped = clamp(t, 0.0, 1.0)
        theta_deg = self.start_deg + self.sweep_deg * t_clamped
        point = self._point_for_angle(theta_deg)
        theta = math.radians(theta_deg)
        sweep_sign = 1.0 if self.sweep_deg >= 0.0 else -1.0
        tangent = Vec2(-math.sin(theta) * sweep_sign, math.cos(theta) * sweep_sign).normalized()
        return point, tangent

    def sample_points(self, max_chord_nm: float) -> list[Vec2]:
        chord = max(max_chord_nm, 0.5)
        count = max(3, int(math.ceil(self.length_nm() / chord)) + 1)
        points: list[Vec2] = []
        for index in range(count):
            t = index / max(1, count - 1)
            point, _ = self.point_tangent(t)
            points.append(point)
        return points

    def reversed(self) -> Segment2D:
        return ArcSegment(
            seg_id=f"{self.seg_id}_rev",
            center=self.center,
            radius_nm=self.radius_nm,
            start_deg=self.start_deg + self.sweep_deg,
            sweep_deg=-self.sweep_deg,
        )

    def _point_for_angle(self, angle_deg: float) -> Vec2:
        theta = math.radians(angle_deg)
        return Vec2(
            self.center.x + self.radius_nm * math.cos(theta),
            self.center.y + self.radius_nm * math.sin(theta),
        )


@dataclass
class InterfaceLoop:
    loop_id: str
    segments: list[Segment2D]


@dataclass
class MaterialDef:
    material_id: str
    name: str
    fill_hex: str
    stroke_hex: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProcessInteractionModel:
    process_id: str
    name: str
    rate_nm_s_by_material: dict[str, float] = field(default_factory=dict)
    notes: str = ""

    def rate_nm_s(self, material_id: str) -> float | None:
        rate = self.rate_nm_s_by_material.get(material_id)
        if rate is None:
            return None
        return float(rate)


@dataclass
class Region2D:
    region_id: str
    material_id: str
    outer_loop: InterfaceLoop
    tags: set[str] = field(default_factory=set)
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExposedEdge:
    start: Vec2
    end: Vec2
    normal_outward: Vec2
    owner_material_id: str | None
    loop_id: str = ""
    edge_index: int = -1
    loop_pos_start_nm: float = 0.0
    loop_pos_end_nm: float = 0.0
    loop_length_nm: float = 0.0

    def midpoint(self) -> Vec2:
        return Vec2(0.5 * (self.start.x + self.end.x), 0.5 * (self.start.y + self.end.y))


@dataclass
class TopologyEdge:
    edge_id: str
    start: Vec2
    end: Vec2
    normal_outward: Vec2
    primary_material_id: str
    secondary_material_id: str | None
    supporting_material_ids: tuple[str, ...]
    is_shared: bool
    source_loop_id: str = ""
    source_edge_index: int = -1

    def midpoint(self) -> Vec2:
        return Vec2(0.5 * (self.start.x + self.end.x), 0.5 * (self.start.y + self.end.y))

    def length_nm(self) -> float:
        return self.start.distance_to(self.end)


@dataclass
class BoundaryLoop:
    loop_id: str
    points: list[Vec2]
    cumulative_nm: list[float]
    total_length_nm: float


@dataclass
class DirectionalSurfaceChain:
    chain_id: str
    owner_material_id: str
    segments: list[Segment2D]
    cumulative_nm: list[float]
    total_length_nm: float
    closed: bool = False


@dataclass(frozen=True)
class ExposedSegmentPiece:
    source_segment_index: int
    t0: float
    t1: float
    segment: Segment2D


@dataclass
class RayHit:
    point: Vec2
    material_id: str
    normal_outward: Vec2
    distance_nm: float
    loop_id: str = ""
    edge_index: int = -1
    edge_t: float = 0.0
    loop_position_nm: float = 0.0


@dataclass
class RayTrace:
    origin: Vec2
    end: Vec2
    hit: RayHit | None
    refinement_pass: int = 0


@dataclass
class DirectionalSpan:
    loop_id: str
    material_id: str
    path: QPainterPath
    weight: float


@dataclass
class LoopDiagnostic:
    loop_id: str
    line_count: int
    arc_count: int
    warnings: list[str]


@dataclass
class CrossSectionState:
    schema_version: str
    extent: tuple[float, float, float, float]
    materials: dict[str, MaterialDef]
    process_models: dict[str, ProcessInteractionModel]
    active_process_id: str
    regions: list[Region2D]
    operation_log: list[str] = field(default_factory=list)


@dataclass
class PrototypeParams:
    mode_label: str
    cap_corner_radius_nm: float
    trench_depth_nm: float
    trench_radius_nm: float
    process_time_s: float
    steps_per_s: float
    ray_angle_deg: float
    ray_count: int
    arc_chord_nm: float
    show_interfaces: bool
    show_normals: bool
    show_rays: bool
    show_shadow: bool
    show_grid: bool = True
    inspect_interfaces: bool = False
    etch_enabled_materials: dict[str, bool] = field(default_factory=dict)
    rate_nm_s_by_material: dict[str, float] = field(default_factory=dict)
    conformal_deposition_material_id: str = "metal"
    directional_deposition_material_id: str = "metal"


@dataclass
class SceneSnapshot:
    extent: tuple[float, float, float, float]
    material_paths: dict[str, QPainterPath]
    material_order: list[str]
    exposed_edges: list[ExposedEdge]
    topology_edges: list[TopologyEdge]
    boundary_loops: dict[str, BoundaryLoop]
    rays: list[RayTrace]
    shadow_mask: QPainterPath
    loop_diagnostics: list[LoopDiagnostic]
    info_lines: list[str]


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def points_area_signed(points: list[Vec2]) -> float:
    if len(points) < 3:
        return 0.0
    total = 0.0
    for idx in range(len(points)):
        p = points[idx]
        q = points[(idx + 1) % len(points)]
        total += p.x * q.y - q.x * p.y
    return 0.5 * total


def sample_loop_points(loop: InterfaceLoop, max_chord_nm: float) -> list[Vec2]:
    sampled: list[Vec2] = []
    for segment in loop.segments:
        points = segment.sample_points(max_chord_nm=max_chord_nm)
        if not points:
            continue
        if sampled and sampled[-1].distance_to(points[0]) <= 1e-4:
            sampled.extend(points[1:])
        else:
            sampled.extend(points)
    if sampled and sampled[0].distance_to(sampled[-1]) <= 1e-4:
        sampled = sampled[:-1]
    return sampled


def reverse_loop(loop: InterfaceLoop) -> InterfaceLoop:
    return InterfaceLoop(
        loop_id=f"{loop.loop_id}_rev",
        segments=[segment.reversed() for segment in reversed(loop.segments)],
    )


def ensure_ccw(loop: InterfaceLoop, max_chord_nm: float) -> InterfaceLoop:
    points = sample_loop_points(loop, max_chord_nm=max_chord_nm)
    if points_area_signed(points) < 0.0:
        return reverse_loop(loop)
    return loop


def loop_to_path(loop: InterfaceLoop, max_chord_nm: float) -> QPainterPath:
    normalized_loop = ensure_ccw(loop, max_chord_nm=max_chord_nm)
    points = sample_loop_points(normalized_loop, max_chord_nm=max_chord_nm)
    path = QPainterPath()
    if len(points) < 3:
        return path
    path.moveTo(points[0].x, points[0].y)
    for point in points[1:]:
        path.lineTo(point.x, point.y)
    path.closeSubpath()
    return path


def path_union(paths: list[QPainterPath]) -> QPainterPath:
    union = QPainterPath()
    for path in paths:
        union = union.united(path)
    return union


def edges_to_path(edges: list[ExposedEdge]) -> QPainterPath:
    path = QPainterPath()
    for edge in edges:
        path.moveTo(edge.start.x, edge.start.y)
        path.lineTo(edge.end.x, edge.end.y)
    return path


def line_from_points(seg_id: str, x0: float, y0: float, x1: float, y1: float) -> LineSegment:
    return LineSegment(seg_id=seg_id, p0=Vec2(x0, y0), p1=Vec2(x1, y1))


def trim_segment(segment: Segment2D, t0: float, t1: float, seg_id: str) -> Segment2D | None:
    start_t = clamp(t0, 0.0, 1.0)
    end_t = clamp(t1, 0.0, 1.0)
    if end_t <= start_t + 1e-9:
        return None
    if isinstance(segment, LineSegment):
        start, _ = segment.point_tangent(start_t)
        end, _ = segment.point_tangent(end_t)
        return LineSegment(seg_id=seg_id, p0=start, p1=end)
    if isinstance(segment, ArcSegment):
        return ArcSegment(
            seg_id=seg_id,
            center=segment.center,
            radius_nm=segment.radius_nm,
            start_deg=segment.start_deg + segment.sweep_deg * start_t,
            sweep_deg=segment.sweep_deg * (end_t - start_t),
        )
    raise TypeError(f"Unsupported segment type: {type(segment).__name__}")


def segment_to_path(segment: Segment2D, max_chord_nm: float) -> QPainterPath:
    path = QPainterPath()
    points = segment.sample_points(max_chord_nm=max_chord_nm)
    if not points:
        return path
    path.moveTo(points[0].x, points[0].y)
    for point in points[1:]:
        path.lineTo(point.x, point.y)
    return path


class GeometryTopologyEngine:
    def __init__(self, state: CrossSectionState, arc_chord_nm: float) -> None:
        self.state = state
        self.arc_chord_nm = max(0.8, arc_chord_nm)

    def material_paths_from_regions(self) -> dict[str, QPainterPath]:
        paths: dict[str, QPainterPath] = {}
        for region in self.state.regions:
            region_path = loop_to_path(region.outer_loop, max_chord_nm=self.arc_chord_nm)
            existing = paths.get(region.material_id)
            if existing is None:
                paths[region.material_id] = region_path
            else:
                paths[region.material_id] = existing.united(region_path)
        return paths

    @staticmethod
    def _coarse_boundary_path(shape_path: QPainterPath, max_points_per_loop: int = 640) -> QPainterPath:
        boundary = QPainterPath()
        polygons = shape_path.toSubpathPolygons()
        for polygon in polygons:
            points = [Vec2.from_qpointf(point) for point in polygon]
            if len(points) > 1 and points[0].distance_to(points[-1]) <= 1e-6:
                points = points[:-1]
            if len(points) < 3:
                continue
            stride = max(1, int(math.ceil(len(points) / max(16, max_points_per_loop))))
            sampled = points[::stride]
            if len(sampled) < 3:
                sampled = points
            if sampled[0].distance_to(sampled[-1]) <= 1e-6:
                sampled = sampled[:-1]
            if len(sampled) < 3:
                continue
            boundary.moveTo(sampled[0].x, sampled[0].y)
            for point in sampled[1:]:
                boundary.lineTo(point.x, point.y)
            boundary.closeSubpath()
        return boundary

    @staticmethod
    def _simplify_closed_points(points: list[Vec2], collinear_sin_tol: float = 0.01) -> list[Vec2]:
        simplified = list(points)
        if simplified and simplified[0].distance_to(simplified[-1]) <= 1e-6:
            simplified = simplified[:-1]
        if len(simplified) < 3:
            return simplified
        changed = True
        while changed and len(simplified) > 3:
            changed = False
            count = len(simplified)
            for idx in range(count):
                prev = simplified[(idx - 1) % count]
                curr = simplified[idx]
                nxt = simplified[(idx + 1) % count]
                v1 = curr.sub(prev)
                v2 = nxt.sub(curr)
                l1 = v1.length()
                l2 = v2.length()
                if l1 <= 1e-9 or l2 <= 1e-9:
                    del simplified[idx]
                    changed = True
                    break
                cross_norm = abs(v1.x * v2.y - v1.y * v2.x) / (l1 * l2)
                dot_norm = (v1.x * v2.x + v1.y * v2.y) / (l1 * l2)
                if cross_norm <= collinear_sin_tol and dot_norm >= 0.995:
                    del simplified[idx]
                    changed = True
                    break
        return simplified

    @staticmethod
    def _iter_time_steps(time_s: float, steps_per_s: float) -> list[float]:
        total_time = max(0.0, time_s)
        sampling = max(1e-6, steps_per_s)
        dt = 1.0 / sampling
        n_full = int(math.floor(total_time / dt))
        remainder = total_time - n_full * dt
        steps = [dt] * n_full
        if remainder > 1e-9:
            steps.append(remainder)
        return steps

    @staticmethod
    def _total_delta_nm(rate_nm_s: float, time_s: float) -> float:
        return max(0.0, rate_nm_s) * max(0.0, time_s)

    @staticmethod
    def _band_from_marked_surface(marked_surface: QPainterPath, delta_nm: float) -> QPainterPath:
        if marked_surface.isEmpty() or delta_nm <= 1e-9:
            return QPainterPath()
        stroker = QPainterPathStroker()
        stroker.setWidth(max(0.2, delta_nm * 2.0))
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return stroker.createStroke(marked_surface).simplified()

    def _local_hit_span_on_chain(self, chain: DirectionalSurfaceChain, hit: RayHit, half_span_nm: float) -> QPainterPath:
        path = QPainterPath()
        if hit.edge_index < 0 or hit.edge_index >= len(chain.segments):
            return path
        segment = chain.segments[hit.edge_index]
        segment_length = segment.length_nm()
        if segment_length <= 1e-9:
            return path
        delta_t = half_span_nm / segment_length
        piece = trim_segment(
            segment,
            hit.edge_t - delta_t,
            hit.edge_t + delta_t,
            seg_id=f"{chain.chain_id}_local_{hit.edge_index:03d}",
        )
        if piece is None:
            return path
        return segment_to_path(piece, max_chord_nm=self.arc_chord_nm)

    @staticmethod
    def _directional_incidence_weight(ray_direction: Vec2, edge_normal_outward: Vec2) -> float:
        # Rays travel along ray_direction; exposed faces with opposing normal receive higher flux.
        return clamp(-ray_direction.normalized().dot(edge_normal_outward.normalized()), 0.0, 1.0)

    @staticmethod
    def _directional_band_from_spans(
        spans: list[DirectionalSpan],
        total_delta_nm: float,
        nominal_steps: int,
    ) -> QPainterPath:
        if total_delta_nm <= 1e-9 or not spans:
            return QPainterPath()
        bin_count = int(clamp(float(max(2, nominal_steps)), 2.0, 10.0))
        path_by_bin: dict[int, QPainterPath] = {}
        for span in spans:
            weight = clamp(span.weight, 0.0, 1.0)
            if weight <= 1e-3 or span.path.isEmpty():
                continue
            level = max(1, min(bin_count, int(math.ceil(weight * bin_count))))
            bucket = path_by_bin.get(level)
            if bucket is None:
                bucket = QPainterPath()
                path_by_bin[level] = bucket
            bucket.addPath(span.path)
        if not path_by_bin:
            return QPainterPath()
        band = QPainterPath()
        for level, marked_path in path_by_bin.items():
            if marked_path.isEmpty():
                continue
            delta = total_delta_nm * (float(level) / float(bin_count))
            band = band.united(GeometryTopologyEngine._band_from_marked_surface(marked_path, delta))
        return band.simplified()

    def _directional_spans_from_surface_rays(
        self,
        traces: list[RayTrace],
        surface_chains: dict[str, DirectionalSurfaceChain],
        allowed_materials: set[str] | None,
        ray_direction: Vec2,
    ) -> list[DirectionalSpan]:
        spans: list[DirectionalSpan] = []
        covered_hits = [False] * len(traces)
        hits_by_chain: dict[str, list[tuple[int, RayTrace, RayHit]]] = {}
        for idx, trace in enumerate(traces):
            hit = trace.hit
            if hit is None:
                continue
            if allowed_materials is not None and hit.material_id not in allowed_materials:
                continue
            if hit.loop_id not in surface_chains:
                continue
            hits_by_chain.setdefault(hit.loop_id, []).append((idx, trace, hit))
        for chain_id, entries in hits_by_chain.items():
            chain = surface_chains.get(chain_id)
            if chain is None or chain.total_length_nm <= 1e-9:
                continue
            entries.sort(key=lambda entry: entry[2].loop_position_nm)
            for (left_idx, left_trace, left_hit), (right_idx, right_trace, right_hit) in zip(entries, entries[1:]):
                path_between = self._surface_chain_path_between_hits(
                    chain=chain,
                    s0=left_hit.loop_position_nm,
                    s1=right_hit.loop_position_nm,
                    x0=left_trace.origin.x,
                    x1=right_trace.origin.x,
                )
                if path_between.isEmpty():
                    continue
                incidence = 0.5 * (
                    self._directional_incidence_weight(ray_direction, left_hit.normal_outward)
                    + self._directional_incidence_weight(ray_direction, right_hit.normal_outward)
                )
                if incidence <= 1e-3:
                    continue
                covered_hits[left_idx] = True
                covered_hits[right_idx] = True
                spans.append(
                    DirectionalSpan(
                        loop_id=left_hit.loop_id,
                        material_id=left_hit.material_id,
                        path=path_between,
                        weight=incidence,
                    )
                )
        for idx, trace in enumerate(traces):
            hit = trace.hit
            if hit is None or covered_hits[idx]:
                continue
            if allowed_materials is not None and hit.material_id not in allowed_materials:
                continue
            chain = surface_chains.get(hit.loop_id)
            if chain is None:
                continue
            left_dx = float("inf")
            right_dx = float("inf")
            if idx > 0:
                left_dx = max(0.0, trace.origin.x - traces[idx - 1].origin.x)
            if idx + 1 < len(traces):
                right_dx = max(0.0, traces[idx + 1].origin.x - trace.origin.x)
            local_spacing = min(left_dx, right_dx)
            if not math.isfinite(local_spacing) or local_spacing <= 1e-9:
                local_spacing = max(left_dx, right_dx)
            if not math.isfinite(local_spacing) or local_spacing <= 1e-9:
                local_spacing = 2.0
            local_half_span = max(0.4, 0.48 * local_spacing)
            local_path = self._local_hit_span_on_chain(
                chain=chain,
                hit=hit,
                half_span_nm=local_half_span,
            )
            incidence = self._directional_incidence_weight(ray_direction, hit.normal_outward)
            if incidence <= 1e-3 or local_path.isEmpty():
                continue
            spans.append(
                DirectionalSpan(
                    loop_id=hit.loop_id,
                    material_id=hit.material_id,
                    path=local_path,
                    weight=incidence,
                )
            )
        return spans

    @staticmethod
    def _surface_chain_segment_index_at_position(chain: DirectionalSurfaceChain, s_nm: float) -> int:
        s = clamp(s_nm, 0.0, max(0.0, chain.total_length_nm - 1e-9))
        for idx in range(len(chain.segments)):
            if s < chain.cumulative_nm[idx + 1] - 1e-9:
                return idx
        return max(0, len(chain.segments) - 1)

    @staticmethod
    def _point_on_surface_chain(chain: DirectionalSurfaceChain, s_nm: float) -> Vec2:
        if chain.total_length_nm <= 1e-9 or not chain.segments:
            return Vec2(0.0, 0.0)
        edge_idx = GeometryTopologyEngine._surface_chain_segment_index_at_position(chain, s_nm)
        start_s = chain.cumulative_nm[edge_idx]
        end_s = chain.cumulative_nm[edge_idx + 1]
        edge_len = max(EPSILON, end_s - start_s)
        t = clamp((s_nm - start_s) / edge_len, 0.0, 1.0)
        point, _ = chain.segments[edge_idx].point_tangent(t)
        return point

    @staticmethod
    def _surface_chain_sample(
        chain: DirectionalSurfaceChain,
        s_nm: float,
    ) -> tuple[Vec2, Vec2, int, float]:
        edge_idx = GeometryTopologyEngine._surface_chain_segment_index_at_position(chain, s_nm)
        start_s = chain.cumulative_nm[edge_idx]
        end_s = chain.cumulative_nm[edge_idx + 1]
        edge_len = max(EPSILON, end_s - start_s)
        t = clamp((s_nm - start_s) / edge_len, 0.0, 1.0)
        point, _tangent = chain.segments[edge_idx].point_tangent(t)
        normal = GeometryTopologyEngine._segment_outward_normal(chain.segments[edge_idx], t)
        return point, normal, edge_idx, t

    def _append_segment_slice(self, path: QPainterPath, segment: Segment2D, t0: float, t1: float) -> None:
        piece = trim_segment(segment, t0, t1, seg_id=f"{getattr(segment, 'seg_id', 'seg')}_slice")
        if piece is None:
            return
        piece_path = segment_to_path(piece, max_chord_nm=self.arc_chord_nm)
        polygons = piece_path.toSubpathPolygons()
        if not polygons:
            return
        points = [Vec2.from_qpointf(point) for point in polygons[0]]
        if points and points[0].distance_to(points[-1]) <= 1e-6:
            points = points[:-1]
        if not points:
            return
        if path.isEmpty():
            path.moveTo(points[0].x, points[0].y)
        else:
            current = Vec2.from_qpointf(path.currentPosition())
            if current.distance_to(points[0]) > 1e-6:
                path.lineTo(points[0].x, points[0].y)
        for point in points[1:]:
            path.lineTo(point.x, point.y)

    def _surface_chain_path_forward(self, chain: DirectionalSurfaceChain, s_start_nm: float, s_end_nm: float) -> QPainterPath:
        path = QPainterPath()
        if chain.total_length_nm <= 1e-9 or not chain.segments:
            return path
        if s_end_nm <= s_start_nm + 1e-9:
            return path
        start = self._point_on_surface_chain(chain, s_start_nm)
        path.moveTo(start.x, start.y)
        s_cursor = s_start_nm
        while True:
            edge_idx = self._surface_chain_segment_index_at_position(chain, s_cursor)
            edge_start = chain.cumulative_nm[edge_idx]
            edge_end = chain.cumulative_nm[edge_idx + 1]
            if edge_end <= s_cursor + 1e-9:
                break
            if edge_end >= s_end_nm - 1e-9:
                break
            edge_len = max(EPSILON, edge_end - edge_start)
            start_t = clamp((s_cursor - edge_start) / edge_len, 0.0, 1.0)
            self._append_segment_slice(path, chain.segments[edge_idx], start_t, 1.0)
            s_cursor = edge_end
        edge_idx = self._surface_chain_segment_index_at_position(chain, s_end_nm)
        edge_start = chain.cumulative_nm[edge_idx]
        edge_end = chain.cumulative_nm[edge_idx + 1]
        edge_len = max(EPSILON, edge_end - edge_start)
        start_t = clamp((s_cursor - edge_start) / edge_len, 0.0, 1.0)
        end_t = clamp((s_end_nm - edge_start) / edge_len, 0.0, 1.0)
        self._append_segment_slice(path, chain.segments[edge_idx], start_t, end_t)
        return path

    @staticmethod
    def _path_strip_score(path: QPainterPath, x0: float, x1: float) -> float:
        polygons = path.toSubpathPolygons()
        if not polygons:
            return float("inf")
        x_low = min(x0, x1)
        x_high = max(x0, x1)
        margin = max(1.0, 0.2 * (x_high - x_low))
        lo = x_low - margin
        hi = x_high + margin
        score = 0.0
        for poly in polygons:
            for point in poly:
                x = float(point.x())
                if x < lo:
                    score += lo - x
                elif x > hi:
                    score += x - hi
        return score

    def _surface_chain_path_between_hits(
        self,
        chain: DirectionalSurfaceChain,
        s0: float,
        s1: float,
        x0: float,
        x1: float,
    ) -> QPainterPath:
        length = chain.total_length_nm
        if length <= 1e-9:
            return QPainterPath()
        if not chain.closed:
            start_s = min(s0, s1)
            end_s = max(s0, s1)
            return self._surface_chain_path_forward(chain, start_s, end_s)
        forward = (s1 - s0) % length
        backward = (s0 - s1) % length
        forward_path = self._surface_chain_path_forward(chain, s0, s0 + forward)
        backward_path = self._surface_chain_path_forward(chain, s1, s1 + backward)
        forward_score = GeometryTopologyEngine._path_strip_score(forward_path, x0, x1)
        backward_score = GeometryTopologyEngine._path_strip_score(backward_path, x0, x1)
        if abs(forward_score - backward_score) <= 1e-6:
            return forward_path if forward <= backward else backward_path
        return forward_path if forward_score < backward_score else backward_path

    def _offset_band_from_chain_span(
        self,
        chain: DirectionalSurfaceChain,
        s0: float,
        s1: float,
        ray_direction: Vec2,
        total_delta_nm: float,
        *,
        outward: bool,
    ) -> QPainterPath:
        del outward
        if total_delta_nm <= 1e-9 or s1 <= s0 + 1e-9 or chain.total_length_nm <= 1e-9:
            return QPainterPath()
        span_path = self._surface_chain_path_forward(chain, s0, s1)
        if span_path.isEmpty():
            return QPainterPath()
        sample_step_nm = max(1.0, min(self.arc_chord_nm * 0.35, 4.0))
        span_length = max(0.0, s1 - s0)
        sample_count = max(2, int(math.ceil(span_length / sample_step_nm)) + 1)
        incidence_total = 0.0
        for sample_index in range(sample_count):
            s = s0 + span_length * (sample_index / max(1, sample_count - 1))
            _point, _normal, edge_idx, edge_t = self._surface_chain_sample(chain, s)
            incidence_total += self._directional_incidence_on_segment(chain.segments[edge_idx], edge_t, ray_direction)
        avg_incidence = incidence_total / sample_count
        if avg_incidence <= 1e-4:
            return QPainterPath()
        stroker = QPainterPathStroker()
        stroker.setWidth(max(0.2, total_delta_nm * avg_incidence * 2.0))
        stroker.setCapStyle(Qt.PenCapStyle.SquareCap)
        stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return stroker.createStroke(span_path).simplified()

    @staticmethod
    def _segment_outward_normal(segment: Segment2D, t: float) -> Vec2:
        _point, tangent = segment.point_tangent(t)
        return Vec2(tangent.y, -tangent.x).normalized()

    @staticmethod
    def _directional_incidence_on_segment(segment: Segment2D, t: float, ray_direction: Vec2) -> float:
        _point, tangent = segment.point_tangent(t)
        tangent_n = tangent.normalized()
        ray_n = ray_direction.normalized()
        return clamp(GeometryTopologyEngine._cross(tangent_n, ray_n), 0.0, 1.0)

    def _segment_is_domain_boundary(self, segment: Segment2D, tol_nm: float = 1e-3) -> bool:
        if not isinstance(segment, LineSegment):
            return False
        return self._is_domain_boundary_edge(segment.start(), segment.end(), tol_nm=tol_nm)

    def _surface_sample_visible_to_source(
        self,
        occluder_chains: dict[str, DirectionalSurfaceChain],
        point: Vec2,
        normal: Vec2,
        ray_direction: Vec2,
        eps_nm: float = 0.6,
    ) -> bool:
        if normal.length() <= 1e-9:
            return False
        origin = point.add(normal.scaled(max(0.2, eps_nm)))
        source_direction = ray_direction.scaled(-1.0).normalized()
        x_min, _y_min, x_max, y_max = self.state.extent
        if source_direction.y <= 1e-9:
            return False
        travel_to_top = (y_max - origin.y) / source_direction.y
        if travel_to_top <= 1e-9:
            return False
        source_x = origin.x + source_direction.x * travel_to_top
        if source_x < x_min - 1e-6 or source_x > x_max + 1e-6:
            return False
        for other_chain_id, other_chain in occluder_chains.items():
            for other_segment_index, other_segment in enumerate(other_chain.segments):
                intersection = self._ray_surface_segment_intersection(origin, source_direction, other_segment)
                if intersection is None:
                    continue
                ray_t, _other_t = intersection
                if ray_t <= max(0.5, eps_nm * 2.0):
                    continue
                if ray_t < travel_to_top - max(0.2, eps_nm):
                    return False
        return True

    def _offset_band_from_segment_piece(
        self,
        segment: Segment2D,
        delta_nm: float,
        *,
        outward: bool,
    ) -> QPainterPath:
        if delta_nm <= 1e-9:
            return QPainterPath()
        segment_length = segment.length_nm()
        if segment_length <= 1e-9:
            return QPainterPath()
        sample_step_nm = max(1.0, min(self.arc_chord_nm * 0.4, 5.0))
        min_points = 3 if isinstance(segment, ArcSegment) else 2
        point_count = max(min_points, int(math.ceil(segment_length / sample_step_nm)) + 1)
        side_sign = 1.0 if outward else -1.0
        inner_points: list[Vec2] = []
        outer_points: list[Vec2] = []
        for idx in range(point_count):
            t = idx / max(1, point_count - 1)
            point, _tangent = segment.point_tangent(t)
            normal = self._segment_outward_normal(segment, t)
            offset_point = point.add(normal.scaled(delta_nm * side_sign))
            inner_points.append(point)
            outer_points.append(offset_point)
        path = QPainterPath()
        path.moveTo(inner_points[0].x, inner_points[0].y)
        for point in inner_points[1:]:
            path.lineTo(point.x, point.y)
        for point in reversed(outer_points):
            path.lineTo(point.x, point.y)
        path.closeSubpath()
        return path.simplified()

    def _directional_band_from_surface_chains(
        self,
        surface_chains: dict[str, DirectionalSurfaceChain],
        allowed_materials: set[str] | None,
        ray_direction: Vec2,
        total_delta_nm: float,
        *,
        outward: bool,
    ) -> QPainterPath:
        if total_delta_nm <= 1e-9:
            return QPainterPath()
        band = QPainterPath()
        occluder_chains = self._extract_full_outer_surface_chains()
        sample_step_nm = max(1.5, min(self.arc_chord_nm * 0.35, 4.0))
        for chain_id, chain in surface_chains.items():
            if allowed_materials is not None and chain.owner_material_id not in allowed_materials:
                continue
            if chain.total_length_nm <= 1e-9:
                continue
            cell_count = max(1, int(math.ceil(chain.total_length_nm / sample_step_nm)))
            visible_flags: list[bool] = []
            for cell_index in range(cell_count):
                s_mid = chain.total_length_nm * ((cell_index + 0.5) / cell_count)
                point, normal, segment_index, segment_t = self._surface_chain_sample(chain, s_mid)
                segment = chain.segments[segment_index]
                if self._segment_is_domain_boundary(segment):
                    visible_flags.append(False)
                    continue
                incidence = self._directional_incidence_on_segment(segment, segment_t, ray_direction)
                if incidence <= 1e-4:
                    visible_flags.append(False)
                    continue
                visible_flags.append(
                    self._surface_sample_visible_to_source(
                        occluder_chains=occluder_chains,
                        point=point,
                        normal=normal,
                        ray_direction=ray_direction,
                    )
                )
            cell_index = 0
            while cell_index < cell_count:
                if not visible_flags[cell_index]:
                    cell_index += 1
                    continue
                start_index = cell_index
                while cell_index + 1 < cell_count and visible_flags[cell_index + 1]:
                    cell_index += 1
                end_index = cell_index
                span_band = self._offset_band_from_chain_span(
                    chain=chain,
                    s0=chain.total_length_nm * (start_index / cell_count),
                    s1=chain.total_length_nm * ((end_index + 1) / cell_count),
                    ray_direction=ray_direction,
                    total_delta_nm=total_delta_nm,
                    outward=outward,
                )
                if not span_band.isEmpty():
                    band = band.united(span_band)
                cell_index += 1
        return band.simplified()

    def _segment_is_exposed_at(
        self,
        segment: Segment2D,
        t: float,
        owner_path: QPainterPath,
        union_path: QPainterPath,
        probe_nm: float,
    ) -> bool:
        point, _tangent = segment.point_tangent(t)
        normal = self._segment_outward_normal(segment, t)
        if normal.length() <= 1e-9:
            return False
        outside_point = point.add(normal.scaled(probe_nm))
        inside_point = point.sub(normal.scaled(probe_nm))
        if not owner_path.contains(inside_point.to_qpointf()):
            return False
        if union_path.contains(outside_point.to_qpointf()):
            return False
        return True

    def _segment_exposed_intervals(
        self,
        segment: Segment2D,
        owner_path: QPainterPath,
        union_path: QPainterPath,
        probe_nm: float,
    ) -> list[tuple[float, float]]:
        length_nm = segment.length_nm()
        if length_nm <= 1e-9:
            return []
        sample_step_nm = max(2.0, min(self.arc_chord_nm * 0.6, 8.0))
        sample_count = max(1, int(math.ceil(length_nm / sample_step_nm)))
        states = [
            self._segment_is_exposed_at(
                segment,
                (idx + 0.5) / sample_count,
                owner_path=owner_path,
                union_path=union_path,
                probe_nm=probe_nm,
            )
            for idx in range(sample_count)
        ]
        if all(states):
            return [(0.0, 1.0)]
        first_true = next((idx for idx, state in enumerate(states) if state), None)
        last_true = next((idx for idx in range(sample_count - 1, -1, -1) if states[idx]), None)
        if first_true is not None and last_true is not None:
            if all(states[idx] for idx in range(first_true, last_true + 1)):
                if first_true <= 1 and (sample_count - 1 - last_true) <= 1:
                    return [(0.0, 1.0)]
        intervals: list[tuple[float, float]] = []
        idx = 0
        while idx < sample_count:
            if not states[idx]:
                idx += 1
                continue
            start_idx = idx
            while idx + 1 < sample_count and states[idx + 1]:
                idx += 1
            end_idx = idx
            intervals.append((start_idx / sample_count, (end_idx + 1) / sample_count))
            idx += 1
        return intervals

    @staticmethod
    def _pieces_are_contiguous(
        left: ExposedSegmentPiece,
        right: ExposedSegmentPiece,
        segment_count: int,
        *,
        wrap: bool = False,
    ) -> bool:
        del segment_count
        if left.source_segment_index == right.source_segment_index:
            return abs(left.t1 - right.t0) <= 1e-6
        if wrap:
            return left.t1 >= 1.0 - 1e-6 and right.t0 <= 1e-6
        return (
            right.source_segment_index == left.source_segment_index + 1
            and left.t1 >= 1.0 - 1e-6
            and right.t0 <= 1e-6
        )

    @staticmethod
    def _build_surface_chain(
        chain_id: str,
        owner_material_id: str,
        segments: list[Segment2D],
        *,
        closed: bool,
    ) -> DirectionalSurfaceChain:
        cumulative = [0.0]
        total = 0.0
        for segment in segments:
            total += max(0.0, segment.length_nm())
            cumulative.append(total)
        return DirectionalSurfaceChain(
            chain_id=chain_id,
            owner_material_id=owner_material_id,
            segments=segments,
            cumulative_nm=cumulative,
            total_length_nm=total,
            closed=closed,
        )

    def _extract_directional_surface_chains(
        self,
        material_paths: dict[str, QPainterPath],
        probe_nm: float = 0.8,
    ) -> dict[str, DirectionalSurfaceChain]:
        union_path = path_union(list(material_paths.values())).simplified()
        chains: dict[str, DirectionalSurfaceChain] = {}
        for region in self.state.regions:
            owner_path = material_paths.get(region.material_id)
            if owner_path is None or owner_path.isEmpty():
                continue
            loop = ensure_ccw(region.outer_loop, max_chord_nm=self.arc_chord_nm)
            pieces: list[ExposedSegmentPiece] = []
            for segment_index, segment in enumerate(loop.segments):
                intervals = self._segment_exposed_intervals(
                    segment,
                    owner_path=owner_path,
                    union_path=union_path,
                    probe_nm=probe_nm,
                )
                for interval_index, (t0, t1) in enumerate(intervals):
                    piece = trim_segment(
                        segment,
                        t0,
                        t1,
                        seg_id=f"{loop.loop_id}_seg_{segment_index:03d}_{interval_index:03d}",
                    )
                    if piece is None or piece.length_nm() <= 1e-6:
                        continue
                    pieces.append(
                        ExposedSegmentPiece(
                            source_segment_index=segment_index,
                            t0=t0,
                            t1=t1,
                            segment=piece,
                        )
                    )
            if not pieces:
                continue
            groups: list[list[ExposedSegmentPiece]] = []
            current_group = [pieces[0]]
            for piece in pieces[1:]:
                if self._pieces_are_contiguous(current_group[-1], piece, len(loop.segments)):
                    current_group.append(piece)
                else:
                    groups.append(current_group)
                    current_group = [piece]
            groups.append(current_group)
            wrap_contiguous = (
                len(groups) > 1
                and self._pieces_are_contiguous(groups[-1][-1], groups[0][0], len(loop.segments), wrap=True)
                and groups[-1][-1].source_segment_index == len(loop.segments) - 1
                and groups[0][0].source_segment_index == 0
            )
            if wrap_contiguous:
                groups[0] = groups[-1] + groups[0]
                groups.pop()
            is_closed = (
                len(groups) == 1
                and groups[0][0].source_segment_index == 0
                and groups[0][0].t0 <= 1e-6
                and groups[0][-1].source_segment_index == len(loop.segments) - 1
                and groups[0][-1].t1 >= 1.0 - 1e-6
            )
            for chain_index, group in enumerate(groups):
                chain_segments = [piece.segment for piece in group]
                chain = self._build_surface_chain(
                    chain_id=f"{loop.loop_id}_chain_{chain_index:02d}",
                    owner_material_id=region.material_id,
                    segments=chain_segments,
                    closed=is_closed and chain_index == 0,
                )
                if chain.total_length_nm <= 1e-6:
                    continue
                chains[chain.chain_id] = chain
        return chains

    def _extract_full_outer_surface_chains(self) -> dict[str, DirectionalSurfaceChain]:
        chains: dict[str, DirectionalSurfaceChain] = {}
        for region in self.state.regions:
            loop = ensure_ccw(region.outer_loop, max_chord_nm=self.arc_chord_nm)
            chain = self._build_surface_chain(
                chain_id=loop.loop_id,
                owner_material_id=region.material_id,
                segments=list(loop.segments),
                closed=True,
            )
            if chain.total_length_nm <= 1e-6:
                continue
            chains[chain.chain_id] = chain
        return chains

    @staticmethod
    def _cross(a: Vec2, b: Vec2) -> float:
        return a.x * b.y - a.y * b.x

    @staticmethod
    def _ray_segment_intersection(
        origin: Vec2,
        direction: Vec2,
        seg_start: Vec2,
        seg_end: Vec2,
    ) -> tuple[float, float] | None:
        segment = seg_end.sub(seg_start)
        denom = GeometryTopologyEngine._cross(direction, segment)
        if abs(denom) <= 1e-10:
            return None
        offset = seg_start.sub(origin)
        ray_t = GeometryTopologyEngine._cross(offset, segment) / denom
        seg_u = GeometryTopologyEngine._cross(offset, direction) / denom
        if ray_t < 1e-8:
            return None
        if seg_u < -1e-8 or seg_u > 1.0 + 1e-8:
            return None
        return ray_t, clamp(seg_u, 0.0, 1.0)

    @staticmethod
    def _ray_arc_intersection(origin: Vec2, direction: Vec2, segment: ArcSegment) -> tuple[float, float] | None:
        offset = origin.sub(segment.center)
        a = direction.dot(direction)
        b = 2.0 * offset.dot(direction)
        c = offset.dot(offset) - segment.radius_nm * segment.radius_nm
        disc = b * b - 4.0 * a * c
        if disc < -1e-10:
            return None
        disc = max(0.0, disc)
        sqrt_disc = math.sqrt(disc)
        candidates = [(-b - sqrt_disc) / (2.0 * a), (-b + sqrt_disc) / (2.0 * a)]
        best: tuple[float, float] | None = None
        sweep_abs = abs(segment.sweep_deg)
        for ray_t in candidates:
            if ray_t < 1e-8:
                continue
            point = origin.add(direction.scaled(ray_t))
            theta_deg = math.degrees(math.atan2(point.y - segment.center.y, point.x - segment.center.x))
            if segment.sweep_deg >= 0.0:
                delta = (theta_deg - segment.start_deg) % 360.0
            else:
                delta = (segment.start_deg - theta_deg) % 360.0
            if delta < -1e-6 or delta > sweep_abs + 1e-6:
                continue
            local_t = 0.0 if sweep_abs <= 1e-9 else clamp(delta / sweep_abs, 0.0, 1.0)
            if best is None or ray_t < best[0]:
                best = (ray_t, local_t)
        return best

    @staticmethod
    def _ray_surface_segment_intersection(origin: Vec2, direction: Vec2, segment: Segment2D) -> tuple[float, float] | None:
        if isinstance(segment, LineSegment):
            return GeometryTopologyEngine._ray_segment_intersection(origin, direction, segment.p0, segment.p1)
        if isinstance(segment, ArcSegment):
            return GeometryTopologyEngine._ray_arc_intersection(origin, direction, segment)
        raise TypeError(f"Unsupported segment type: {type(segment).__name__}")

    def validate_loops(self, tangent_tolerance_deg: float = 8.0, closure_tolerance_nm: float = 1e-2) -> list[LoopDiagnostic]:
        diagnostics: list[LoopDiagnostic] = []
        for region in self.state.regions:
            loop = region.outer_loop
            warnings: list[str] = []
            line_count = sum(1 for seg in loop.segments if isinstance(seg, LineSegment))
            arc_count = sum(1 for seg in loop.segments if isinstance(seg, ArcSegment))
            if len(loop.segments) < 3:
                warnings.append("loop has fewer than 3 segments")
            for idx, current in enumerate(loop.segments):
                nxt = loop.segments[(idx + 1) % len(loop.segments)]
                end_point = current.end()
                next_start = nxt.start()
                gap = end_point.distance_to(next_start)
                if gap > closure_tolerance_nm:
                    warnings.append(f"segment gap at join {idx}->{idx + 1}: {gap:.3f} nm")
                _, tan_a = current.point_tangent(1.0)
                _, tan_b = nxt.point_tangent(0.0)
                dot = clamp(tan_a.normalized().dot(tan_b.normalized()), -1.0, 1.0)
                angle = math.degrees(math.acos(dot))
                if angle > tangent_tolerance_deg and (isinstance(current, ArcSegment) or isinstance(nxt, ArcSegment)):
                    warnings.append(f"non-tangential curve join {idx}->{idx + 1}: {angle:.1f} deg")
            diagnostics.append(
                LoopDiagnostic(
                    loop_id=loop.loop_id,
                    line_count=line_count,
                    arc_count=arc_count,
                    warnings=warnings,
                )
            )
        return diagnostics

    @staticmethod
    def _build_boundary_loop(loop_id: str, points: list[Vec2]) -> BoundaryLoop:
        cleaned = GeometryTopologyEngine._simplify_closed_points(points)
        cumulative = [0.0]
        total = 0.0
        count = len(cleaned)
        for idx in range(count):
            a = cleaned[idx]
            b = cleaned[(idx + 1) % count]
            total += a.distance_to(b)
            cumulative.append(total)
        return BoundaryLoop(loop_id=loop_id, points=cleaned, cumulative_nm=cumulative, total_length_nm=total)

    def _extract_exposed_boundary(
        self,
        material_paths: dict[str, QPainterPath],
        probe_nm: float = 0.8,
    ) -> tuple[list[ExposedEdge], dict[str, BoundaryLoop]]:
        union_path = path_union(list(material_paths.values())).simplified()
        exposed_edges: list[ExposedEdge] = []
        loops: dict[str, BoundaryLoop] = {}
        polygons = union_path.toSubpathPolygons()
        for poly_idx, polygon in enumerate(polygons):
            points = [Vec2.from_qpointf(point) for point in polygon]
            loop_id = f"loop_{poly_idx}"
            points = self._simplify_closed_points(points)
            if len(points) < 3:
                continue
            loop = self._build_boundary_loop(loop_id=loop_id, points=points)
            if loop.total_length_nm <= 1e-6:
                continue
            loops[loop_id] = loop
            for idx in range(len(points)):
                p = points[idx]
                q = points[(idx + 1) % len(points)]
                edge = q.sub(p)
                edge_len = edge.length()
                if edge_len <= 1e-4:
                    continue
                midpoint = Vec2(0.5 * (p.x + q.x), 0.5 * (p.y + q.y))
                normal_candidate = Vec2(edge.y / edge_len, -edge.x / edge_len)
                plus_point = midpoint.add(normal_candidate.scaled(probe_nm))
                minus_point = midpoint.sub(normal_candidate.scaled(probe_nm))
                plus_inside = union_path.contains(plus_point.to_qpointf())
                minus_inside = union_path.contains(minus_point.to_qpointf())
                if plus_inside and not minus_inside:
                    normal = normal_candidate.scaled(-1.0)
                    inside_point = plus_point
                    outside_point = minus_point
                elif minus_inside and not plus_inside:
                    normal = normal_candidate
                    inside_point = minus_point
                    outside_point = plus_point
                else:
                    continue
                owner_material_id: str | None = None
                for material_id, material_path in material_paths.items():
                    if material_path.contains(inside_point.to_qpointf()):
                        owner_material_id = material_id
                        break
                exposed_edges.append(
                    ExposedEdge(
                        start=p,
                        end=q,
                        normal_outward=normal,
                        owner_material_id=owner_material_id,
                        loop_id=loop_id,
                        edge_index=idx,
                        loop_pos_start_nm=loop.cumulative_nm[idx],
                        loop_pos_end_nm=loop.cumulative_nm[idx + 1],
                        loop_length_nm=loop.total_length_nm,
                    )
                )
        return exposed_edges, loops

    def extract_exposed_edges(self, material_paths: dict[str, QPainterPath], probe_nm: float = 0.8) -> list[ExposedEdge]:
        edges, _loops = self._extract_exposed_boundary(material_paths, probe_nm=probe_nm)
        return edges

    @staticmethod
    def _find_material_at_point(
        material_paths: dict[str, QPainterPath],
        point: Vec2,
        exclude_material: str | None = None,
    ) -> str | None:
        for material_id, path in material_paths.items():
            if exclude_material is not None and material_id == exclude_material:
                continue
            if path.contains(point.to_qpointf()):
                return material_id
        return None

    def extract_topology_edges(
        self,
        material_paths: dict[str, QPainterPath],
        probe_nm: float = 0.8,
    ) -> list[TopologyEdge]:
        raw_edges: list[TopologyEdge] = []
        for material_id, material_path in material_paths.items():
            polygons = material_path.toSubpathPolygons()
            for poly_idx, polygon in enumerate(polygons):
                points = [Vec2.from_qpointf(point) for point in polygon]
                points = self._simplify_closed_points(points)
                if len(points) < 3:
                    continue
                loop_id = f"{material_id}_loop_{poly_idx}"
                for edge_index in range(len(points)):
                    start = points[edge_index]
                    end = points[(edge_index + 1) % len(points)]
                    edge_vec = end.sub(start)
                    edge_len = edge_vec.length()
                    if edge_len <= 1e-4:
                        continue
                    normal_candidate = Vec2(edge_vec.y / edge_len, -edge_vec.x / edge_len)
                    midpoint = Vec2(0.5 * (start.x + end.x), 0.5 * (start.y + end.y))
                    plus_point = midpoint.add(normal_candidate.scaled(probe_nm))
                    minus_point = midpoint.sub(normal_candidate.scaled(probe_nm))
                    plus_inside = material_path.contains(plus_point.to_qpointf())
                    minus_inside = material_path.contains(minus_point.to_qpointf())
                    if plus_inside and not minus_inside:
                        normal = normal_candidate.scaled(-1.0)
                        outside_point = minus_point
                    elif minus_inside and not plus_inside:
                        normal = normal_candidate
                        outside_point = plus_point
                    else:
                        area = points_area_signed(points)
                        normal = normal_candidate if area >= 0.0 else normal_candidate.scaled(-1.0)
                        outside_point = midpoint.add(normal.scaled(probe_nm))
                    neighbor_material_id = self._find_material_at_point(
                        material_paths=material_paths,
                        point=outside_point,
                        exclude_material=material_id,
                    )
                    raw_edges.append(
                        TopologyEdge(
                            edge_id="",
                            start=start,
                            end=end,
                            normal_outward=normal,
                            primary_material_id=material_id,
                            secondary_material_id=neighbor_material_id,
                            supporting_material_ids=tuple(
                                sorted(
                                    {material_id}
                                    | ({neighbor_material_id} if neighbor_material_id is not None else set())
                                )
                            ),
                            is_shared=neighbor_material_id is not None,
                            source_loop_id=loop_id,
                            source_edge_index=edge_index,
                        )
                    )
        raw_edges.sort(key=lambda edge: (-edge.midpoint().y, edge.midpoint().x, edge.length_nm()))
        topology_edges: list[TopologyEdge] = []
        for edge_index, edge in enumerate(raw_edges):
            topology_edges.append(
                TopologyEdge(
                    edge_id=f"topo_{edge_index:05d}",
                    start=edge.start,
                    end=edge.end,
                    normal_outward=edge.normal_outward,
                    primary_material_id=edge.primary_material_id,
                    secondary_material_id=edge.secondary_material_id,
                    supporting_material_ids=edge.supporting_material_ids,
                    is_shared=edge.is_shared,
                    source_loop_id=edge.source_loop_id,
                    source_edge_index=edge.source_edge_index,
                )
            )
        return topology_edges

    def _is_domain_boundary_edge(self, start: Vec2, end: Vec2, tol_nm: float = 1e-3) -> bool:
        x_min, y_min, x_max, _y_max = self.state.extent
        on_left = abs(start.x - x_min) <= tol_nm and abs(end.x - x_min) <= tol_nm
        on_right = abs(start.x - x_max) <= tol_nm and abs(end.x - x_max) <= tol_nm
        on_bottom = abs(start.y - y_min) <= tol_nm and abs(end.y - y_min) <= tol_nm
        return on_left or on_right or on_bottom

    def deposit_blanket(
        self,
        material_paths: dict[str, QPainterPath],
        material_id: str,
        thickness_nm: float,
    ) -> dict[str, QPainterPath]:
        if thickness_nm <= 0.0:
            return dict(material_paths)
        result = dict(material_paths)
        union_path = path_union(list(material_paths.values()))
        bounds = union_path.boundingRect()
        x_min = self.state.extent[0]
        x_max = self.state.extent[2]
        y_surface = float(bounds.bottom())
        blanket = QPainterPath()
        blanket.addRect(x_min, y_surface, x_max - x_min, thickness_nm)
        previous = result.get(material_id, QPainterPath())
        result[material_id] = previous.united(blanket)
        return result

    def deposit_conformal(
        self,
        material_paths: dict[str, QPainterPath],
        material_id: str,
        rate_nm_s: float,
        time_s: float,
        steps_per_s: float,
    ) -> tuple[dict[str, QPainterPath], QPainterPath]:
        del steps_per_s
        result = dict(material_paths)
        total_delta_nm = self._total_delta_nm(rate_nm_s=rate_nm_s, time_s=time_s)
        if total_delta_nm <= 1e-9:
            return result, QPainterPath()
        occupied = path_union(list(result.values()))
        if occupied.isEmpty():
            return result, QPainterPath()
        exposed_edges = self.extract_exposed_edges(result)
        growth_edges = [
            edge
            for edge in exposed_edges
            if not self._is_domain_boundary_edge(edge.start, edge.end)
        ]
        if not growth_edges:
            return result, QPainterPath()
        boundary_path = edges_to_path(growth_edges)
        shell_band = self._band_from_marked_surface(boundary_path, total_delta_nm)
        grown_path = shell_band.subtracted(occupied).simplified()
        if grown_path.isEmpty():
            return result, QPainterPath()
        previous = result.get(material_id, QPainterPath())
        result[material_id] = previous.united(grown_path)
        return result, grown_path

    def etch_isotropic(
        self,
        material_paths: dict[str, QPainterPath],
        material_id: str,
        rate_nm_s: float,
        time_s: float,
        steps_per_s: float,
        top_only: bool = True,
    ) -> tuple[dict[str, QPainterPath], QPainterPath]:
        result = dict(material_paths)
        etched_total = QPainterPath()
        total_delta_nm = self._total_delta_nm(rate_nm_s=rate_nm_s, time_s=time_s)
        if total_delta_nm <= 1e-9:
            return result, etched_total
        top_limit = self.state.extent[1] + 0.42 * (self.state.extent[3] - self.state.extent[1])
        del steps_per_s
        if material_id not in result:
            return result, etched_total
        exposed_edges = self.extract_exposed_edges(result)
        target_edges: list[ExposedEdge] = []
        for edge in exposed_edges:
            if edge.owner_material_id != material_id:
                continue
            if top_only and edge.midpoint().y < top_limit:
                continue
            target_edges.append(edge)
        if not target_edges:
            return result, etched_total
        edge_path = edges_to_path(target_edges)
        band = self._band_from_marked_surface(edge_path, total_delta_nm)
        if band.isEmpty():
            return result, etched_total
        target = result[material_id]
        result[material_id] = target.subtracted(band)
        etched_total = etched_total.united(target.intersected(band))
        return result, etched_total.simplified()

    def etch_anisotropic(
        self,
        material_paths: dict[str, QPainterPath],
        material_id: str,
        rate_nm_s: float,
        time_s: float,
        steps_per_s: float,
        ray_count: int,
        ray_angle_deg: float,
    ) -> tuple[dict[str, QPainterPath], list[RayTrace], QPainterPath]:
        result = dict(material_paths)
        traces, surface_chains = self.scan_surface_rays(
            result,
            ray_count=ray_count,
            ray_angle_deg=ray_angle_deg,
            adaptive_passes=2,
        )
        total_delta_nm = self._total_delta_nm(rate_nm_s=rate_nm_s, time_s=time_s)
        if total_delta_nm <= 1e-9:
            return result, traces, QPainterPath()
        if material_id not in result:
            return result, traces, QPainterPath()
        ray_direction = self._ray_direction(ray_angle_deg)
        etch_band = self._directional_band_from_surface_chains(
            surface_chains=surface_chains,
            allowed_materials={material_id},
            ray_direction=ray_direction,
            total_delta_nm=total_delta_nm,
            outward=False,
        )
        if etch_band.isEmpty():
            return result, traces, QPainterPath()
        target = result[material_id]
        etched_part = target.intersected(etch_band)
        if etched_part.isEmpty():
            return result, traces, QPainterPath()
        result[material_id] = target.subtracted(etch_band)
        return result, traces, etched_part.simplified()

    def deposit_directional(
        self,
        material_paths: dict[str, QPainterPath],
        material_id: str,
        rate_nm_s: float,
        time_s: float,
        steps_per_s: float,
        ray_count: int,
        ray_angle_deg: float,
        allowed_surface_materials: set[str] | None = None,
    ) -> tuple[dict[str, QPainterPath], list[RayTrace], QPainterPath]:
        result = dict(material_paths)
        traces, surface_chains = self.scan_surface_rays(
            result,
            ray_count=ray_count,
            ray_angle_deg=ray_angle_deg,
            adaptive_passes=2,
        )
        total_delta_nm = self._total_delta_nm(rate_nm_s=rate_nm_s, time_s=time_s)
        if total_delta_nm <= 1e-9:
            return result, traces, QPainterPath()
        ray_direction = self._ray_direction(ray_angle_deg)
        deposition_band = self._directional_band_from_surface_chains(
            surface_chains=surface_chains,
            allowed_materials=allowed_surface_materials,
            ray_direction=ray_direction,
            total_delta_nm=total_delta_nm,
            outward=True,
        )
        if deposition_band.isEmpty():
            return result, traces, QPainterPath()
        occupied = path_union(list(result.values()))
        shell = deposition_band.subtracted(occupied).simplified()
        if shell.isEmpty():
            return result, traces, QPainterPath()
        previous = result.get(material_id, QPainterPath())
        result[material_id] = previous.united(shell)
        return result, traces, shell

    def etch_selective(
        self,
        material_paths: dict[str, QPainterPath],
        rate_scale_by_material: dict[str, float],
        base_rate_nm_s: float,
        time_s: float,
        steps_per_s: float,
    ) -> tuple[dict[str, QPainterPath], dict[str, QPainterPath]]:
        result = dict(material_paths)
        etched_by_material: dict[str, QPainterPath] = {}
        for material_id, multiplier in rate_scale_by_material.items():
            scaled_rate = max(0.0, base_rate_nm_s * max(0.0, multiplier))
            result, etched = self.etch_isotropic(
                result,
                material_id=material_id,
                rate_nm_s=scaled_rate,
                time_s=time_s,
                steps_per_s=steps_per_s,
                top_only=False,
            )
            etched_by_material[material_id] = etched
        return result, etched_by_material

    def lift_off(
        self,
        material_paths: dict[str, QPainterPath],
        mask_ref: str,
        deposited_materials: list[str],
    ) -> dict[str, QPainterPath]:
        result = dict(material_paths)
        mask = result.get(mask_ref)
        if mask is None:
            return result
        for material_id in deposited_materials:
            path = result.get(material_id)
            if path is None:
                continue
            result[material_id] = path.subtracted(mask)
        return result

    def scan_surface_rays(
        self,
        material_paths: dict[str, QPainterPath],
        ray_count: int,
        ray_angle_deg: float,
        step_nm: float = 1.8,
        adaptive_passes: int = 0,
    ) -> tuple[list[RayTrace], dict[str, DirectionalSurfaceChain]]:
        del step_nm
        surface_chains = self._extract_directional_surface_chains(material_paths)
        occluder_chains = self._extract_full_outer_surface_chains()
        direction = self._ray_direction(ray_angle_deg)
        x_min, y_min, x_max, y_max = self.state.extent
        samples = max(3, ray_count)
        entries: list[tuple[float, int]] = [
            (x_min + (x_max - x_min) * (idx / max(1, samples - 1)), 0)
            for idx in range(samples)
        ]
        max_distance = (y_max - y_min) * 2.0 + (x_max - x_min)
        min_spacing = (x_max - x_min) / max(1, samples - 1)
        min_spacing /= max(1.0, 2.0 ** max(0, adaptive_passes))

        def cast_for_entries(ray_entries: list[tuple[float, int]]) -> list[RayTrace]:
            traces_local: list[RayTrace] = []
            for x, refinement_pass in ray_entries:
                origin = Vec2(x, y_max + 40.0)
                hit = self._ray_cast_first_surface_hit(
                    origin=origin,
                    direction=direction,
                    max_distance_nm=max_distance,
                    surface_chains=occluder_chains,
                )
                if hit is None:
                    end = origin.add(direction.scaled(max_distance))
                else:
                    end = hit.point
                traces_local.append(
                    RayTrace(
                        origin=origin,
                        end=end,
                        hit=hit,
                        refinement_pass=refinement_pass,
                    )
                )
            return traces_local

        passes = max(0, int(adaptive_passes))
        for pass_idx in range(passes):
            traces = cast_for_entries(entries)
            inserts: list[tuple[float, int]] = []
            for left, right in zip(traces, traces[1:]):
                dx = right.origin.x - left.origin.x
                if dx <= min_spacing + 1e-9:
                    continue
                if not self._should_refine_ray_pair(left, right, dx):
                    continue
                inserts.append((0.5 * (left.origin.x + right.origin.x), pass_idx + 1))
            if not inserts:
                return traces, surface_chains
            merged_map: dict[float, int] = {}
            for x, level in entries + inserts:
                key = round(x, 6)
                previous = merged_map.get(key)
                if previous is None:
                    merged_map[key] = level
                else:
                    merged_map[key] = min(previous, level)
            merged = sorted((x, lvl) for x, lvl in merged_map.items())
            if len(merged) == len(entries):
                return traces, surface_chains
            entries = merged
        return cast_for_entries(entries), surface_chains

    def scan_rays(
        self,
        material_paths: dict[str, QPainterPath],
        ray_count: int,
        ray_angle_deg: float,
        step_nm: float = 1.8,
        adaptive_passes: int = 0,
    ) -> list[RayTrace]:
        traces, _surface_chains = self.scan_surface_rays(
            material_paths,
            ray_count=ray_count,
            ray_angle_deg=ray_angle_deg,
            step_nm=step_nm,
            adaptive_passes=adaptive_passes,
        )
        return traces

    @staticmethod
    def _should_refine_ray_pair(left: RayTrace, right: RayTrace, spacing_nm: float) -> bool:
        left_hit = left.hit
        right_hit = right.hit
        if left_hit is None and right_hit is None:
            return False
        if left_hit is None or right_hit is None:
            return True
        if left_hit.material_id != right_hit.material_id:
            return True
        if left_hit.loop_id != right_hit.loop_id:
            return True
        if left_hit.edge_index != right_hit.edge_index:
            return True
        if left_hit.normal_outward.dot(right_hit.normal_outward) < 0.92:
            return True
        if left_hit.point.distance_to(right_hit.point) > spacing_nm * 1.35:
            return True
        return False

    @staticmethod
    def _ray_direction(angle_deg: float) -> Vec2:
        theta = math.radians(angle_deg)
        return Vec2(math.sin(theta), -math.cos(theta)).normalized()

    def _ray_cast_first_surface_hit(
        self,
        origin: Vec2,
        direction: Vec2,
        max_distance_nm: float,
        surface_chains: dict[str, DirectionalSurfaceChain],
    ) -> RayHit | None:
        if not surface_chains:
            return None
        best_hit: RayHit | None = None
        best_distance = max_distance_nm + 1.0
        for chain in surface_chains.values():
            for edge_index, segment in enumerate(chain.segments):
                if self._segment_is_domain_boundary(segment):
                    continue
                intersection = self._ray_surface_segment_intersection(origin, direction, segment)
                if intersection is None:
                    continue
                ray_t, edge_t = intersection
                if ray_t < 0.0 or ray_t > max_distance_nm:
                    continue
                if ray_t >= best_distance:
                    continue
                hit_point, _tangent = segment.point_tangent(edge_t)
                normal = self._segment_outward_normal(segment, edge_t)
                if self._directional_incidence_on_segment(segment, edge_t, direction) <= 1e-4:
                    continue
                loop_position = chain.cumulative_nm[edge_index] + edge_t * (
                    chain.cumulative_nm[edge_index + 1] - chain.cumulative_nm[edge_index]
                )
                best_distance = ray_t
                best_hit = RayHit(
                    point=hit_point,
                    material_id=chain.owner_material_id,
                    normal_outward=normal,
                    distance_nm=ray_t,
                    loop_id=chain.chain_id,
                    edge_index=edge_index,
                    edge_t=edge_t,
                    loop_position_nm=loop_position,
                )
        if best_hit is not None:
            return best_hit
        return None


def build_t_grating_loop(
    loop_id: str,
    center_x: float,
    base_y: float,
    stem_width_nm: float,
    stem_height_nm: float,
    cap_width_nm: float,
    cap_height_nm: float,
    cap_corner_radius_nm: float,
) -> InterfaceLoop:
    stem_left = center_x - stem_width_nm * 0.5
    stem_right = center_x + stem_width_nm * 0.5
    cap_left = center_x - cap_width_nm * 0.5
    cap_right = center_x + cap_width_nm * 0.5
    stem_top = base_y + stem_height_nm
    cap_top = stem_top + cap_height_nm
    radius = clamp(cap_corner_radius_nm, 0.0, min(cap_height_nm, cap_width_nm * 0.45))
    segments: list[Segment2D] = [
        line_from_points("t_base", stem_left, base_y, stem_right, base_y),
        line_from_points("t_stem_rise", stem_right, base_y, stem_right, stem_top),
        line_from_points("t_cap_out_r", stem_right, stem_top, cap_right, stem_top),
    ]
    if radius > EPSILON:
        segments.extend(
            [
                line_from_points("t_cap_r_wall", cap_right, stem_top, cap_right, cap_top - radius),
                ArcSegment(
                    seg_id="t_cap_r_arc",
                    center=Vec2(cap_right - radius, cap_top - radius),
                    radius_nm=radius,
                    start_deg=0.0,
                    sweep_deg=90.0,
                ),
                line_from_points("t_cap_top", cap_right - radius, cap_top, cap_left + radius, cap_top),
                ArcSegment(
                    seg_id="t_cap_l_arc",
                    center=Vec2(cap_left + radius, cap_top - radius),
                    radius_nm=radius,
                    start_deg=90.0,
                    sweep_deg=90.0,
                ),
                line_from_points("t_cap_l_wall", cap_left, cap_top - radius, cap_left, stem_top),
            ]
        )
    else:
        segments.extend(
            [
                line_from_points("t_cap_r_wall", cap_right, stem_top, cap_right, cap_top),
                line_from_points("t_cap_top", cap_right, cap_top, cap_left, cap_top),
                line_from_points("t_cap_l_wall", cap_left, cap_top, cap_left, stem_top),
            ]
        )
    segments.extend(
        [
            line_from_points("t_cap_out_l", cap_left, stem_top, stem_left, stem_top),
            line_from_points("t_stem_drop", stem_left, stem_top, stem_left, base_y),
        ]
    )
    return InterfaceLoop(loop_id=loop_id, segments=segments)


def build_substrate_loop(
    width_nm: float,
    depth_nm: float,
    trench_depth_nm: float,
    trench_radius_nm: float,
    trench_left_nm: float,
    trench_right_nm: float,
) -> InterfaceLoop:
    top_segments_lr: list[Segment2D] = []
    cursor_x = 0.0
    left = clamp(trench_left_nm, 0.0, width_nm)
    right = clamp(trench_right_nm, left + 1.0, width_nm)
    depth = max(0.0, trench_depth_nm)
    radius = clamp(trench_radius_nm, 0.0, min(depth, (right - left) * 0.49))
    if left > cursor_x + EPSILON:
        top_segments_lr.append(line_from_points("s_top_left", cursor_x, 0.0, left, 0.0))
    if depth > EPSILON:
        if radius > EPSILON:
            top_segments_lr.extend(
                [
                    line_from_points("s_trench_drop_l", left, 0.0, left, -depth + radius),
                    ArcSegment(
                        seg_id="s_trench_fillet_l",
                        center=Vec2(left + radius, -depth + radius),
                        radius_nm=radius,
                        start_deg=180.0,
                        sweep_deg=90.0,
                    ),
                    line_from_points("s_trench_floor", left + radius, -depth, right - radius, -depth),
                    ArcSegment(
                        seg_id="s_trench_fillet_r",
                        center=Vec2(right - radius, -depth + radius),
                        radius_nm=radius,
                        start_deg=270.0,
                        sweep_deg=90.0,
                    ),
                    line_from_points("s_trench_rise_r", right, -depth + radius, right, 0.0),
                ]
            )
        else:
            top_segments_lr.extend(
                [
                    line_from_points("s_trench_drop_l", left, 0.0, left, -depth),
                    line_from_points("s_trench_floor", left, -depth, right, -depth),
                    line_from_points("s_trench_rise_r", right, -depth, right, 0.0),
                ]
            )
    cursor_x = right
    if cursor_x < width_nm - EPSILON:
        top_segments_lr.append(line_from_points("s_top_right", cursor_x, 0.0, width_nm, 0.0))
    segments: list[Segment2D] = [
        line_from_points("s_bottom", 0.0, -depth_nm, width_nm, -depth_nm),
        line_from_points("s_right_wall", width_nm, -depth_nm, width_nm, 0.0),
    ]
    for segment in reversed(top_segments_lr):
        segments.append(segment.reversed())
    segments.append(line_from_points("s_left_wall", 0.0, 0.0, 0.0, -depth_nm))
    return InterfaceLoop(loop_id="substrate_outer", segments=segments)


def build_base_state(
    *,
    cap_corner_radius_nm: float,
    trench_depth_nm: float,
    trench_radius_nm: float,
) -> CrossSectionState:
    materials = {
        "substrate": MaterialDef(
            material_id="substrate",
            name="Silicon Substrate",
            fill_hex="#8D6E63",
            stroke_hex="#5D4037",
            properties={"class": "semiconductor"},
        ),
        "core": MaterialDef(
            material_id="core",
            name="Patterned Core",
            fill_hex="#86C5DA",
            stroke_hex="#3A7895",
            properties={"class": "dielectric"},
        ),
        "metal": MaterialDef(
            material_id="metal",
            name="Conformal Metal",
            fill_hex="#C8B273",
            stroke_hex="#8A7640",
            properties={"class": "metal"},
        ),
    }
    process_models = {
        "ion_beam": ProcessInteractionModel(
            process_id="ion_beam",
            name="Ion Beam Etch",
            rate_nm_s_by_material={
                "substrate": 7.0 / 60.0,
                "core": 33.0 / 60.0,
                "metal": 15.0 / 60.0,
            },
            notes="Preview model only. Rates are placeholders for UI testing.",
        ),
        "wet_etch": ProcessInteractionModel(
            process_id="wet_etch",
            name="Wet Selective Etch",
            rate_nm_s_by_material={
                "substrate": 16.0 / 60.0,
                "core": 42.0 / 60.0,
                "metal": 1.5 / 60.0,
            },
            notes="Preview model only. Selectivity handling is simplified.",
        ),
    }
    substrate_loop = build_substrate_loop(
        width_nm=1200.0,
        depth_nm=260.0,
        trench_depth_nm=trench_depth_nm,
        trench_radius_nm=trench_radius_nm,
        trench_left_nm=520.0,
        trench_right_nm=640.0,
    )
    t_left = build_t_grating_loop(
        loop_id="grating_left",
        center_x=360.0,
        base_y=0.0,
        stem_width_nm=88.0,
        stem_height_nm=122.0,
        cap_width_nm=188.0,
        cap_height_nm=68.0,
        cap_corner_radius_nm=cap_corner_radius_nm,
    )
    t_right = build_t_grating_loop(
        loop_id="grating_right",
        center_x=760.0,
        base_y=0.0,
        stem_width_nm=88.0,
        stem_height_nm=122.0,
        cap_width_nm=188.0,
        cap_height_nm=68.0,
        cap_corner_radius_nm=cap_corner_radius_nm,
    )
    return CrossSectionState(
        schema_version="prototype.curve_loop.v1",
        extent=(0.0, -260.0, 1200.0, 280.0),
        materials=materials,
        process_models=process_models,
        active_process_id="ion_beam",
        regions=[
            Region2D(region_id="substrate_region", material_id="substrate", outer_loop=substrate_loop),
            Region2D(region_id="grating_region_left", material_id="core", outer_loop=t_left),
            Region2D(region_id="grating_region_right", material_id="core", outer_loop=t_right),
        ],
        operation_log=["base: substrate + two-period T grating + rounded trench overetch"],
    )


class PrototypeModel:
    MODE_CONFORMAL = "Conformal Growth"
    MODE_ISOTROPIC = "Isotropic Undercut"
    MODE_DIRECTIONAL_GROWTH = "Directional Growth"
    MODE_DIRECTIONAL_ETCH = "Directional Etch"
    MODE_COMBINED = "Combined Stress Test"
    MODE_DEBUG = "Topology Diagnostics"

    MODE_OPTIONS = [
        MODE_CONFORMAL,
        MODE_ISOTROPIC,
        MODE_DIRECTIONAL_GROWTH,
        MODE_DIRECTIONAL_ETCH,
        MODE_COMBINED,
        MODE_DEBUG,
    ]

    def build_scene(self, params: PrototypeParams) -> SceneSnapshot:
        state = build_base_state(
            cap_corner_radius_nm=params.cap_corner_radius_nm,
            trench_depth_nm=params.trench_depth_nm,
            trench_radius_nm=params.trench_radius_nm,
        )
        engine = GeometryTopologyEngine(state, arc_chord_nm=params.arc_chord_nm)
        loop_diagnostics = engine.validate_loops()
        material_paths = engine.material_paths_from_regions()
        rays: list[RayTrace] = []
        shadow_mask = QPainterPath()
        all_material_ids = list(state.materials.keys())
        process_model = state.process_models[state.active_process_id]
        rates_nm_s = {
            material_id: float(
                params.rate_nm_s_by_material.get(
                    material_id,
                    process_model.rate_nm_s_by_material.get(material_id, 0.2),
                )
            )
            for material_id in all_material_ids
        }
        enabled_materials = {
            material_id
            for material_id in all_material_ids
            if params.etch_enabled_materials.get(material_id, material_id in {"substrate", "core"})
        }
        if params.mode_label == self.MODE_ISOTROPIC:
            for material_id in all_material_ids:
                if material_id not in enabled_materials:
                    continue
                material_paths, _ = engine.etch_isotropic(
                    material_paths,
                    material_id=material_id,
                    rate_nm_s=max(0.0, rates_nm_s[material_id]),
                    time_s=params.process_time_s,
                    steps_per_s=params.steps_per_s,
                    top_only=True,
                )
        elif params.mode_label == self.MODE_CONFORMAL:
            material_paths, _ = engine.deposit_conformal(
                material_paths,
                material_id=params.conformal_deposition_material_id,
                rate_nm_s=max(0.0, rates_nm_s.get(params.conformal_deposition_material_id, 0.2)),
                time_s=params.process_time_s,
                steps_per_s=params.steps_per_s,
            )
        elif params.mode_label == self.MODE_DIRECTIONAL_GROWTH:
            allowed_surface_materials = enabled_materials if enabled_materials else None
            material_paths, rays, shadow_mask = engine.deposit_directional(
                material_paths,
                material_id=params.directional_deposition_material_id,
                rate_nm_s=max(0.0, rates_nm_s.get(params.directional_deposition_material_id, 0.2)),
                time_s=params.process_time_s,
                steps_per_s=params.steps_per_s,
                ray_count=params.ray_count,
                ray_angle_deg=params.ray_angle_deg,
                allowed_surface_materials=allowed_surface_materials,
            )
        elif params.mode_label == self.MODE_DIRECTIONAL_ETCH:
            etch_mask_total = QPainterPath()
            for material_id in all_material_ids:
                if material_id not in enabled_materials:
                    continue
                material_paths, rays, etch_mask = engine.etch_anisotropic(
                    material_paths,
                    material_id=material_id,
                    rate_nm_s=max(0.0, rates_nm_s[material_id]),
                    time_s=params.process_time_s,
                    steps_per_s=params.steps_per_s,
                    ray_count=params.ray_count,
                    ray_angle_deg=params.ray_angle_deg,
                )
                etch_mask_total = etch_mask_total.united(etch_mask)
            shadow_mask = etch_mask_total.simplified()
        elif params.mode_label == self.MODE_COMBINED:
            for material_id in all_material_ids:
                if material_id not in enabled_materials:
                    continue
                material_paths, _ = engine.etch_isotropic(
                    material_paths,
                    material_id=material_id,
                    rate_nm_s=max(0.0, rates_nm_s[material_id]),
                    time_s=params.process_time_s,
                    steps_per_s=params.steps_per_s,
                    top_only=True,
                )
            for material_id in all_material_ids:
                if material_id not in enabled_materials:
                    continue
                material_paths, rays, etch_mask = engine.etch_anisotropic(
                    material_paths,
                    material_id=material_id,
                    rate_nm_s=max(0.0, rates_nm_s[material_id]),
                    time_s=params.process_time_s,
                    steps_per_s=params.steps_per_s,
                    ray_count=params.ray_count,
                    ray_angle_deg=params.ray_angle_deg,
                )
                shadow_mask = shadow_mask.united(etch_mask)
            material_paths, _ = engine.deposit_conformal(
                material_paths,
                material_id=params.conformal_deposition_material_id,
                rate_nm_s=max(0.0, rates_nm_s.get(params.conformal_deposition_material_id, 0.2)),
                time_s=params.process_time_s,
                steps_per_s=params.steps_per_s,
            )
        if params.show_rays and not rays:
            adaptive = 5 if params.mode_label in {self.MODE_DIRECTIONAL_GROWTH, self.MODE_DIRECTIONAL_ETCH, self.MODE_COMBINED, self.MODE_DEBUG} else 0
            rays = engine.scan_rays(
                material_paths,
                ray_count=params.ray_count,
                ray_angle_deg=params.ray_angle_deg,
                adaptive_passes=adaptive,
            )
        exposed_edges, boundary_loops = engine._extract_exposed_boundary(material_paths)
        topology_edges = engine.extract_topology_edges(material_paths)
        if params.show_shadow and rays and shadow_mask.isEmpty():
            shadow_mask = build_shadow_mask(rays, state.extent)
        line_count = sum(diagnostic.line_count for diagnostic in loop_diagnostics)
        arc_count = sum(diagnostic.arc_count for diagnostic in loop_diagnostics)
        warning_count = sum(len(diagnostic.warnings) for diagnostic in loop_diagnostics)
        shared_edge_count = sum(1 for edge in topology_edges if edge.is_shared)
        exposed_topology_count = len(topology_edges) - shared_edge_count
        hit_count = sum(1 for ray in rays if ray.hit is not None)
        open_count = len(rays) - hit_count
        rate_summary = ", ".join(
            f"{material_id}:{rate:.3f}"
            for material_id, rate in rates_nm_s.items()
        )
        info_lines = [
            f"schema: {state.schema_version}",
            f"mode: {params.mode_label}",
            f"time/steps: {params.process_time_s:.2f}s @ {params.steps_per_s:.2f}Hz",
            f"loop segments line/arc: {line_count}/{arc_count}",
            f"loop warnings: {warning_count}",
            f"exposed edges: {len(exposed_edges)}",
            f"topology edges shared/exposed: {shared_edge_count}/{exposed_topology_count}",
            f"ray hits/open: {hit_count}/{open_count}" if rays else "ray hits/open: n/a",
            f"active process: {process_model.name}",
            f"rates nm/s: {rate_summary}",
        ]
        if params.mode_label == self.MODE_DEBUG:
            info_lines.append(
                "diagnostics mode: no process mutation, only topology checks, boundary extraction, and optional rays."
            )
        return SceneSnapshot(
            extent=state.extent,
            material_paths=material_paths,
            material_order=["substrate", "core", "metal"],
            exposed_edges=exposed_edges,
            topology_edges=topology_edges,
            boundary_loops=boundary_loops,
            rays=rays,
            shadow_mask=shadow_mask,
            loop_diagnostics=loop_diagnostics,
            info_lines=info_lines,
        )


def build_shadow_mask(rays: list[RayTrace], extent: tuple[float, float, float, float]) -> QPainterPath:
    x_min, y_min, x_max, _ = extent
    if not rays:
        return QPainterPath()
    mask = QPainterPath()
    spacing = (x_max - x_min) / max(1, len(rays) - 1)
    for ray in rays:
        if ray.hit is None:
            continue
        strip = QPainterPath()
        strip.addRect(ray.end.x - spacing * 0.5, y_min, spacing, ray.end.y - y_min)
        mask = mask.united(strip)
    return mask


class SliderRow(QWidget):
    def __init__(self, title: str, minimum: int, maximum: int, value: int) -> None:
        super().__init__()
        self.title_label = QLabel(title)
        self.value_label = QLabel("")
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setTracking(False)
        self.slider.setMinimum(minimum)
        self.slider.setMaximum(maximum)
        self.slider.setValue(value)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self.title_label)
        header.addStretch(1)
        header.addWidget(self.value_label)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(3)
        root.addLayout(header)
        root.addWidget(self.slider)
        self.setObjectName("SliderRow")
        self.title_label.setObjectName("SliderTitle")
        self.value_label.setObjectName("SliderValue")
        self.slider.valueChanged.connect(self._refresh_value)
        self._refresh_value(self.slider.value())

    def _refresh_value(self, value: int) -> None:
        self.value_label.setText(str(value))


class MaterialRow(QWidget):
    def __init__(self, material_id: str, label: str, default_rate: float, enabled: bool) -> None:
        super().__init__()
        self.material_id = material_id
        self.checkbox = QCheckBox(label)
        self.checkbox.setChecked(enabled)
        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setDecimals(3)
        self.rate_spin.setRange(0.0, 50.0)
        self.rate_spin.setSingleStep(0.01)
        self.rate_spin.setValue(default_rate)
        self.rate_spin.setSuffix(" nm/s")
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        root.addWidget(self.checkbox, 1)
        root.addWidget(self.rate_spin, 0)
        self.setObjectName("MaterialRow")

    def set_rate_visible(self, visible: bool) -> None:
        self.rate_spin.setVisible(visible)

    def set_checkbox_visible(self, visible: bool) -> None:
        self.checkbox.setVisible(visible)

class CrossSectionCanvas(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.scene: SceneSnapshot | None = None
        self.material_palette: dict[str, tuple[QColor, QColor]] = {}
        self.show_interfaces = True
        self.show_normals = False
        self.show_rays = False
        self.show_shadow = False
        self.show_grid = True
        self.inspect_mode = False
        self.selected_edge_key: str | None = None
        self._last_pick_candidates: tuple[str, ...] = ()
        self.on_interface_selected = None
        self._view_scale = 1.0
        self._view_translate_x = 0.0
        self._view_translate_y = 0.0
        self._fit_scale = 1.0
        self._fit_translate_x = 0.0
        self._fit_translate_y = 0.0
        self._zoom = 1.0
        self._pan_world = Vec2(0.0, 0.0)
        self._panning = False
        self._pan_last_pos: QPointF | None = None
        self.setMinimumSize(760, 520)
        self.setObjectName("Canvas")

    def set_scene(
        self,
        scene: SceneSnapshot,
        material_palette: dict[str, tuple[QColor, QColor]],
        show_interfaces: bool,
        show_normals: bool,
        show_rays: bool,
        show_shadow: bool,
        show_grid: bool,
        inspect_mode: bool,
    ) -> None:
        self.scene = scene
        self.material_palette = material_palette
        self.show_interfaces = show_interfaces
        self.show_normals = show_normals
        self.show_rays = show_rays
        self.show_shadow = show_shadow
        self.show_grid = show_grid
        self.inspect_mode = inspect_mode
        if self.selected_edge_key is not None:
            found = any(edge.edge_id == self.selected_edge_key for edge in scene.topology_edges)
            if not found:
                self.selected_edge_key = None
                self._last_pick_candidates = ()
                if callable(self.on_interface_selected):
                    self.on_interface_selected(None)
        self.update()

    def reset_view(self) -> None:
        self._zoom = 1.0
        self._pan_world = Vec2(0.0, 0.0)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, on=True)
        gradient = QLinearGradient(0.0, 0.0, 0.0, float(self.height()))
        gradient.setColorAt(0.0, QColor("#132331"))
        gradient.setColorAt(1.0, QColor("#0F1A24"))
        painter.fillRect(self.rect(), gradient)
        if self.scene is None:
            painter.end()
            return
        content_rect = self.rect().adjusted(22, 22, -22, -22)
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 14))
        painter.drawRoundedRect(content_rect, 18, 18)
        painter.restore()
        x_min, y_min, x_max, y_max = self.scene.extent
        width = max(1.0, x_max - x_min)
        height = max(1.0, y_max - y_min)
        view_rect = content_rect.adjusted(20, 20, -20, -20)
        self._fit_scale = min(view_rect.width() / width, view_rect.height() / height)
        self._fit_translate_x = view_rect.left() + 0.5 * (view_rect.width() - width * self._fit_scale) - x_min * self._fit_scale
        self._fit_translate_y = view_rect.top() + 0.5 * (view_rect.height() - height * self._fit_scale) + y_max * self._fit_scale
        self._view_scale = self._fit_scale * self._zoom
        self._view_translate_x = self._fit_translate_x + self._pan_world.x * self._view_scale
        self._view_translate_y = self._fit_translate_y + self._pan_world.y * self._view_scale
        painter.save()
        painter.translate(self._view_translate_x, self._view_translate_y)
        painter.scale(self._view_scale, -self._view_scale)
        if self.show_grid:
            self._draw_grid(painter, x_min, y_min, x_max, y_max)
        if not self.inspect_mode:
            for material_id in self.scene.material_order:
                path = self.scene.material_paths.get(material_id)
                if path is None or path.isEmpty():
                    continue
                fill, stroke = self.material_palette.get(material_id, (QColor("#BDBDBD"), QColor("#616161")))
                painter.setPen(QPen(stroke, 0.0))
                painter.setBrush(fill)
                painter.drawPath(path)
            if self.show_shadow and not self.scene.shadow_mask.isEmpty():
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(250, 85, 40, 70))
                painter.drawPath(self.scene.shadow_mask)
        if self.inspect_mode:
            selected_edge = self._selected_topology_edge()
            if selected_edge is not None:
                self._draw_selected_support_regions(painter, selected_edge)
            shared_pen = QPen(QColor("#FFC857"), 0.0)
            shared_pen.setCosmetic(True)
            exposed_pen = QPen(QColor("#64D6FF"), 0.0)
            exposed_pen.setCosmetic(True)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for edge in self.scene.topology_edges:
                painter.setPen(shared_pen if edge.is_shared else exposed_pen)
                painter.drawLine(edge.start.to_qpointf(), edge.end.to_qpointf())
        elif self.show_interfaces:
            edge_pen = QPen(QColor("#64D6FF"), 0.0)
            edge_pen.setCosmetic(True)
            painter.setPen(edge_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for edge in self.scene.exposed_edges:
                painter.drawLine(edge.start.to_qpointf(), edge.end.to_qpointf())
        if self.inspect_mode and self.selected_edge_key is not None:
            selected_pen = QPen(QColor("#FFEA00"), 0.0)
            selected_pen.setCosmetic(True)
            selected_pen.setWidthF(2.0)
            painter.setPen(selected_pen)
            selected_edge = self._selected_topology_edge()
            if selected_edge is not None:
                painter.drawLine(selected_edge.start.to_qpointf(), selected_edge.end.to_qpointf())
                mid = selected_edge.midpoint()
                tip = mid.add(selected_edge.normal_outward.scaled(16.0))
                painter.drawLine(mid.to_qpointf(), tip.to_qpointf())
        if self.show_normals and not self.inspect_mode:
            normal_pen = QPen(QColor("#FFE082"), 0.0)
            normal_pen.setCosmetic(True)
            painter.setPen(normal_pen)
            for idx, edge in enumerate(self.scene.exposed_edges):
                if idx % 8 != 0:
                    continue
                mid = edge.midpoint()
                tip = mid.add(edge.normal_outward.scaled(12.0))
                painter.drawLine(mid.to_qpointf(), tip.to_qpointf())
        if self.show_rays and not self.inspect_mode:
            max_pass = 0
            for trace in self.scene.rays:
                max_pass = max(max_pass, trace.refinement_pass)
            bright_red = QColor("#FF7A7A")
            dark_red = QColor("#7A0000")
            for trace in self.scene.rays:
                t = 0.0 if max_pass <= 0 else clamp(trace.refinement_pass / max_pass, 0.0, 1.0)
                ray_color = QColor(
                    int(bright_red.red() + (dark_red.red() - bright_red.red()) * t),
                    int(bright_red.green() + (dark_red.green() - bright_red.green()) * t),
                    int(bright_red.blue() + (dark_red.blue() - bright_red.blue()) * t),
                    220 if trace.hit is not None else 170,
                )
                ray_pen = QPen(ray_color, 0.0)
                ray_pen.setCosmetic(True)
                painter.setPen(ray_pen)
                painter.drawLine(trace.origin.to_qpointf(), trace.end.to_qpointf())
                if trace.hit is not None:
                    hit_pen = QPen(QColor("#FFF176"), 0.0)
                    hit_pen.setCosmetic(True)
                    painter.setPen(hit_pen)
                    hit_tip = trace.hit.point.add(trace.hit.normal_outward.scaled(10.0))
                    painter.drawLine(trace.hit.point.to_qpointf(), hit_tip.to_qpointf())
        painter.restore()
        painter.end()

    def wheelEvent(self, event) -> None:  # noqa: N802
        if self.scene is None:
            return
        delta = event.angleDelta().y()
        if delta == 0:
            return
        before = self._screen_to_world(event.position())
        factor = 1.15 ** (delta / 120.0)
        self._zoom = clamp(self._zoom * factor, 0.25, 20.0)
        after = self._screen_to_world(event.position())
        self._pan_world = self._pan_world.add(before.sub(after))
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            self._panning = True
            self._pan_last_pos = event.position()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self.inspect_mode:
            self._select_interface_at(event.position())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._panning and self._pan_last_pos is not None:
            delta = event.position() - self._pan_last_pos
            if self._view_scale > 1e-8:
                self._pan_world = self._pan_world.add(
                    Vec2(float(delta.x()) / self._view_scale, float(delta.y()) / self._view_scale)
                )
            self._pan_last_pos = event.position()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            self._panning = False
            self._pan_last_pos = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            self.reset_view()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _screen_to_world(self, position: QPointF) -> Vec2:
        if self._view_scale <= 1e-8:
            return Vec2(0.0, 0.0)
        x = (float(position.x()) - self._view_translate_x) / self._view_scale
        y = (self._view_translate_y - float(position.y())) / self._view_scale
        return Vec2(x, y)

    @staticmethod
    def _point_segment_distance(point: Vec2, start: Vec2, end: Vec2) -> tuple[float, float]:
        segment = end.sub(start)
        length2 = segment.dot(segment)
        if length2 <= EPSILON:
            return point.distance_to(start), 0.0
        t = clamp(point.sub(start).dot(segment) / length2, 0.0, 1.0)
        proj = start.add(segment.scaled(t))
        return point.distance_to(proj), t

    def _select_interface_at(self, position: QPointF) -> None:
        if self.scene is None:
            return
        world_point = self._screen_to_world(position)
        tolerance_nm = 8.0 / max(self._view_scale, 1e-8)
        best_edge: TopologyEdge | None = None
        best_distance = float("inf")
        for edge in self.scene.topology_edges:
            distance, _t = self._point_segment_distance(world_point, edge.start, edge.end)
            if distance < best_distance:
                best_distance = distance
                best_edge = edge
        if best_edge is None or best_distance > tolerance_nm:
            self.selected_edge_key = None
            self._last_pick_candidates = ()
            if callable(self.on_interface_selected):
                self.on_interface_selected(None)
            self.update()
            return
        close_candidates: list[tuple[float, TopologyEdge]] = []
        for edge in self.scene.topology_edges:
            distance, _t = self._point_segment_distance(world_point, edge.start, edge.end)
            if distance <= tolerance_nm:
                close_candidates.append((distance, edge))
        close_candidates.sort(key=lambda item: item[0])
        candidate_ids = tuple(edge.edge_id for _dist, edge in close_candidates)
        if not candidate_ids:
            candidate_ids = (best_edge.edge_id,)
            close_candidates = [(best_distance, best_edge)]
        if candidate_ids == self._last_pick_candidates and self.selected_edge_key in candidate_ids:
            current_index = candidate_ids.index(self.selected_edge_key)
            next_index = (current_index + 1) % len(candidate_ids)
            best_edge = close_candidates[next_index][1]
        else:
            best_edge = close_candidates[0][1]
        self.selected_edge_key = best_edge.edge_id
        self._last_pick_candidates = candidate_ids
        if callable(self.on_interface_selected):
            self.on_interface_selected(best_edge)
        self.update()

    def _selected_topology_edge(self) -> TopologyEdge | None:
        if self.scene is None or self.selected_edge_key is None:
            return None
        for edge in self.scene.topology_edges:
            if edge.edge_id == self.selected_edge_key:
                return edge
        return None

    def _draw_selected_support_regions(self, painter: QPainter, selected_edge: TopologyEdge) -> None:
        if self.scene is None:
            return
        for material_id in selected_edge.supporting_material_ids:
            material_path = self.scene.material_paths.get(material_id)
            if material_path is None or material_path.isEmpty():
                continue
            fill, stroke = self.material_palette.get(material_id, (QColor("#BDBDBD"), QColor("#616161")))
            fill_color = QColor(fill)
            fill_color.setAlpha(88)
            stroke_color = QColor(stroke)
            stroke_color.setAlpha(180)
            pen = QPen(stroke_color, 0.0)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(fill_color)
            painter.drawPath(material_path)

    @staticmethod
    def _draw_grid(painter: QPainter, x_min: float, y_min: float, x_max: float, y_max: float) -> None:
        grid_pen = QPen(QColor(255, 255, 255, 24), 0.0)
        grid_pen.setCosmetic(True)
        painter.setPen(grid_pen)
        step_x = 100.0
        step_y = 50.0
        x = math.floor(x_min / step_x) * step_x
        while x <= x_max + EPSILON:
            painter.drawLine(QPointF(x, y_min), QPointF(x, y_max))
            x += step_x
        y = math.floor(y_min / step_y) * step_y
        while y <= y_max + EPSILON:
            painter.drawLine(QPointF(x_min, y), QPointF(x_max, y))
            y += step_y
        axis_pen = QPen(QColor(255, 255, 255, 60), 0.0)
        axis_pen.setCosmetic(True)
        painter.setPen(axis_pen)
        painter.drawLine(QPointF(x_min, 0.0), QPointF(x_max, 0.0))


class CrossSectionCardWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Cross Section Topology Prototype")
        self.resize(1380, 860)
        self.model = PrototypeModel()
        self._selected_interface_text = "selected edge: none"
        self._build_ui()
        self._connect_events()
        self.refresh_scene()

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(14)
        controls_card = QFrame()
        controls_card.setObjectName("ControlsCard")
        controls_layout = QVBoxLayout(controls_card)
        controls_layout.setContentsMargins(16, 16, 16, 16)
        controls_layout.setSpacing(10)
        title = QLabel("Geometry / Topology Stress Test")
        title.setObjectName("CardTitle")
        subtitle = QLabel("Line + arc interface loops, iterative growth, ray diagnostics")
        subtitle.setObjectName("CardSubtitle")
        controls_layout.addWidget(title)
        controls_layout.addWidget(subtitle)
        mode_label = QLabel("Test Mode")
        mode_label.setObjectName("FieldLabel")
        self.mode_box = QComboBox()
        self.mode_box.addItems(PrototypeModel.MODE_OPTIONS)
        controls_layout.addWidget(mode_label)
        controls_layout.addWidget(self.mode_box)
        self.cap_radius = SliderRow("Cap Corner Radius (nm)", 0, 80, 12)
        self.trench_depth = SliderRow("Trench Depth (nm)", 0, 60, 14)
        self.trench_radius = SliderRow("Trench Radius (nm)", 0, 26, 8)
        self.process_time = SliderRow("Process Time (s)", 0, 120, 1)
        self.steps_per_s = SliderRow("Steps Per Second", 1, 30, 2)
        self.ray_angle = SliderRow("Ray Angle (deg)", -60, 60, 0)
        self.ray_count = SliderRow("Ray Count", 8, 180, 8)
        self.arc_chord = SliderRow("Arc Chord (nm)", 2, 24, 12)
        self.slider_rows = [
            self.cap_radius,
            self.trench_depth,
            self.trench_radius,
            self.process_time,
            self.steps_per_s,
            self.ray_angle,
            self.ray_count,
            self.arc_chord,
        ]
        for row in self.slider_rows:
            controls_layout.addWidget(row)
        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(6)
        self.btn_interfaces = QPushButton("Interfaces")
        self.btn_normals = QPushButton("Normals")
        self.btn_rays = QPushButton("Rays")
        self.btn_shadow = QPushButton("Shadow")
        self.btn_grid = QPushButton("Grid")
        self.btn_inspect = QPushButton("Inspect")
        self.btn_reset_view = QPushButton("Reset View")
        for button in [self.btn_interfaces, self.btn_normals, self.btn_rays, self.btn_shadow, self.btn_grid, self.btn_inspect]:
            button.setCheckable(True)
            button.setObjectName("ToggleButton")
            toggle_row.addWidget(button)
        self.btn_reset_view.setObjectName("ToggleButton")
        toggle_row.addWidget(self.btn_reset_view)
        self.btn_interfaces.setChecked(True)
        self.btn_rays.setChecked(True)
        self.btn_grid.setChecked(True)
        controls_layout.addLayout(toggle_row)
        materials_title = QLabel("Process Materials")
        materials_title.setObjectName("FieldLabel")
        controls_layout.addWidget(materials_title)
        base_state = build_base_state(
            cap_corner_radius_nm=float(self.cap_radius.slider.value()),
            trench_depth_nm=float(self.trench_depth.slider.value()),
            trench_radius_nm=float(self.trench_radius.slider.value()),
        )
        default_rates = base_state.process_models[base_state.active_process_id].rate_nm_s_by_material
        self.material_rows: dict[str, MaterialRow] = {}
        self.material_rows_layout = QVBoxLayout()
        self.material_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.material_rows_layout.setSpacing(4)
        for material_id, material in base_state.materials.items():
            row = MaterialRow(
                material_id=material_id,
                label=material.name,
                default_rate=float(default_rates.get(material_id, 10.0)),
                enabled=material_id in {"substrate", "core"},
            )
            self.material_rows[material_id] = row
            self.material_rows_layout.addWidget(row)
        materials_box = QWidget()
        materials_box.setLayout(self.material_rows_layout)
        controls_layout.addWidget(materials_box)
        self.conformal_material_label = QLabel("Conformal Deposit Material")
        self.conformal_material_label.setObjectName("FieldLabel")
        self.conformal_material_box = QComboBox()
        self.directional_material_label = QLabel("Directional Deposit Material")
        self.directional_material_label.setObjectName("FieldLabel")
        self.directional_material_box = QComboBox()
        for material_id, material in base_state.materials.items():
            self.conformal_material_box.addItem(material.name, material_id)
            self.directional_material_box.addItem(material.name, material_id)
        index_metal = self.conformal_material_box.findData("metal")
        if index_metal >= 0:
            self.conformal_material_box.setCurrentIndex(index_metal)
            self.directional_material_box.setCurrentIndex(index_metal)
        controls_layout.addWidget(self.conformal_material_label)
        controls_layout.addWidget(self.conformal_material_box)
        controls_layout.addWidget(self.directional_material_label)
        controls_layout.addWidget(self.directional_material_box)
        self.info_label = QLabel("")
        self.info_label.setObjectName("InfoLabel")
        self.info_label.setWordWrap(True)
        controls_layout.addWidget(self.info_label)
        controls_layout.addStretch(1)
        self.canvas = CrossSectionCanvas()
        self.canvas.on_interface_selected = self._on_interface_selected
        outer.addWidget(controls_card, 0)
        outer.addWidget(self.canvas, 1)
        self._material_palette = {
            "substrate": (QColor("#8D6E63"), QColor("#5D4037")),
            "core": (QColor("#86C5DA"), QColor("#3A7895")),
            "metal": (QColor("#C8B273"), QColor("#8A7640")),
        }
        self.setStyleSheet(
            """
            QWidget {
                font-family: "Segoe UI";
                color: #E6F0F7;
                background: #0E1822;
            }
            #ControlsCard {
                background: #152432;
                border: 1px solid #27445A;
                border-radius: 16px;
                min-width: 360px;
                max-width: 420px;
            }
            #CardTitle {
                font-size: 17px;
                font-weight: 700;
            }
            #CardSubtitle {
                color: #9CB8CA;
                font-size: 12px;
                margin-bottom: 4px;
            }
            #FieldLabel {
                color: #B9D0DF;
                font-weight: 600;
            }
            QComboBox {
                background: #1B2D3D;
                border: 1px solid #36546A;
                border-radius: 6px;
                padding: 5px;
            }
            #SliderTitle {
                color: #CCE0EC;
                font-size: 12px;
            }
            #SliderValue {
                color: #90CAF9;
                font-size: 12px;
                min-width: 36px;
                qproperty-alignment: AlignRight;
            }
            #ToggleButton {
                background: #1A2B39;
                border: 1px solid #355165;
                border-radius: 8px;
                padding: 6px 8px;
                font-weight: 600;
            }
            #ToggleButton:checked {
                background: #2D5873;
                border-color: #6AB7E7;
            }
            #InfoLabel {
                margin-top: 8px;
                padding: 8px;
                border-radius: 8px;
                background: #1A2B39;
                border: 1px solid #30495D;
                color: #D4E5EF;
            }
            #Canvas {
                border: 1px solid #26465A;
                border-radius: 18px;
                background: #0F1E2B;
            }
            """
        )
        self._apply_mode_visibility(self.mode_box.currentText())

    def _connect_events(self) -> None:
        self.mode_box.currentTextChanged.connect(self._on_mode_changed)
        for row in self.slider_rows:
            row.slider.valueChanged.connect(lambda _value: self.refresh_scene())
        for button in [self.btn_interfaces, self.btn_normals, self.btn_rays, self.btn_shadow, self.btn_grid, self.btn_inspect]:
            button.clicked.connect(self.refresh_scene)
        self.btn_reset_view.clicked.connect(self._reset_canvas_view)
        self.conformal_material_box.currentIndexChanged.connect(lambda _idx: self.refresh_scene())
        self.directional_material_box.currentIndexChanged.connect(lambda _idx: self.refresh_scene())
        for row in self.material_rows.values():
            row.checkbox.toggled.connect(lambda _checked: self.refresh_scene())
            row.rate_spin.valueChanged.connect(lambda _value: self.refresh_scene())

    def _on_mode_changed(self, mode_label: str) -> None:
        self._apply_mode_visibility(mode_label)
        self.refresh_scene()

    def _reset_canvas_view(self) -> None:
        self.canvas.reset_view()

    def _on_interface_selected(self, edge: TopologyEdge | None) -> None:
        if edge is None:
            self._selected_interface_text = "selected edge: none"
        else:
            length_nm = edge.length_nm()
            mid = edge.midpoint()
            supporting = ", ".join(edge.supporting_material_ids) if edge.supporting_material_ids else edge.primary_material_id
            shared_label = "yes" if edge.is_shared else "no"
            if edge.is_shared and edge.secondary_material_id is not None:
                relation = f"{edge.primary_material_id}<->{edge.secondary_material_id}"
            else:
                relation = f"{edge.primary_material_id}<->void"
            self._selected_interface_text = (
                f"selected edge: id={edge.edge_id} src={edge.source_loop_id}:{edge.source_edge_index} "
                f"materials={supporting} shared={shared_label} relation={relation} len={length_nm:.2f}nm "
                f"mid=({mid.x:.2f},{mid.y:.2f}) "
                f"normal=({edge.normal_outward.x:.3f},{edge.normal_outward.y:.3f})"
            )
        if self.btn_inspect.isChecked():
            self.refresh_scene()

    def _apply_mode_visibility(self, mode_label: str) -> None:
        common = {"cap_radius", "trench_depth", "trench_radius", "arc_chord"}
        mode_rows = {
            PrototypeModel.MODE_CONFORMAL: common | {"process_time", "steps_per_s"},
            PrototypeModel.MODE_ISOTROPIC: common | {"process_time", "steps_per_s"},
            PrototypeModel.MODE_DIRECTIONAL_GROWTH: common
            | {"process_time", "steps_per_s", "ray_angle", "ray_count"},
            PrototypeModel.MODE_DIRECTIONAL_ETCH: common
            | {"process_time", "steps_per_s", "ray_angle", "ray_count"},
            PrototypeModel.MODE_COMBINED: common
            | {
                "process_time",
                "steps_per_s",
                "ray_angle",
                "ray_count",
            },
            PrototypeModel.MODE_DEBUG: common,
        }
        row_by_name = {
            "cap_radius": self.cap_radius,
            "trench_depth": self.trench_depth,
            "trench_radius": self.trench_radius,
            "process_time": self.process_time,
            "steps_per_s": self.steps_per_s,
            "ray_angle": self.ray_angle,
            "ray_count": self.ray_count,
            "arc_chord": self.arc_chord,
        }
        visible_rows = mode_rows.get(mode_label, common)
        for name, row in row_by_name.items():
            row.setVisible(name in visible_rows)
        ray_controls_visible = mode_label in {
            PrototypeModel.MODE_DIRECTIONAL_GROWTH,
            PrototypeModel.MODE_DIRECTIONAL_ETCH,
            PrototypeModel.MODE_COMBINED,
            PrototypeModel.MODE_DEBUG,
        }
        self.btn_rays.setVisible(ray_controls_visible)
        self.btn_shadow.setVisible(ray_controls_visible)
        if not ray_controls_visible:
            self.btn_rays.setChecked(False)
            self.btn_shadow.setChecked(False)
        show_rates = mode_label != PrototypeModel.MODE_DEBUG
        show_checkboxes = True
        for row in self.material_rows.values():
            row.set_checkbox_visible(show_checkboxes)
            row.set_rate_visible(show_rates)
        self.conformal_material_label.setVisible(
            mode_label in {PrototypeModel.MODE_CONFORMAL, PrototypeModel.MODE_COMBINED}
        )
        self.conformal_material_box.setVisible(
            mode_label in {PrototypeModel.MODE_CONFORMAL, PrototypeModel.MODE_COMBINED}
        )
        self.directional_material_label.setVisible(mode_label == PrototypeModel.MODE_DIRECTIONAL_GROWTH)
        self.directional_material_box.setVisible(mode_label == PrototypeModel.MODE_DIRECTIONAL_GROWTH)

    def current_params(self) -> PrototypeParams:
        etch_enabled = {material_id: row.checkbox.isChecked() for material_id, row in self.material_rows.items()}
        rate_nm_s = {material_id: float(row.rate_spin.value()) for material_id, row in self.material_rows.items()}
        conformal_material = self.conformal_material_box.currentData()
        directional_material = self.directional_material_box.currentData()
        return PrototypeParams(
            mode_label=self.mode_box.currentText(),
            cap_corner_radius_nm=float(self.cap_radius.slider.value()),
            trench_depth_nm=float(self.trench_depth.slider.value()),
            trench_radius_nm=float(self.trench_radius.slider.value()),
            process_time_s=float(self.process_time.slider.value()),
            steps_per_s=float(self.steps_per_s.slider.value()),
            ray_angle_deg=float(self.ray_angle.slider.value()),
            ray_count=int(self.ray_count.slider.value()),
            arc_chord_nm=float(self.arc_chord.slider.value()),
            show_interfaces=self.btn_interfaces.isChecked(),
            show_normals=self.btn_normals.isChecked(),
            show_rays=self.btn_rays.isVisible() and self.btn_rays.isChecked(),
            show_shadow=self.btn_shadow.isVisible() and self.btn_shadow.isChecked(),
            show_grid=self.btn_grid.isChecked(),
            inspect_interfaces=self.btn_inspect.isChecked(),
            etch_enabled_materials=etch_enabled,
            rate_nm_s_by_material=rate_nm_s,
            conformal_deposition_material_id=str(conformal_material) if conformal_material is not None else "metal",
            directional_deposition_material_id=str(directional_material) if directional_material is not None else "metal",
        )

    def refresh_scene(self) -> None:
        params = self.current_params()
        scene = self.model.build_scene(params)
        info_lines = list(scene.info_lines)
        if scene.loop_diagnostics:
            first_warning = ""
            for diagnostic in scene.loop_diagnostics:
                if diagnostic.warnings:
                    first_warning = f"{diagnostic.loop_id}: {diagnostic.warnings[0]}"
                    break
            if first_warning:
                info_lines.append(f"first warning: {first_warning}")
            else:
                info_lines.append("first warning: none")
        if params.inspect_interfaces:
            info_lines.append(self._selected_interface_text)
        self.info_label.setText("\n".join(info_lines))
        self.canvas.set_scene(
            scene=scene,
            material_palette=self._material_palette,
            show_interfaces=params.show_interfaces,
            show_normals=params.show_normals,
            show_rays=params.show_rays,
            show_shadow=params.show_shadow,
            show_grid=params.show_grid,
            inspect_mode=params.inspect_interfaces,
        )


def main() -> int:
    app = QApplication(sys.argv)
    window = CrossSectionCardWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
