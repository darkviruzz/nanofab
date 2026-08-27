"""The resist set: spin-coat, exposure, development (plan §6, rows 2-6).

This is where plan §3.3's ideal/physical split stops being a sentence about
fields and becomes two pairs of processes:

| tier | exposure writes | development reads | how it moves the front |
|---|---|---|---|
| ideal | `exposed` (int8) | `resist & exposed` | one set operation |
| physical | `dose` (float32) | `develop_rate(dose)` | advection, gated |

Both pairs act on the same `Structure` and the same resist. What differs is the
`Field` and the *kind* of operation — which is exactly interview decision I1
(complexity lives in the process, the structure model stays uniform) and exactly
what makes the capability contract of §5.3 do real work: `develop.ideal` requires
`resist.exposed` and `develop.rate` requires `resist.dose`, so a chain that mixes
tiers is either complete or not runnable, and never silently wrong.

**Where a resist's numbers live** is settled the same way in both directions
(roadmap E13, E17): on the *material*. The develop step reads tone and clearing
dose from the resist's `DevelopModel`, and the spin coat reads its thickness from
the resist's `SpinCurve` at the speed the operator set. Both keep the typed value
as an **override** rather than removing it, because "I know this resist spins to
110 nm on our tool" is a legitimate thing to say — what ends is having to say it.

The **exposure patterns** are constructors (plan §4.1): sampled onto the grid
once, at exposure time, and then forgotten. `windows` and `grating` below return
signed-distance fields, so an ideal exposure boundary is exact to the constructor
rather than to the cell — and a `dose` exposure gets a smooth field to blur.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np
from scipy import ndimage

from nanofab_v3.kernel import constructors as ctor
from nanofab_v3.kernel import csg, motion, predicates, regions
from nanofab_v3.kernel.occurrences import label_region
from nanofab_v3.materials import RESIST, MaterialId
from nanofab_v3.model import capability
from nanofab_v3.model.field import FieldKey, FieldSpec
from nanofab_v3.model.grid import PHI_DTYPE, Grid
from nanofab_v3.model.quantity import Quantity
from nanofab_v3.model.structure import Structure
from nanofab_v3.materials.selection import MaterialFilter
from nanofab_v3.processes.contract import (
    DIDACTIC,
    IDEAL,
    FunctionStep,
    ParamSpec,
    StepContext,
    StepResult,
)
from nanofab_v3.processes.rates import develop_rates

EXPOSED = FieldSpec(
    name="exposed", dtype=np.int8, default=0, material_scoped=True, unit=""
)
"""The ideal tier's exposure field: 1 where the pattern struck the resist."""

DOSE = FieldSpec(
    name="dose", dtype=np.float32, default=0.0, material_scoped=True, unit="mJ/cm^2"
)
"""The physical tier's exposure field, in mJ/cm^2 (plan §3.3)."""


# -- exposure patterns, as constructors (plan §4.1) --------------------------


def windows(
    grid: Grid, spans: Sequence[tuple[float, float]], *, axis: str | int = -1
) -> np.ndarray:
    """Signed-distance field of a set of open stripes along one lateral axis.

    The simplest mask there is, and the one S1-S4 pattern with: a list of
    `(start, end)` in nm, negative inside. Built from `constructors.box`, so the
    edges are exact where the grid can represent them and the field is a usable
    distance everywhere else — which is what lets a `dose` exposure blur it into
    a realistic aerial image instead of a staircase.
    """
    if not spans:
        raise ValueError("windows needs at least one span")
    index = grid.axis_index(axis)
    boxes = []
    for start, end in spans:
        if float(end) <= float(start):
            raise ValueError(f"window span {(start, end)} is empty or inverted")
        lower: list[float | None] = [None] * grid.ndim
        upper: list[float | None] = [None] * grid.ndim
        lower[index] = float(start)
        upper[index] = float(end)
        boxes.append(ctor.box(grid, lower=lower, upper=upper))
    return csg.union(*boxes)


def grating(
    grid: Grid,
    *,
    period: float,
    duty: float = 0.5,
    phase: float = 0.0,
    axis: str | int = -1,
) -> np.ndarray:
    """Signed-distance field of a periodic line/space pattern (plan §4.1, §6).

    The procedural pattern of plan §3.3, sampled once. `duty` is the open
    fraction of a period; `phase` shifts the pattern in nm. Every open stripe that
    intersects the domain becomes a `box`, so the result is an exact SDF rather
    than a sampled square wave — the distinction that matters as soon as anything
    blurs it.
    """
    period = float(period)
    duty = float(duty)
    if period <= 0.0:
        raise ValueError(f"period must be positive, got {period}")
    if not 0.0 < duty < 1.0:
        raise ValueError(f"duty must be in (0, 1), got {duty}")
    index = grid.axis_index(axis)
    first, last = grid.extent(index)
    start = first - period + math.fmod(float(phase), period)
    spans = []
    while start < last + period:
        spans.append((start, start + duty * period))
        start += period
    return windows(grid, spans, axis=index)


# -- spin coating -------------------------------------------------------------


def spin_coat(
    structure: Structure,
    material: MaterialId,
    *,
    thickness: float,
    level: float | None = None,
) -> Structure:
    """Fill everything below a level with `material` — a planarising coat (plan §6).

    One constructor operation: a slab up to `level`, carved against everything
    already there by `add_material`. Planarising because that is what a spin coat
    does — the film is thick in a trench and thin over a bump, and its **top is
    flat**, which is the property lithography depends on and the reason the model
    does not simply offset the surface.

    `level` defaults to `thickness` above the highest solid cell, so "80 nm of
    resist" over a flat wafer means what it says, and over a 40 nm step means 80
    nm above the step — which is how a resist thickness is quoted.
    """
    grid = structure.grid
    thickness = float(thickness)
    if thickness <= 0.0:
        raise ValueError(f"thickness must be positive, got {thickness}")
    if level is None:
        solid = structure.solid_mask
        if not solid.any():
            raise ValueError("spin_coat needs something to coat")
        highest = int(np.max(np.argwhere(solid)[:, 0]))
        level = grid.origin[0] + grid.spacing * highest + thickness
    top, _ = grid.extent(0)
    upper: list[float | None] = [None] * grid.ndim
    upper[0] = float(level)
    return ctor.add_material(structure, material, ctor.box(grid, [None] * grid.ndim, upper))


# -- exposure -----------------------------------------------------------------


def expose_ideal(
    structure: Structure, material: MaterialId, pattern: np.ndarray
) -> Structure:
    """Write the `exposed` field from a pattern — the ideal tier (plan §3.3).

    A binary field: the pattern either struck this cell or it did not. No optics,
    no depth term, no diffusion — which is the point of the tier, and the honest
    statement of what an "ideal" lithography is. It is stored over the whole grid
    rather than masked to the resist, because the field is *material-scoped* and
    the commit gate's scoping rule is what keeps it meaningful: resist spun after
    this step arrives unexposed, whatever the pattern said about those cells.
    """
    grid = structure.grid
    if material not in structure.phi:
        raise KeyError(f"no material {material!r} to expose")
    struck = grid.as_field(pattern, dtype=PHI_DTYPE) <= 0.0
    # E33: a second exposure ORs into the first rather than replacing it. Both
    # halves of the decision are here and they are not the same statement:
    # `exposed` is binary, so OR is the only thing "twice" can mean, and it
    # loses the information that a cell was struck twice. `dose` below adds,
    # which is physically what two exposures do. The log says which happened.
    key = EXPOSED.key(material)
    if key in structure.fields:
        struck = struck | (np.asarray(structure.field(key)) != 0)
    return structure.with_field(key, struck.astype(np.int8))


def expose_dose(
    structure: Structure,
    material: MaterialId,
    pattern: np.ndarray,
    *,
    dose: float,
    blur: float = 0.0,
    absorption: float | None = None,
    library=None,
) -> Structure:
    """Write the `dose` field: pattern * blur, with a Beer-Lambert depth term (plan §6).

    Three effects, each one line, each the reason the physical tier exists:

    - the **aerial image** is the pattern smoothed by `blur` nm, so an edge is a
      gradient rather than a step and the developed sidewall gets a slope;
    - **Beer-Lambert** attenuates the dose with depth into the resist,
      `exp(-alpha * d)`, which is why a thick resist develops a foot;
    - the dose is a `float32` field, so `develop_rate(dose)` has something
      continuous to read.

    Depth is measured from the resist's own top surface — the distance transform
    of the cells above it — rather than from a nominal plane, so a resist coating
    a step gets the depth its geometry actually has.
    """
    grid = structure.grid
    if material not in structure.phi:
        raise KeyError(f"no material {material!r} to expose")
    aerial = (grid.as_field(pattern, dtype=PHI_DTYPE) <= 0.0).astype(np.float64)
    if blur > 0.0:
        aerial = ndimage.gaussian_filter(aerial, float(blur) / grid.spacing, mode="nearest")

    alpha = absorption
    if alpha is None:
        entry = None if library is None else library.get(material)
        alpha = 0.0 if entry is None else float(entry.absorption)
    values = float(dose) * aerial
    if alpha > 0.0:
        inside = predicates.cells_of(structure, material)
        depth = ndimage.distance_transform_edt(inside, sampling=grid.spacing)
        values = values * np.exp(-float(alpha) * depth)
    # E33: energy adds. Two exposures at 0.6 D0 clear a resist that neither
    # clears on its own, which is the whole of what a double exposure is for and
    # was silently impossible while this overwrote.
    key = DOSE.key(material)
    if key in structure.fields:
        values = values + np.asarray(structure.field(key), dtype=np.float64)
    return structure.with_field(key, values.astype(np.float32))


def threshold_dose(
    structure: Structure, material: MaterialId, *, threshold: float
) -> Structure:
    """The **downgrade adapter** of plan §5.3: `dose` -> `exposed`, information lost.

    Plan §5.3 allows downgrades and forbids upgrades, and this is what a downgrade
    looks like: a continuous dose profile becomes a binary field, and everything
    the profile said about the sidewall slope and the foot is gone. The step
    warns about exactly that — an adapter that discarded information silently
    would be worse than not having one, because the chain would keep running and
    the picture would quietly become the ideal tier's.

    There is deliberately no adapter the other way. `exposed -> dose` would have
    to invent the profile, and missing information cannot be invented.
    """
    key = DOSE.key(material)
    if not structure.has_field(key):
        raise KeyError(f"no dose field on {material!r} to downgrade")
    dose = np.asarray(structure.field(key))
    return structure.with_field(
        EXPOSED.key(material), (dose >= float(threshold)).astype(np.int8)
    )


# -- development --------------------------------------------------------------


def developed_tone(library, material: MaterialId) -> str:
    """Which of exposed/unexposed dissolves, according to the resist itself.

    Roadmap E13's other half, and the twin of `spun_thickness`: the *step* keeps a
    typed override because "our negative resist behaves like a positive one in
    this developer" is a legitimate thing to say, but nobody should have to say
    "this negative resist is negative".

    A library that cannot be asked answers `"positive"` rather than raising. This
    runs on the common path of every ideal development, and a resist with no
    `DevelopModel` is the same case E15 already warns about once, at the commit —
    failing here would report it a second time as a crash.
    """
    try:
        model = library[material].develop if library is not None else None
    except KeyError:
        model = None
    return getattr(model, "tone", None) or "positive"


def develop_ideal(
    structure: Structure,
    material: MaterialId,
    *,
    tone: str = "positive",
    faces: tuple[tuple[str, str], ...] | None = None,
) -> Structure:
    """Remove `resist & exposed` where the developer reaches it (plan §6).

    The **ideal tier's shape**, and the reason plan §4.4's reachability gate has
    two implementations: this is one `csg` operation with no rate and no time in
    it, so gating it is a question about *regions* — which connected pieces of
    the soluble region can the developer get to — and not about a speed field.

    Per connected piece, not per cell: a developer that reaches the top of an
    exposed column develops the column. A soluble pocket with no path to the
    surface stays, which is the ideal tier's version of the same physics S3 shows
    at scenario scale.
    """
    grid = structure.grid
    key = EXPOSED.key(material)
    if not structure.has_field(key):
        raise KeyError(f"no exposed field on {material!r}; run an exposure first")
    exposed = np.asarray(structure.field(key)) != 0
    if tone not in ("positive", "negative"):
        raise ValueError(f"tone must be 'positive' or 'negative', got {tone!r}")
    soluble = predicates.cells_of(structure, material) & (exposed if tone == "positive" else ~exposed)
    if not soluble.any():
        return structure

    labels, count = label_region(grid, soluble)
    wet = predicates.reachable_surface(grid, structure.solid_phi, faces=faces)
    reachable = np.unique(labels[wet & soluble])
    reachable = reachable[reachable > 0]
    if reachable.size == 0:
        return structure
    removed = np.isin(labels, reachable)
    return regions.remove_region(structure, removed, materials=(material,))


def develop_at_rate(
    structure: Structure,
    material: MaterialId,
    *,
    duration: float,
    library,
    faces: tuple[tuple[str, str], ...] | None = None,
    policy=None,
) -> motion.MotionOutcome:
    """Advect the front through the resist at `develop_rate(dose)` (plan §6).

    The **physical tier's shape**: a rate field, CFL sub-stepping, and the
    reachability gate as a *multiplier* rather than as a region — because the
    front moves, and every nanometre it moves opens paths that were closed. The
    two factors go through `advect_front(flux=...)` as one product
    (`motion.gated`), which is the seam that already existed for the flux model.

    Regrouping the speed field is what lets the motion kernel stay ignorant of
    dose: `rate(x) = bound * (develop_rate(dose(x)) / bound)` with
    `SurfaceRates({resist: bound})` is the same product `F = rate * flux` the
    solver already computes.
    """
    key = DOSE.key(material)
    if not structure.has_field(key):
        raise KeyError(f"no dose field on {material!r}; run a dose exposure first")
    rate_map, bound = develop_rates(library, structure, material, np.asarray(structure.field(key)))
    if bound <= 0.0:
        return motion.MotionOutcome(structure, swept=0.0, sub_steps=0)
    rates = motion.SurfaceRates({material: bound}, default=0.0)
    normalised = np.clip(rate_map / bound, 0.0, 1.0)
    gate = motion.gated(_ArrayFlux(normalised), predicates.ReachableFront(faces=faces))
    kwargs = {} if policy is None else {"policy": policy}
    return motion.advect_front(structure, rates, float(duration), flux=gate, **kwargs)


class _ArrayFlux:
    """A fixed per-cell multiplier in `FrontFlux` clothing.

    The dose does not change while the resist develops — it is a property of the
    exposure, not of the front — so this factor is a constant array. It still has
    to be a model rather than a bare array, because it is being *multiplied* by
    the reachability gate, which is not constant.
    """

    __slots__ = ("_values", "_bound")

    def __init__(self, values: np.ndarray) -> None:
        self._values = np.asarray(values, dtype=np.float64)
        self._bound = float(np.max(np.abs(self._values))) if self._values.size else 0.0

    @property
    def max_arrival(self) -> float:
        return self._bound

    def on_front(self, grid: Grid, solid: np.ndarray) -> np.ndarray:
        return self._values


# -- registered steps ---------------------------------------------------------


def pattern_from_params(grid: Grid, params) -> np.ndarray:
    """The mask an exposure step's parameters describe, on `grid`.

    Public because roadmap E9's light preview needs the *same* pattern the step
    would use, before the step runs: a preview built from a second reading of the
    parameters would be a second definition of what the mask is, and the two
    would drift the first time a parameter was added.
    """
    return _pattern_from_params(grid, params)


def domain_defaults(grid: Grid, params) -> dict[str, float]:
    """The litho parameters a `0` leaves to the domain (roadmap E33).

    `0` means "from the domain", the third instance of a convention this
    repository already has twice: `thickness=0` is "from the spin curve" and
    `material=""` is "from the preset". A marker rather than a new mechanism,
    because the alternative — a nullable default, or a separate "auto" checkbox
    per parameter — would be a second way to say the same thing.

    What the domain says, and why each is the obvious answer rather than a
    tunable one:

    - `center` and `grating_center`: the middle of the domain. A window at x = 0
      sits on the left wall, which is where the old default put it — a default
      nobody would type on purpose.
    - `period`: a third of the domain width, so a grating has three periods to
      look at. Wide enough that the shape is legible, narrow enough that the
      pattern is visibly periodic.

    Returns only the keys it resolved, so a caller can log what the domain
    decided rather than silently substituting.
    """
    ctx = params if hasattr(params, "__getitem__") else dict(params)
    width = float((grid.shape[-1] - 1) * grid.spacing)
    middle = float(grid.origin[-1]) + 0.5 * width
    resolved: dict[str, float] = {}
    if float(ctx["center"]) == 0.0:
        resolved["center"] = middle
    if float(ctx["grating_center"]) == 0.0:
        resolved["grating_center"] = middle
    if float(ctx["period"]) == 0.0:
        resolved["period"] = width / 3.0
    return resolved


def _pattern_from_params(grid: Grid, ctx: StepContext) -> np.ndarray:
    """Build the exposure pattern named by the step parameters."""
    resolved = domain_defaults(grid, ctx)
    if ctx["pattern"] == "grating":
        period = resolved.get("period", float(ctx["period"]))
        # `grating_center` is where a *line* sits, not where the waveform starts.
        # The old `phase` was the second, which is the same number only for one
        # duty cycle and is unusable as "put a line here" — the question anybody
        # actually has. Renamed rather than reinterpreted (E33), because a
        # parameter that quietly changed meaning would silently move every saved
        # recipe's grating.
        centre = resolved.get("grating_center", float(ctx["grating_center"]))
        duty = float(ctx["duty"])
        phase = centre - 0.5 * duty * period
        return grating(grid, period=period, duty=duty, phase=phase)
    half = 0.5 * float(ctx["width"])
    centre = resolved.get("center", float(ctx["center"]))
    return windows(grid, [(centre - half, centre + half)])


_PATTERN_PARAMS = (
    ParamSpec(
        "pattern",
        str,
        default="window",
        choices=("window", "grating"),
        description="Procedural pattern the mask projects",
    ),
    ParamSpec("center", float, unit="nm", default=0.0, minimum=0.0,
              description="Window centre; 0 is the middle of the domain (E33)"),
    ParamSpec("width", float, unit="nm", default=100.0, minimum=0.0, description="Window width"),
    ParamSpec("period", float, unit="nm", default=0.0, minimum=0.0,
              description="Grating period; 0 is a third of the domain width, so three lines"),
    ParamSpec("duty", float, default=0.5, minimum=0.0, maximum=1.0, description="Open fraction"),
    ParamSpec("grating_center", float, unit="nm", default=0.0, minimum=0.0,
              description=(
                  "Where a grating line sits; 0 is the middle of the domain. Was `phase`, "
                  "which named where the waveform started — the same number only at one "
                  "duty cycle, and never the question anybody has"
              )),
)


def spun_thickness(library, material: MaterialId, speed: float) -> tuple[float, bool]:
    """`(nm, was it clamped)` for one material at one spin speed (E17, §3.1).

    The seam between the step and the material's `SpinCurve`, and the place the
    two failures a spin coat can have get their sentences: a material the library
    does not know, and a material nobody measured a curve for. Both end in the
    same instruction — give it one, or type a thickness — because both are the
    same thing, which is that nothing on record says how thick this spins.
    """
    entry = library.get(material)
    if entry is None:
        raise ValueError(
            f"no MaterialType {material!r} in this library, so a spin speed does not "
            f"determine a thickness; add data/materials/{material}.json, or give this "
            "step a thickness"
        )
    if entry.spin_curve is None:
        raise ValueError(
            f"material {material!r} has no spin curve, so a spin speed does not "
            f"determine a thickness; measure one into data/materials/{material}.json "
            "(backlog B11), or give this step a thickness"
        )
    return entry.spin_thickness(speed), entry.spin_curve.clamps(speed)


def _run_spin_coat(ctx: StepContext) -> StepResult:
    material = MaterialId(str(ctx["material"]))
    speed = float(ctx["spin_speed"])
    override = float(ctx["thickness"])
    notes: list[str] = []
    if override > 0.0:
        thickness = override
        notes.append(f"thickness {thickness:.1f} nm (typed, overriding the spin curve)")
    else:
        thickness, clamped = spun_thickness(ctx.library, material, speed)
        notes.append(f"{thickness:.1f} nm at {speed:.0f} rpm (from the resist's spin curve)")
        if clamped:
            low, high = ctx.library[material].spin_curve.speed_range
            notes.append(
                f"{speed:.0f} rpm is outside the measured {low:.0f}-{high:.0f} rpm; the "
                "curve was clamped, not extrapolated"
            )
    structure = spin_coat(ctx.structure, material, thickness=thickness)
    return StepResult(
        structure=structure,
        provides=frozenset({capability.of_material(material)}),
        measurements={
            "thickness": Quantity(thickness, "nm"),
            "spin_speed": Quantity(speed, "rpm"),
        },
        logs=(f"spin-coated {material}: " + "; ".join(notes),),
    )


def _cumulative_note(structure: Structure, material: MaterialId, field: str) -> tuple[str, ...]:
    """Say that this exposure landed on an existing one, and what that costs.

    Information, not a warning — the same honesty `threshold_dose` already
    practises about what it discards. Adding energy is right and losing the count
    of how often a cell was struck is a real loss; both are facts about what just
    happened, and neither is a mistake to be corrected.
    """
    spec = DOSE if field == DOSE.name else EXPOSED
    if spec.key(material) not in structure.fields:
        return ()
    if field == DOSE.name:
        return (f"    a {field} field was already there: the two doses add",)
    return (
        f"    an {field} field was already there: the two are OR-ed, so how often "
        "a cell was struck is not recorded",
    )


def _run_expose_ideal(ctx: StepContext) -> StepResult:
    material = MaterialId(str(ctx["material"]))
    pattern = _pattern_from_params(ctx.structure.grid, ctx)
    structure = expose_ideal(ctx.structure, material, pattern)
    return StepResult(
        structure=structure,
        provides=frozenset({capability.of_field(material, EXPOSED.name)}),
        field_specs={EXPOSED.name: EXPOSED},
        logs=(
            f"exposed {material} through a {ctx['pattern']} pattern (ideal)",
        ) + _cumulative_note(ctx.structure, material, EXPOSED.name),
    )


def _run_expose_dose(ctx: StepContext) -> StepResult:
    material = MaterialId(str(ctx["material"]))
    pattern = _pattern_from_params(ctx.structure.grid, ctx)
    structure = expose_dose(
        ctx.structure,
        material,
        pattern,
        dose=ctx["dose"],
        blur=ctx["blur"],
        library=ctx.library,
    )
    return StepResult(
        structure=structure,
        provides=frozenset({capability.of_field(material, DOSE.name)}),
        field_specs={DOSE.name: DOSE},
        measurements={"dose": Quantity(ctx["dose"], "mJ/cm^2")},
        logs=(
            f"exposed {material} at {ctx['dose']:.0f} mJ/cm^2, blur {ctx['blur']:.1f} nm",
        ) + _cumulative_note(ctx.structure, material, DOSE.name),
    )


def _run_threshold(ctx: StepContext) -> StepResult:
    material = MaterialId(str(ctx["material"]))
    structure = threshold_dose(ctx.structure, material, threshold=ctx["threshold"])
    return StepResult(
        structure=structure,
        provides=frozenset({capability.of_field(material, EXPOSED.name)}),
        field_specs={EXPOSED.name: EXPOSED, DOSE.name: DOSE},
        logs=(
            f"downgraded dose to exposed at {ctx['threshold']:.0f} mJ/cm^2 — "
            "the dose profile's sidewall slope and foot are discarded",
        ),
    )


def _run_develop_ideal(ctx: StepContext) -> StepResult:
    material = MaterialId(str(ctx["material"]))
    typed = str(ctx["tone"])
    tone, source = (typed, "typed") if typed else (developed_tone(ctx.library, material), "from the resist")
    structure = develop_ideal(ctx.structure, material, tone=tone)
    return StepResult(
        structure=structure,
        field_specs={EXPOSED.name: EXPOSED},
        logs=(f"developed {material} ({tone} tone, {source}; ideal, reachability-gated)",),
    )


def _run_develop_rate(ctx: StepContext) -> StepResult:
    material = MaterialId(str(ctx["material"]))
    outcome = develop_at_rate(
        ctx.structure, material, duration=ctx["duration"], library=ctx.library
    )
    return StepResult(
        structure=outcome.structure,
        swept=outcome.swept,
        field_specs={DOSE.name: DOSE},
        measurements={"duration": Quantity(ctx["duration"], "s")},
        logs=(f"developed {material} for {ctx['duration']:.1f} s at develop_rate(dose)",),
    )


_MATERIAL = ParamSpec(
    "material",
    str,
    default=str(RESIST),
    description="Resist material",
    # Roadmap E22, the *tag* half. A spin coat at this tier puts a layer down for
    # a typed thickness and consults no curve, so "what does the library know
    # about it" filters nothing — and chromium is still nonsense in a spin
    # coater. E21's substance classes are the only thing that can say so.
    material=MaterialFilter(tags=("resist",), what="resists"),
)

_DEVELOPABLE = ParamSpec(
    "material",
    str,
    default=str(RESIST),
    description="Resist material",
    # The *library data* half: a developer bath acts through `DevelopModel`, so
    # a material without one is a material this step would run on at rate zero.
    material=MaterialFilter(submodel="develop", what="resists a developer attacks"),
)

SPIN_COAT = FunctionStep(
    step_id="resist.spin_coat",
    display_name="Spin-coat resist",
    fidelity=IDEAL,
    schema=(
        _MATERIAL,
        ParamSpec(
            "spin_speed",
            float,
            unit="rpm",
            default=3000.0,
            minimum=1.0,
            maximum=12000.0,
            description=(
                "Spin speed. The thickness follows from the resist's own measured spin "
                "curve; outside the measured range the curve is clamped rather than "
                "extrapolated, and the run log says so."
            ),
        ),
        ParamSpec(
            "thickness",
            float,
            unit="nm",
            default=0.0,
            minimum=0.0,
            description=(
                "Override: film thickness above the highest topography. 0 means 'derive "
                "it from spin_speed', which is the normal case — the thickness belongs to "
                "the resist, not to this step (roadmap E17)."
            ),
        ),
        ParamSpec(
            "spin_time",
            float,
            unit="s",
            default=30.0,
            minimum=0.0,
            description=(
                "Documented only: it does NOT enter the thickness. The measured curve "
                "parameterises speed alone, which is physically reasonable above some "
                "minimum time but is an assumption — so the time is recorded and not "
                "used, rather than quietly folded into a number (roadmap §3.1)."
            ),
        ),
    ),
    required=frozenset(),
    provided=frozenset(),
    run_function=_run_spin_coat,
    description=(
        "Coats the sample with resist. The film is planarising — thick in a trench, thin over a "
        "bump, and flat on top — which is what lithography depends on and what a spin coat "
        "really does."
        "\n\n"
        "`spin_speed` decides the thickness, through the resist's own measured spin curve: at "
        "3000 rpm the generic resist gives 82 nm. `thickness` overrides that when you know "
        "better, and 0 means 'use the curve'. `spin_time` is recorded and does NOT enter the "
        "thickness — the curve was measured against speed alone, and inventing a time "
        "dependence would be inventing data."
        "\n\n"
        "Outside the measured 1000-5000 rpm the curve is clamped rather than extrapolated, and "
        "the run log says so."
        "\n\n"
        "Needs: something to coat."
    ),
)

EXPOSE_IDEAL = FunctionStep(
    step_id="litho.expose_ideal",
    display_name="Exposure (ideal)",
    fidelity=IDEAL,
    schema=(_MATERIAL, *_PATTERN_PARAMS),
    required=frozenset(),
    provided=frozenset(),
    run_function=_run_expose_ideal,
    description=(
        "Exposes the resist through a mask with no optics at all: wherever the pattern is open "
        "the resist is marked exposed, exactly, to the edge of the pattern rather than to the "
        "edge of a cell."
        "\n\n"
        "`pattern` chooses a single window or a grating; `center` and `width`, or `period`, "
        "`duty` and `grating_center`, place it. It writes the `exposed` field, which is what ideal "
        "development consumes."
        "\n\n"
        "This is the ideal tier: no dose, no blur, no depth. Run `litho.expose_dose` on the "
        "same stack to see what a real aerial image does to an edge — the difference between "
        "the two pictures is the point of having both."
        "\n\n"
        "Needs: a resist to expose."
    ),
)

EXPOSE_DOSE = FunctionStep(
    step_id="litho.expose_dose",
    display_name="Exposure (dose)",
    fidelity=DIDACTIC,
    schema=(
        _MATERIAL,
        *_PATTERN_PARAMS,
        ParamSpec(
            "dose", float, unit="mJ/cm^2", default=150.0, minimum=0.0, description="Peak dose"
        ),
        ParamSpec(
            "blur", float, unit="nm", default=8.0, minimum=0.0, description="Aerial image blur"
        ),
    ),
    required=frozenset(),
    provided=frozenset(),
    run_function=_run_expose_dose,
    description=(
        "Exposes the resist with a real aerial image: the mask pattern blurred by `blur`, "
        "scaled to a peak `dose`, and attenuated with depth through the resist's own absorption "
        "(Beer-Lambert)."
        "\n\n"
        "It writes the `dose` field in mJ/cm^2, which `develop.rate` turns into a shape through "
        "the resist's contrast curve. A large `blur` is a poor aerial image, and the sloped "
        "resist wall that follows from it is not modelled anywhere — it is what a blurred dose "
        "develops into."
        "\n\n"
        "Needs: a resist to expose."
    ),
)

THRESHOLD_DOSE = FunctionStep(
    step_id="litho.threshold_dose",
    display_name="Threshold dose to exposed (downgrade)",
    fidelity=IDEAL,
    schema=(
        _MATERIAL,
        ParamSpec(
            "threshold",
            float,
            unit="mJ/cm^2",
            default=100.0,
            minimum=0.0,
            description="Dose above which a cell counts as exposed",
        ),
    ),
    required=frozenset(),
    provided=frozenset(),
    run_function=_run_threshold,
    description=(
        "Turns a `dose` field into an `exposed` one by thresholding it — the one downgrade "
        "adapter in the set."
        "\n\n"
        "It exists to make the direction of information explicit. A dose knows more than a "
        "yes/no, and throwing that away should be a step somebody chose rather than something "
        "the engine does quietly. There is no adapter the other way, because there is no way to "
        "invent the dose that produced a binary image."
        "\n\n"
        "Needs: a resist with a `dose` field."
    ),
)

DEVELOP_IDEAL = FunctionStep(
    step_id="develop.ideal",
    display_name="Development (ideal)",
    fidelity=IDEAL,
    schema=(
        _DEVELOPABLE,
        ParamSpec(
            "tone",
            str,
            default="",
            choices=("", "positive", "negative"),
            description="Which of exposed/unexposed dissolves; empty takes the resist's own",
        ),
    ),
    required=frozenset({capability.of_field(RESIST, EXPOSED.name)}),
    provided=frozenset(),
    run_function=_run_develop_ideal,
    description=(
        "Develops the resist in one set operation: every reachable piece of exposed resist — or "
        "unexposed, for a negative tone — is simply gone. No time, no rate."
        "\n\n"
        "`tone` comes from the resist's own develop model — leave it empty and the material "
        "decides, which is the whole of roadmap E13; typing one overrides it for this step and "
        "the run log says which of the two happened. Reachability still applies: resist the "
        "developer cannot get to stays, which is why a sealed cavity does not clear."
        "\n\n"
        "The honest description of this tier is `develop.rate` with infinite contrast. Use that "
        "one to see a partially developed profile."
        "\n\n"
        "Needs: a resist with an `exposed` field."
    ),
)

DEVELOP_RATE = FunctionStep(
    step_id="develop.rate",
    display_name="Development (rate)",
    fidelity=DIDACTIC,
    schema=(
        _DEVELOPABLE,
        ParamSpec(
            "duration", float, unit="s", default=None, minimum=0.0, description="Develop time"
        ),
    ),
    required=frozenset({capability.of_field(RESIST, DOSE.name)}),
    provided=frozenset(),
    run_function=_run_develop_rate,
    description=(
        "Develops for `duration` seconds at the rate the resist's contrast curve gives for the "
        "local dose, so the front moves at a different speed in every cell."
        "\n\n"
        "This is where dose contrast becomes a shape: a high-contrast resist gives a vertical "
        "wall, a low-contrast one a slope, and an under-exposed window never clears. Unexposed "
        "resist still creeps at the model's dark rate, which is what thins a film during a long "
        "develop."
        "\n\n"
        "Needs: a resist with a `dose` field."
    ),
)
