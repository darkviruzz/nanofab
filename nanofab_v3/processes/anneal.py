"""Anneal (plan §6, row 15): fields and material models, no geometry.

Plan §16 keeps reflow **deliberately open** — curvature-driven flow is a natural
level-set extension and nothing here is it. What an anneal does in this model is
the other half of §6's row, "update fields/material models", and getting that
half right needed one decision the handoff (§6, item 4) asked to be made rather
than assumed.

## Where an annealed material's new rates live

`StepContext.library` is passed *in*, never stored in a `Structure` (plan §3.4):
"a `Structure` that carried its own rate table would be a `Structure` whose
meaning changed when the library was corrected, and every cached revision would
have to be replayed to find out". So an anneal cannot hand back a modified
library — there is nowhere for it to go, and a cached revision would not know
which one it was computed under.

**It does not need to.** An anneal that changes how a material behaves has turned
it into a *different material*, and the library already holds both: `resist` and
`resist_hardbaked` are two `MaterialType`s, and the anneal moves the geometry
from one to the other. The library stays immutable and passed-in; what changes is
which entry the geometry points at, and every rate downstream follows without a
single step being told about temperature.

That is also how a cleanroom talks about it. A hard-baked resist is not resist
with a footnote — it is a material acetone does not dissolve, which is why
hard-baking before lift-off is a mistake with a shape rather than a number. The
capability machinery comes along free: `material:resist` retires because the
resist is gone, `material:resist_hardbaked` appears because it is there, and
nothing had to remember either.

## The field half

The transformation is discrete; the **thermal budget** is not, and a sample
carries its whole thermal history rather than its last bake. `anneal.thermal`
accumulates a *global* field (plan §3.3's rare case — a furnace heats the whole
sample, not one material), so two 5-minute bakes and one 10-minute bake leave the
same number, and a later step could read it. Global fields back no structural
capability, so the promise is the free-form `"annealed"` — no dot, which §5.3
reserves for `<material>.<field>`.

Material-scoped fields of a transformed material are dropped by the commit gate,
because their material is gone. That is the right answer and worth stating: a
latent image in a resist that has been hard-baked is not a latent image any more.
"""

from __future__ import annotations

import numpy as np

from nanofab_v3.kernel import regions
from nanofab_v3.materials import MaterialId
from nanofab_v3.model import capability
from nanofab_v3.model.field import FieldSpec
from nanofab_v3.model.quantity import Quantity
from nanofab_v3.model.structure import Structure
from nanofab_v3.processes.contract import (
    DIDACTIC,
    FunctionStep,
    ParamSpec,
    StepContext,
    StepResult,
)

ANNEALED = "annealed"
"""The free-form capability an anneal provides (plan §5.3: no dot)."""

THERMAL_BUDGET = FieldSpec(
    name="thermal_budget",
    dtype=np.float32,
    default=0.0,
    material_scoped=False,
    unit="K*s",
)
"""The sample's accumulated thermal history — global, because a furnace is."""


def accumulate_budget(
    structure: Structure, *, temperature: float, duration: float
) -> Structure:
    """Add `temperature * duration` to the global thermal-budget field.

    Absolute temperature, so a bake at room temperature still costs something and
    the number is monotone in both arguments. Uniform over the domain: a
    cross-section 300 nm across sits in one furnace, and a temperature *gradient*
    across a wafer is plan §8's business — a `RadialProfile` on this step's
    `temperature` parameter, resolved per position before it ever gets here.
    """
    key = THERMAL_BUDGET.key()
    current = (
        structure.field(key)
        if structure.has_field(key)
        else THERMAL_BUDGET.new(structure.grid)
    )
    added = (float(temperature) + 273.15) * float(duration)
    return structure.with_field(key, (current + added).astype(THERMAL_BUDGET.dtype))


def transform(
    structure: Structure, material: MaterialId, becomes: MaterialId
) -> Structure:
    """Reassign every cell of `material` to `becomes` — the property change.

    The geometry does not move: the same `phi` array is handed to the new
    material, so this is exact and costs one dict operation rather than a
    reinitialisation. `remove_region` is not involved and neither is any set
    operation — nothing is being taken away, it is being renamed.

    A `becomes` that is already present is unioned onto rather than replaced,
    which is what makes two bakes of two resist layers land in one material
    instead of the second erasing the first.
    """
    if material not in structure.phi:
        return structure
    if material == becomes:
        return structure
    phi = structure.phi_of(material)
    existing = structure.phi.get(becomes)
    if existing is not None:
        phi = np.minimum(existing, phi)
    # The old material's scoped fields go with it: a latent image in a resist
    # that has been hard-baked is not a latent image any more.
    return structure.without_material(material).with_material(becomes, phi)


def _run_anneal(ctx: StepContext) -> StepResult:
    temperature = float(ctx["temperature"])
    duration = float(ctx["duration"])
    structure = accumulate_budget(
        ctx.structure, temperature=temperature, duration=duration
    )

    named = str(ctx["material"]).strip()
    into = str(ctx["becomes"]).strip()
    activation = float(ctx["activation"])
    provides = {ANNEALED}
    retires: set[str] = set()
    logs = [
        f"anneal: {temperature:.0f} C for {duration:.0f} s "
        f"(+{(temperature + 273.15) * duration:.0f} K*s)"
    ]

    if named and into:
        material, becomes = MaterialId(named), MaterialId(into)
        if material not in structure.phi:
            logs.append(f"no {material} to transform")
        elif temperature < activation:
            logs.append(
                f"{temperature:.0f} C is below {material}'s {activation:.0f} C "
                f"activation; it stays {material}"
            )
        else:
            before = structure.measure(structure.inside(material))
            structure = transform(structure, material, becomes)
            provides.add(capability.of_material(becomes))
            retires.add(capability.of_material(material))
            logs.append(
                f"{material} -> {becomes} ({before:.0f} nm^{structure.grid.ndim}), "
                f"{_behaviour_change(ctx, material, becomes)}"
            )

    return StepResult(
        structure=structure,
        provides=frozenset(provides),
        retires=frozenset(retires),
        field_specs={THERMAL_BUDGET.name: THERMAL_BUDGET},
        measurements={
            "temperature": Quantity(temperature, "C"),
            "duration": Quantity(duration, "s"),
            "thermal_budget": Quantity(
                float(structure.field(THERMAL_BUDGET.key()).max()), "K*s"
            ),
        },
        logs=tuple(logs),
    )


def _behaviour_change(ctx: StepContext, material: MaterialId, becomes: MaterialId) -> str:
    """One line saying what the new library entry does differently.

    The step's whole point is that behaviour changed, and behaviour lives in the
    library — so the log says which of it moved rather than leaving an operator
    to diff two `MaterialType`s.
    """
    was, now = ctx.library.get(material), ctx.library.get(becomes)
    if was is None or now is None:
        return "no library entry to compare"
    changes = []
    if bool(was.dissolve) != bool(now.dissolve):
        changes.append("soluble" if now.dissolve else "no longer soluble")
    if bool(was.develop) != bool(now.develop):
        changes.append("developable" if now.develop else "no longer developable")
    for process_class in sorted(set(was.rates) | set(now.rates)):
        before, after = was.rate_for(process_class), now.rate_for(process_class)
        if before != after:
            changes.append(f"{process_class} {before:g} -> {after:g} nm/s")
    return ", ".join(changes) if changes else "same behaviour"


ANNEAL = FunctionStep(
    step_id="anneal.thermal",
    display_name="Anneal / bake",
    fidelity=DIDACTIC,
    schema=(
        ParamSpec("temperature", float, unit="C", default=None, minimum=-273.15,
                  maximum=2000.0, description="Furnace or hotplate temperature"),
        ParamSpec("duration", float, unit="s", default=None, minimum=0.0,
                  description="Time at temperature"),
        ParamSpec("material", str, default="",
                  description="Material the bake transforms; blank transforms nothing"),
        ParamSpec("becomes", str, default="",
                  description="Library entry it turns into at or above the activation"),
        ParamSpec("activation", float, unit="C", default=0.0, minimum=-273.15,
                  description="Temperature the transformation needs"),
    ),
    required=frozenset(),
    provided=frozenset({ANNEALED}),
    run_function=_run_anneal,
)
