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


def build_step_preview(
        structure: Structure,
        step_id: str,
        params: Mapping[str, Any],
        library: MaterialLibrary,
        *,
        pixels_per_nm: float = 20.0,
) -> StepPreview:
    """Build a cheap geometric preview; no flux or motion solver is evaluated."""
    scale = float(pixels_per_nm)
    if not math.isfinite(scale) or scale < 0.0:
        scale = 20.0
    if scale == 0.0:
        return StepPreview(pixels_per_nm=0.0)
    if not structure.materials:
        return StepPreview(pixels_per_nm=scale)

    if step_id == "particle.seed":
        return _particles(structure, params, scale)

    length = _length_nm(structure, step_id, params, library)
    if length is None or length <= 0.0:
        return StepPreview(pixels_per_nm=scale)
    if length * scale < 5.0:
        return StepPreview(
            note=f"{length:.3g} nm is {length * scale:.2f} px at {scale:g} px/nm",
            physical_length_nm=length,
            pixels_per_nm=scale,
        )

    if step_id in _DIRECTED:
        return _directed(structure, step_id, params, length, scale)
    if step_id in _ETCH_CLASS or step_id in _CONFORMAL:
        return _normal_arrows(
            structure,
            length,
            outward=step_id in _CONFORMAL,
            color=_DEPOSIT if step_id in _CONFORMAL else _ETCH,
            scale=scale,
        )
    return StepPreview(pixels_per_nm=scale)


def _number(params: Mapping[str, Any], name: str, default: float = 0.0) -> float:
    try:
        value = float(params.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def _length_nm(
        structure: Structure,
        step_id: str,
        params: Mapping[str, Any],
        library: MaterialLibrary,
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
    if step_id == "develop.rate":
        duration = _number(params, "duration")
        rates = [
            entry.develop.bound
            for material in structure.materials
            if (entry := library.get(material)) is not None and entry.develop is not None
        ]
        return max(rates, default=0.0) * duration
    process_class = _ETCH_CLASS.get(step_id)
    if process_class is None:
        return None
    rate = max(
        (
            entry.rate_for(process_class)
            for material in structure.materials
            if (entry := library.get(material)) is not None
        ),
        default=0.0,
    )
    return rate * _number(params, "duration") * _number(params, "scale", 1.0)


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
        structure: Structure,
        step_id: str,
        params: Mapping[str, Any],
        length: float,
        scale: float,
) -> StepPreview:
    deposition = step_id.startswith("deposit.")
    arrows: list[PreviewArrow] = []
    for direction in _directions(step_id, params):
        for fraction in (0.2, 0.5, 0.8):
            hit = _raycast(structure, direction, fraction)
            if hit is None:
                continue
            draw_direction = -direction if deposition else direction
            arrows.append(
                PreviewArrow(
                    tuple(hit),
                    tuple(draw_direction),
                    length,
                    _DEPOSIT if deposition else _ETCHANT,
                )
            )
            if step_id == "etch.ion_beam":
                returned = length * _number(params, "redeposition_yield")
                if returned * scale >= 5.0:
                    arrows.append(
                        PreviewArrow(tuple(hit), tuple(-direction), returned, _REDEPOSIT, dashed=True)
                    )
    mobility = _number(params, "mobility_length")
    if deposition and mobility > 0.0 and arrows:
        anchor = arrows[len(arrows) // 2].start
        arrows.append(PreviewArrow(anchor, (0.0, 1.0), mobility, _MOBILITY, dashed=True))
    return StepPreview(
        arrows=tuple(arrows),
        physical_length_nm=length,
        pixels_per_nm=scale,
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
        structure: Structure,
        length: float,
        *,
        outward: bool,
        color: str,
        scale: float,
) -> StepPreview:
    segments = surface_normals(structure, samples=16)
    if segments is None:
        return StepPreview(pixels_per_nm=scale)
    arrows = []
    for start, tip in segments:
        direction = tip - start
        norm = float(np.linalg.norm(direction))
        if norm <= 0.0:
            continue
        direction = direction / norm
        arrows.append(
            PreviewArrow(tuple(start), tuple(direction if outward else -direction), length, color)
        )
    return StepPreview(
        arrows=tuple(arrows), physical_length_nm=length, pixels_per_nm=scale
    )


def _particles(
        structure: Structure, params: Mapping[str, Any], scale: float
) -> StepPreview:
    count = max(0, int(_number(params, "count")))
    radius = max(0.0, _number(params, "radius"))
    spread = max(0.0, _number(params, "radius_spread"))
    if count == 0 or radius <= 0.0:
        return StepPreview(pixels_per_nm=scale)
    shown = min(count, 12)
    sizes = (radius,)
    if 2.0 * radius * spread > structure.grid.spacing:
        sizes = (radius * (1.0 - spread), radius, radius * (1.0 + spread))
    circles: list[PreviewCircle] = []
    for index in range(shown):
        hit = _raycast(structure, np.array((-1.0, 0.0)), (index + 1.0) / (shown + 1.0))
        if hit is None:
            continue
        for size in sizes:
            circles.append(
                PreviewCircle((float(hit[0] + size), float(hit[1])), size, _PARTICLE, dashed=True)
            )
    note = "" if count <= shown else f"{shown} of {count} particle positions shown"
    return StepPreview(circles=tuple(circles), note=note, pixels_per_nm=scale)
