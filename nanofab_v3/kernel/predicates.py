"""Predicates: what the geometry says about itself (plan §7, §4.4).

Interview decision I6 — *geometry is the truth, diagnoses are predicates
evaluated on it* — is what this module implements. Nothing here changes a
`Structure`; everything here answers a question about one, and the answers are
the didactic payload: "the resist cannot be reached", "this metal is not
supported", "the trench pinched off", "the etch undercut the mask by 1.2x its
depth".

Two of them are also **kernel steps**, and that is the whole reason the module
sits in `kernel/` rather than beside the processes (plan §4.4: "Both are
predicates as well as kernel steps — same functions"):

- **Reachability** — which empty space connects to the outside world. A wet
  process acts only on material adjacent to it, so `ReachableFront` below is a
  `motion.FrontFlux` and gates a rate-driven process exactly the way the flux
  model does. S3's failure *is* this query returning "the resist is unreachable".
- **Support** — which solid connects to the substrate. Lift-off is dissolution
  followed by removing what support this query no longer finds, and S4's fences
  survive because they are attached to the film.

Writing them once is the point. A second implementation of "which components
touch the top" inside a process would be a second definition of reachability, and
the two would diverge on the first re-entrant profile.

Connectivity is face connectivity, inherited from `occurrences.label_region`, and
every mask is taken from `structure.solid_mask` — **never** from a strict
`solid_phi < 0`. Where two materials touch, the union field is exactly zero along
their shared interface (§17.1), and a strict test opens a one-cell crack through
continuous material that every query in this module would read as a passage.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from scipy import ndimage

from nanofab_v3.kernel import measures, occurrences, regions
from nanofab_v3.materials import MaterialId
from nanofab_v3.model.grid import PHI_DTYPE, Grid
from nanofab_v3.model.structure import Structure

_COLLAR_CELLS = 12
"""Cells the reachability gate is carried past the front, as `flux` does (§18.5).

A velocity extension is only valid near the front — the same finding, in the same
place. Extended over the whole domain, a cell deep inside a wall would be handed
the gate value of whatever front happens to be nearest and would start moving;
beyond the collar the value is zero and the cell is frozen, which is what a
narrow-band solver does. The number is `flux._EXTENSION_CELLS`, deliberately: the
two collars answer the same question about the same front.
"""


# -- which faces are "outside" ------------------------------------------------


def open_faces(grid: Grid) -> tuple[tuple[str, str], ...]:
    """The domain faces a reactant arrives through — the max face of axis 0.

    The convention the whole package already runs on: the first axis is the
    stacking direction and grows upward, so its max face is the headroom above
    the sample (plan §3.1) and its min face is "solid continues" (the wafer).
    The gate's headroom guard reads the same face for the same reason (§17.5).

    Lateral faces are deliberately **not** open. A cross-section continues
    sideways, so empty space touching `x-min` is neither clearly connected to the
    bath nor clearly sealed off — and guessing "connected" would make a sealed
    cavity reachable the moment it happened to reach the domain edge, which is a
    property of where the window was cropped and not of the sample. A scene that
    needs a lateral bath says so by passing `faces` explicitly.
    """
    return ((grid.axes[0], "max"),)


def _face_mask(grid: Grid, faces: Sequence[tuple[str, str]]) -> np.ndarray:
    """Boolean mask of the cells lying on the named domain faces."""
    mask = np.zeros(grid.shape, dtype=bool)
    for axis, side in faces:
        index = grid.axis_index(axis)
        if side not in ("min", "max"):
            raise ValueError(f"face side must be 'min' or 'max', got {side!r}")
        selector: list[slice | int] = [slice(None)] * grid.ndim
        selector[index] = 0 if side == "min" else grid.shape[index] - 1
        mask[tuple(selector)] = True
    return mask


def _front_window(grid: Grid, front: np.ndarray, margin: int) -> tuple[slice, ...]:
    """A box around the front, grown by `margin` cells and clipped to the domain.

    Everything the collar needs is within `margin` of a front cell, so the
    distance transform that builds it has no business running over the headroom
    and the bulk of the wafer as well.
    """
    extents = np.argwhere(front)
    lower = np.maximum(extents.min(axis=0) - margin, 0)
    upper = np.minimum(extents.max(axis=0) + margin + 1, np.array(grid.shape))
    return tuple(slice(int(a), int(b)) for a, b in zip(lower, upper))


def _components_touching(
    labels: np.ndarray, count: int, seeds: np.ndarray
) -> np.ndarray:
    """Mask of the labelled components that contain at least one seed cell."""
    if count == 0:
        return np.zeros(labels.shape, dtype=bool)
    touched = np.unique(labels[seeds & (labels > 0)])
    if touched.size == 0:
        return np.zeros(labels.shape, dtype=bool)
    return np.isin(labels, touched)


def cells_of(structure: Structure, material: MaterialId) -> np.ndarray:
    """The **closed** region of one material — §17.1's other half.

    Not `Structure.inside`, and the difference is one cell wide and decides every
    answer in this module. A constructor samples exactly on the grid, so a
    material's own boundary cells read `phi_m == 0`; `inside` is strict, because
    that is what keeps two touching materials' *interiors* disjoint. But a
    reachability query asks a different question — "can the bath touch this
    material" — and the cell the bath touches first is exactly the one `inside`
    leaves out.

    Measured on the T-profile fixture: with `inside`, a solvent standing in the
    mouth is two cells away from the nearest resist cell it is allowed to see, and
    `is_reachable(resist)` comes back `False` for a profile that is wide open.

    It is not `phi_m <= 0` either — see `regions.closed_region`, which this
    delegates to: a carved field is exactly zero along interfaces between *other*
    materials, and a value test would put the whole domain inside the resist.

    The closed regions of two touching materials share their interface cell, so
    this is not a partition (`Structure.material_index` is). That is right here:
    both materials really are present in that cell, and both really are wet.
    """
    return regions.closed_region(structure.grid, structure.phi_of(material))


# -- reachability -------------------------------------------------------------


def reachable_empty(
    grid: Grid, solid: np.ndarray, *, faces: Sequence[tuple[str, str]] | None = None
) -> np.ndarray:
    """Empty cells connected to the outside world through empty space.

    Works on a bare union field rather than on a `Structure` so the motion solver
    can call it mid-step, when there is no `Structure` yet — the same reason
    `motion.FrontFlux.on_front` takes `(grid, solid)`.
    """
    empty = np.asarray(solid) > 0.0
    labels, count = occurrences.label_region(grid, empty)
    seeds = _face_mask(grid, open_faces(grid) if faces is None else tuple(faces))
    return _components_touching(labels, count, seeds & empty)


def reachable_surface(
    grid: Grid, solid: np.ndarray, *, faces: Sequence[tuple[str, str]] | None = None
) -> np.ndarray:
    """Cells a bath can act on: reachable empty space and the solid it touches.

    One dilation wide, because "a wet process acts on material cells *adjacent to*
    reachable empty space" (plan §4.4) — the solvent is in the empty cell and the
    material it attacks is its neighbour.
    """
    reachable = reachable_empty(grid, solid, faces=faces)
    if not reachable.any():
        return reachable
    return ndimage.binary_dilation(
        reachable, ndimage.generate_binary_structure(grid.ndim, 1)
    )


def is_reachable(
    structure: Structure,
    material: MaterialId,
    *,
    faces: Sequence[tuple[str, str]] | None = None,
) -> bool:
    """Whether any of `material` can be touched from outside — S3's question.

    The whole of scenario S3 in one call: after a conformal film has sealed the
    resist sidewalls, this is `False`, and every wet process that consults it
    becomes a no-op without a single line of special-casing.
    """
    if material not in structure.phi:
        return False
    wet = reachable_surface(structure.grid, structure.solid_phi, faces=faces)
    return bool(np.any(wet & cells_of(structure, material)))


def reachable_occurrences(
    structure: Structure,
    material: MaterialId,
    *,
    faces: Sequence[tuple[str, str]] | None = None,
) -> np.ndarray:
    """Mask of the cells of `material` whose whole occurrence a bath can reach.

    Per **occurrence**, not per cell: a solvent that reaches one corner of a
    connected piece of resist dissolves the piece, not the corner. That is the
    difference between the ideal tier and the rate tier — the rate tier eats
    inward from the surface it can touch and would stall at the first constriction
    — and it is why the ideal tier is a single set operation (see
    `regions.remove_region`).
    """
    if material not in structure.phi:
        return np.zeros(structure.grid.shape, dtype=bool)
    region = cells_of(structure, material)
    labels, count = occurrences.label_region(structure.grid, region)
    wet = reachable_surface(structure.grid, structure.solid_phi, faces=faces)
    return _components_touching(labels, count, wet & region)


@dataclass(frozen=True)
class ReachableFront:
    """Reachability as a `motion.FrontFlux` — the gate a rate-driven process runs behind.

    Plan §4.4 says a wet process "only acts on material cells adjacent to
    reachable empty space". For the *ideal* tier that is a region operation
    (`regions.remove_region`, one exact set operation, no sub-stepping). For the
    **rate** tier it has to be a multiplier on the speed field, because the front
    moves and the answer changes while it does: dissolving resist opens paths that
    were closed, and a gate computed once at the start would keep eating a cavity
    it can no longer reach.

    So it is shaped exactly like `flux.FluxModel2D` — `max_arrival` for the CFL
    bound before the first sub-step, `on_front` for the per-cell multiplier — and
    `advect_front` rebuilds it on the same cadence as the visibility, for the same
    reason: both answer "where are the walls", and neither changes as fast as the
    front moves.

    Unlike the flux model this one is **N-D generic**: it is connectivity, not
    ray tracing, and `ndimage.label` and the distance transform are both N-D. The
    package has exactly two 2D-only seams (`contours`, `flux`) and this is
    deliberately not a third.

    Attributes:
        faces: Domain faces the bath arrives through; `None` = `open_faces`.
        collar_cells: How far past the front the gate value is carried (§18.5).
        floor: Multiplier for unreachable front, normally 0. A small positive
            value is the honest way to say "the bath seeps in slowly", and is
            what a swelling resist would need — plan §16 leaves that open.
    """

    faces: tuple[tuple[str, str], ...] | None = None
    collar_cells: int = _COLLAR_CELLS
    floor: float = 0.0

    def __post_init__(self) -> None:
        if not 0.0 <= float(self.floor) <= 1.0:
            raise ValueError(f"floor must be in [0, 1], got {self.floor}")
        if int(self.collar_cells) < 1:
            raise ValueError(f"collar_cells must be at least 1, got {self.collar_cells}")

    @property
    def max_arrival(self) -> float:
        """1.0 — the gate multiplies a rate, it never amplifies one."""
        return 1.0

    def on_front(self, grid: Grid, solid: np.ndarray) -> np.ndarray:
        """1 where the front can be reached from outside, `floor` where it cannot."""
        union = grid.as_field(solid, dtype=PHI_DTYPE)
        front = np.abs(union) < grid.spacing
        arrival = np.zeros(grid.shape, dtype=np.float64)
        if not front.any():
            return arrival
        # Reachability itself is global — a path from the top of the domain to a
        # cavity can run anywhere — so the labelling reads the whole field. It is
        # the cheap half: ~5 ms at the reference grid against ~48 ms for the
        # collar's distance transform over the same domain.
        wet = reachable_surface(grid, union, faces=self.faces)
        values = np.where(front & wet, 1.0, float(self.floor))
        # The collar: carry each cell's value in from the nearest front cell, and
        # freeze everything beyond it (§18.5). Without the extension the front
        # would be handed a speed on one side of the zero level and none on the
        # other, and the upwind stencil would read the discontinuity as a kink.
        #
        # The front is a curve and the domain is an area, so the transform runs
        # in a box around the front rather than over the whole field — the same
        # windowing `flux._Window` does, for the same reason and the same saving.
        window = _front_window(grid, front, int(self.collar_cells) + 1)
        local_front = front[window]
        distance, indices = ndimage.distance_transform_edt(
            ~local_front, sampling=grid.spacing, return_indices=True
        )
        within = distance <= float(self.collar_cells) * grid.spacing
        arrival[window] = np.where(within, values[window][tuple(indices)], 0.0)
        return arrival


# -- support ------------------------------------------------------------------


def supported(
    structure: Structure,
    *,
    faces: Sequence[tuple[str, str]] | None = None,
    anchor: MaterialId | None = None,
) -> np.ndarray:
    """Solid cells belonging to a component that reaches the wafer.

    "The wafer" is the min face of the stacking axis by default — the boundary
    condition that says the substrate continues below the domain (plan §3.1). An
    `anchor` material is the alternative for a scene whose substrate does not
    reach the domain floor: any component containing that material counts as
    supported.
    """
    grid = structure.grid
    solid = structure.solid_mask
    labels, count = occurrences.label_region(grid, solid)
    seeds = _face_mask(grid, ((grid.axes[0], "min"),) if faces is None else tuple(faces))
    seeds = seeds & solid
    if anchor is not None and anchor in structure.phi:
        seeds = seeds | structure.inside(anchor)
    return _components_touching(labels, count, seeds)


def unsupported(
    structure: Structure,
    *,
    faces: Sequence[tuple[str, str]] | None = None,
    anchor: MaterialId | None = None,
) -> np.ndarray:
    """Solid cells no longer connected to the wafer — what lift-off carries away.

    The complement of `supported` within the solid. After the resist of S1 has
    dissolved this is exactly the metal that was sitting on it; after S4's it is
    exactly the metal that was *not* touching the film on the substrate.
    """
    return structure.solid_mask & ~supported(structure, faces=faces, anchor=anchor)


# -- enclosed voids -----------------------------------------------------------


@dataclass(frozen=True)
class Void:
    """One enclosed empty region — a pinch-off, a keyhole, a sealed cavity.

    Attributes:
        cells: Cell count of the void.
        measure: Its area (2D) / volume (3D) in nm^ndim.
        centroid: Its centre of mass in nm, per axis.
    """

    cells: int
    measure: float
    centroid: tuple[float, ...]


def enclosed_voids(
    structure: Structure, *, faces: Sequence[tuple[str, str]] | None = None
) -> tuple[Void, ...]:
    """Every empty component the outside world cannot reach, largest first.

    The pinch-off / keyhole predicate of plan §7, and the same query as
    reachability read the other way round. A conformal deposition closing a
    re-entrant mouth produces one of these and nothing in the kernel had to know
    what a mouth is — the topology change *is* `ndimage.label` returning a
    component that no longer touches the top.
    """
    grid = structure.grid
    empty = ~structure.solid_mask
    labels, count = occurrences.label_region(grid, empty)
    if count == 0:
        return ()
    seeds = _face_mask(grid, open_faces(grid) if faces is None else tuple(faces))
    reachable = _components_touching(labels, count, seeds & empty)
    sealed = np.where(reachable, 0, labels)
    remaining = [label for label in np.unique(sealed) if label != 0]
    if not remaining:
        return ()
    cells = ndimage.sum_labels(np.ones(grid.shape), sealed, index=remaining)
    centres = ndimage.center_of_mass(sealed > 0, sealed, remaining)
    voids = [
        Void(
            cells=int(count_of),
            measure=float(count_of) * grid.cell_measure,
            centroid=tuple(
                origin + grid.spacing * float(index) for origin, index in zip(grid.origin, centre)
            ),
        )
        for count_of, centre in zip(np.atleast_1d(cells), centres)
    ]
    return tuple(sorted(voids, key=lambda void: void.cells, reverse=True))


# -- undercut -----------------------------------------------------------------


@dataclass(frozen=True)
class Undercut:
    """How far a removal ran sideways under a mask, against how deep it went.

    `CONTEXT.md`: undercut is "material removed laterally beneath a masking layer,
    so the mask overhangs the feature it defined... the signature of an isotropic
    removal component; a purely directional etch produces none". This turns that
    sentence into a number, which is what scenario S2 asserts.

    Attributes:
        lateral: Furthest the empty space reaches under the mask's footprint,
            measured from the nearest edge of that footprint, in nm.
        vertical: How far the front dropped below the mask's underside, in nm.
        ratio: `lateral / vertical` — 0 for a purely directional etch, ~1 for a
            purely isotropic one, because an isotropic front is a circle centred
            on the mask edge and a circle's radius is the same in both directions.
    """

    lateral: float
    vertical: float

    @property
    def ratio(self) -> float:
        """Lateral over vertical; 0.0 when nothing was etched at all."""
        if self.vertical <= 0.0:
            return 0.0
        return self.lateral / self.vertical


def undercut(
    structure: Structure, mask: MaterialId, *, axis: str | int = 0
) -> Undercut:
    """Measure the undercut beneath `mask` (plan §7), N-D generic.

    `axis` is the stacking direction; the remaining axes are lateral. The mask's
    **footprint** is its projection along that axis — the columns it covers — and
    the measurement is taken entirely from the current revision:

    - `lateral` is the deepest any empty cell has got into that footprint,
      measured as the distance from the footprint's own edge. A distance
      transform over the footprint gives that in one pass and in any dimension.
    - `vertical` is how far below the mask's underside the empty space reaches in
      the *open* window next to it.

    Only empty space **below the mask's underside** counts: the headroom above the
    sample is empty too, and is not an undercut.
    """
    grid = structure.grid
    index = grid.axis_index(axis)
    if mask not in structure.phi:
        raise KeyError(f"no material {mask!r} in this Structure")
    mask_cells = cells_of(structure, mask)
    if not mask_cells.any():
        return Undercut(lateral=0.0, vertical=0.0)

    footprint = np.any(mask_cells, axis=index)  # (lateral axes)
    # The mask's underside, per lateral position: the lowest index it occupies.
    stacking = np.arange(grid.shape[index]).reshape(
        [-1 if a == index else 1 for a in range(grid.ndim)]
    )
    underside = np.min(np.where(mask_cells, stacking, grid.shape[index]), axis=index)

    empty = ~structure.solid_mask
    below = stacking < np.expand_dims(underside, index)
    empty_below = empty & below

    # Lateral: how far into the footprint the empty space has reached.
    into = ndimage.distance_transform_edt(footprint, sampling=grid.spacing)
    under_mask = np.any(empty_below, axis=index) & footprint
    lateral = float(np.max(into[under_mask])) if np.any(under_mask) else 0.0

    # Vertical: the deepest empty cell in the open window, below the mask plane.
    plane = int(np.min(underside[footprint])) if np.any(footprint) else grid.shape[index]
    open_columns = ~footprint
    floor_depth = 0.0
    if np.any(open_columns):
        window = empty & np.expand_dims(open_columns, index) & (stacking < plane)
        if np.any(window):
            deepest = int(np.min(np.where(window, stacking, grid.shape[index])))
            floor_depth = float(plane - deepest) * grid.spacing
    return Undercut(lateral=lateral, vertical=floor_depth)


# -- step coverage ------------------------------------------------------------


@dataclass(frozen=True)
class StepCoverage:
    """Thinnest against nominal film thickness — how well a deposit wrapped a step.

    Attributes:
        nominal: Thickness on the open, flat part of the front, in nm.
        minimum: Thinnest place the film reaches anywhere, in nm.
        ratio: `minimum / nominal`. 1 is conformal (`CONTEXT.md`: "equal layer
            thickness on every reachable surface"), 0 means the film is
            discontinuous — which is what makes S1's lift-off work and S4's
            fences stand.
        continuous: Whether the film is one occurrence.
    """

    nominal: float
    minimum: float
    continuous: bool

    @property
    def ratio(self) -> float:
        """Minimum over nominal; 0.0 when nothing was deposited."""
        if self.nominal <= 0.0:
            return 0.0
        return self.minimum / self.nominal


def step_coverage(
    structure: Structure, material: MaterialId, *, nominal: float | None = None
) -> StepCoverage:
    """Measure how evenly `material` covers the surface it was deposited on.

    Thickness at a cell is `-phi` at the film's own medial axis — the deepest
    point inside the film is half its local thickness away from both surfaces, so
    `2 * max(-phi)` over a local neighbourhood is the local thickness. Taken
    globally, `2 * max(-phi)` is the thickest place and `2 * min over the film's
    ridge` the thinnest.

    Rather than reconstruct the ridge, this reads the film's own distance field
    where it is locally deepest: a cell is on the ridge when no neighbour is
    deeper. That is `ndimage.maximum_filter` on `-phi`, one pass, N-D.

    `nominal` overrides the measured open-surface thickness — the honest thing to
    pass is what the process was *asked* to deposit, because on a scene with no
    flat open surface there is nothing to measure it against.
    """
    grid = structure.grid
    if material not in structure.phi:
        return StepCoverage(nominal=0.0, minimum=0.0, continuous=False)
    depth = -np.asarray(structure.phi_of(material), dtype=np.float64)
    inside = depth > 0.0
    if not inside.any():
        return StepCoverage(nominal=0.0, minimum=0.0, continuous=False)

    peaks = depth >= ndimage.maximum_filter(depth, size=3, mode="nearest") - 1e-6
    ridge = peaks & inside
    if not ridge.any():
        ridge = inside
    thickness = 2.0 * depth[ridge]
    measured_nominal = float(np.max(thickness)) if nominal is None else float(nominal)
    _, components = occurrences.label_region(grid, inside)
    return StepCoverage(
        nominal=measured_nominal,
        minimum=float(np.min(thickness)),
        continuous=components == 1,
    )


# -- summary ------------------------------------------------------------------


def film_thickness(structure: Structure, material: MaterialId) -> float:
    """Mean thickness of `material` — its measure divided by its lateral extent.

    The number a UI puts next to a layer, and the one an ellipsometer would
    report. Derived, never stored: plan §3.6 keeps no 1D layer list, and "where
    the UI wants a stack summary, it is derived".
    """
    grid = structure.grid
    if material not in structure.phi:
        return 0.0
    area = measures.enclosed_measure(grid, structure.phi_of(material))
    footprint = np.any(structure.inside(material), axis=0)
    width = float(np.count_nonzero(footprint)) * grid.spacing ** (grid.ndim - 1)
    if width <= 0.0 or not math.isfinite(width):
        return 0.0
    return area / width
