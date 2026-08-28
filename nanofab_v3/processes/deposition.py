"""Deposition: evaporation, sputtering, ALD (plan §6, rows 10-12).

Three techniques, four registered steps, and **no physics in this module**. The
flux solver already carries the differences — a delta source, a `cos^n` lobe plus
a mobility smear, and the isotropic case that needs no visibility at all — so a
wrapper's job here is exactly what the M3 handoff says it is: turn typed
parameters into a `FluxModel2D` plus a `SurfaceRates`, and hand both to
`advect_front`.

Two things this module *does* decide, and they are decisions rather than
plumbing:

- **A deposition's rate belongs to the source, not to the surface.** Every step
  here uses `SurfaceRates(default=rate)` — one number, uniform over the front —
  because the arriving atom does not care what it lands on at this fidelity.
  Selectivity in deposition (a nucleation delay on one material, area-selective
  ALD) is a tier-(b) rate model, and would be expressed by giving the rate table
  entries rather than by changing anything below.
- **ALD comes in two fidelities and the default is the gated one** (plan §5.4:
  several registered processes may model the same technique). `conformal_offset`
  is the exact geometric answer — one array operation, dose splitting bit-exact —
  and it keeps growing inside a cavity it has sealed. `ALD` runs the same growth
  behind `predicates.ReachableFront`, and stops. Scenario S3 is that difference.

M6 added a fifth step, `deposit.sputter_rate`, and the difference from
`deposit.sputter` is which direction the arithmetic runs. The older step is given
a thickness and finds the time; this one is given a **time** and finds the
thickness, from the target's `sputter_deposit` rate in the library. That is what
rows 7-9 of roadmap §3's table actually state — "run the sputterer for so long"
is the operator's input and the film is the outcome — and it is the shape in
which a wrong rate is visible: the step reports the thickness it derived.
"""

from __future__ import annotations

import math

from nanofab_v3.kernel import flux, motion, predicates
from nanofab_v3.materials import DEPOSIT, METAL, SPUTTER_DEPOSIT, MaterialId
from nanofab_v3.model import capability
from nanofab_v3.model.quantity import Quantity
from nanofab_v3.model.structure import Structure
from nanofab_v3.materials.selection import MaterialFilter
from nanofab_v3.processes.contract import (
    sub_cell_warning,
    DIDACTIC,
    IDEAL,
    FunctionStep,
    ParamSpec,
    StepContext,
    StepResult,
)


def _deposition_rates(rate: float) -> motion.SurfaceRates:
    """A uniform blanket rate over the whole front — see the module docstring."""
    if rate <= 0.0:
        raise ValueError(f"deposition rate must be positive, got {rate}")
    return motion.SurfaceRates(rates={}, default=float(rate))


def _duration(thickness: float, rate: float) -> float:
    """Seconds needed to lay down `thickness` nm on an open, normal-facing surface.

    Exactly `thickness / rate` because of the flux model's normalisation: plan
    §4.3's distributions are scaled so an unobstructed flat surface receives an
    arrival of 1, which is what lets a rate keep meaning "nm/s on an open
    surface" no matter how broad the source's lobe is.
    """
    if thickness <= 0.0:
        raise ValueError(f"thickness must be positive, got {thickness}")
    return float(thickness) / float(rate)


def evaporate(
        structure: Structure,
        material: MaterialId,
        *,
        thickness: float,
        angle: float = 0.0,
        divergence: float = 0.0,
        rate: float = 1.0,
) -> motion.MotionOutcome:
    """Directional deposition from a distant point source — S1's and S4's metal.

    A delta source: a vertical sidewall is at normal incidence to it and receives
    nothing, which is precisely what makes a naive lift-off work. The metal on the
    resist and the metal in the window are two disconnected pieces because the
    wall between them was never coated, and no step had to say so.
    """
    model = flux.evaporation(angle=float(angle), divergence=float(divergence))
    return motion.advect_front(
        structure,
        _deposition_rates(rate),
        _duration(thickness, rate),
        deposit_material=material,
        flux=model,
    )


def sputter_deposit(
        structure: Structure,
        material: MaterialId,
        *,
        thickness: float,
        exponent: float = 1.0,
        angle: float = 0.0,
        mobility_length: float = 0.0,
        rate: float = 1.0,
) -> motion.MotionOutcome:
    """Broad `cos^n` deposition with surface mobility — S4's fences (plan §6).

    The broad lobe is what puts metal on a sidewall an evaporation leaves bare,
    and the mobility length decides whether that sidewall film is continuous or
    beaded. Both are why S4 exists as a separate scenario from S1: same stack,
    same lift-off, and the deposit's *angular* character decides whether the
    lift-off is clean.
    """
    model = flux.sputter_deposition(
        exponent=float(exponent), angle=float(angle), mobility_length=float(mobility_length)
    )
    return motion.advect_front(
        structure,
        _deposition_rates(rate),
        _duration(thickness, rate),
        deposit_material=material,
        flux=model,
    )


def conformal_offset(
        structure: Structure, material: MaterialId, *, thickness: float
) -> motion.MotionOutcome:
    """Grow the whole front by `thickness` — the exact geometric answer (plan §4.2).

    The isotropic fast path: one array operation, `phi <- phi - t`, exact for a
    signed-distance field and bit-exact under dose splitting (`1 x 20 nm` and
    `4 x 5 nm` agree to the last bit — measured in M1).

    It is registered as a step, at fidelity `ideal`, and it is **not** what a real
    ALD does once a cavity has closed: with no visibility and no reachability in
    it, growth continues inside a sealed void until the void disappears. That is
    the correct answer to the question this process asks — "offset the surface" —
    and the wrong answer to "deposit from a precursor", which is why `ALD` below
    exists and is the default.
    """
    return motion.offset_solid(structure, float(thickness), deposit_material=material)


def atomic_layer_deposition(
        structure: Structure,
        material: MaterialId,
        *,
        thickness: float,
        rate: float = 1.0,
        faces: tuple[tuple[str, str], ...] | None = None,
) -> motion.MotionOutcome:
    """Conformal growth that only reaches what the precursor can reach (plan §4.4).

    Isotropic arrival — no lobe, no shadowing, equal thickness on every surface —
    behind `predicates.ReachableFront`. The gate is rebuilt as the front moves,
    on the same cadence as a flux rebuild, because that is when the answer can
    change: the mouth of a re-entrant profile narrows with every nanometre grown
    and closes at half the opening, and from that sub-step on the cavity's own
    front is handed a speed of zero.

    **This is the reachability gate proving itself** (plan §1, S3): the sealed
    void stops shrinking, the lift-off that depended on the solvent reaching the
    resist fails, and nothing anywhere is special-cased. Compare
    `conformal_offset`, which is the same growth without the gate.

    The cost of the gate, relative to the fast path, is a full advection: the fast
    path is one array operation and this is `thickness / (cfl * spacing)`
    sub-steps. It buys the topology.
    """
    gate = predicates.ReachableFront(faces=faces)
    return motion.advect_front(
        structure,
        _deposition_rates(rate),
        _duration(thickness, rate),
        deposit_material=material,
        flux=gate,
    )


# -- registered steps ---------------------------------------------------------


def _deposit_result(ctx: StepContext, material: MaterialId, outcome, note: str) -> StepResult:
    """The one place every thickness-driven deposition ends, so the one place to warn.

    Roadmap §0.5's sub-cell warning is here rather than in each of the four run
    functions for the reason the four of them already share this function: a
    warning that has to be remembered in four places is a warning that is missing
    from one of them.
    """
    warning = sub_cell_warning(float(ctx["thickness"]), ctx.grid.spacing, str(material))
    return StepResult(
        structure=outcome.structure,
        swept=outcome.swept,
        provides=frozenset({capability.of_material(material)}),
        measurements={"thickness": Quantity(ctx["thickness"], "nm")},
        logs=(note,) + ((warning,) if warning else ()),
    )


def _rate_of(ctx: StepContext, material: MaterialId, fallback: float = 1.0) -> float:
    """The material's blanket deposition rate, or `fallback` if unlisted."""
    entry = ctx.library.get(material)
    rate = fallback if entry is None else entry.rate_for(DEPOSIT, fallback)
    return rate if rate > 0.0 else fallback


def _run_evaporate(ctx: StepContext) -> StepResult:
    material = MaterialId(str(ctx["material"]))
    outcome = evaporate(
        ctx.structure,
        material,
        thickness=ctx["thickness"],
        angle=math.radians(ctx["angle"]),
        divergence=math.radians(ctx["divergence"]),
        rate=_rate_of(ctx, material),
    )
    return _deposit_result(
        ctx,
        material,
        outcome,
        f"evaporated {ctx['thickness']:.1f} nm of {material} at {ctx['angle']:.0f} deg",
    )


def _run_sputter(ctx: StepContext) -> StepResult:
    material = MaterialId(str(ctx["material"]))
    outcome = sputter_deposit(
        ctx.structure,
        material,
        thickness=ctx["thickness"],
        exponent=ctx["exponent"],
        angle=math.radians(ctx["angle"]),
        mobility_length=ctx["mobility_length"],
        rate=_rate_of(ctx, material),
    )
    return _deposit_result(
        ctx,
        material,
        outcome,
        f"sputtered {ctx['thickness']:.1f} nm of {material} "
        f"(cos^{ctx['exponent']:.1f}, mobility {ctx['mobility_length']:.0f} nm)",
    )


def _run_conformal(ctx: StepContext) -> StepResult:
    material = MaterialId(str(ctx["material"]))
    outcome = conformal_offset(ctx.structure, material, thickness=ctx["thickness"])
    return _deposit_result(
        ctx,
        material,
        outcome,
        f"offset the front by {ctx['thickness']:.1f} nm of {material} (geometric)",
    )


def _run_ald(ctx: StepContext) -> StepResult:
    material = MaterialId(str(ctx["material"]))
    outcome = atomic_layer_deposition(
        ctx.structure, material, thickness=ctx["thickness"], rate=_rate_of(ctx, material)
    )
    return _deposit_result(
        ctx,
        material,
        outcome,
        f"deposited {ctx['thickness']:.1f} nm of {material} conformally, where reachable",
    )


def _run_sputter_rate(ctx: StepContext) -> StepResult:
    material = MaterialId(str(ctx["material"]))
    entry = ctx.library.get(material)
    if entry is None:
        raise ValueError(
            f"no MaterialType {material!r} in this library, so there is no sputter "
            "deposition rate to run at; add data/materials/"
            f"{material}.json or pick a material the library knows"
        )
    rate = entry.rate_for(SPUTTER_DEPOSIT)
    if rate <= 0.0:
        raise ValueError(
            f"material {material!r} has no {SPUTTER_DEPOSIT!r} rate, so this step would "
            "deposit nothing. That zero means 'nobody stated a rate', not 'it does not "
            f"grow' — give it one in data/materials/{material}.json, or use "
            "deposit.sputter, which takes a thickness instead"
        )
    duration = float(ctx["duration"])
    thickness = rate * duration
    outcome = sputter_deposit(
        ctx.structure,
        material,
        thickness=thickness,
        exponent=ctx["exponent"],
        angle=math.radians(ctx["angle"]),
        mobility_length=ctx["mobility_length"],
        rate=rate,
    )
    return StepResult(
        structure=outcome.structure,
        swept=outcome.swept,
        provides=frozenset({capability.of_material(material)}),
        measurements={
            "thickness": Quantity(thickness, "nm"),
            "duration": Quantity(duration, "s"),
            "rate": Quantity(rate, "nm/s"),
        },
        logs=(
            f"sputtered {material} for {duration:.1f} s at {rate:.4f} nm/s "
            f"-> {thickness:.1f} nm",
        ),
    )


_DEPOSITABLE = MaterialFilter(
    tags=("metal", "oxide", "metal_oxide", "dielectric", "semiconductor"),
    what="films",
)
"""What a source can put down (E22). A resist arrives by spinning and a particle
by falling on the sample; neither is a thing a chamber deposits."""

_MATERIAL = ParamSpec(
    "material", str, default=str(METAL), description="Deposited material",
    material=_DEPOSITABLE,
)
_THICKNESS = ParamSpec(
    "thickness",
    float,
    unit="nm",
    default=None,
    minimum=0.0,
    description="Thickness on an open, normal-facing surface",
)

EVAPORATE = FunctionStep(
    step_id="deposit.evaporate",
    display_name="Evaporation",
    fidelity=DIDACTIC,
    schema=(
        _MATERIAL,
        _THICKNESS,
        ParamSpec("angle", float, unit="deg", default=0.0, minimum=-85.0, maximum=85.0,
                  description="Source tilt from the surface normal"),
        ParamSpec("divergence", float, unit="deg", default=0.0, minimum=0.0, maximum=45.0,
                  description="Angular half-width of the source"),
    ),
    required=frozenset(),
    provided=frozenset(),
    run_function=_run_evaporate,
    description=(
        "Deposits `material` from a distant point source. A vertical sidewall is edge-on to it "
        "and receives nothing, which is exactly what makes a naive lift-off work: the metal on "
        "the resist and the metal in the window are two disconnected pieces because the wall "
        "between them was never coated."
        "\n\n"
        "`angle` tilts the source; `divergence` turns the point into a small lobe, which is the "
        "difference between an idealised evaporation and one from a real crucible. `thickness` "
        "is what an open, normal-facing surface receives — everything else follows from what "
        "that surface can see. Incoming metal atoms stick; deposition has no specular ion bounce."
        "\n\n"
        "Needs: something to deposit on."
    ),
)

SPUTTER = FunctionStep(
    step_id="deposit.sputter",
    display_name="Sputter deposition",
    fidelity=DIDACTIC,
    schema=(
        _MATERIAL,
        _THICKNESS,
        ParamSpec("exponent", float, default=1.0, minimum=0.0, maximum=8.0,
                  description="Exponent n of the cos^n source distribution"),
        ParamSpec("angle", float, unit="deg", default=0.0, minimum=-85.0, maximum=85.0,
                  description="Source tilt from the surface normal"),
        ParamSpec("mobility_length", float, unit="nm", default=0.0, minimum=0.0,
                  description="Surface diffusion length of the arriving material"),
    ),
    required=frozenset(),
    provided=frozenset(),
    run_function=_run_sputter,
    description=(
        "Deposits `material` from a broad cos^n source, with optional surface mobility. The "
        "broad lobe puts metal on sidewalls an evaporation leaves bare, and that is where lift- "
        "off fences come from."
        "\n\n"
        "`exponent` is the source's directionality — 1 is a thermal cosine law, larger is a "
        "forward-peaked magnetron. `mobility_length` decides whether the sidewall film is "
        "continuous or beaded. Try the same stack with `deposit.evaporate` to see how much of a "
        "lift-off's outcome is the deposit's angular character rather than the resist. Incoming "
        "metal atoms stick; deposition has no specular ion bounce."
        "\n\n"
        "Needs: something to deposit on."
    ),
)

CONFORMAL_OFFSET = FunctionStep(
    step_id="deposit.conformal_offset",
    display_name="Conformal offset (geometric)",
    fidelity=IDEAL,
    schema=(_MATERIAL, _THICKNESS),
    required=frozenset(),
    provided=frozenset(),
    run_function=_run_conformal,
    description=(
        "Grows the whole front by `thickness` in one array operation — the exact geometric "
        "answer to 'offset this surface', and bit-exact under splitting: one 20 nm step and "
        "four 5 nm steps agree to the last bit."
        "\n\n"
        "It is also the wrong answer to 'deposit from a precursor', and deliberately so: with "
        "no reachability in it, growth continues inside a cavity it has already sealed until "
        "the cavity disappears. `deposit.ald` is the same growth with the gate, and the "
        "difference between the two is one of this model's clearest pictures."
        "\n\n"
        "Needs: something to deposit on."
    ),
)

ALD = FunctionStep(
    step_id="deposit.ald",
    display_name="Atomic layer deposition",
    fidelity=DIDACTIC,
    schema=(_MATERIAL, _THICKNESS),
    required=frozenset(),
    provided=frozenset(),
    run_function=_run_ald,
    description=(
        "Conformal growth that only reaches what the precursor can reach: equal thickness on "
        "every surface, no shadowing, and nothing at all inside a cavity that has closed."
        "\n\n"
        "The gate is rebuilt as the front moves, because that is when the answer can change — "
        "the mouth of a re-entrant profile narrows with every nanometre grown and closes at "
        "half the opening. From that moment the cavity's own front is handed a speed of zero. "
        "This is what breaks a lift-off that a directional deposition would have left workable. "
        "Conformality is represented by reachability and geometric growth, not by reflecting "
        "low-energy precursor molecules or assigning them a second sticking coefficient."
        "\n\n"
        "Needs: something to deposit on."
    ),
)

SPUTTER_RATE = FunctionStep(
    step_id="deposit.sputter_rate",
    display_name="Sputter deposition (timed)",
    fidelity=DIDACTIC,
    schema=(
        ParamSpec("material", str, default=str(METAL),
                  description="Deposited material; its sputter_deposit rate sets the thickness",
                  # The rate *is* the thickness here, so a material without one
                  # would deposit nothing and say nothing (E22's library half).
                  material=MaterialFilter(
                      process_class=SPUTTER_DEPOSIT, what="sputter targets"
                  )),
        ParamSpec("duration", float, unit="s", default=None, minimum=0.0,
                  description="Time in the chamber — the thickness follows from the rate"),
        ParamSpec("exponent", float, default=1.0, minimum=0.0, maximum=8.0,
                  description="Exponent n of the cos^n source distribution"),
        ParamSpec("angle", float, unit="deg", default=0.0, minimum=-85.0, maximum=85.0,
                  description="Source tilt from the surface normal"),
        ParamSpec("mobility_length", float, unit="nm", default=0.0, minimum=0.0,
                  description="Surface diffusion length of the arriving material"),
    ),
    required=frozenset(),
    provided=frozenset(),
    run_function=_run_sputter_rate,
    description=(
        "The same sputter deposition, with the arithmetic the other way round: you give it a "
        "time and it reads the target's own deposition rate out of the material library, so the "
        "film thickness is an outcome rather than an input."
        "\n\n"
        "That is how the process table states rows 7 to 9 — 'run the sputterer for so long' — "
        "and it is the shape in which a wrong rate is visible: the step reports the thickness "
        "it derived. A target with no `sputter_deposit` rate refuses rather than depositing "
        "nothing, because a zero there means nobody stated a rate, not that it does not grow."
        "\n\n"
        "Needs: something to deposit on."
    ),
)
