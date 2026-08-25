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
"""

from __future__ import annotations

import math

from nanofab_v3.kernel import flux, motion, predicates
from nanofab_v3.materials import DRY_ETCH, ION_BEAM, WET_ETCH, MaterialId
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
    """
    model = flux.ion_beam_etch(
        angle=float(angle),
        divergence=float(divergence),
        redeposition_yield=float(redeposition_yield),
        yield_model=dominant_yield(library, structure, ION_BEAM),
    )
    rates = surface_rates(library, structure, ION_BEAM, scale=scale)
    gate = motion.gated(model, predicates.ReachableFront(faces=faces))
    outcome = motion.advect_front(structure, rates, float(duration), flux=gate)
    if redeposition_yield <= 0.0 or redeposit_as is None:
        return outcome

    etched = outcome.structure
    bounce = model.on_structure(etched, release=release_map(library, etched, ION_BEAM))
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
)
