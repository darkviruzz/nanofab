"""Removal: wet etch, RIE, ion beam etch (plan §6, rows 7-9).

The contrast S2 is about lives entirely in which flux model a wrapper picks:

- **wet etch** — no flux model at all, only the reachability gate. Isotropic by
  construction, so it undercuts a mask by exactly as much as it etches down, and
  the undercut ratio comes out at 1 without anything in the model knowing what an
  undercut is.
- **RIE** — a narrow ion lobe plus an orientation-blind chemical floor. The floor
  is what makes it undercut *a little*, and it is gated: §18's note on the floor
  says a radical flux keeps feeding a surface the ions cannot see, and plan
  §4.4's reachability gate is what stops it feeding a cavity that has sealed.
- **IBE** — a narrow lobe with an angle-dependent yield and no chemistry, so the
  walls stand where the mask edge is. Optionally with the redeposition bounce,
  which is the one place a process runs the solver **twice**: once to remove, once
  to put back what did not leave.

Selectivity is not modelled here either. It is the material's rate table: a mask
at rate 0 stalls the front, which is plan §4.2's "mask behaviour emerges from
rates", and `rates.surface_rates` is the only place that is read.

**M6 added the chemistries of roadmap §3's process table**, and they are the same
three shapes with a different rate key. What decides which shape a chemistry gets
is one column of that table: it distinguishes "horizontal = vertical" from
"vertical", and those are *not* two rates. A rate here is a scalar — the speed of
an open, normal-facing surface (`materials.MaterialType.rate_for`) — so the
distinction lives entirely in the angular distribution the wrapper picks:

| the table says | the step builds | which reads |
|---|---|---|
| horizontal = vertical | no flux model, reachability gate only | `isotropic_etch` |
| vertical | a narrow lobe, reachability-gated | `directional_etch` |

That is why an oxygen RIE and a chromium wet etch are the *same function* here
with a different `process_class`: at this fidelity an isotropic plasma and an
isotropic bath differ in what they attack, not in how they move a front. The
difference between them is data, and it is in `data/materials/`.
"""

from __future__ import annotations

import math

from nanofab_v3.kernel import flux, motion, predicates
from nanofab_v3.materials import (
    DRY_ETCH,
    ICP_FLUORINE,
    ION_BEAM,
    RIE_CHLORINE,
    RIE_OXYGEN,
    SPUTTER_ETCH,
    WET_ETCH,
    WET_ETCH_CR,
    WET_ETCH_OXIDE,
    MaterialId,
)
from nanofab_v3.model.quantity import Quantity
from nanofab_v3.model.structure import Structure
from nanofab_v3.processes.contract import (
    DIDACTIC,
    FunctionStep,
    ParamSpec,
    StepContext,
    StepResult,
)
from nanofab_v3.processes.rates import dominant_yield, release_map, surface_rates


def wet_etch(
    structure: Structure,
    *,
    duration: float,
    library,
    scale: float = 1.0,
    faces: tuple[tuple[str, str], ...] | None = None,
) -> motion.MotionOutcome:
    """Isotropic chemical removal, gated on reachability (plan §6, §4.4).

    No flux model: an isotropic etchant has no line to block, so there is nothing
    to compute visibility for (`CONTEXT.md`, *Isotropic*). What there *is* to
    compute is whether the etchant gets there at all — a sealed cavity is not
    etched, and a bath cannot reach through a mask it does not attack.

    The general path rather than `offset_solid`, even though the motion is
    isotropic, because the rates are not uniform over the front: a mask at rate 0
    and a substrate at rate 1 make the fast path's precondition false. That the
    result *is* an offset wherever one material fills the front is worth knowing
    and is a standing test.
    """
    rates = surface_rates(library, structure, WET_ETCH, scale=scale)
    return motion.advect_front(
        structure, rates, float(duration), flux=predicates.ReachableFront(faces=faces)
    )


def isotropic_etch(
    structure: Structure,
    *,
    duration: float,
    library,
    process_class: str,
    scale: float = 1.0,
    faces: tuple[tuple[str, str], ...] | None = None,
) -> motion.MotionOutcome:
    """Removal at one material rate in every direction, gated on reachability.

    `wet_etch` above with the rate key as an argument, which is what M6's table
    needed: rows 3-6 are four different baths and plasmas whose only modelled
    difference is which material each one attacks. "Horizontal = vertical" is
    exactly the absence of a flux model — an isotropic process has no line to
    block (`CONTEXT.md`, *Isotropic*), so undercut equals depth and nothing has
    to be told to make that happen.

    The gate is not decoration even for a plasma: a radical that cannot reach a
    surface does not etch it, which is what stops a sealed cavity from being fed
    (plan §4.4). `flux.Isotropic` is the more expensive alternative, where the
    hemisphere is *shadowed* and a deep trench therefore etches slower — the
    mechanism behind aspect-ratio-dependent etching. It is deliberately not what
    these steps use: the table states one rate per material and no ARDE, and
    modelling an effect the numbers do not contain would make the picture look
    more measured than it is.
    """
    rates = surface_rates(library, structure, process_class, scale=scale)
    return motion.advect_front(
        structure, rates, float(duration), flux=predicates.ReachableFront(faces=faces)
    )


def directional_etch(
    structure: Structure,
    *,
    duration: float,
    library,
    process_class: str,
    angle: float = 0.0,
    divergence: float = math.radians(5.0),
    chemical_fraction: float = 0.0,
    scale: float = 1.0,
    faces: tuple[tuple[str, str], ...] | None = None,
) -> motion.MotionOutcome:
    """A narrow ion lobe at one material rate — the table's "vertical" rows.

    `reactive_ion_etch` with the rate key as an argument and the chemical floor
    at **zero** by default, which is the difference between the two: the didactic
    RIE step is about what a chemical component does to a profile, and this is
    about a chemistry whose measured lateral rate is nothing. Leaving the floor
    as a parameter rather than removing it is the didactic payload — turning it up
    is how a student sees the vertical wall of the table become the undercut one.
    """
    model = flux.reactive_ion_etch(
        angle=float(angle),
        divergence=float(divergence),
        chemical_fraction=float(chemical_fraction),
    )
    rates = surface_rates(library, structure, process_class, scale=scale)
    gate = motion.gated(model, predicates.ReachableFront(faces=faces))
    return motion.advect_front(structure, rates, float(duration), flux=gate)


def reactive_ion_etch(
    structure: Structure,
    *,
    duration: float,
    library,
    angle: float = 0.0,
    divergence: float = math.radians(5.0),
    chemical_fraction: float = 0.2,
    scale: float = 1.0,
    faces: tuple[tuple[str, str], ...] | None = None,
) -> motion.MotionOutcome:
    """Directional ion lobe plus an orientation-blind chemical component (plan §6).

    The chemical fraction is what separates RIE from IBE in every didactic
    picture, and it is a *flux floor* rather than a mixture component with its own
    visibility (an M2 decision, §18): a radical flux is scattering-dominated and
    effectively orientation-blind. The floor is exactly why this process needs the
    reachability gate and an ion beam barely does — an orientation-blind arrival
    is also a visibility-blind one.
    """
    model = flux.reactive_ion_etch(
        angle=float(angle), divergence=float(divergence), chemical_fraction=float(chemical_fraction)
    )
    rates = surface_rates(library, structure, DRY_ETCH, scale=scale)
    gate = motion.gated(model, predicates.ReachableFront(faces=faces))
    return motion.advect_front(structure, rates, float(duration), flux=gate)


def ion_beam_etch(
    structure: Structure,
    *,
    duration: float,
    library,
    angle: float = 0.0,
    divergence: float = math.radians(3.0),
    redeposition_yield: float = 0.0,
    redeposit_as: MaterialId | None = None,
    scale: float = 1.0,
    faces: tuple[tuple[str, str], ...] | None = None,
    process_class: str = ION_BEAM,
) -> motion.MotionOutcome:
    """Narrow-lobe physical sputtering, optionally with a redeposition bounce (plan §6).

    Two passes when `redeposition_yield > 0`, which is the shape the M3 handoff
    describes: `FluxOutcome.redeposited` is a *deposition* flux in the same units
    as the arrival, so the second pass is an ordinary `advect_front` with it as a
    static array. It is static on purpose — one bounce off the surface the etch
    just produced, evaluated once, rather than a coupled removal/redeposition
    problem the didactic tier has no business solving.

    `release` is what stops a hard mask from redepositing material it is not
    losing: `rates.release_map` weights each site by its own material's etch rate
    relative to the fastest. Without it the flux model, which knows only geometry,
    would treat every surface in sight as a source.

    `process_class` exists because M6's table has a sputter-etch row of its own
    (roadmap §3 row 1) whose numbers are not the didactic `ion_beam` ones. Same
    physics, same wrapper, a different rate key — plan §5.4's "several processes
    may model the same technique", here differing only in which column of the
    library they read.
    """
    model = flux.ion_beam_etch(
        angle=float(angle),
        divergence=float(divergence),
        redeposition_yield=float(redeposition_yield),
        yield_model=dominant_yield(library, structure, process_class),
    )
    rates = surface_rates(library, structure, process_class, scale=scale)
    gate = motion.gated(model, predicates.ReachableFront(faces=faces))
    outcome = motion.advect_front(structure, rates, float(duration), flux=gate)
    if redeposition_yield <= 0.0 or redeposit_as is None:
        return outcome

    etched = outcome.structure
    bounce = model.on_structure(etched, release=release_map(library, etched, process_class))
    if bounce.redeposited is None:
        return outcome
    # The bounce is an arrival per unit front like any other, so the deposition
    # that follows is a plain motion: the redeposited layer's thickness is what
    # that flux lays down over the same time at the same rate.
    back = motion.advect_front(
        etched,
        motion.SurfaceRates(rates={}, default=rates.bound),
        float(duration),
        deposit_material=redeposit_as,
        flux=bounce.redeposited,
    )
    return motion.MotionOutcome(
        structure=back.structure,
        swept=outcome.swept + back.swept,
        sub_steps=outcome.sub_steps + back.sub_steps,
        dt=outcome.dt,
        max_speed=max(outcome.max_speed, back.max_speed),
        reinit_passes=outcome.reinit_passes + back.reinit_passes,
        flux_rebuilds=outcome.flux_rebuilds + back.flux_rebuilds,
    )


# -- registered steps ---------------------------------------------------------


def _etch_result(ctx: StepContext, outcome, note: str) -> StepResult:
    return StepResult(
        structure=outcome.structure,
        swept=outcome.swept,
        measurements={"duration": Quantity(ctx["duration"], "s")},
        logs=(note,),
    )


def _run_wet(ctx: StepContext) -> StepResult:
    outcome = wet_etch(
        ctx.structure, duration=ctx["duration"], library=ctx.library, scale=ctx["scale"]
    )
    return _etch_result(ctx, outcome, f"wet etch, {ctx['duration']:.1f} s (reachability-gated)")


def _run_rie(ctx: StepContext) -> StepResult:
    outcome = reactive_ion_etch(
        ctx.structure,
        duration=ctx["duration"],
        library=ctx.library,
        angle=math.radians(ctx["angle"]),
        divergence=math.radians(ctx["divergence"]),
        chemical_fraction=ctx["chemical_fraction"],
        scale=ctx["scale"],
    )
    return _etch_result(
        ctx,
        outcome,
        f"RIE, {ctx['duration']:.1f} s, chemical fraction {ctx['chemical_fraction']:.2f}",
    )


def _run_ibe(ctx: StepContext) -> StepResult:
    redeposit = ctx["redeposit_as"].strip()
    outcome = ion_beam_etch(
        ctx.structure,
        duration=ctx["duration"],
        library=ctx.library,
        angle=math.radians(ctx["angle"]),
        divergence=math.radians(ctx["divergence"]),
        redeposition_yield=ctx["redeposition_yield"],
        redeposit_as=MaterialId(redeposit) if redeposit else None,
        scale=ctx["scale"],
    )
    return _etch_result(
        ctx,
        outcome,
        f"ion beam etch, {ctx['duration']:.1f} s at {ctx['angle']:.0f} deg",
    )


_DURATION = ParamSpec(
    "duration", float, unit="s", default=None, minimum=0.0, description="Process time"
)
_SCALE = ParamSpec(
    "scale",
    float,
    default=1.0,
    minimum=0.0,
    description="Machine setting as a factor on every material's blanket rate",
)

WET_ETCH_STEP = FunctionStep(
    step_id="etch.wet",
    display_name="Wet / chemical etch",
    fidelity=DIDACTIC,
    schema=(_DURATION, _SCALE),
    required=frozenset(),
    provided=frozenset(),
    run_function=_run_wet,
    description=(
        "Isotropic chemical removal in a bath. No flux model at all: an isotropic etchant has "
        "no line of sight to block, so it undercuts a mask by exactly as much as it etches "
        "down, and the undercut ratio comes out at 1 without anything in the model knowing what "
        "an undercut is."
        "\n\n"
        "What it does compute is whether the etchant gets there: a sealed cavity is not etched, "
        "and a bath cannot reach through a mask it does not attack. Which materials it attacks "
        "is the material library's `wet_etch` column, not a parameter — a mask at rate 0 stalls "
        "the front, and that is all a hard mask is here."
        "\n\n"
        "`duration` is the process time; `scale` is a machine setting as a factor on every "
        "material's rate."
        "\n\n"
        "Needs: a sample."
    ),
)

RIE_STEP = FunctionStep(
    step_id="etch.rie",
    display_name="Reactive ion etch",
    fidelity=DIDACTIC,
    schema=(
        _DURATION,
        _SCALE,
        ParamSpec("angle", float, unit="deg", default=0.0, minimum=-85.0, maximum=85.0,
                  description="Beam tilt from the surface normal"),
        ParamSpec("divergence", float, unit="deg", default=5.0, minimum=0.0, maximum=45.0,
                  description="Angular half-width of the ion lobe"),
        ParamSpec("chemical_fraction", float, default=0.2, minimum=0.0, maximum=0.95,
                  description="Share of the etch carried by orientation-blind chemistry"),
    ),
    required=frozenset(),
    provided=frozenset(),
    run_function=_run_rie,
    description=(
        "A narrow ion lobe plus an orientation-blind chemical floor. The floor is what "
        "separates RIE from ion milling in every didactic picture: it etches sideways a little, "
        "so an RIE profile undercuts where an ion beam does not, and it keeps feeding a surface "
        "the ions cannot see."
        "\n\n"
        "`chemical_fraction` is that floor. Turn it to 0 and the walls stand where the mask "
        "edge is; turn it up and watch the profile open out. `angle` and `divergence` shape the "
        "ion lobe. Rates come from the library's `dry_etch` column."
        "\n\n"
        "Needs: a sample."
    ),
)

# -- the chemistries of roadmap §3's process table -----------------------------
#
# Seven wrappers over the two functions above, and nothing else. What separates
# them is one string each — which column of `data/materials/*.json` they read —
# and, for `etch.icp_fluorine`, that the table calls it vertical.


# Four near-identical runners rather than one factory returning a closure, and
# the reason is the cache. `registry.implementation_digest` reads a step's
# wrapper with `inspect.getsource`, and four closures made by one factory have
# **one** source text between them: the rate key each captured would be invisible
# to the digest, so pointing `etch.rie_chlorine` at the oxygen column would not
# retire a single cached revision. Written out, each one's own class constant is
# in its own source, which is what the digest is for (plan §21.1).


def _run_rie_chlorine(ctx: StepContext) -> StepResult:
    outcome = isotropic_etch(
        ctx.structure,
        duration=ctx["duration"],
        library=ctx.library,
        process_class=RIE_CHLORINE,
        scale=ctx["scale"],
    )
    return _etch_result(
        ctx, outcome, f"RIE in chlorine, {ctx['duration']:.1f} s (isotropic, gated)"
    )


def _run_rie_oxygen(ctx: StepContext) -> StepResult:
    outcome = isotropic_etch(
        ctx.structure,
        duration=ctx["duration"],
        library=ctx.library,
        process_class=RIE_OXYGEN,
        scale=ctx["scale"],
    )
    return _etch_result(
        ctx, outcome, f"RIE in oxygen, {ctx['duration']:.1f} s (isotropic, gated)"
    )


def _run_wet_cr(ctx: StepContext) -> StepResult:
    outcome = isotropic_etch(
        ctx.structure,
        duration=ctx["duration"],
        library=ctx.library,
        process_class=WET_ETCH_CR,
        scale=ctx["scale"],
    )
    return _etch_result(
        ctx, outcome, f"chromium wet etch, {ctx['duration']:.1f} s (isotropic, gated)"
    )


def _run_wet_oxide(ctx: StepContext) -> StepResult:
    outcome = isotropic_etch(
        ctx.structure,
        duration=ctx["duration"],
        library=ctx.library,
        process_class=WET_ETCH_OXIDE,
        scale=ctx["scale"],
    )
    return _etch_result(
        ctx, outcome, f"buffered oxide etch, {ctx['duration']:.1f} s (isotropic, gated)"
    )


def _run_icp_fluorine(ctx: StepContext) -> StepResult:
    outcome = directional_etch(
        ctx.structure,
        duration=ctx["duration"],
        library=ctx.library,
        process_class=ICP_FLUORINE,
        angle=math.radians(ctx["angle"]),
        divergence=math.radians(ctx["divergence"]),
        chemical_fraction=ctx["chemical_fraction"],
        scale=ctx["scale"],
    )
    return _etch_result(
        ctx,
        outcome,
        f"ICP fluorine etch, {ctx['duration']:.1f} s, chemical fraction "
        f"{ctx['chemical_fraction']:.2f}",
    )


def _run_sputter_etch(ctx: StepContext) -> StepResult:
    redeposit = ctx["redeposit_as"].strip()
    outcome = ion_beam_etch(
        ctx.structure,
        duration=ctx["duration"],
        library=ctx.library,
        angle=math.radians(ctx["angle"]),
        divergence=math.radians(ctx["divergence"]),
        redeposition_yield=ctx["redeposition_yield"],
        redeposit_as=MaterialId(redeposit) if redeposit else None,
        scale=ctx["scale"],
        process_class=SPUTTER_ETCH,
    )
    return _etch_result(
        ctx, outcome, f"sputter etch, {ctx['duration']:.1f} s at {ctx['angle']:.0f} deg"
    )


_ANGLE = ParamSpec(
    "angle", float, unit="deg", default=0.0, minimum=-85.0, maximum=85.0,
    description="Beam tilt from the surface normal",
)
_DIVERGENCE = ParamSpec(
    "divergence", float, unit="deg", default=5.0, minimum=0.0, maximum=45.0,
    description="Angular half-width of the ion lobe",
)

SPUTTER_ETCH_STEP = FunctionStep(
    step_id="etch.sputter",
    display_name="Sputter etching (Ar+)",
    fidelity=DIDACTIC,
    schema=(
        _DURATION,
        _SCALE,
        _ANGLE,
        ParamSpec("divergence", float, unit="deg", default=3.0, minimum=0.0, maximum=45.0,
                  description="Angular half-width of the ion lobe"),
        ParamSpec("redeposition_yield", float, default=0.0, minimum=0.0, maximum=1.0,
                  description="Fraction of removed material that lands again"),
        ParamSpec("redeposit_as", str, default="",
                  description="Material the redeposited film is recorded as; empty = none"),
    ),
    required=frozenset(),
    provided=frozenset(),
    run_function=_run_sputter_etch,
    description=(
        "Argon sputter etching at the process table's own rates — the same physics as "
        "`etch.ibe`, reading a different column of the material library."
        "\n\n"
        "Two steps for one technique is deliberate: `etch.ibe` carries the didactic numbers the "
        "acceptance scenarios are tuned to, and this one carries a measured table. Mixing them "
        "under one name would make the library's own provenance unreadable."
        "\n\n"
        "Needs: a sample."
    ),
)

ICP_FLUORINE_STEP = FunctionStep(
    step_id="etch.icp_fluorine",
    display_name="ICP etching (fluorine)",
    fidelity=DIDACTIC,
    schema=(
        _DURATION,
        _SCALE,
        _ANGLE,
        _DIVERGENCE,
        ParamSpec(
            "chemical_fraction", float, default=0.0, minimum=0.0, maximum=0.95,
            description=(
                "Share of the etch carried by orientation-blind chemistry. Zero by "
                "default: the process table gives this chemistry a vertical rate and no "
                "lateral one. Raise it to see the vertical wall become an undercut one."
            ),
        ),
    ),
    required=frozenset(),
    provided=frozenset(),
    run_function=_run_icp_fluorine,
    description=(
        "ICP etching in fluorine chemistry, and the table's vertical process: it takes fused "
        "silica and silicon quickly, resist faster still, and chromium 25 times more slowly — "
        "which is why a chromium hard mask survives it and a resist mask does not."
        "\n\n"
        "The direction is not in the rate. A rate here is the speed of an open, normal-facing "
        "surface; what makes this one vertical is the narrow angular distribution of the step. "
        "`chemical_fraction` is 0 by default because the table gives no lateral rate — raise it "
        "to watch the vertical wall become an undercutting one."
        "\n\n"
        "Needs: a sample."
    ),
)

RIE_CHLORINE_STEP = FunctionStep(
    step_id="etch.rie_chlorine",
    display_name="RIE (chlorine)",
    fidelity=DIDACTIC,
    schema=(_DURATION, _SCALE),
    required=frozenset(),
    provided=frozenset(),
    run_function=_run_rie_chlorine,
    description=(
        "RIE in chlorine chemistry: fast on chromium, slow on resist, and nothing at all on "
        "fused silica. The classic way to pattern a chromium mask with a resist mask over it."
        "\n\n"
        "The table gives this one the same rate horizontally and vertically, so the step builds "
        "no flux model at all — it is isotropic, gated only on whether the plasma can reach the "
        "surface. Undercut therefore equals depth, which is the honest consequence of what was "
        "measured."
        "\n\n"
        "Needs: a sample."
    ),
)

RIE_OXYGEN_STEP = FunctionStep(
    step_id="etch.rie_oxygen",
    display_name="RIE (oxygen)",
    fidelity=DIDACTIC,
    schema=(_DURATION, _SCALE),
    required=frozenset(),
    provided=frozenset(),
    run_function=_run_rie_oxygen,
    description=(
        "An oxygen plasma: a resist strip and a descum. The table gives chromium and fused "
        "silica a rate of exactly zero, so it takes the polymer off a patterned mask and leaves "
        "the pattern."
        "\n\n"
        "Isotropic, like the chlorine chemistry, and gated on reachability — resist under a "
        "sealed film is not stripped, however long you run it."
        "\n\n"
        "Needs: a sample."
    ),
)

WET_CR_STEP = FunctionStep(
    step_id="etch.wet_cr",
    display_name="Chromium etch (wet)",
    fidelity=DIDACTIC,
    schema=(_DURATION, _SCALE),
    required=frozenset(),
    provided=frozenset(),
    run_function=_run_wet_cr,
    description=(
        "The chromium wet etchant. It attacks chromium at 1000 nm/min and everything else the "
        "table names at nothing, which makes it the cleanest selectivity in the set."
        "\n\n"
        "Isotropic and reachability-gated, so it undercuts a resist mask by as much as it "
        "etches down, and it leaves chromium the bath cannot get to — under intact resist, or "
        "inside a sealed void — completely alone."
        "\n\n"
        "Needs: a sample."
    ),
)

WET_OXIDE_STEP = FunctionStep(
    step_id="etch.wet_oxide",
    display_name="Buffered oxide etch (wet)",
    fidelity=DIDACTIC,
    schema=(_DURATION, _SCALE),
    required=frozenset(),
    provided=frozenset(),
    run_function=_run_wet_oxide,
    description=(
        "Buffered oxide etch: fast on silicon dioxide and fused silica, slow on resist, and "
        "nothing on silicon or chromium. The etch that stops at the wafer surface."
        "\n\n"
        "Isotropic and reachability-gated. Compare it against `etch.icp_fluorine` on the same "
        "oxide: same material removed, same depth, and a completely different profile — one "
        "eats under the mask and the other does not."
        "\n\n"
        "Needs: a sample."
    ),
)

IBE_STEP = FunctionStep(
    step_id="etch.ibe",
    display_name="Ion beam etch",
    fidelity=DIDACTIC,
    schema=(
        _DURATION,
        _SCALE,
        ParamSpec("angle", float, unit="deg", default=0.0, minimum=-85.0, maximum=85.0,
                  description="Beam tilt from the surface normal"),
        ParamSpec("divergence", float, unit="deg", default=3.0, minimum=0.0, maximum=45.0,
                  description="Angular half-width of the ion lobe"),
        ParamSpec("redeposition_yield", float, default=0.0, minimum=0.0, maximum=1.0,
                  description="Fraction of removed material that lands again"),
        ParamSpec("redeposit_as", str, default="",
                  description="Material the redeposited film is recorded as; empty = none"),
    ),
    required=frozenset(),
    provided=frozenset(),
    run_function=_run_ibe,
    description=(
        "Purely physical sputtering: a narrow beam, an angle-dependent yield, no chemistry and "
        "therefore no undercut. The yield peak off normal incidence is what facets a corner, "
        "and it is the material's own property rather than the beam's."
        "\n\n"
        "`redeposition_yield` turns on the one process here that runs the solver twice: once to "
        "remove material, once to put back what did not leave. `redeposit_as` names the "
        "material the returned film is recorded as — that is what lines a trench sidewall with "
        "what came off its floor."
        "\n\n"
        "Needs: a sample."
    ),
)
