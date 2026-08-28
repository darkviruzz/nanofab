"""Qt-free live previews of the currently selected process (roadmap E29)."""

from __future__ import annotations

import math
from typing import Any, Mapping

import numpy as np

from nanofab_v3.materials import (
    DRY_ETCH,
    ICP_FLUORINE,
    ION_BEAM,
    RIE_CHLORINE,
    RIE_OXYGEN,
    SPUTTER_DEPOSIT,
    WET_ETCH,
    WET_ETCH_CR,
    WET_ETCH_OXIDE,
    MaterialId,
    MaterialLibrary,
)
from nanofab_v3.model.structure import Structure
from nanofab_v3.ui.scene import PreviewArrow, PreviewCircle, StepPreview, surface_normals

_ETCH_CLASS = {
    "etch.wet": WET_ETCH,
    "etch.rie": DRY_ETCH,
    "etch.ion_beam": ION_BEAM,
    "etch.icp_fluorine": ICP_FLUORINE,
    "etch.rie_chlorine": RIE_CHLORINE,
    "etch.rie_oxygen": RIE_OXYGEN,
    "etch.wet_cr": WET_ETCH_CR,
    "etch.wet_oxide": WET_ETCH_OXIDE,
}
_DIRECTED = {
    "etch.rie",
    "etch.ion_beam",
    "etch.icp_fluorine",
    "deposit.evaporate",
    "deposit.sputter",
    "deposit.sputter_rate",
}
_CONFORMAL = {"deposit.conformal_offset", "deposit.ald"}
_ETCHANT = "#ff6b6b"
_DEPOSIT = "#5ac8fa"
_REDEPOSIT = "#ffd166"
_MOBILITY = "#5ac87a"
_PARTICLE = "#d6dbe0"
_ARROW_SAMPLES = 20
"""Maximum reachable-surface anchor count for one process preview."""


def build_step_preview(
        structure: Structure,
        step_id: str,
        params: Mapping[str, Any],
        library: MaterialLibrary,
        *,
        thickness_scale: float = 1.0,
        samples: int = _ARROW_SAMPLES,
) -> StepPreview:
    """Build a cheap geometric preview; no flux or motion solver is evaluated."""
    scale = float(thickness_scale)
    if not math.isfinite(scale) or scale < 0.0:
        scale = 1.0
    if not structure.materials:
        return StepPreview(thickness_scale=scale)

    if step_id == "particle.seed":
        return _particles(structure, params, scale)
    if scale == 0.0:
        return StepPreview(thickness_scale=0.0)

    segments = surface_normals(
        structure, samples=max(1, int(samples)), reachable_only=True
    )
    anchors = _surface_anchors(structure, segments)
    if not anchors:
        return StepPreview(thickness_scale=scale)

    if step_id in _DIRECTED:
        return _directed(anchors, step_id, params, library, scale)
    if step_id in _ETCH_CLASS or step_id in _CONFORMAL:
        return _normal_arrows(
            anchors, step_id, params, library, scale
        )
    return StepPreview(thickness_scale=scale)


def _number(params: Mapping[str, Any], name: str, default: float = 0.0) -> float:
    try:
        value = float(params.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def _deposition_length_nm(
        step_id: str, params: Mapping[str, Any], library: MaterialLibrary
) -> float | None:
    if step_id in {"deposit.evaporate", "deposit.sputter", *_CONFORMAL}:
        return _number(params, "thickness")
    if step_id == "deposit.sputter_rate":
        material = MaterialId(str(params.get("material", "")))
        entry = library.get(material)
        return (
            0.0
            if entry is None
            else entry.rate_for(SPUTTER_DEPOSIT) * _number(params, "duration")
        )
    return None


def _etch_length_nm(
        material: MaterialId,
        step_id: str,
        params: Mapping[str, Any],
        library: MaterialLibrary,
) -> float:
    process_class = _ETCH_CLASS.get(step_id)
    if process_class is None:
        return 0.0
    entry = library.get(material)
    rate = 0.0 if entry is None else entry.rate_for(process_class)
    return rate * _number(params, "duration") * _number(params, "scale", 1.0)


def _surface_anchors(
        structure: Structure, segments: np.ndarray | None
) -> tuple[tuple[np.ndarray, np.ndarray, MaterialId], ...]:
    """Reachable front points, outward normals and the material under each point."""
    if segments is None or not len(segments):
        return ()
    starts = np.asarray(segments[:, 0], dtype=float)
    directions = np.asarray(segments[:, 1] - segments[:, 0], dtype=float)
    norms = np.linalg.norm(directions, axis=1, keepdims=True)
    directions = np.divide(directions, np.where(norms == 0.0, 1.0, norms))
    cells = np.clip(
        np.round((starts - np.asarray(structure.grid.origin)) / structure.grid.spacing).astype(int),
        0,
        np.asarray(structure.grid.shape) - 1,
    )
    owners = structure.nearest_material_index[cells[:, 0], cells[:, 1]]
    return tuple(
        (start, direction, structure.materials[int(owner)])
        for start, direction, owner in zip(starts, directions, owners, strict=True)
        if int(owner) >= 0
    )


def _directions(step_id: str, params: Mapping[str, Any]) -> tuple[np.ndarray, ...]:
    if step_id == "etch.icp_fluorine":
        angle, divergence = 0.0, 3.0
    else:
        angle = _number(params, "angle")
        if step_id in {"deposit.sputter", "deposit.sputter_rate"}:
            exponent = max(0.0, _number(params, "exponent", 1.0))
            divergence = min(70.0, 55.0 / math.sqrt(exponent + 1.0))
        else:
            divergence = _number(params, "divergence")
    offsets = (-divergence, 0.0, divergence) if divergence > 0.0 else (0.0,)
    return tuple(
        np.array((-math.cos(math.radians(angle + offset)), -math.sin(math.radians(angle + offset))))
        for offset in offsets
    )


def _directed(
        anchors: tuple[tuple[np.ndarray, np.ndarray, MaterialId], ...],
        step_id: str,
        params: Mapping[str, Any],
        library: MaterialLibrary,
        scale: float,
) -> StepPreview:
    deposition = step_id.startswith("deposit.")
    deposited_length = _deposition_length_nm(step_id, params, library)
    arrows: list[PreviewArrow] = []
    lengths: list[float] = []
    for start, _normal, material in anchors:
        length = (
            float(deposited_length or 0.0)
            if deposition
            else _etch_length_nm(material, step_id, params, library)
        )
        if length <= 0.0:
            continue
        lengths.append(length)
        for direction in _directions(step_id, params):
            draw_direction = -direction if deposition else direction
            arrows.append(
                PreviewArrow(
                    tuple(start),
                    tuple(draw_direction),
                    length,
                    _DEPOSIT if deposition else _ETCHANT,
                )
            )
            if step_id == "etch.ion_beam":
                returned = length * _number(params, "redeposition_yield")
                if returned > 0.0:
                    arrows.append(
                        PreviewArrow(tuple(start), tuple(-direction), returned, _REDEPOSIT, dashed=True)
                    )
        mobility = _number(params, "mobility_length")
        if deposition and mobility > 0.0:
            arrows.append(
                PreviewArrow(tuple(start), (0.0, 1.0), mobility, _MOBILITY, dashed=True)
            )
    return StepPreview(
        arrows=tuple(arrows),
        physical_length_nm=max(lengths, default=0.0),
        thickness_scale=scale,
    )


def _raycast(
        structure: Structure, direction: np.ndarray, lateral_fraction: float
) -> np.ndarray | None:
    """March from the top face to the first cell where solid_phi <= 0."""
    grid = structure.grid
    up0, up1 = grid.extent(0)
    right0, right1 = grid.extent(1)
    point = np.array((up1 - 0.25 * grid.spacing, right0 + lateral_fraction * (right1 - right0)))
    step = max(0.5 * grid.spacing, 1e-9)
    count = int(math.ceil(math.hypot(up1 - up0, right1 - right0) / step)) + 2
    for _ in range(count):
        cell = np.rint((point - np.asarray(grid.origin)) / grid.spacing).astype(int)
        if np.any(cell < 0) or np.any(cell >= np.asarray(grid.shape)):
            if point[0] < up0:
                return None
        elif structure.solid_phi[tuple(cell)] <= 0.0:
            return point - direction * step
        point = point + direction * step
    return None


def _normal_arrows(
        anchors: tuple[tuple[np.ndarray, np.ndarray, MaterialId], ...],
        step_id: str,
        params: Mapping[str, Any],
        library: MaterialLibrary,
        scale: float,
) -> StepPreview:
    outward = step_id in _CONFORMAL
    deposited_length = _deposition_length_nm(step_id, params, library)
    arrows: list[PreviewArrow] = []
    lengths: list[float] = []
    for start, direction, material in anchors:
        length = (
            float(deposited_length or 0.0)
            if outward
            else _etch_length_nm(material, step_id, params, library)
        )
        if length <= 0.0:
            continue
        lengths.append(length)
        arrows.append(PreviewArrow(
            tuple(start),
            tuple(direction if outward else -direction),
            length,
            _DEPOSIT if outward else _ETCHANT,
        ))
    return StepPreview(
        arrows=tuple(arrows),
        physical_length_nm=max(lengths, default=0.0),
        thickness_scale=scale,
    )


def _particles(
        structure: Structure, params: Mapping[str, Any], scale: float
) -> StepPreview:
    count = max(0, int(_number(params, "count")))
    radius = max(0.0, _number(params, "radius"))
    spread = max(0.0, _number(params, "radius_spread"))
    if count == 0 or radius <= 0.0:
        return StepPreview(thickness_scale=scale)
    right0, right1 = structure.grid.extent(1)
    span = right1 - right0
    diameter_max = 2.0 * radius * (1.0 + spread)
    capacity = max(0, int(math.floor(0.9 * span / diameter_max)))
    shown = min(count, capacity)
    sizes = (radius,)
    if 2.0 * radius * spread > structure.grid.spacing:
        sizes = (radius * (1.0 - spread), radius, radius * (1.0 + spread))
    circles: list[PreviewCircle] = []
    fractions = (0.5,) if shown == 1 else tuple(np.linspace(0.05, 0.95, shown))
    for fraction in fractions:
        hit = _raycast(structure, np.array((-1.0, 0.0)), float(fraction))
        if hit is None:
            continue
        for size in sizes:
            circles.append(
                PreviewCircle((float(hit[0] + size), float(hit[1])), size, _PARTICLE, dashed=True)
            )
    note = "" if count <= shown else f"{shown} of {count} particle positions shown"
    return StepPreview(circles=tuple(circles), note=note, thickness_scale=scale)
