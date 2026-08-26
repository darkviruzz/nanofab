"""Strip, dissolve and lift-off (plan §6, rows 13-14; §4.4).

The scenario-carrying module. Everything S1, S3 and S4 turn on is here, and it is
two kernel queries and one set operation:

    lift-off = dissolve the resist where the solvent reaches it
             + remove every solid component the substrate no longer supports

Plan §4.4 states it in exactly those terms, and the reason it works without a
single special case is that both halves are *predicates*. "Which metal lifts off"
is a connectivity question, never an identity question (ADR-0003): the metal that
was sitting on the resist is carried away because nothing holds it, and the metal
in the window stays because the substrate does. The film in S4 keeps its
sidewall fences by the same rule, and S3's lift-off fails at the first half
rather than the second — the solvent never reaches the resist, so nothing is ever
unsupported.

Both fidelity tiers are here for dissolution, and the split is the one recorded
in `memory.md` for M3: the ideal tier is a **region** operation
(`regions.remove_region` on the reachable occurrences, exact, no sub-stepping),
the rate tier is a **speed-field** one (`ReachableFront` as a multiplier on
`advect_front`). Same predicate, two shapes, because a region operation cannot
express a partially dissolved film and a speed field cannot express "the piece
came away".
"""

from __future__ import annotations

import numpy as np

from nanofab_v3.kernel import motion, predicates, regions
from nanofab_v3.materials import RESIST, MaterialId
from nanofab_v3.model.quantity import Quantity
from nanofab_v3.model.structure import Structure
from nanofab_v3.processes.contract import (
    DIDACTIC,
    IDEAL,
    FunctionStep,
    ParamSpec,
    StepContext,
    StepResult,
)
from nanofab_v3.processes.rates import dissolve_rates


def dissolve(
    structure: Structure,
    material: MaterialId,
    *,
    faces: tuple[tuple[str, str], ...] | None = None,
) -> Structure:
    """Remove every occurrence of `material` the solvent can reach (plan §6, §4.4).

    Per **occurrence**, which is what makes this the ideal tier rather than a
    coarse etch: a solvent that reaches one corner of a connected piece of resist
    takes the piece, not the corner. Cell-by-cell removal would stall at the first
    constriction and leave a plug that no real bath would leave.

    An occurrence with no path to the outside stays, and that is the whole of S3.
    """
    if material not in structure.phi:
        return structure
    removed = predicates.reachable_occurrences(structure, material, faces=faces)
    if not removed.any():
        return structure
    return regions.remove_region(structure, removed, materials=(material,))


def dissolve_at_rate(
    structure: Structure,
    *,
    duration: float,
    library,
    solvent: str = "acetone",
    faces: tuple[tuple[str, str], ...] | None = None,
) -> motion.MotionOutcome:
    """Recede every soluble surface the bath reaches, at the material's own rate.

    The rate tier of the same process, and the one that shows the *time* course:
    a resist under a metal overhang dissolves inward from the crack it can be
    reached through, and how far it gets in ten seconds is a question only this
    tier can answer.

    `dissolve_rates` gives a rate of zero to every material the bath does not
    attack, so this is a bath applied to the whole sample rather than a list of
    things to remove — which is also what makes it safe to run on a structure
    whose materials it has never heard of.
    """
    rates = dissolve_rates(library, structure, solvent)
    if rates.bound <= 0.0:
        return motion.MotionOutcome(structure, swept=0.0, sub_steps=0)
    return motion.advect_front(
        structure, rates, float(duration), flux=predicates.ReachableFront(faces=faces)
    )


def remove_unsupported(
    structure: Structure,
    *,
    faces: tuple[tuple[str, str], ...] | None = None,
    anchor: MaterialId | None = None,
) -> Structure:
    """Carry away every solid component the wafer no longer holds (plan §4.4).

    Not material-selective: whatever is floating goes, whichever material it is
    made of. `regions.remove_region` is therefore called without a `materials`
    restriction, which is safe here for the reason its docstring gives — the
    removed region is a union of complete solid components, and a component is
    separated from what stays by empty space, so no shared interface cell is in
    play.
    """
    floating = predicates.unsupported(structure, faces=faces, anchor=anchor)
    if not floating.any():
        return structure
    return regions.remove_region(structure, floating)


def lift_off(
    structure: Structure,
    resist: MaterialId = RESIST,
    *,
    faces: tuple[tuple[str, str], ...] | None = None,
    anchor: MaterialId | None = None,
) -> Structure:
    """Dissolve the resist, then drop what is no longer supported (plan §6).

    The order matters and is the physics: the solvent acts first, and only what it
    actually removed changes who is supported. A lift-off that removed the
    unsupported metal *first* would carry away a film that was still resting on
    resist, and would then work perfectly in S3 — where the whole point is that it
    must not.
    """
    return remove_unsupported(dissolve(structure, resist, faces=faces), faces=faces, anchor=anchor)


# -- registered steps ---------------------------------------------------------


def _run_dissolve(ctx: StepContext) -> StepResult:
    material = MaterialId(str(ctx["material"]))
    before = ctx.structure.measure(ctx.structure.solid_mask)
    structure = dissolve(ctx.structure, material)
    after = structure.measure(structure.solid_mask)
    return StepResult(
        structure=structure,
        measurements={"removed": Quantity(before - after, "nm^2")},
        logs=(
            f"dissolved the reachable {material} ({before - after:.0f} nm^2)"
            if after < before
            else f"{material} was not reachable — nothing dissolved",
        ),
    )


def _run_strip_rate(ctx: StepContext) -> StepResult:
    outcome = dissolve_at_rate(
        ctx.structure,
        duration=ctx["duration"],
        library=ctx.library,
        solvent=ctx["solvent"],
    )
    return StepResult(
        structure=outcome.structure,
        swept=outcome.swept,
        measurements={"duration": Quantity(ctx["duration"], "s")},
        logs=(f"{ctx['solvent']} strip, {ctx['duration']:.1f} s (reachability-gated)",),
    )


def _run_lift_off(ctx: StepContext) -> StepResult:
    material = MaterialId(str(ctx["material"]))
    before = ctx.structure
    structure = lift_off(before, material)
    carried = before.measure(before.solid_mask) - structure.measure(structure.solid_mask)
    lifted = material not in structure.phi
    return StepResult(
        structure=structure,
        measurements={"removed": Quantity(carried, "nm^2")},
        logs=(
            f"lift-off removed {carried:.0f} nm^2"
            if lifted
            else f"lift-off failed: the solvent never reached the {material}",
        ),
    )


def _run_remove_unsupported(ctx: StepContext) -> StepResult:
    structure = remove_unsupported(ctx.structure)
    floating = int(np.count_nonzero(predicates.unsupported(ctx.structure)))
    return StepResult(
        structure=structure,
        logs=(f"removed {floating} unsupported solid cells",),
    )


_MATERIAL = ParamSpec("material", str, default=str(RESIST), description="Material the bath attacks")

DISSOLVE = FunctionStep(
    step_id="strip.dissolve",
    display_name="Strip / dissolve (ideal)",
    fidelity=IDEAL,
    schema=(_MATERIAL,),
    required=frozenset(),
    provided=frozenset(),
    run_function=_run_dissolve,
    description=(
        "Removes every *reachable* piece of `material` in one set operation. Reachable is the "
        "whole content of the step: chemically identical material the solvent cannot get to "
        "stays, and that is not a special case anywhere — it is the same query that makes a "
        "sealed cavity stop being fed."
        "\n\n"
        "At this tier naming the material IS the statement that the bath attacks it; no rate "
        "table is consulted. Which also means a recipe that keeps asking for `resist` after a "
        "hard bake finds none and quietly does nothing, because `anneal.thermal` turned it into "
        "a different material."
        "\n\n"
        "Needs: the material you name."
    ),
)

STRIP_RATE = FunctionStep(
    step_id="strip.rate",
    display_name="Strip / dissolve (rate)",
    fidelity=DIDACTIC,
    schema=(
        ParamSpec("solvent", str, default="acetone", description="Bath the sample sits in"),
        ParamSpec("duration", float, unit="s", default=None, minimum=0.0,
                  description="Time in the bath"),
    ),
    required=frozenset(),
    provided=frozenset(),
    run_function=_run_strip_rate,
    description=(
        "The same bath with a clock: the front recedes at each material's own dissolution rate "
        "in the named `solvent` for `duration` seconds, behind the same reachability gate."
        "\n\n"
        "Unlike the ideal tier this one does consult chemistry, so it is where a hard-baked "
        "resist visibly survives an acetone strip that takes an unbaked one to nothing in "
        "seconds. A material with no dissolve model for that solvent has a rate of zero, which "
        "is a statement about the material rather than about the recipe."
        "\n\n"
        "Needs: a sample."
    ),
)

LIFT_OFF = FunctionStep(
    step_id="strip.lift_off",
    display_name="Lift-off",
    fidelity=IDEAL,
    schema=(_MATERIAL,),
    required=frozenset(),
    provided=frozenset(),
    run_function=_run_lift_off,
    description=(
        "Lift-off: dissolve the sacrificial layer, then remove whatever metal no longer "
        "connects to the wafer."
        "\n\n"
        "'Which metal lifts off' is a connectivity question and never an identity one, which is "
        "why this is two operations and not a rule. A film that touches the substrate at the "
        "foot of a sidewall stays — that is a fence, and it is why the same recipe over a "
        "sputtered film and an evaporated one gives two different results."
        "\n\n"
        "If nothing lifts, the usual reason is that the solvent never reached the resist: check "
        "whether a conformal film sealed it."
        "\n\n"
        "Needs: the material you name."
    ),
)

REMOVE_UNSUPPORTED = FunctionStep(
    step_id="strip.remove_unsupported",
    display_name="Remove unsupported components",
    fidelity=IDEAL,
    schema=(),
    required=frozenset(),
    provided=frozenset(),
    run_function=_run_remove_unsupported,
    description=(
        "Removes solid that no longer connects to the wafer, without dissolving anything first "
        "— the second half of a lift-off, on its own."
        "\n\n"
        "Useful for seeing what support actually means here: it is topological, so one shared "
        "cell is enough to keep a piece, and `anchor` lets you ask the question against a "
        "material other than the substrate."
        "\n\n"
        "Needs: a sample."
    ),
)
