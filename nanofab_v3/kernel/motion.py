"""Front motion: the isotropic fast path and the general advection (plan §4.2).

Only the exposed union front ever moves. Buried interfaces are never advected —
materials are maintained by clipping against the new union — so they keep their
sub-cell shape until a later step re-exposes them, which is the whole reason for
per-material fields (ADR-0002).

Two paths, one contract:

- **Isotropic fast path** (`offset_solid`) — when the motion is isotropic and the
  rate uniform over the affected front, offsetting is exact and instant:
  `phi <- phi -/+ rate * t`, one array operation. Splitting a dose is exact here.
- **General path** (`advect_front`) — first-order upwind advection of the union
  front with the speed field `F(x) = sign * rate(material_at_front(x)) * flux(x)`,
  sub-stepped under the CFL condition `dt <= cfl * spacing / max|F|`.

Sub-stepping is **internal** (plan Q6): the user's "etch 10 s" is one chain step,
and the solver divides it invisibly. The speed field is rebuilt from the current
front every sub-step, so etching through material A into B switches rates by
itself — and a material with rate 0 simply stalls the front there. **Mask
behaviour emerges from rates**; it is not a special case anywhere in this module.

Material bookkeeping after each move (plan §3.2):

    etch:    phi_m <- max(phi_m, phi_solid_new)                 for every material
    deposit: phi_k <- min(phi_k, max(phi_solid_new, -phi_solid_old))
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Protocol, runtime_checkable

import numpy as np
from scipy import ndimage

from nanofab_v3.kernel import invariants, measures, reinit, stencil
from nanofab_v3.materials import MaterialId
from nanofab_v3.model.grid import PHI_DTYPE, Grid
from nanofab_v3.model.structure import Structure

_GRADIENT_QUANTILE = 0.99
"""Quantile the distortion trigger reads (see `nanofab_v3.kernel.invariants`)."""

_OWNER_REFRESH = 5
"""Sub-steps between two extensions of the front-material map into empty space.

A solver constant, like the flux solver's rebuild interval in plan §4.3: the
solid half of that map is exact every sub-step, and the half that says where the
surrounding walls are changes far more slowly than the front moves.
"""

_FLUX_REFRESH = _OWNER_REFRESH
"""Sub-steps between two flux rebuilds — plan §4.3's `K`, deliberately shared.

Both maps answer the same question, "where are the walls": one turns it into
which material owns a piece of empty space, the other into what a piece of front
can see. Neither changes as fast as the front moves, so they are refreshed at
the same sub-steps rather than on two independent cadences.

`K` is a cost knob and not an accuracy one, but only because the visibility is
honest cell by cell. While the flux solver's hit test read the field at the
nearest cell, `K` was the dominant *accuracy* knob instead — a stale arrival at
a mask's concave foot was spread over the wedge of material the mask shadows,
and a 30 nm ion-beam etch through a 40 nm window ran 14 nm sideways under the
mask at `K = 5` against 3 nm at `K = 1`. With the bilinear hit test
(`_SELF_HIT_NOTE` in `kernel.flux`) the same measurement reads 0 nm at `K = 1..3`
and 1 nm at `K = 5`, i.e. inside the cell the grid owes anyway. Plan §4.3's
`K = 5..10` therefore stands; §18.1 records the measurement.
"""


@runtime_checkable
class FrontFlux(Protocol):
    """What `advect_front` needs from a flux model — `kernel.flux.FluxModel2D` is one.

    Structural, not an import: the motion solver is N-D generic and the flux
    solver is a named 2D-only seam (plan §4.3, Q7). Depending on it by name would
    drag that restriction into the one module that must not have it.

    `max_arrival` has to be available *before* the first sub-step, because it is
    what bounds the speed field for the CFL condition — measuring it off the
    front instead would make a split dose take different sub-steps than an
    unsplit one.
    """

    @property
    def max_arrival(self) -> float:
        """Largest arrival per unit front any surface orientation could receive."""

    def on_front(self, grid: Grid, solid: np.ndarray) -> np.ndarray:
        """Arrival per cell for the current union field, non-negative."""


@dataclass(frozen=True)
class ProductFlux:
    """Several `FrontFlux` models multiplied cell by cell.

    What it is for: a process whose speed field has more than one per-cell factor.
    An RIE is a directional lobe *and* a reachability gate — the lobe decides what
    a surface can see of the source, the gate decides whether the bath reaches it
    at all — and §18's note on the chemical floor says why the two are not the
    same question: the floor is deliberately orientation-blind, so it keeps
    feeding a cavity that has sealed itself unless something else says otherwise.

    The bound multiplies too, which is what keeps the CFL sub-step count
    independent of the front: each factor bounds itself before the first sub-step
    (`FluxModel2D.max_arrival`, `ReachableFront.max_arrival`), so their product
    bounds the speed field the same way.

    Deliberately not a special case inside `advect_front`: the solver already
    takes any object with the two members, so composition belongs to whoever is
    composing.
    """

    models: tuple[FrontFlux, ...]

    def __post_init__(self) -> None:
        if not self.models:
            raise ValueError("ProductFlux needs at least one model")

    @property
    def max_arrival(self) -> float:
        """The product of the factors' bounds."""
        bound = 1.0
        for model in self.models:
            bound *= float(model.max_arrival)
        return bound

    def on_front(self, grid: Grid, solid: np.ndarray) -> np.ndarray:
        """The factors' arrivals, multiplied cell by cell."""
        product = np.asarray(self.models[0].on_front(grid, solid), dtype=np.float64)
        for model in self.models[1:]:
            product = product * np.asarray(model.on_front(grid, solid), dtype=np.float64)
        return product


def gated(*models: FrontFlux | None) -> FrontFlux | None:
    """Combine flux factors, dropping the `None`s — `None` if nothing is left.

    The shape every process wrapper wants: "the technique's flux, and the
    reachability gate if this process is gated", where either may be absent.
    """
    present = tuple(model for model in models if model is not None)
    if not present:
        return None
    if len(present) == 1:
        return present[0]
    return ProductFlux(present)


@dataclass(frozen=True)
class SurfaceRates:
    """`rate(material_at_front)` in nm/s — the material half of the speed field.

    Attributes:
        rates: Rate per material at the front, in nm/s.
        default: Rate for a material that is not listed. The default default is
            0.0: a material nobody gave a rate to does not move, which is how a
            hard mask behaves without being modelled as one.
    """

    rates: Mapping[MaterialId, float] = field(default_factory=dict)
    default: float = 0.0

    def for_material(self, material: MaterialId) -> float:
        """The rate of one material, falling back to `default`."""
        return float(self.rates.get(material, self.default))

    @property
    def bound(self) -> float:
        """The largest rate that can occur, in nm/s — the CFL condition's input.

        Taken over every listed rate and the default rather than over the
        materials currently at the front, so the sub-step size does not depend on
        where the front happens to be. That is what keeps a split dose comparable
        to an unsplit one.
        """
        return max([abs(self.default), *(abs(float(r)) for r in self.rates.values())])

    def map_onto(self, grid: Grid, materials: list[MaterialId], nearest: np.ndarray) -> np.ndarray:
        """The per-cell rate of the material nearest to each cell."""
        table = np.array([self.for_material(m) for m in materials], dtype=PHI_DTYPE)
        if table.size == 0:
            return grid.zeros()
        return table[nearest]


@dataclass(frozen=True)
class MotionOutcome:
    """What one motion did, in the terms the commit gate checks it against.

    Attributes:
        structure: The moved `Structure` (a new revision, input untouched).
        swept: Signed measure the front integral says was added (positive) or
            removed (negative), in nm^ndim — `∫ rate * flux * dt` along the
            front, the reference of the balance check (plan §4.5.4).
        sub_steps: CFL sub-steps taken; 1 on the fast path.
        dt: Sub-step length in s, `0.0` on the fast path (which is not
            time-resolved — it is one exact offset).
        max_speed: The CFL bound used, in nm/s.
        reinit_passes: Mid-motion renormalisations the distortion trigger fired.
        flux_rebuilds: Visibility rebuilds a `FrontFlux` model was asked for; 0
            for a static flux array or none at all.
    """

    structure: Structure
    swept: float
    sub_steps: int
    dt: float = 0.0
    max_speed: float = 0.0
    reinit_passes: int = 0
    flux_rebuilds: int = 0


def _clipped(
    originals: dict[MaterialId, np.ndarray], solid: np.ndarray
) -> dict[MaterialId, np.ndarray]:
    """Etch bookkeeping: no material may stick out of the new union (plan §3.2).

    `max(phi_m, phi_solid_new)` exactly as the plan states it, with one
    refinement: always computed from the material's field at the **start of the
    motion**, never from the previous sub-step, so a receding front leaves the
    current distance behind rather than a sawtooth of stale ones. Where another
    material's surface is nearer than m's own, the union's distance understates
    `phi_m`; that is a value the commit gate's reinitialisation repairs, and the
    sign — which is what makes this a correct set operation — is right either way.
    """
    return {material: np.maximum(values, solid) for material, values in originals.items()}


def _assign_deposit(
    phi: dict[MaterialId, np.ndarray],
    material: MaterialId,
    solid_start: np.ndarray,
    solid_now: np.ndarray,
    existing: np.ndarray | None,
    spacing: float,
) -> None:
    """Deposition bookkeeping: the material owns what the front grew into.

    Always measured against the solid at the **start of the motion**, never
    against the previous sub-step. Deposition only ever grows the solid, so
    `solid_now \\ solid_start` is the deposited region however many sub-steps it
    took — and taking it in one piece keeps `phi_k` a usable field instead of the
    sawtooth that accumulating per-sub-step shells would leave behind (each shell
    is only `rate * dt` thick, so every value in the deposit would sit within a
    sub-step of zero).

    `max(solid_now, -solid_start)` is the right *set*, and on its own the wrong
    *field* wherever the front did not move — which is every shadowed stretch of
    a directional deposition, i.e. the whole point of milestone M2. There
    `solid_now == solid_start`, the formula collapses to `|solid_start|`, and the
    result is exactly zero all along the old surface: a zero level with no
    interior behind it. Nothing is inside it (`inside` is strict), but every
    measure taken off the field reads those cells as half full and every front
    integral counts them as front — measured on a 4 nm sputter deposition through
    a mask, 1849 phantom cells and ~600 nm^2 of metal that was never deposited.

    Clamping those cells positive is not enough, and the reason is worth stating:
    `|solid_start|` is a V whose vertex sits on the old surface, and a V has a
    zero central derivative at its vertex whatever its floor is. The band
    invariant reads it as `|grad(phi)| = 0` either way. What is wrong is the
    *proxy*: away from the deposit, "distance to where the surface used to be"
    is not "distance to the deposited material", and the second is what `phi_k`
    is supposed to mean. So where nothing grew, the field is the distance
    transform of the region that did — monotone, correct, and cell-quantised,
    which is exactly the accuracy an empty region deserves. Cells the deposit
    actually reached keep the sub-cell value the moved front gives them.
    """
    shell = np.maximum(solid_now, -solid_start)
    grew = solid_now < solid_start
    if not grew.all():
        # One transform per motion, not per sub-step, and only when the front
        # left part of itself behind — a blanket deposition never gets here.
        reach = ndimage.distance_transform_edt(~grew, sampling=spacing).astype(PHI_DTYPE)
        shell = np.where(grew, shell, np.maximum(shell, reach))
    phi[material] = shell if existing is None else np.minimum(existing, shell)


def union_front(
    structure: Structure, policy: reinit.ReinitPolicy = reinit.ReinitPolicy()
) -> np.ndarray:
    """The field the front is advected on: `min_m phi[m]`, with seams repaired.

    Where two materials touch, `min_m phi[m]` is exactly zero *along their shared
    interface* — the price of a per-material representation, because each field
    is correctly zero on its own boundary there. Left alone, that buried seam
    would behave like a front: an offset would push it positive and punch a void
    along a perfectly continuous interface, and the balance check's front
    integral would count it.

    The repair is the reinitialisation the plan already mandates: with a cell at
    the zero level counting as inside (`stencil.has_opposite_sign_neighbour`),
    only the real solid/empty interface is held fixed, and the seam relaxes to
    the distance it should have had. It is run only when a seam is actually
    there — a single material, or materials that do not touch, need nothing.
    """
    solid = structure.solid_phi.copy()
    if len(structure.materials) < 2 or not _has_buried_seam(structure.grid, solid):
        return solid
    return reinit.reinitialise(structure.grid, solid, policy).phi


def _has_buried_seam(grid: Grid, solid: np.ndarray) -> bool:
    """Whether the union field has a zero level that no empty space touches."""
    empty = solid > 0.0
    reachable = ndimage.binary_dilation(empty, ndimage.generate_binary_structure(grid.ndim, 1))
    return bool(np.any((np.abs(solid) < grid.spacing) & ~reachable))


def _bookkeep(
    originals: dict[MaterialId, np.ndarray],
    solid_start: np.ndarray,
    solid_now: np.ndarray,
    deposit_material: MaterialId | None,
    spacing: float,
) -> dict[MaterialId, np.ndarray]:
    """Distribute a moved union front back onto the materials (plan §3.2).

    Always derived from the fields at the start of the motion, so calling it once
    per sub-step costs the same as calling it once at the end and gives the same
    answer — which is what lets the sub-steps stay invisible.
    """
    if deposit_material is None:
        return _clipped(originals, solid_now)
    phi = dict(originals)
    _assign_deposit(
        phi, deposit_material, solid_start, solid_now, originals.get(deposit_material), spacing
    )
    return phi


class _FrontMaterial:
    """Which material owns the nearest piece of solid, for every cell.

    This is the `material_at_front(x)` of plan §4.2's speed field, and getting it
    from `argmin_m phi[m]` alone is not enough. Inside the solid that argmin is
    exactly right, and — since an etch only ever removes cells — it never changes
    during a motion, so the front switching from material A to B as it eats
    through is captured to sub-cell order for free.

    Outside the solid it is wrong in the one case that matters. In an undercut
    void the nearest solid is the **mask overhanging it**, not the material that
    used to fill the void; reading a clipped field there would hand the mask's
    own exposed face the etch rate of the material below it and the undercut
    would run away. So the map is extended into empty space by "the owner of the
    nearest solid cell", which is a distance transform, and therefore refreshed
    every `_OWNER_REFRESH` sub-steps rather than every one. The solid half stays
    exact every sub-step; the void half changes slowly, being a statement about
    where the walls are.
    """

    def __init__(self, grid: Grid, owners: np.ndarray) -> None:
        self._grid = grid
        self._structure = ndimage.generate_binary_structure(grid.ndim, 1)
        self._owners = owners
        self._extended = owners
        self._age = 0

    def of(self, solid: np.ndarray, owners: np.ndarray | None = None) -> np.ndarray:
        """The owning material index per cell, given the current union field."""
        if owners is not None:
            self._owners = owners
        solid_mask = solid <= 0.0
        if self._age % _OWNER_REFRESH == 0:
            self._extended = self._extend(solid_mask)
        self._age += 1
        return np.where(solid_mask, self._owners, self._extended)

    def _extend(self, solid_mask: np.ndarray) -> np.ndarray:
        """Carry the owner of each solid cell out into the empty space."""
        if not solid_mask.any() or solid_mask.all():
            return self._owners
        _, indices = ndimage.distance_transform_edt(~solid_mask, return_indices=True)
        return self._owners[tuple(indices)]


def offset_solid(
    structure: Structure,
    distance: float,
    *,
    deposit_material: MaterialId | None = None,
    policy: reinit.ReinitPolicy = reinit.ReinitPolicy(),
) -> MotionOutcome:
    """Move the whole front by `distance` nm at once — the isotropic fast path.

    `distance > 0` grows the solid and needs a `deposit_material` to own the new
    shell (conformal deposition, ALD); `distance < 0` shrinks it and clips every
    material (uniform wet etch). Exact for a signed-distance field, so splitting
    the dose changes nothing: `1 x 20 nm` and `4 x 5 nm` agree to the last bit.
    """
    grid = structure.grid
    distance = float(distance)
    if not math.isfinite(distance):
        raise ValueError(f"distance must be finite, got {distance}")
    if distance > 0.0 and deposit_material is None:
        raise ValueError("growing the front needs a deposit_material to own the new shell")
    if distance < 0.0 and deposit_material is not None:
        raise ValueError("a receding front removes material; it takes no deposit_material")

    if not structure.materials and deposit_material is None:
        raise ValueError("an empty Structure has no front to move")
    if distance == 0.0:
        return MotionOutcome(structure, swept=0.0, sub_steps=0)
    solid_before = union_front(structure, policy)
    solid_after = (solid_before - PHI_DTYPE(distance)).astype(PHI_DTYPE)

    originals = dict(structure.phi)
    phi = _bookkeep(originals, solid_before, solid_after, deposit_material, grid.spacing)
    moved = Structure(grid, phi, dict(structure.fields), dict(structure.metadata))
    # Trapezoidal front integral: the front's length changes while it moves, and
    # taking only its starting length would miss the curvature term entirely
    # (a disk grown by 10 nm would come out 10 % short).
    front_before = measures.front_integral(grid, solid_before)
    front_after = measures.front_integral(grid, solid_after)
    swept = math.copysign(0.5 * (front_before + front_after) * abs(distance), distance)
    return MotionOutcome(moved, swept=swept, sub_steps=1)


def advect_front(
    structure: Structure,
    rates: SurfaceRates,
    duration: float,
    *,
    deposit_material: MaterialId | None = None,
    flux: np.ndarray | FrontFlux | None = None,
    cfl: float = 0.5,
    policy: reinit.ReinitPolicy = reinit.ReinitPolicy(),
) -> MotionOutcome:
    """Advect the union front for `duration` seconds under a material-dependent rate.

    Etches unless a `deposit_material` is named, in which case the front grows and
    that material owns what it grows into.

    `flux` is the per-cell multiplier on the rate that turns an isotropic motion
    into a directional one. Two forms:

    - a **plain array**, held fixed for the whole motion — right for a source
      whose visibility cannot change while the front moves;
    - a **`FrontFlux` model** (`kernel.flux.FluxModel2D`), re-evaluated against the
      current front every `_FLUX_REFRESH` sub-steps. A deep directional etch needs
      this: the trench it is digging shadows its own sidewalls more with every
      nanometre, and a flux computed once at the surface would keep etching the
      walls as if the trench were not there.

    Either way the flux enters the CFL bound and the front integral the balance
    check reads, so nothing downstream has to know which form was used.
    """
    grid = structure.grid
    duration = float(duration)
    if duration < 0.0 or not math.isfinite(duration):
        raise ValueError(f"duration must be a non-negative finite time, got {duration}")
    if not 0.0 < cfl <= 1.0:
        raise ValueError(f"cfl must be in (0, 1], got {cfl}")
    model: FrontFlux | None = None
    if flux is not None and not isinstance(flux, np.ndarray):
        model = flux
        flux = None
    elif flux is not None:
        flux = grid.as_field(flux, dtype=PHI_DTYPE)

    if not structure.materials and deposit_material is None:
        raise ValueError("an empty Structure has no front to move")

    sign = PHI_DTYPE(1.0 if deposit_material is not None else -1.0)
    if model is not None:
        flux_bound = float(model.max_arrival)
    elif flux is not None:
        flux_bound = float(np.max(np.abs(flux)))
    else:
        flux_bound = 1.0
    speed_bound = rates.bound * flux_bound
    if duration == 0.0 or speed_bound == 0.0:
        return MotionOutcome(structure, swept=0.0, sub_steps=0, max_speed=speed_bound)

    sub_steps = max(1, int(math.ceil(duration * speed_bound / (cfl * grid.spacing))))
    dt = PHI_DTYPE(duration / sub_steps)

    originals = dict(structure.phi)
    materials = list(originals)
    if deposit_material is not None and deposit_material not in originals:
        materials.append(deposit_material)
    rate_table = np.array([rates.for_material(m) for m in materials], dtype=PHI_DTYPE)

    solid_start = union_front(structure, policy)
    solid = solid_start.copy()
    front = _FrontMaterial(grid, _owner_map(grid, originals, materials))
    swept = 0.0
    previous_rate_integral = 0.0
    reinit_passes = 0
    flux_rebuilds = 0

    for step in range(sub_steps):
        # The speed field is rebuilt from the current front every sub-step, which
        # is what makes a front etching through A into B switch rates by itself.
        # For an etch the solid half of the ownership map cannot change — cells
        # only ever leave the solid — so it is computed once.
        owners = (
            None
            if deposit_material is None
            else _owner_map(grid, originals, materials, deposit_material, solid_start, solid)
        )
        if model is not None and step % _FLUX_REFRESH == 0:
            flux = grid.as_field(model.on_front(grid, solid), dtype=PHI_DTYPE)
            flux_rebuilds += 1
        rate_map = rate_table[front.of(solid, owners)]
        if flux is not None:
            rate_map = rate_map * flux
        speed = sign * rate_map

        if step == 0:
            previous_rate_integral = measures.front_integral(grid, solid, np.abs(rate_map))
        # A cell the front does not move at all is classified with the majority:
        # its update is multiplied by zero either way, and keeping the sign
        # uniform is what lets `godunov_norm` compute one upwind side instead of
        # two. Without this a directional deposition would lose the fast path in
        # exactly the cells its own shadow created.
        moving_out = speed >= PHI_DTYPE(0.0) if sign > 0 else speed > PHI_DTYPE(0.0)
        solid = solid - dt * speed * stencil.godunov_norm(solid, grid.spacing, moving_out)

        rate_integral = measures.front_integral(grid, solid, np.abs(rate_map))
        swept += float(dt) * 0.5 * (previous_rate_integral + rate_integral)
        previous_rate_integral = rate_integral

        # Distortion trigger (plan §4.2): tied to sub-step count and to how far
        # the field has drifted from a distance function — never to a user step
        # boundary, or 3 x 10 s and 1 x 30 s would diverge.
        is_last = step == sub_steps - 1
        if not is_last and (step + 1) % policy.every_sub_steps == 0:
            error = invariants.band_gradient_error(grid, solid, quantile=_GRADIENT_QUANTILE)
            if error > policy.max_gradient_error:
                solid = reinit.reinitialise(grid, solid, policy).phi
                reinit_passes += 1

    phi = _bookkeep(originals, solid_start, solid, deposit_material, grid.spacing)
    moved = Structure(grid, phi, dict(structure.fields), dict(structure.metadata))
    return MotionOutcome(
        structure=moved,
        swept=math.copysign(swept, float(sign)),
        sub_steps=sub_steps,
        dt=float(dt),
        max_speed=speed_bound,
        reinit_passes=reinit_passes,
        flux_rebuilds=flux_rebuilds,
    )


def _owner_map(
    grid: Grid,
    originals: dict[MaterialId, np.ndarray],
    materials: list[MaterialId],
    deposit_material: MaterialId | None = None,
    solid_start: np.ndarray | None = None,
    solid_now: np.ndarray | None = None,
) -> np.ndarray:
    """Index into `materials` of the material owning each **solid** cell.

    `argmin_m phi[m]` over the fields as they were at the start of the motion:
    an etch only removes cells, so a cell that is still solid still belongs to
    whoever owned it. Deposition is the one thing that adds solid, and what it
    adds belongs to the deposited material.
    """
    if not originals:
        owners = np.zeros(grid.shape, dtype=np.int16)
    else:
        owners = np.argmin(np.stack([originals[m] for m in materials if m in originals]), axis=0)
        owners = owners.astype(np.int16)
    if deposit_material is not None and solid_start is not None and solid_now is not None:
        grew = (solid_now <= 0.0) & (solid_start > 0.0)
        owners = np.where(grew, np.int16(materials.index(deposit_material)), owners)
    return owners
