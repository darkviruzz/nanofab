"""`SceneSnapshot` v2 — everything a picture of a revision needs, and no Qt (plan §10).

ADR-0001's central finding was that v1 had *two* geometry representations and let
the drawing one win: `QPainterPath` was where the booleans happened, so every
process decision was made by a renderer. This module is the structural answer.
It imports numpy and the kernel; it does not import Qt, and it never will —
**anything that decides geometry lives here or below, and Qt only maps nm to
pixels.** A `SceneSnapshot` can therefore be built, asserted and diffed in a test
with no display, which is exactly what makes the rule enforceable rather than
aspirational.

## This is the third deliberately 2D module, and it is named

`kernel.contours` and `kernel.flux` are the v2 core's two 2D-only seams; the M4
handoff asks that the renderer not add a third to the *kernel* by accident.
Rendering is 2D by decision (interview Q7, plan §10), so the 2D-ness lives here,
declared, and `builds` raises on a grid that is not 2-D rather than pretending
otherwise. `kernel.predicates` stays N-D.

## Which picture of a material is the right one

Two rules, and they are not the same rule:

- **Outlines come from `phi_m` through `marching_squares`.** That is the sub-cell
  smooth path plan §10 asks for. It is also safe against the phantom zero level
  of §19.2, and measurably so: marching squares tests `field < level` strictly,
  and a phantom seam is a zero-valued cell with no strictly-inside cell on either
  side, so it produces no sign change and no contour (measured on the S2 stack,
  where `phi_resist` is exactly 0.0 in all 301 columns of a buried
  silicon/oxide interface: the resist still contours as 2 loops of 600.0 nm).
- **Regions come from `material_index`.** A fill rule of `phi_m <= 0` is what the
  handoff's trap actually is: on that same stack it claims the resist fills 301
  extra cells, one full row across the domain, 60 nm below its own underside.
  `material_index` is `argmin_m phi[m]` masked by the *union's* `solid_mask`, so
  it is an exclusive partition and cannot contain a phantom.

Going the other way — contouring `regions.closed_region` — is correct but
cell-quantised by construction (`regions.signed_distance_of`'s own docstring),
and it shows: on S1 after evaporation the metal's outline comes out 687.2 nm
against the field's 681.4 nm. So the region path is the fallback, not the default.

Every shape carries the occurrence count `kernel.occurrences` derived for the
same revision, which is the check the handoff asks for — a picture whose loop
count disagrees with the labelling is a picture to distrust, and the test suite
says so rather than the eye.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from dataclasses import replace
from typing import Mapping, Sequence

import numpy as np

from nanofab_v3.kernel import contours as contour_kernel
from nanofab_v3.kernel import occurrences as occurrence_kernel
from nanofab_v3.kernel import predicates
from nanofab_v3.materials import MaterialId, MaterialLibrary
from nanofab_v3.model.grid import Grid
from nanofab_v3.model.structure import EMPTY, Structure

DEFAULT_COLOR = "#808080"
"""Colour for a material the library has never heard of (plan §5.4 allows those)."""

EMPTY_COLOR = "#101418"
"""What empty space is painted as — a colour, not a material."""


@dataclass(frozen=True)
class MaterialShape:
    """One material's outline at one revision.

    Attributes:
        material: Which material.
        label: Its display name, or the id when the library does not have it.
        color: `#rrggbb` from the `MaterialType` (plan §10: display only, never
            physics).
        outlines: Closed polylines in nm, `(N, 2)` float arrays in the grid's axis
            order. Sub-cell smooth — from the field, not from a cell mask.
        occurrences: How many connected pieces `kernel.occurrences` found. A
            picture whose loop count disagrees with this is a picture to
            distrust.
        measure: The material's enclosed area in nm², summed per material as
            §17.1 requires.
    """

    material: MaterialId
    label: str
    color: str
    outlines: tuple[np.ndarray, ...]
    occurrences: int = 0
    measure: float = 0.0


@dataclass(frozen=True)
class OverlayBand:
    """One filled region of a banded overlay — roadmap E28's exposure picture.

    Attributes:
        label: What this band is, in the reader's units: "1.0-1.5 D0".
        outlines: Closed polylines in nm, fill-ready like a shape's.
        shade: 0..1, how dark this band paints. Monotonic in dose, so "darker
            means more" is readable without the legend.
    """

    label: str
    outlines: tuple[np.ndarray, ...] = ()
    shade: float = 0.5


@dataclass(frozen=True)
class Overlay:
    """One inspect overlay on top of the geometry (plan §10).

    Overlays are *derived per request*, never per frame: handoff §4.3's finding
    is that anything computed over the whole domain per frame should be asked
    whether it needs to be, and a predicate is 3–12 ms. `SceneSnapshot.build`
    takes the list of overlay names it should compute and computes only those.

    Attributes:
        kind: What it shows — `"reachable"`, `"voids"`, `"unsupported"`,
            `"normals"`.
        label: What the legend calls it.
        color: `#rrggbb`.
        outlines: Closed polylines in nm, like a shape's.
        segments: Straight segments in nm as `(N, 2, 2)` — what a normals field
            is, and what an arrow needs.
        note: One sentence for the UI, e.g. how many voids there are.
        bands: Filled regions, darkest last (E28). A predicate has none; the two
            exposure overlays are the only banded ones, because they are the only
            ones showing a *quantity* rather than a yes/no.
        filled: Whether `outlines` are painted as an area rather than as a line.
    """

    kind: str
    label: str
    color: str
    outlines: tuple[np.ndarray, ...] = ()
    segments: np.ndarray | None = None
    note: str = ""
    bands: tuple[OverlayBand, ...] = ()
    filled: bool = False


OVERLAY_KINDS = ("exposed", "dose", "reachable", "voids", "unsupported", "normals")
"""The overlays `SceneSnapshot.build` knows how to compute.

`exposed` and `dose` are first because they are different in kind from the rest.
The other four are *predicates* — questions asked of the geometry. These two are
**stored fields**, already on the structure, and roadmap E9 asks that the exposure
result always colour rather than waiting to be switched on: a latent image you
have to remember to look for is a latent image nobody looks at.
"""

ALWAYS_ON = ("exposed", "dose")
"""Overlays a shell shows without being asked (E9).

The *data* is free — it is a field the structure already carries. **Drawing** it
is not: an outline costs a distance transform and a marching-squares pass, which
is ~80 ms at the reference grid, the same order as a predicate. Measured rather
than assumed (plan §24.7), and they stay on anyway because a scene is rebuilt
when the revision changes and not per frame (§20.6) — 80 ms against a step that
takes seconds is not where the time goes.
"""

_OVERLAY_COLORS = {
    "exposed": "#c8ccd2",
    "dose": "#ff9f43",
    "reachable": "#5ac8fa",
    "voids": "#ff6b6b",
    "unsupported": "#ffd166",
    "normals": "#a0e7a0",
}

DOSE_BANDS = (0.5, 1.0, 1.5, 2.0)
"""Band edges of the dose picture, **in multiples of the resist's clearing dose**.

Roadmap E28. Four edges make five bands — under half D0, approaching it, the
first stop over, the second, and everything beyond — and the point of discrete
bands rather than a gradient is that you can *read* one off: "this is twice
over-dosed" is a sentence a continuous ramp cannot produce.

**This is where plan §10 gets softened, deliberately, and it is recorded here so
that it does not go on softening unnoticed.** §10 says the renderer decides
pictures and never physics, and D0 is physics: it is the resist's
`DevelopModel.clearing_dose`. The alternative — bands as fractions of the *peak
dose present*, which is what this module drew before — is a picture that changes
meaning between two revisions of the same recipe, because the peak moves. A scale
that moves is not a scale. And the cost is small and bounded: `build` already
receives the library (it needs it for the colours), so nothing new crosses the
boundary; what crosses is one number, read by name, for one overlay.

The rule that stays: no rate, no model evaluation, no decision about *geometry*
here. If a second physical quantity ever wants in, that is the moment to move
this to a "presentation scale" the session computes and hands over, rather than
to soften §10 a third time.
"""

_UNDOSED_SHADE = 0.12
"""How dark the below-D0 band paints. Light, because "not enough" is the default
state of a resist and a picture where nothing happened should look like it."""


@dataclass(frozen=True)
class PreviewArrow:
    """One process-preview vector in nm, with a presentation-scaled length."""

    start: tuple[float, float]
    direction: tuple[float, float]
    length_nm: float
    color: str
    dashed: bool = False


@dataclass(frozen=True)
class PreviewCircle:
    """One particle outline in the sample's nm coordinates."""

    center: tuple[float, float]
    radius_nm: float
    color: str
    dashed: bool = True


@dataclass(frozen=True)
class StepPreview:
    """Qt-free geometric preview of a process before it runs (roadmap E29)."""

    arrows: tuple[PreviewArrow, ...] = ()
    circles: tuple[PreviewCircle, ...] = ()
    note: str = ""
    physical_length_nm: float = 0.0
    pixels_per_nm: float = 20.0

    def __bool__(self) -> bool:
        return bool(self.arrows or self.circles or self.note)


@dataclass(frozen=True)
class SceneSnapshot:
    """Everything a cross-section picture of one revision needs.

    Attributes:
        grid: The grid it was built on — the sole spatial authority, carried so
            the canvas can map nm to pixels without guessing an extent.
        shapes: One entry per material, in the structure's own order (which is
            deposition order, so painting them in order stacks correctly).
        overlays: The inspect overlays that were asked for.
        index_map: `structure.material_index` — the raster fast path, `EMPTY`
            (-1) where a cell is empty.
        palette: Colour per material, for the index map and the legend.
        caption: One line naming the revision.
        light: Where the light would go, when a shell has asked for the preview
            (roadmap E9). Empty otherwise, and never computed from the structure
            — it comes from the mask parameters, which is why it is set by the
            caller rather than by `build`.
    """

    grid: Grid
    shapes: tuple[MaterialShape, ...] = ()
    overlays: tuple[Overlay, ...] = ()
    index_map: np.ndarray | None = None
    palette: Mapping[MaterialId, str] = dataclass_field(default_factory=dict)
    caption: str = ""
    light: LightPreview = dataclass_field(default_factory=lambda: LightPreview())
    preview: StepPreview = dataclass_field(default_factory=StepPreview)

    def with_light(self, light: LightPreview) -> "SceneSnapshot":
        """The same snapshot with a light preview on it."""
        return replace(self, light=light)

    def with_preview(self, preview: StepPreview) -> "SceneSnapshot":
        """The same snapshot with the selected process preview on it."""
        return replace(self, preview=preview)

    @property
    def extent(self) -> tuple[float, float, float, float]:
        """`(min, max)` along each grid axis in nm, as `(a0, a1, b0, b1)`.

        The **first** axis is the stacking direction and is drawn upwards; the
        second is drawn to the right. That is the one rendering convention in
        v2, and it is the same convention `kernel.gate`'s headroom guard uses
        for "the max face of the first axis".
        """
        first = self.grid.extent(0)
        second = self.grid.extent(1)
        return (first[0], first[1], second[0], second[1])

    def shape_of(self, material: MaterialId) -> MaterialShape | None:
        """One material's shape, or `None` when it is not in this revision."""
        for shape in self.shapes:
            if shape.material == material:
                return shape
        return None

    def material_at(self, point: tuple[float, float]) -> MaterialId | None:
        """Which material occupies a position in nm — the hit test.

        Reads `index_map`, which is an exclusive partition, rather than testing
        the fields: `phi_m <= 0` would answer with a phantom (see the module
        docstring) and two materials would both claim their shared interface
        cell.
        """
        if self.index_map is None:
            return None
        index = []
        for axis, value in enumerate(point):
            cell = int(round((value - self.grid.origin[axis]) / self.grid.spacing))
            if not 0 <= cell < self.grid.shape[axis]:
                return None
            index.append(cell)
        found = int(self.index_map[tuple(index)])
        if found == EMPTY:
            return None
        materials = [shape.material for shape in self.shapes]
        return materials[found] if found < len(materials) else None


def build(
        structure: Structure,
        *,
        library: MaterialLibrary | None = None,
        overlays: Sequence[str] = (),
        caption: str = "",
        index_map: bool = True,
) -> SceneSnapshot:
    """Turn one revision's `Structure` into everything a picture of it needs.

    Deliberately a plain function of a `Structure`: no widget, no revision, no
    session. A test builds one; the canvas paints one; an external tool could
    write one to SVG without any of this package's Qt.
    """
    grid = structure.grid
    if grid.ndim != 2:
        raise ValueError(
            f"rendering is 2D by decision (plan Q7, §10); this grid has {grid.ndim} axes"
        )
    colors = library.display_colors() if library is not None else {}
    names = _display_names(library)
    labelled = occurrence_kernel.label_occurrences(structure)

    shapes = []
    for material in structure.materials:
        phi = structure.phi_of(material)
        pieces = labelled.of(material)
        shapes.append(
            MaterialShape(
                material=material,
                label=names.get(material, material),
                color=colors.get(material, DEFAULT_COLOR),
                # From the field, not from a mask: sub-cell smooth, and immune
                # to the phantom zero because marching squares tests `< level`.
                # Stitched closed along the domain edge, because a blanket
                # layer's outline leaves the domain and is not a polygon.
                outlines=_outlines(grid, phi),
                occurrences=len(pieces),
                measure=float(sum(piece.measure for piece in pieces)),
            )
        )

    return SceneSnapshot(
        grid=grid,
        shapes=tuple(shapes),
        overlays=tuple(
            overlay
            for overlay in (
                _overlay(structure, kind, library)
                for kind in overlays
                if kind in OVERLAY_KINDS
            )
            if overlay.label
        ),
        index_map=structure.material_index if index_map else None,
        palette={shape.material: shape.color for shape in shapes},
        caption=caption,
    )


def _outlines(grid: Grid, phi: np.ndarray) -> tuple[np.ndarray, ...]:
    """One material's fill-ready outlines.

    A material with no contour at all is either absent or fills the whole domain,
    and the two are not the same picture: the second one has to be the domain
    rectangle or a blanket substrate thicker than its headroom vanishes.
    """
    lines = contour_kernel.marching_squares(grid, phi)
    if lines:
        return fillable_outlines(grid, lines)
    if not np.any(np.asarray(phi) < 0.0):
        return ()
    corners = [point for _, point in _Perimeter(grid).corners]
    return (np.array(corners + corners[:1], dtype=float),)


def fillable_outlines(grid: Grid, outlines: Sequence[np.ndarray]) -> tuple[np.ndarray, ...]:
    """Close the contours that leave the domain, along the domain's own edge.

    A blanket layer's outline is **not a polygon**, and that is not an edge case:
    it is what every substrate, every spin coat and every deposited film looks
    like, for the same reason §17.5 gives for the headroom guard — a layer
    reaches the lateral faces by construction. `marching_squares` says so
    plainly ("open polylines … do not [repeat their first point]"), and plan §10
    does not say what a filler should then do.

    Measured on a two-material stack at 300 x 240 nm: silicon contours as one
    open polyline from (40, 300) to (40, 0), and the resist as two, at 40 and
    130 nm. Filling each on its own closes it with a straight chord between its
    own ends, which for a horizontal line is a polygon of zero area — the
    substrate and the resist simply did not appear.

    So the open pieces are **stitched to each other** around the boundary rather
    than each to itself. Walking counter-clockwise in the drawn frame keeps the
    region on the left, which is the orientation `marching_squares` already
    guarantees, so the boundary run from where one piece leaves to where the
    next comes back is exactly the part of the domain edge that belongs to the
    region. Corners passed on the way are inserted.
    """
    closed: list[np.ndarray] = []
    open_pieces: list[np.ndarray] = []
    for line in outlines:
        if len(line) < 2:
            continue
        if np.allclose(line[0], line[-1]):
            closed.append(np.asarray(line, dtype=float))
        else:
            open_pieces.append(np.asarray(line, dtype=float))
    if not open_pieces:
        return tuple(closed)

    perimeter = _Perimeter(grid)
    starts = sorted(range(len(open_pieces)), key=lambda i: perimeter.at(open_pieces[i][0]))
    unused = set(starts)
    while unused:
        first = min(unused, key=lambda i: perimeter.at(open_pieces[i][0]))
        loop: list[np.ndarray] = []
        current = first
        while True:
            unused.discard(current)
            loop.append(open_pieces[current])
            exit_at = open_pieces[current][-1]
            following = _next_entry(perimeter, open_pieces, starts, unused, first, exit_at)
            loop.append(perimeter.walk(exit_at, open_pieces[following][0]))
            if following == first:
                break
            current = following
        closed.append(np.concatenate(loop + [loop[0][:1]], axis=0))
    return tuple(closed)


def _next_entry(
        perimeter: "_Perimeter",
        pieces: Sequence[np.ndarray],
        order: Sequence[int],
        unused: set[int],
        first: int,
        exit_at: np.ndarray,
) -> int:
    """The piece whose start comes first counter-clockwise from `exit_at`."""
    here = perimeter.at(exit_at)
    candidates = sorted(
        (i for i in order if i in unused or i == first),
        key=lambda i: (perimeter.at(pieces[i][0]) - here) % perimeter.length,
    )
    return candidates[0]


class _Perimeter:
    """Arc length counter-clockwise around the domain, for stitching open contours.

    Counter-clockwise in the *drawn* frame — first axis up, second to the right —
    starting at the (min, min) corner: along the min face of the first axis, up
    the max face of the second, back along the max face of the first, down the
    min face of the second. That is the same "up" the commit gate's headroom
    guard means.
    """

    def __init__(self, grid: Grid) -> None:
        self.grid = grid
        (self.up0, self.up1) = grid.extent(0)
        (self.right0, self.right1) = grid.extent(1)
        self.width = self.right1 - self.right0
        self.height = self.up1 - self.up0
        self.length = 2.0 * (self.width + self.height)
        self.corners = (
            (0.0, np.array([self.up0, self.right0])),
            (self.width, np.array([self.up0, self.right1])),
            (self.width + self.height, np.array([self.up1, self.right1])),
            (2.0 * self.width + self.height, np.array([self.up1, self.right0])),
        )
        self._tolerance = 1e-6 * max(grid.spacing, 1.0)

    def at(self, point: np.ndarray) -> float:
        """Where a boundary point sits on the perimeter, in nm of arc length."""
        up, right = float(point[0]), float(point[1])
        if abs(up - self.up0) <= self._tolerance:
            return right - self.right0
        if abs(right - self.right1) <= self._tolerance:
            return self.width + (up - self.up0)
        if abs(up - self.up1) <= self._tolerance:
            return self.width + self.height + (self.right1 - right)
        if abs(right - self.right0) <= self._tolerance:
            return 2.0 * self.width + self.height + (self.up1 - up)
        raise ValueError(
            f"an open contour ended at {up:.3f}, {right:.3f}, which is not on the domain "
            "boundary — marching squares only leaves a contour open where it does"
        )

    def walk(self, start: np.ndarray, end: np.ndarray) -> np.ndarray:
        """The boundary points from `start` to `end`, counter-clockwise, corners included."""
        here = self.at(start)
        there = self.at(end)
        span = (there - here) % self.length
        passed = [
            point
            for offset, point in self.corners
            if 0.0 < (offset - here) % self.length <= span
        ]
        return np.array(passed, dtype=float).reshape(-1, 2)


def _display_names(library: MaterialLibrary | None) -> dict[MaterialId, str]:
    if library is None:
        return {}
    return {key: entry.name for key, entry in library.entries.items()}


@dataclass(frozen=True)
class LightPreview:
    """Where the light goes, drawn from the mask parameters — not from a simulation.

    Roadmap E9 splits lithography into two pictures on purpose, and the *whole
    didactic content is the difference between them*:

    - this one is geometry. Straight rays down through the open parts of the
      mask, stopping at the surface they strike. It knows nothing about dose,
      blur, absorption or the resist, and it is available **before** the step
      runs, from the values sitting in the form;
    - the `exposed` and `dose` overlays are the simulated result, with the
      aerial image's blur and the Beer-Lambert falloff in them, and they always
      colour.

    A student who expects the second to look like the first has just learned what
    an aerial image is. Merging them into one "exposure view" would delete the
    lesson, which is why this is a separate object rather than a seventh overlay:
    an overlay is derived from a `Structure`, and this is derived from a *recipe
    parameter* the sample has never seen.

    Attributes:
        segments: `(N, 2, 2)` ray segments in nm, in the grid's axis order.
        color: `#rrggbb`.
        note: One sentence for the legend.
    """

    segments: np.ndarray | None = None
    color: str = "#fff3bf"
    note: str = ""

    def __bool__(self) -> bool:
        return self.segments is not None and len(self.segments) > 0


def light_preview(
        structure: Structure,
        pattern: np.ndarray,
        *,
        rays_per_opening: int = 5,
) -> LightPreview:
    """Rays through the open parts of `pattern`, down to whatever they hit first.

    `pattern` is the signed-distance field the exposure step would use, sampled
    on the same grid — so this shows the mask that is *about to* be applied,
    which is the point of a preview.

    Each ray stops at the topmost solid cell in its column, because a ray drawn
    through the sample would say the light goes through it. Where a column is
    empty the ray runs to the floor of the domain, which is the honest picture of
    a window with nothing under it.
    """
    grid = structure.grid
    if grid.ndim != 2:
        raise ValueError("the light preview is 2D, like the rest of the rendering")
    open_columns = np.any(np.asarray(pattern) <= 0.0, axis=0)
    if not np.any(open_columns):
        return LightPreview(note="the mask is closed everywhere")

    solid = structure.solid_mask
    rows = np.arange(grid.shape[0]).reshape(-1, 1)
    top_cell = np.where(solid.any(axis=0), np.max(np.where(solid, rows, -1), axis=0), -1)
    top_nm = np.where(
        top_cell >= 0,
        grid.origin[0] + grid.spacing * top_cell,
        grid.extent(0)[0],
    )
    ceiling = grid.extent(0)[1]

    segments = []
    runs = _runs(open_columns)
    for start, stop in runs:
        # Never more rays than the opening has columns: three rays on one column
        # would be a picture claiming three times the light, and a narrow opening
        # is exactly where somebody is looking closely.
        count = max(1, min(int(rays_per_opening), int(stop - start)))
        # Inset by half a ray spacing so the outermost rays sit inside the
        # opening rather than on its edge, where an edge ray would suggest the
        # mask edge is a place light both does and does not reach.
        offsets = (np.arange(count) + 0.5) / count
        for offset in offsets:
            column = int(start + offset * (stop - start))
            column = min(max(column, int(start)), int(stop) - 1)
            x = grid.origin[1] + grid.spacing * column
            segments.append([[ceiling, x], [float(top_nm[column]), x]])
    openings = len(runs)
    return LightPreview(
        segments=np.array(segments, dtype=float) if segments else None,
        note=(
            f"{openings} opening{'s' if openings != 1 else ''} in the mask; "
            "geometry only — no dose, no blur, no absorption"
        ),
    )


def _runs(mask: np.ndarray):
    """`(start, stop)` index pairs of each contiguous True run in a 1-D mask."""
    padded = np.concatenate(([False], np.asarray(mask, dtype=bool), [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return list(zip(edges[0::2], edges[1::2]))


def _clearing_dose(structure: Structure, library: MaterialLibrary | None) -> tuple[float, str]:
    """`(D0, which resist it came from)` for the dose picture — see `DOSE_BANDS`.

    The first resist on the structure that has a develop model, because a
    cross-section with two resists exposed at once is not a thing any recipe in
    this repository builds and inventing a rule for it would be inventing a
    requirement. `(0.0, "")` when nobody can answer, and the caller then falls
    back to the peak — a relative scale is worse than an absolute one and much
    better than no picture.
    """
    if library is None:
        return 0.0, ""
    for key in structure.fields:
        if key.name != "dose" or key.material is None:
            continue
        entry = library.get(key.material)
        if entry is not None and entry.develop is not None:
            return float(entry.develop.clearing_dose), str(key.material)
    return 0.0, ""


def _field_overlay(
        structure: Structure, kind: str, library: MaterialLibrary | None = None
) -> Overlay:
    """`exposed` or `dose` — the latent image, drawn from the field that holds it.

    Roadmap §0 found these fields existed and were rendered nowhere, which made
    the whole ideal/physical split invisible in the application that is supposed
    to teach it. E9 fixes that and asks for the *result* to colour always, with
    the light preview as the separate, optional picture beside it.

    Material-scoped, so a structure with two resists has two of each; they are
    merged into one overlay here because the question a reader has is "what was
    exposed", not "which resist's field says so".
    """
    grid = structure.grid
    color = _OVERLAY_COLORS[kind]
    keys = [key for key in structure.fields if key.name == kind]
    if not keys:
        return Overlay(kind, "", color, note="")
    # Clipped to the material each field is scoped to. `expose_ideal` writes over
    # the whole grid on purpose — the commit gate's scoping rule is what keeps
    # the field meaningful (plan §3.3) — but a *picture* of a latent image
    # floating in empty space above the resist is a picture of nothing.
    planes = []
    for key in keys:
        values = np.asarray(structure.field(key), dtype=np.float64)
        if key.material is not None and key.material in structure.phi:
            values = np.where(structure.inside(key.material), values, 0.0)
        planes.append(values)
    stacked = np.maximum.reduce(planes)
    if kind == "exposed":
        # E28: a flat translucent area, not a contour. `exposed` is binary — it
        # has one value and nothing to grade — and an outline of it read as a
        # *shape*, which is exactly the thing a latent image is not.
        mask = stacked > 0.5
        struck = int(np.count_nonzero(mask))
        return Overlay(
            kind,
            "Exposed" if struck else "",
            color,
            filled=True,
            bands=(
                (OverlayBand("struck by the pattern", _mask_outlines(grid, mask), 0.35),)
                if struck
                else ()
            ),
            note=f"{struck} cells the pattern struck",
        )
    peak = float(np.max(stacked))
    if peak <= 0.0:
        return Overlay(kind, "Dose", color, note="no dose anywhere")

    reference, resist = _clearing_dose(structure, library)
    unit = "D0" if reference > 0.0 else "peak"
    scale = reference if reference > 0.0 else peak
    edges = [level * scale for level in DOSE_BANDS]

    bands: list[OverlayBand] = []
    lows = [0.0] + edges
    highs = edges + [float("inf")]
    for index, (low, high) in enumerate(zip(lows, highs)):
        region = (stacked > low) & (stacked <= high) if np.isfinite(high) else stacked > low
        if not region.any():
            continue
        # Monotonic in dose, so darker always means more without reading the key.
        shade = _UNDOSED_SHADE + (0.75 - _UNDOSED_SHADE) * index / max(1, len(lows) - 1)
        edge = "over" if np.isinf(high) else f"{low / scale:.2g}-{high / scale:.2g}"
        bands.append(OverlayBand(f"{edge} {unit}", _mask_outlines(grid, region), shade))

    # The one *line*, and the only one: the clearing-dose contour is where the
    # developer will actually cut, so it predicts the edge the next step makes.
    # Every other iso-dose line is decoration next to that.
    contour = tuple(
        fillable_outlines(grid, contour_kernel.marching_squares(grid, scale - stacked))
    )
    where = f" of {resist}" if resist else ""
    return Overlay(
        kind,
        "Dose",
        color,
        outlines=contour,
        bands=tuple(bands),
        note=(
            f"bands of {', '.join(f'{level:g}' for level in DOSE_BANDS)} x the "
            f"clearing dose{where} ({scale:.0f} mJ/cm^2); the line is D0, where "
            "development will cut"
            if reference > 0.0
            else f"no clearing dose in the library — bands are fractions of the "
                 f"peak {peak:.0f} mJ/cm^2"
        ),
    )


def _overlay(
        structure: Structure, kind: str, library: MaterialLibrary | None = None
) -> Overlay:
    """Compute one inspect overlay (plan §10's "predicate highlights")."""
    grid = structure.grid
    color = _OVERLAY_COLORS[kind]
    if kind in ALWAYS_ON:
        return _field_overlay(structure, kind, library)
    if kind in ("reachable", "voids"):
        # `solid_phi` is the right field for a *connectivity* question even
        # though §17.1 forbids reading geometry off it: what is read here is the
        # sign, and a buried seam reads exactly zero, i.e. solid — which is the
        # answer connectivity wants. `kernel.predicates` passes the same field
        # for the same reason. It is the *normals* overlay below that needs
        # `motion.union_front`, because that one reads a gradient.
        reachable = predicates.reachable_empty(grid, structure.solid_phi)
        if kind == "reachable":
            return Overlay(
                kind,
                "Reachable from outside",
                color,
                outlines=_mask_outlines(grid, reachable),
                note=f"{int(np.count_nonzero(reachable))} cells a bath can touch",
            )
        sealed = ~structure.solid_mask & ~reachable
        voids = predicates.enclosed_voids(structure)
        return Overlay(
            kind,
            "Enclosed voids",
            color,
            outlines=_mask_outlines(grid, sealed),
            note=f"{len(voids)} sealed cavit{'y' if len(voids) == 1 else 'ies'}",
        )
    if kind == "unsupported":
        mask = predicates.unsupported(structure)
        return Overlay(
            kind,
            "Not connected to the wafer",
            color,
            outlines=_mask_outlines(grid, mask),
            note=f"{int(np.count_nonzero(mask))} cells nothing holds up",
        )
    segments = surface_normals(structure)
    return Overlay(
        kind,
        "Surface normals",
        color,
        segments=segments,
        note=f"{0 if segments is None else len(segments)} samples along the front",
    )


def _mask_outlines(grid: Grid, mask: np.ndarray) -> tuple[np.ndarray, ...]:
    """Outlines of a cell mask, for an overlay.

    Cell-quantised on purpose: a predicate answers in cells, and drawing its
    answer with a sub-cell smooth boundary would claim a precision the predicate
    does not have. That is the opposite choice from a material's outline, and it
    is the same reasoning.
    """
    from nanofab_v3.kernel import regions

    if not np.any(mask):
        return ()
    field = regions.signed_distance_of(grid, mask)
    return tuple(contour_kernel.marching_squares(grid, field))


def surface_normals(structure: Structure, *, samples: int = 48) -> np.ndarray | None:
    """Outward normals sampled along the solid front, as `(N, 2, 2)` segments in nm.

    Read off `motion.union_front` rather than `structure.solid_phi`: where two
    materials touch, the union field is exactly zero along their buried seam
    (§17.1), so its gradient there is the gradient of a seam and the arrows would
    point out of the middle of continuous material. Third milestone this has bitten
    something; the renderer is the place the handoff predicted it would bite next.

    Sampled rather than dense, and that is handoff §4.3's finding applied: the
    front is a curve and the domain is an area, so an arrow per front cell is
    thousands of arrows nobody can read and 650 000 cells of gradient nobody
    needed.
    """
    from nanofab_v3.kernel import motion

    grid = structure.grid
    if not structure.materials:
        return None
    front = motion.union_front(structure)
    outlines = contour_kernel.marching_squares(grid, front)
    if not outlines:
        return None
    gradients = np.gradient(np.asarray(front, dtype=np.float64), grid.spacing)
    points = np.concatenate([line[:-1] for line in outlines if len(line) > 1], axis=0)
    if len(points) == 0:
        return None
    take = max(1, len(points) // max(1, samples))
    points = points[::take]
    cells = np.clip(
        np.round((points - np.asarray(grid.origin)) / grid.spacing).astype(int),
        0,
        np.asarray(grid.shape) - 1,
    )
    normal = np.stack([g[cells[:, 0], cells[:, 1]] for g in gradients], axis=1)
    length = np.linalg.norm(normal, axis=1, keepdims=True)
    normal = np.divide(normal, np.where(length == 0.0, 1.0, length))
    tip = points + normal * (6.0 * grid.spacing)
    return np.stack([points, tip], axis=1)


# -- how a domain is fitted into a widget (roadmap E8) ------------------------

ASPECT_LIMIT = 4.0
"""How far from square a picture may be drawn before its long axis is compressed.

Roadmap E8: *"automatisch maßstabsgetreu bis ~4:1, darüber gestaucht — mit
permanent sichtbarem Verzerrungsfaktor und einem Knopf zum Umschalten"*.
"""


@dataclass(frozen=True)
class DisplayScale:
    """The nm-to-pixel scale of each axis, and how much they disagree.

    Attributes:
        up: Pixels per nm along the stacking axis (drawn upwards).
        right: Pixels per nm along the lateral axis.
        distortion: `right / up`. Exactly 1 means true to scale.
    """

    up: float
    right: float

    @property
    def distortion(self) -> float:
        return self.right / self.up

    @property
    def true_to_scale(self) -> bool:
        """Whether a flank angle read off this picture is the flank's real angle."""
        return abs(self.distortion - 1.0) < 1e-9

    def describe(self) -> str:
        """The label E8 wants permanently visible — never absent, never silent."""
        if self.true_to_scale:
            return "1:1 true to scale"
        factor = self.distortion if self.distortion > 1.0 else 1.0 / self.distortion
        squeezed = "vertical" if self.distortion > 1.0 else "horizontal"
        return f"{factor:.2f}x compressed {squeezed}ly — angles are not true"


def display_scale(
        span_up: float,
        span_right: float,
        usable_up: float,
        usable_right: float,
        *,
        limit: float = ASPECT_LIMIT,
        isotropic: bool = False,
) -> DisplayScale:
    """Fit a domain into a widget, compressing its long axis only past `limit`.

    Roadmap E8's rule, and its reasoning is worth keeping next to the arithmetic:
    **a silently compressed etch flank is worse for a didactic tool than an
    awkward view**, because flank angles are exactly what is being judged. So a
    domain within `limit` of square is drawn true to scale and a more extreme one
    has its *long* axis compressed until the picture is `limit:1` — never more,
    and never without saying so (`DisplayScale.describe`).

    A 1200 x 240 nm cross-section is 5:1 and therefore drawn with a 1.25x
    vertical exaggeration; a 250 nm x 5 um one would otherwise be a sliver. The
    factor is reported either way, and `isotropic=True` is the button that turns
    the whole thing off.
    """
    if min(span_up, span_right, usable_up, usable_right) <= 0.0:
        raise ValueError("a display scale needs positive spans")
    aspect = span_right / span_up
    target = aspect if isotropic else min(max(aspect, 1.0 / limit), limit)
    ratio = target / aspect
    up = min(usable_right / (span_right * ratio), usable_up / span_up)
    return DisplayScale(up=up, right=up * ratio)
