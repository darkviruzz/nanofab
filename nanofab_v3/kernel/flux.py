"""Flux and visibility: reverse marching against the union front (plan §4.3).

This is the **second deliberately 2D-only seam** of the v2 core, next to
`contours` (plan Q7). 3D means writing `FluxModel3D` with two-angle hemisphere
integration — algorithmically a different thing — so nothing here pretends to be
N-D generic: every entry point checks the grid and raises on anything but 2D.

What it computes
----------------

`FluxModel2D` answers one question per front cell: **how much of the source can
this piece of surface see, and at what angle?** The answer is the dimensionless
*arrival per unit front*

    A(x) = sum_k  w_k * V_k(x) * max(0, n(x) . d_k) * Y(theta_incidence)   [+ floor]

- `d_k = (cos theta_k, sin theta_k)` is a unit vector **towards** the source, in
  grid-axis order: `theta` is measured from the first axis (the stacking
  direction, "up") towards the second. A source is always above the wafer, so
  `|theta| < 90 deg`.
- `w_k` are the quadrature weights of the source's angular distribution `g(theta)`,
  **normalised so that an unobstructed flat surface receives exactly 1**. That is
  what makes the arrival a multiplier on a plain blanket rate: `SurfaceRates`
  keeps saying "nm/s on an open surface" and everything angular lives here.
- `V_k(x)` is the visibility of the source at angle `k` from `x` — the reverse
  march below.
- `Y` is the angle-dependent yield (`AngularYield`), folded into the arrival
  rather than into `SurfaceRates`: it is a per-cell quantity like the rest, and
  the angles are known here and nowhere else. The speed field of plan §4.2 keeps
  its two factors, `F = sign * rate(material) * A(x)`.

`A(x)` is non-negative by construction, which keeps a directional etch uniformly
signed and lets the solver's Godunov fast path stand (plan §17, M1 trap 5).

Reverse marching
----------------

Visibility is computed **from each front cell towards the source** — the
grid-native successor of v1's reverse-visibility solver — by sphere tracing:

1. The occupancy is coarsened (`visibility_spacing`, 2 cells by default) and a
   Euclidean distance transform on it gives, for every point, a *lower bound* on
   the distance to the nearest solid. A ray may safely jump that far.
2. The **hit test** reads the fine union field, bilinearly — not the coarse one,
   and not at the nearest cell (`_SELF_HIT_NOTE` is why). So the coarsening is a
   pure speed knob: it changes how many steps a ray takes, never where the
   shadow boundary lands. Measured on a mask edge, the wedge position is
   identical at a visibility spacing of 1, 2 and 4 cells. (Plan §4.3 expected a
   coarse occupancy to cost accuracy; it does not — plan §18.2.)
3. A ray is done when it hits solid, leaves the domain, or rises above every
   solid cell. Steps grow geometrically in open space, so crossing 500 nm of
   headroom costs ~15 iterations rather than 500.

Rays that resolve neither way within `_MAX_MARCH_STEPS` count as blocked — flux
is never invented where a clear line to the source could not be shown — and are
reported as `FluxOutcome.unresolved`.

Per cell, not per sample
------------------------

Plan §4.3 describes flux "per front sample"; the solver consumes a per-cell
array. This module resolves that in favour of **per-cell throughout** (decision
recorded in `memory.md`, 2026-08-25): the front cells are `|phi_solid| < spacing`,
each ray starts from the sub-cell foot point `x - n * phi(x)` so the sampling is
not cell-quantised, and the result is extended off the front by "the value of the
nearest front cell" — the same distance-transform extension the motion solver
already uses for material ownership. The flux array is the contract with the
solver; how it is filled stays behind this interface.

The occupancy input is `motion.union_front`, **never** `structure.solid_phi`:
where two materials touch, `min_m phi[m]` is exactly zero along their shared
interface (plan §17.1), and a visibility march would read that seam as a wall.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage

from nanofab_v3.kernel import measures, motion, reinit
from nanofab_v3.model.grid import PHI_DTYPE, Grid
from nanofab_v3.model.structure import Structure

_HALF_PI = 0.5 * math.pi

_MAX_MARCH_STEPS = 256
"""Sphere-tracing iterations a single ray may take before it counts as blocked.

Open space costs ~15 steps (the step size doubles), a deep trench a few dozen.
The rays that exhaust this budget are the ones running nearly parallel to a wall
they start on, whose `cos(theta_incidence)` is ~0 anyway; calling them blocked
keeps the rule "never invent flux without a clear line to the source", and
`FluxOutcome.unresolved` says how many there were.
"""

_SELF_HIT_NOTE = """Why the hit test reads the field bilinearly (see `_Visibility._sample`).

A ray leaves a front cell, and a front cell is solid by definition, so a
nearest-cell hit test reports every ray blocked by its own origin. The two
obvious repairs were tried and both fail:

- displacing the ray's origin along the surface normal moves the geometry — the
  mask then casts the shadow of a mask one cell shorter, a bias of
  `spacing * tan(theta)` that grows with the source angle;
- latching on clearance ("a ray may hit only once it has been a cell clear of
  every surface") tunnels straight through a concave corner: a ray leaving the
  substrate at the foot of a mask enters the mask without ever having been clear
  of anything, and comes out above it reported as lit. Measured, that lit corner
  is then spread by the extension over the whole wedge of material the mask
  shadows, and a 30 nm ion-beam etch ate 14 nm sideways under a mask it could
  not see under.

Bilinear sampling removes the problem instead of patching it: the field is a
smooth signed distance, so half a cell along an outward ray already reads
positive and the only negative readings are inside real material.
"""

_TRUSTED_CELLS = 3.0
"""Cells over which a ray trusts the union field itself as a distance bound.

The reinitialisation keeps `|grad(phi)| ~ 1` in a narrow band, so within a few
cells of a surface the field *is* the distance to it and a ray may jump that
far. Beyond the band the field is only a correct sign, so the guaranteed
coarse bound takes over. Trusting it near the surface is what removes the
half-cell crawl a ray would otherwise do along every wall it passes.
"""

_EXTENSION_CELLS = 12
"""Cells the arrival is carried past the front; beyond it, cells do not move.

The lower bound is what the front actually needs between two rebuilds: `cfl`
cells per sub-step over `motion._FLUX_REFRESH` sub-steps, plus the one-cell band
`measures.front_integral` reads for the balance check — 3.5 cells at the
defaults. Freezing everything beyond does not disturb the front: for a uniformly
signed motion the Godunov upwind side is the one *away* from the frozen
boundary, so the step in `phi` there is never read.

The upper bound is that a cell far from the front should not be handed a
velocity at all (see `_FrontExtension`). Twelve leaves the front three times the
room it needs and still keeps the collar thin against a feature.
"""


def _require_2d(grid: Grid) -> None:
    """The named 2D seam of plan §4.3/Q7 — stated, not silently assumed."""
    if grid.ndim != 2:
        raise ValueError(
            f"the flux solver is 2D-only (plan §4.3), grid has {grid.ndim} axes; "
            "3D needs FluxModel3D, which is deliberately not abstracted over"
        )


# -- angular distributions ---------------------------------------------------


@dataclass(frozen=True)
class AngularDistribution:
    """`g(theta)`: where the flux comes from, as a quadrature over directions.

    Subclasses return raw `(angles, weights)` from `samples`; `quadrature`
    rescales them so that an unobstructed flat surface receives exactly 1. That
    normalisation is what parameterises the *techniques* (plan §4.3) without
    touching the rate models: evaporation, RIE, IBE and sputter differ in this
    object and in `AngularYield`, in nothing else.

    Angles are radians from the first grid axis (up) towards the second, and must
    stay strictly inside the hemisphere — a source at or below the horizon
    delivers nothing to a flat wafer and would make the normalisation singular.
    """

    def samples(self) -> tuple[np.ndarray, np.ndarray]:
        """Raw quadrature angles (rad) and weights, in arbitrary units."""
        raise NotImplementedError

    def quadrature(self) -> tuple[np.ndarray, np.ndarray]:
        """Angles and weights, normalised to `sum_k w_k cos(theta_k) = 1`."""
        angles, weights = self.samples()
        angles = np.asarray(angles, dtype=np.float64).reshape(-1)
        weights = np.asarray(weights, dtype=np.float64).reshape(-1)
        if angles.size == 0 or angles.size != weights.size:
            raise ValueError("an angular distribution needs matching non-empty angles and weights")
        if not np.all(np.isfinite(angles)) or np.any(np.abs(angles) >= _HALF_PI):
            raise ValueError("source angles must be finite and inside (-90 deg, +90 deg)")
        if np.any(weights < 0.0):
            raise ValueError("angular weights must be non-negative")
        response = float(np.sum(weights * np.cos(angles)))
        if response <= 0.0:
            raise ValueError("an angular distribution must deliver flux to a flat surface")
        return angles, weights / response


@dataclass(frozen=True)
class Delta(AngularDistribution):
    """A point source: all flux from one direction (plan §4.3's evaporation).

    One quadrature angle, so the cheapest model there is and the one with the
    sharpest shadows — the reference case the shadow-wedge test measures against.
    """

    angle: float = 0.0

    def samples(self) -> tuple[np.ndarray, np.ndarray]:
        return np.array([float(self.angle)]), np.array([1.0])


@dataclass(frozen=True)
class Lobe(AngularDistribution):
    """A narrow Gaussian lobe around `angle` — RIE and IBE (plan §4.3).

    `divergence` is the standard deviation in radians; the lobe is truncated at
    `_TRUNCATION` sigma and clipped to the hemisphere. The width is what turns a
    sharp shadow into a penumbra, which is the visible difference between an
    evaporation edge and an ion-beam edge.
    """

    angle: float = 0.0
    divergence: float = math.radians(5.0)
    samples_count: int = 9

    _TRUNCATION = 2.5

    def samples(self) -> tuple[np.ndarray, np.ndarray]:
        spread = float(self.divergence)
        if not math.isfinite(spread) or spread < 0.0:
            raise ValueError(f"divergence must be a non-negative angle, got {self.divergence}")
        if spread == 0.0 or self.samples_count <= 1:
            return Delta(self.angle).samples()
        limit = self._TRUNCATION * spread
        low = max(float(self.angle) - limit, -_HALF_PI + 1e-6)
        high = min(float(self.angle) + limit, _HALF_PI - 1e-6)
        angles = np.linspace(low, high, int(self.samples_count))
        weights = np.exp(-0.5 * ((angles - float(self.angle)) / spread) ** 2)
        return angles, weights


@dataclass(frozen=True)
class CosinePower(AngularDistribution):
    """`g(theta) ~ cos^n(theta - angle)` over the hemisphere — sputter (plan §4.3).

    `exponent = 1` is the Knudsen cosine law of a thermal source, larger values
    are the forward-peaked lobes of magnetron sputtering. A broad lobe is what
    puts metal on a sidewall at all, which is where S4's fences come from.
    """

    exponent: float = 1.0
    angle: float = 0.0
    samples_count: int = 17

    def samples(self) -> tuple[np.ndarray, np.ndarray]:
        exponent = float(self.exponent)
        if not math.isfinite(exponent) or exponent < 0.0:
            raise ValueError(f"exponent must be a non-negative number, got {self.exponent}")
        count = max(2, int(self.samples_count))
        centre = float(self.angle)
        low = max(centre - _HALF_PI, -_HALF_PI) + 1e-6
        high = min(centre + _HALF_PI, _HALF_PI) - 1e-6
        angles = np.linspace(low, high, count)
        weights = np.cos(angles - centre) ** exponent
        return angles, np.maximum(weights, 0.0)


@dataclass(frozen=True)
class Isotropic(AngularDistribution):
    """Uniform arrival from the whole hemisphere.

    Available as an honest (and expensive) alternative to `FluxModel2D`'s
    `isotropic_floor`: this one is shadowed like every other component, so a deep
    trench sees less of it — the mechanism behind aspect-ratio-dependent etching.
    """

    samples_count: int = 17

    def samples(self) -> tuple[np.ndarray, np.ndarray]:
        count = max(2, int(self.samples_count))
        angles = np.linspace(-_HALF_PI + 1e-6, _HALF_PI - 1e-6, count)
        return angles, np.ones(count)


@dataclass(frozen=True)
class Scaled(AngularDistribution):
    """`inner`, delivering only `fraction` of the blanket flux.

    The counterpart of `FluxModel2D.isotropic_floor`: a technique whose
    directional part carries 80 % of the etch and whose chemistry carries the
    rest is `Scaled(Lobe(...), 0.8)` plus a floor of 0.2. Deliberately *not*
    renormalised — that is the whole point of it.
    """

    inner: AngularDistribution = field(default_factory=lambda: Delta())
    fraction: float = 1.0

    def samples(self) -> tuple[np.ndarray, np.ndarray]:
        angles, weights = self.inner.quadrature()
        fraction = float(self.fraction)
        if not math.isfinite(fraction) or fraction < 0.0:
            raise ValueError(f"fraction must be a non-negative finite number, got {self.fraction}")
        return angles, fraction * weights

    def quadrature(self) -> tuple[np.ndarray, np.ndarray]:
        return self.samples()


@dataclass(frozen=True)
class Mixture(AngularDistribution):
    """Several sources at once, weighted by the fraction of blanket flux each carries.

    Each component is normalised on its own first, so the fractions mean what they
    say: `Mixture(((0.8, Lobe(...)), (0.2, Isotropic())))` delivers 80 % of the
    blanket rate through the lobe and 20 % isotropically. Fractions are rescaled
    to sum to 1 — this is a decomposition of one flux, not a way to turn the
    source up.
    """

    components: tuple[tuple[float, AngularDistribution], ...] = ()

    def samples(self) -> tuple[np.ndarray, np.ndarray]:
        if not self.components:
            raise ValueError("a Mixture needs at least one component")
        fractions = np.array([float(f) for f, _ in self.components], dtype=np.float64)
        if np.any(fractions < 0.0) or float(np.sum(fractions)) <= 0.0:
            raise ValueError("mixture fractions must be non-negative and not all zero")
        fractions = fractions / float(np.sum(fractions))
        angles: list[np.ndarray] = []
        weights: list[np.ndarray] = []
        for fraction, component in zip(fractions, (c for _, c in self.components)):
            part_angles, part_weights = component.quadrature()
            angles.append(part_angles)
            weights.append(fraction * part_weights)
        return np.concatenate(angles), np.concatenate(weights)


# -- angle-dependent yield ---------------------------------------------------


@dataclass(frozen=True)
class AngularYield:
    """`Y(theta_incidence) / Y(0)`: how much a surface responds off normal incidence.

    Folded into the arrival rather than into `SurfaceRates` (plan §4.2's third
    factor): it is a per-cell quantity, and the incidence angles only exist here.
    """

    def relative(self, cos_incidence: np.ndarray) -> np.ndarray:
        """Yield relative to normal incidence, given `cos(theta_incidence) > 0`."""
        raise NotImplementedError

    def reflected_fraction(self, cos_incidence: np.ndarray) -> np.ndarray:
        """Fraction of incident particles reflected specularly; zero by default."""
        return np.zeros_like(np.asarray(cos_incidence, dtype=np.float64))

    @property
    def max_reflected_fraction(self) -> float:
        cosines = np.linspace(1e-3, 1.0, 512)
        return float(np.max(self.reflected_fraction(cosines)))

    @property
    def peak_response(self) -> float:
        """`max_theta cos(theta) * Y(theta)` — the arrival's upper bound per unit weight.

        The CFL condition needs a bound on the speed field before the first
        sub-step, so it cannot be measured from the front; it is evaluated here on
        a dense sweep of incidence angles instead.
        """
        cosines = np.linspace(1e-3, 1.0, 512)
        return float(np.max(cosines * self.relative(cosines)))


@dataclass(frozen=True)
class UnitYield(AngularYield):
    """`Y == 1`: the response is the projected area and nothing else.

    Right for deposition (an arriving atom sticks whatever the angle) and the
    honest default for a didactic etch.
    """

    def relative(self, cos_incidence: np.ndarray) -> np.ndarray:
        return np.ones_like(np.asarray(cos_incidence, dtype=np.float64))


@dataclass(frozen=True)
class SputterYield(AngularYield):
    """Physical sputtering: more material per ion at glancing incidence.

    Yamamura's form, normalised to normal incidence:

        Y(theta)/Y(0) = cos^-f(theta) * exp(-sigma * (1/cos(theta) - 1))

    It rises off normal (a glancing ion transfers more momentum into the surface)
    and collapses towards grazing (the ion reflects). With the defaults the peak
    sits at `cos(theta) = 1/2`, i.e. **60 degrees, at 1.47x** the normal-incidence
    yield. That maximum is what makes an ion-beam etch facet a corner instead of
    reproducing the mask, and it is the reason `IBE` needs an angle model at all
    while an evaporation does not.

    Attributes:
        rise: `f` above — how steeply the yield climbs off normal incidence.
        fall: `sigma` above — how quickly reflection wins near grazing. The peak
            sits at `cos(theta) = fall / rise`.
    """

    rise: float = 2.0
    fall: float = 1.0

    def relative(self, cos_incidence: np.ndarray) -> np.ndarray:
        cosines = np.clip(np.asarray(cos_incidence, dtype=np.float64), 1e-6, 1.0)
        secant = 1.0 / cosines
        return secant ** float(self.rise) * np.exp(-float(self.fall) * (secant - 1.0))

    def reflected_fraction(self, cos_incidence: np.ndarray) -> np.ndarray:
        """The normalised yield lost near grazing becomes one reflected ion."""
        return np.clip(1.0 - self.relative(cos_incidence), 0.0, 1.0)


# -- reverse marching --------------------------------------------------------


@dataclass(frozen=True)
class _MarchResult:
    """What a batch of rays did: blocked or not, where, and how many gave up."""

    blocked: np.ndarray
    hit_cell: np.ndarray
    unresolved: int


class _Visibility:
    """Sphere tracing of rays against one union front (see the module docstring).

    Built once per flux rebuild and used for every ray of that rebuild: the
    coarse distance transform is the expensive part and it depends only on the
    front, not on the source.
    """

    def __init__(self, grid: Grid, solid: np.ndarray, coarse_spacing: float) -> None:
        self._grid = grid
        self._origin = np.asarray(grid.origin, dtype=np.float64)
        self._shape = np.asarray(grid.shape, dtype=np.intp)
        self._solid = np.asarray(solid, dtype=np.float64)
        self._flat_solid = self._solid.reshape(-1)
        self._min_step = 0.5 * grid.spacing
        self._trusted = _TRUSTED_CELLS * grid.spacing

        occupied = self._solid <= 0.0
        factor = max(1, int(round(coarse_spacing / grid.spacing)))
        self.spacing = factor * grid.spacing
        coarse = _block_any(occupied, factor)
        self._coarse_origin = self._origin + 0.5 * (factor - 1) * grid.spacing
        self._coarse_shape = np.asarray(coarse.shape, dtype=np.intp)
        if coarse.any():
            # Distance from every free coarse cell to the nearest occupied one.
            self._free = ndimage.distance_transform_edt(~coarse) * self.spacing
        else:
            self._free = np.full(coarse.shape, float(np.hypot(*grid.shape)) * grid.spacing)
        # A point is at least this far from the *region* an occupied coarse cell
        # covers: half a coarse diagonal to get from the sampled centre to the
        # point, and another half to get from the nearest occupied centre out to
        # its own corner. Anything less and a ray could step through a wall.
        self._margin = math.sqrt(2.0) * self.spacing

        rows = np.flatnonzero(occupied.any(axis=1))
        self._solid_top = (
            grid.origin[0] + grid.spacing * float(rows.max()) if rows.size else -math.inf
        )

    def march(self, start: np.ndarray, direction: np.ndarray) -> "_MarchResult":
        """Trace rays from `start` along `direction` until they hit or escape.

        `hit_cell` is the flat index of the first solid cell a ray reached, or -1
        where it escaped. Redeposition needs that index; plain visibility only
        reads `blocked`.
        """
        count = int(start.shape[0])
        blocked = np.zeros(count, dtype=bool)
        hit_cell = np.full(count, -1, dtype=np.intp)
        if count == 0:
            return _MarchResult(blocked, hit_cell, 0)

        # Half a cell off the foot point, so the very first sample is already
        # strictly outside the surface the ray leaves (see `_sample`).
        position = start + direction * self._min_step
        upward = direction[:, 0] > 0.0
        alive = np.arange(count, dtype=np.intp)
        for _ in range(_MAX_MARCH_STEPS):
            if alive.size == 0:
                return _MarchResult(blocked, hit_cell, 0)
            here = position[alive]
            distance, nearest, inside = self._sample(here)
            escaped = ~inside | (upward[alive] & (here[:, 0] > self._solid_top))
            hits = ~escaped & (distance < 0.0)
            struck = alive[hits]
            blocked[struck] = True
            hit_cell[struck] = nearest[hits]

            running = ~(escaped | hits)
            alive = alive[running]
            if alive.size == 0:
                return _MarchResult(blocked, hit_cell, 0)
            # How far the ray may jump: the larger of two lower bounds on the
            # distance to solid. The coarse transform is guaranteed but pays a
            # diagonal margin, which is most of the cost right where rays spend
            # their steps — hugging a surface. The union field is the sharper
            # bound there and is a true distance inside the reinitialisation band,
            # so it is trusted for a few cells and no further.
            free = self._free_distance(here[running]) - self._margin
            near = np.minimum(distance[running] - self._min_step, self._trusted)
            step = np.maximum(self._min_step, np.maximum(free, near))
            position[alive] += step[:, None] * direction[alive]

        # Out of budget: unresolved rays count as blocked, never as lit.
        blocked[alive] = True
        return _MarchResult(blocked, hit_cell, int(alive.size))

    def _sample(self, points: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """The union field at `points`, the nearest cell, and whether it is in the domain.

        The field is read **bilinearly**, and that is what makes the hit test
        `phi < 0` correct rather than merely plausible. Read at the nearest cell
        instead, a ray leaving a front cell samples its own cell — whose value is
        `<= 0`, since that is what "front" means — and reports itself blocked; and
        the obvious repairs both fail (see `_SELF_HIT_NOTE`). Interpolated, the
        field is a smooth signed distance: half a cell along a ray that points
        away from the surface it starts on already reads positive, and the one
        place it reads negative is inside real material. Measured on a mask edge
        at 30 degrees, that is the difference between a shadow that starts under
        the mask and one that starts where `h * tan(theta)` says.
        """
        fractional = (points - self._origin) / self._grid.spacing
        inside = np.all((fractional >= -0.5) & (fractional <= self._shape - 0.5), axis=1)
        corner = np.clip(np.floor(fractional).astype(np.intp), 0, self._shape - 2)
        weight = np.clip(fractional - corner, 0.0, 1.0)
        base = corner[:, 0] * self._shape[1] + corner[:, 1]
        low = self._flat_solid[base] * (1.0 - weight[:, 1]) + self._flat_solid[base + 1] * weight[
            :, 1
        ]
        top = base + self._shape[1]
        high = self._flat_solid[top] * (1.0 - weight[:, 1]) + self._flat_solid[top + 1] * weight[
            :, 1
        ]
        value = low * (1.0 - weight[:, 0]) + high * weight[:, 0]
        nearest = np.rint(fractional).astype(np.intp)
        np.clip(nearest, 0, self._shape - 1, out=nearest)
        return value, nearest[:, 0] * self._shape[1] + nearest[:, 1], inside

    def _free_distance(self, points: np.ndarray) -> np.ndarray:
        """Distance to the nearest occupied coarse cell centre, in nm."""
        index = np.rint((points - self._coarse_origin) / self.spacing).astype(np.intp)
        np.clip(index, 0, self._coarse_shape - 1, out=index)
        return self._free[index[:, 0], index[:, 1]]


def _block_any(mask: np.ndarray, factor: int) -> np.ndarray:
    """Coarsen a boolean mask by `factor`, a block counting as set if any cell is.

    Conservative on purpose: the coarse occupancy must contain the fine one, or
    the free distance it feeds could let a ray step across a wall.
    """
    if factor == 1:
        return mask
    padding = [(0, (-size) % factor) for size in mask.shape]
    padded = np.pad(mask, padding, constant_values=False)
    blocks = padded.reshape(padded.shape[0] // factor, factor, padded.shape[1] // factor, factor)
    return blocks.any(axis=(1, 3))


class _Window:
    """The crop of one union field around its front, and the map back out of it.

    Every per-cell step of a rebuild — gradients, indexing, the smear, the collar —
    is done here rather than on the domain. The front is a curve and the domain
    is an area, so at the plan's reference grid the crop is a few times smaller
    than the field and those steps stop dominating the marching they exist to
    serve. Only the ray tracer reads the full field, and it only samples it.
    """

    def __init__(self, grid: Grid, phi: np.ndarray, front: np.ndarray, margin: int) -> None:
        occupied = np.argwhere(front)
        low = np.maximum(occupied.min(axis=0) - margin, 0)
        high = np.minimum(occupied.max(axis=0) + margin + 1, grid.shape)
        self.slices = tuple(slice(int(a), int(b)) for a, b in zip(low, high))
        self.offset = tuple(int(a) for a in low)
        self.full_shape = grid.shape
        self.front = front[self.slices]
        self.phi = np.asarray(phi[self.slices], dtype=np.float64)
        self.shape = self.front.shape
        self.grid = Grid(
            origin=tuple(o + grid.spacing * i for o, i in zip(grid.origin, self.offset)),
            spacing=grid.spacing,
            shape=self.shape,
            axes=grid.axes,
        )

    def crop(self, field: np.ndarray) -> np.ndarray:
        """The part of a full-domain field this window covers."""
        return field[self.slices]

    def lift(self, values: np.ndarray) -> np.ndarray:
        """A full-domain array carrying `values` in the window and zero outside."""
        full = np.zeros(self.full_shape, dtype=np.float64)
        full[self.slices] = values
        return full

    def local_flat(self, flat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Translate full-domain flat indices into window ones, dropping outsiders."""
        rows, columns = np.divmod(flat, self.full_shape[1])
        rows = rows - self.offset[0]
        columns = columns - self.offset[1]
        inside = (
                (rows >= 0) & (rows < self.shape[0]) & (columns >= 0) & (columns < self.shape[1])
        )
        return (rows * self.shape[1] + columns)[inside], inside


class _FrontExtension:
    """A collar around the front, each cell carrying its nearest front cell's value.

    The same trick `motion._FrontMaterial` uses for material ownership: a
    distance transform of the complement of the front gives, for every cell, the
    index of the front cell nearest to it — which is exactly the velocity
    extension a level-set solver wants, since it is constant along the normals.

    Two restrictions, both load-bearing:

    - a **window**, because the front is a curve and the domain is an area: a
      full-field transform would cost more than the whole flux rebuild;
    - a **collar**, because the extension is only meaningful near the front. This
      one is not an optimisation. Extended to the whole window, a cell ten cells
      deep under a hard mask keeps being handed the etch rate of the trench floor
      that happens to be its nearest front, and `phi` there climbs by `rate * t`
      until it crosses zero — measured: a 30 s ion-beam etch through a 40 nm mask
      window opened a row of disconnected voids under the mask, growing with
      depth. Beyond the collar the cells are simply frozen, which is what a
      narrow-band solver does and what keeps the drift bounded.
    """

    def __init__(self, view: _Window, cells: int) -> None:
        self._view = view
        distances, indices = ndimage.distance_transform_edt(~view.front, return_indices=True)
        self._indices = tuple(indices)
        self._within = distances <= float(cells)

    def apply(self, values: np.ndarray) -> np.ndarray:
        """Carry a window-local field's front values into the collar, as a full field."""
        return self._view.lift(np.where(self._within, values[self._indices], 0.0))

    def front_flat(self, local_flat: np.ndarray) -> np.ndarray:
        """Nearest front-cell flat index for arbitrary window-local cells."""
        rows, columns = np.divmod(local_flat, self._view.shape[1])
        return (
                self._indices[0][rows, columns] * self._view.shape[1]
                + self._indices[1][rows, columns]
        )


# -- the model ---------------------------------------------------------------


@dataclass(frozen=True)
class FluxOutcome:
    """One flux rebuild, with what it cost and how well it resolved.

    Attributes:
        arrival: Arrival per unit front, per cell — the array `advect_front`
            multiplies onto the material rate. Non-negative everywhere, zero
            outside the collar around the front.
        redeposited: Deposition flux from the one redeposition bounce, in the
            same units, or `None` when the model has no redeposition yield.
        reflected: Etch flux from the one specular ion bounce, in the same units,
            or `None` when the yield model reflects no ions.
        front_cells: Front cells the arrival was evaluated at.
        angles: Quadrature angles of the source.
        rays: Rays actually marched (angles pointing into a surface are skipped).
        unresolved: Rays that ran out of march budget and were counted as
            blocked. A large number means the scene has structures the visibility
            grid struggles with — the honest signal, not a silent inaccuracy.
        visibility_spacing: Cell size of the coarsened occupancy, in nm.
    """

    arrival: np.ndarray
    redeposited: np.ndarray | None = None
    reflected: np.ndarray | None = None
    front_cells: int = 0
    angles: int = 0
    rays: int = 0
    unresolved: int = 0
    visibility_spacing: float = 0.0


@dataclass(frozen=True)
class FluxModel2D:
    """A directional source and how a surface responds to it (plan §4.3).

    One object per *technique*: the differences between evaporation, RIE, IBE and
    sputter deposition are entirely the fields below. The factory functions at
    the end of this module are the didactic set of plan §6, and building a
    variant means constructing a different `FluxModel2D`, not writing new physics.

    Attributes:
        distribution: `g(theta)` — where the flux comes from.
        yield_model: `Y(theta_incidence)` — how the surface responds to it.
        isotropic_floor: A fraction of the blanket rate delivered to every front
            cell regardless of orientation and visibility — RIE's chemical
            component (plan §4.3). A radical flux is scattering-dominated and
            effectively orientation-blind, and a floor keeps the arrival strictly
            positive, which keeps the solver's uniform-sign fast path. What it
            deliberately does not model is depletion deep in a feature; use an
            `Isotropic` mixture component for that, and plan §4.4's reachability
            gate (M3) for a sealed void.
        mobility_length: Surface mobility of deposited material, in nm: arriving
            flux is smeared along the front over this length before it is
            deposited (plan §4.3's mobility kernel). It is what fills the sharp
            minimum a lobe leaves at the foot of a sidewall, and therefore what
            makes S4's fences continuous instead of beaded.
        redeposition_yield: Fraction of removed material that leaves a site and
            is re-deposited elsewhere in **one** isotropic bounce (plan §4.3).
        redeposition_samples: Quadrature directions per front cell for that bounce.
        visibility_spacing: Cell size of the coarsened occupancy the march steps
            on, in nm; `None` means two grid cells. A pure speed knob — the hit
            test reads the fine field.
        extension_cells: Collar the arrival is extended past the front by.
    """

    distribution: AngularDistribution = field(default_factory=Delta)
    yield_model: AngularYield = field(default_factory=UnitYield)
    isotropic_floor: float = 0.0
    mobility_length: float = 0.0
    redeposition_yield: float = 0.0
    redeposition_samples: int = 12
    visibility_spacing: float | None = None
    extension_cells: int = _EXTENSION_CELLS

    def __post_init__(self) -> None:
        for name in ("isotropic_floor", "mobility_length", "redeposition_yield"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be a non-negative finite number, got {value}")

    # -- the solver seam -----------------------------------------------------

    @property
    def max_arrival(self) -> float:
        """Largest arrival any surface orientation could receive.

        The CFL bound has to exist before the first sub-step, so it is derived
        from the distribution and the yield rather than measured on the front —
        the same reason `SurfaceRates.bound` is taken over the rate table and not
        over the materials currently exposed. Both together make a split dose
        comparable to an unsplit one.
        """
        _, weights = self.distribution.quadrature()
        direct = float(np.sum(weights)) * self.yield_model.peak_response
        reflected = direct * self.yield_model.max_reflected_fraction
        return direct + reflected + float(self.isotropic_floor)

    def on_front(self, grid: Grid, solid: np.ndarray) -> np.ndarray:
        """Arrival per cell for an already-repaired union field — what the solver calls."""
        return self.evaluate(grid, solid).arrival

    def on_structure(
            self,
            structure: Structure,
            *,
            release: np.ndarray | None = None,
            policy: reinit.ReinitPolicy = reinit.ReinitPolicy(),
    ) -> FluxOutcome:
        """Everything this model has to say about one `Structure`.

        Takes the union front through `motion.union_front`, never
        `structure.solid_phi`: a buried seam between two touching materials is
        exactly zero there and a march would read it as a wall (plan §17.1).
        """
        _require_2d(structure.grid)
        return self.evaluate(
            structure.grid, motion.union_front(structure, policy), release=release
        )

    # -- the computation -----------------------------------------------------

    def evaluate(
            self, grid: Grid, solid: np.ndarray, *, release: np.ndarray | None = None
    ) -> FluxOutcome:
        """Arrival (and redeposition) for a union field, as a `FluxOutcome`.

        `release` scales, per cell, how readily a site gives material up to the
        redeposition bounce — normally each material's etch rate relative to the
        fastest one. It is the seam where material knowledge enters a module that
        otherwise only knows geometry: without it a hard mask standing in an ion
        beam would redeposit material it is not losing. `None` means every site
        releases in proportion to what it receives, which is right for a scene of
        one material and is what the geometry alone can say.
        """
        _require_2d(grid)
        union = grid.as_field(solid, dtype=PHI_DTYPE)
        coarse = (
            2.0 * grid.spacing
            if self.visibility_spacing is None
            else float(self.visibility_spacing)
        )

        front = np.abs(union) < grid.spacing
        if not front.any():
            empty = np.zeros(grid.shape, dtype=np.float64)
            return FluxOutcome(arrival=empty, visibility_spacing=coarse)

        # Everything per-cell happens in a window around the front. The front is a
        # curve and the domain is an area, so gradients, indexing and the
        # extension over the whole domain would each cost more than the marching
        # they serve. Only the ray tracing reads the full field, and it only
        # *samples* it. The window is grown two cells past the collar so the
        # gradient stencil never reads a one-sided difference at a cell that is
        # used.
        view = _Window(grid, union, front, int(self.extension_cells) + 2)
        cells = np.argwhere(view.front)
        normals = measures.surface_normals(view.grid, view.phi)
        front_normals = normals[:, view.front].T.astype(np.float64)  # (N, 2), outward
        # Sub-cell foot point: the front cells straddle the zero level, and
        # `x - n * phi(x)` is where the front actually is to first order. Marching
        # from there is what keeps the shadow boundary from being cell-quantised.
        centres = np.asarray(view.grid.origin) + grid.spacing * cells
        feet = centres - front_normals * view.phi[view.front][:, None]

        visibility = _Visibility(grid, union, coarse)
        angles, weights = self.distribution.quadrature()
        directions = np.stack([np.cos(angles), np.sin(angles)], axis=1)  # (K, 2)

        cos_incidence = front_normals @ directions.T  # (N, K)
        lit = cos_incidence > 1e-9
        starts = np.broadcast_to(feet[:, None, :], (len(cells), len(angles), 2))
        fanned = np.broadcast_to(directions, (len(cells), len(angles), 2))
        rays = np.flatnonzero(lit.ravel())
        ray_count = int(rays.size)
        blocked = np.zeros(lit.size, dtype=bool)
        unresolved = 0
        if rays.size:
            march = visibility.march(
                starts.reshape(-1, 2)[rays], fanned.reshape(-1, 2)[rays]
            )
            blocked[rays] = march.blocked
            unresolved = march.unresolved

        response = self.yield_model.relative(np.clip(cos_incidence, 1e-6, 1.0))
        visible = lit & ~blocked.reshape(lit.shape)
        arrival = np.sum(weights * np.where(visible, cos_incidence, 0.0) * response, axis=1)
        arrival = arrival + float(self.isotropic_floor)

        local = np.zeros(view.shape, dtype=np.float64)
        local[view.front] = arrival
        if self.mobility_length > 0.0:
            local = _smear_along_front(view.grid, view.front, local, self.mobility_length)

        extension = _FrontExtension(view, int(self.extension_cells))
        extended = extension.apply(local)

        reflected = None
        reflection_fraction = self.yield_model.reflected_fraction(
            np.clip(cos_incidence, 1e-6, 1.0)
        )
        reflecting = visible & (reflection_fraction > 0.0)
        if np.any(reflecting):
            reflected_local, reflected_rays, reflected_unresolved = self._reflection(
                view,
                feet,
                front_normals,
                normals,
                directions,
                weights,
                cos_incidence,
                reflection_fraction,
                reflecting,
                visibility,
                extension,
            )
            reflected = extension.apply(reflected_local)
            extended = extended + reflected
            ray_count += reflected_rays
            unresolved += reflected_unresolved

        redeposited = None
        if self.redeposition_yield > 0.0:
            removed = extended
            if release is not None:
                removed = extended * grid.as_field(release, dtype=np.float64)
            redeposited = extension.apply(
                self._bounce(view, feet, front_normals, normals, removed, visibility)
            )

        return FluxOutcome(
            arrival=extended,
            redeposited=redeposited,
            reflected=reflected,
            front_cells=len(cells),
            angles=len(angles),
            rays=ray_count,
            unresolved=unresolved,
            visibility_spacing=visibility.spacing,
        )

    def _reflection(
            self,
            view: "_Window",
            feet: np.ndarray,
            front_normals: np.ndarray,
            normals: np.ndarray,
            directions: np.ndarray,
            weights: np.ndarray,
            cos_incidence: np.ndarray,
            fractions: np.ndarray,
            reflecting: np.ndarray,
            visibility: _Visibility,
            extension: _FrontExtension,
    ) -> tuple[np.ndarray, int, int]:
        """One specular ion bounce; reflected particles carry no material."""
        emitter, angle = np.nonzero(reflecting)
        incident_to_source = directions[angle]
        emitter_normal = front_normals[emitter]
        cosine = cos_incidence[emitter, angle]
        outgoing = -incident_to_source + 2.0 * cosine[:, None] * emitter_normal
        march = visibility.march(feet[emitter], outgoing)
        struck = march.blocked & (march.hit_cell >= 0)
        local_result = np.zeros(view.shape, dtype=np.float64)
        if not np.any(struck):
            return local_result, len(emitter), march.unresolved

        hit = np.flatnonzero(struck)
        local, seen = view.local_flat(march.hit_cell[hit])
        hit, local = hit[seen], local[seen]
        receiver_normal = normals.reshape(2, -1)[:, local].T
        receiver_cos = np.maximum(0.0, -np.sum(receiver_normal * outgoing[hit], axis=1))
        response = self.yield_model.relative(np.clip(receiver_cos, 1e-6, 1.0))
        strength = (
                weights[angle[hit]]
                * cosine[hit]
                * fractions[emitter[hit], angle[hit]]
                * receiver_cos
                * response
        )
        target = extension.front_flat(local)
        np.add.at(local_result.reshape(-1), target, strength)
        bound = (
                float(np.sum(weights))
                * self.yield_model.peak_response
                * self.yield_model.max_reflected_fraction
        )
        np.minimum(local_result, bound, out=local_result)
        return local_result, len(emitter), march.unresolved

    def _bounce(
            self,
            view: "_Window",
            feet: np.ndarray,
            front_normals: np.ndarray,
            normals: np.ndarray,
            removal: np.ndarray,
            visibility: _Visibility,
    ) -> np.ndarray:
        """One isotropic redeposition bounce off the sputtered sites (plan §4.3).

        Every front cell looks around its own hemisphere; whatever surface a
        direction lands on is a secondary source whose strength is the removal
        flux there. Marching from the *receiver* is what makes the bounce
        occlusion-correct for free — the first surface a ray reaches is by
        definition the one that can see it — and it reuses the same tracer as the
        primary visibility instead of a second, pairwise form factor.

        The weighting is the didactic two-cosine form factor: the receiver's
        `cos` (projected area, as for the primary flux) times the emitter's `cos`
        (an isotropically sputtering site radiates least along its own surface),
        averaged over the receiver's hemisphere. So the deposit can never exceed
        `redeposition_yield` times the strongest removal in sight, which is the
        bound the one-bounce approximation deserves.
        """
        count = max(2, int(self.redeposition_samples))
        offsets = -_HALF_PI + (np.arange(count) + 0.5) * (math.pi / count)  # (J,)
        cos_out, sin_out = np.cos(offsets), np.sin(offsets)
        # Rotate each front normal by every offset: the local hemisphere.
        tangents = np.stack([-front_normals[:, 1], front_normals[:, 0]], axis=1)
        directions = (
                front_normals[:, None, :] * cos_out[None, :, None]
                + tangents[:, None, :] * sin_out[None, :, None]
        )  # (N, J, 2)
        starts = np.broadcast_to(feet[:, None, :], directions.shape)

        flat_directions = directions.reshape(-1, 2)
        march = visibility.march(starts.reshape(-1, 2), flat_directions)
        emitted = np.zeros(march.blocked.shape, dtype=np.float64)
        struck = march.blocked & (march.hit_cell >= 0)
        if np.any(struck):
            hit = np.flatnonzero(struck)
            local, seen = view.local_flat(march.hit_cell[hit])
            hit, local = hit[seen], local[seen]
            source = removal.reshape(-1)[march.hit_cell[hit]]
            emitter_normals = normals.reshape(2, -1)[:, local].T
            emitter_cos = np.maximum(0.0, -np.sum(emitter_normals * flat_directions[hit], axis=1))
            emitted[hit] = source * emitter_cos

        received = np.sum(emitted.reshape(len(feet), count) * cos_out, axis=1) / float(
            np.sum(cos_out)
        )
        deposited = np.zeros(view.shape, dtype=np.float64)
        deposited[view.front] = float(self.redeposition_yield) * received
        return deposited


def _smear_along_front(
        grid: Grid, front: np.ndarray, values: np.ndarray, length: float
) -> np.ndarray:
    """Surface mobility: spread deposited flux over `length` nm of front (plan §4.3).

    A normalised convolution restricted to the front band — blur the flux and the
    band indicator with the same kernel and divide. Because the band is a thin
    tube around a curve, an isotropic blur of it *is* a smear along the front,
    without needing an arc-length parameterisation that a level-set representation
    does not have in the first place.
    """
    sigma = float(length) / grid.spacing
    indicator = front.astype(np.float64)
    smeared = ndimage.gaussian_filter(values, sigma, mode="nearest")
    weight = ndimage.gaussian_filter(indicator, sigma, mode="nearest")
    result = np.zeros_like(values)
    np.divide(smeared, weight, out=result, where=(weight > 1e-12) & front)
    return result


# -- the didactic technique set (plan §4.3, §6) ------------------------------


def evaporation(angle: float = 0.0, divergence: float = 0.0) -> FluxModel2D:
    """Directional deposition from a distant point source — S1's metal.

    A `Delta` source: sidewalls at normal incidence receive nothing, and a mask
    edge casts a shadow with a sharp boundary. `divergence > 0` turns the point
    source into a small lobe, which is the difference between an idealised
    evaporation and one from a finite crucible.
    """
    distribution: AngularDistribution = (
        Delta(angle) if divergence <= 0.0 else Lobe(angle, divergence)
    )
    return FluxModel2D(distribution=distribution)


def ion_beam_etch(
        angle: float = 0.0,
        divergence: float = math.radians(3.0),
        redeposition_yield: float = 0.0,
        yield_model: AngularYield | None = None,
) -> FluxModel2D:
    """Narrow-lobe physical sputtering with an angle-dependent yield (plan §6, IBE).

    Purely physical removal: no chemistry, hence no isotropic floor and no
    undercut. The yield peak off normal incidence is what facets corners, and the
    redeposition bounce is what lines a trench sidewall with what came out of its
    floor.
    """
    return FluxModel2D(
        distribution=Lobe(angle, divergence),
        yield_model=SputterYield() if yield_model is None else yield_model,
        redeposition_yield=redeposition_yield,
    )


def reactive_ion_etch(
        angle: float = 0.0,
        divergence: float = math.radians(5.0),
        chemical_fraction: float = 0.2,
) -> FluxModel2D:
    """Directional ion lobe plus an orientation-blind chemical component (plan §6, RIE).

    The chemical fraction is what separates RIE from IBE in every didactic
    picture: it etches sideways, so an RIE profile undercuts a little where an
    ion beam does not, and it keeps etching a surface the ions cannot see.
    """
    fraction = float(chemical_fraction)
    if not 0.0 <= fraction < 1.0:
        raise ValueError(f"chemical_fraction must be in [0, 1), got {chemical_fraction}")
    return FluxModel2D(
        distribution=Scaled(Lobe(angle, divergence), 1.0 - fraction),
        isotropic_floor=fraction,
    )


def sputter_deposition(
        exponent: float = 1.0, angle: float = 0.0, mobility_length: float = 0.0
) -> FluxModel2D:
    """Broad `cos^n` deposition with optional surface mobility (plan §6, sputter).

    The broad lobe puts metal on sidewalls that an evaporation leaves bare, which
    is what makes S4's fences exist at all; the mobility length decides whether
    they are continuous.
    """
    return FluxModel2D(
        distribution=CosinePower(exponent, angle), mobility_length=mobility_length
    )
