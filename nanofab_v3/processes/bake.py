"""Three bake processes with three explicit field rules (roadmap M12 / E31)."""

from __future__ import annotations

import numpy as np
from scipy import ndimage

from nanofab_v3.materials import (
    RESIST,
    MaterialId,
    MissingMaterial,
    MissingMaterialsError,
)
from nanofab_v3.materials.selection import MaterialFilter
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
from nanofab_v3.processes.lithography import DOSE

ANNEALED = "annealed"
"""Free-form capability shared by all three thermal processes."""

THERMAL_BUDGET = FieldSpec(
    name="thermal_budget",
    dtype=np.float32,
    default=0.0,
    material_scoped=False,
    unit="K*s",
)
"""Accumulated absolute-temperature exposure of the whole sample."""


def accumulate_budget(
        structure: Structure, *, temperature: float, duration: float
) -> Structure:
    """Add one uniform hotplate/furnace exposure to the global thermal budget."""
    key = THERMAL_BUDGET.key()
    current = (
        structure.field(key)
        if structure.has_field(key)
        else THERMAL_BUDGET.new(structure.grid)
    )
    added = (float(temperature) + 273.15) * float(duration)
    return structure.with_field(key, (current + added).astype(THERMAL_BUDGET.dtype))


def transform(
        structure: Structure, material: MaterialId, target: MaterialId
) -> Structure:
    """Reassign one material without moving or reinitialising its geometry."""
    if material not in structure.phi or material == target:
        return structure
    phi = structure.phi_of(material)
    existing = structure.phi.get(target)
    if existing is not None:
        phi = np.minimum(existing, phi)
    return structure.without_material(material).with_material(target, phi)


def diffuse_dose(
        structure: Structure, material: MaterialId, *, diffusion_length: float
) -> Structure:
    """Diffuse a latent dose inside one resist while preserving its integral."""
    length = float(diffusion_length)
    if length <= 0.0:
        return structure
    key = DOSE.key(material)
    if not structure.has_field(key) or material not in structure.phi:
        return structure

    inside = structure.inside(material)
    if not inside.any():
        return structure
    original = np.asarray(structure.field(key), dtype=np.float64)
    sigma = length / structure.grid.spacing
    weights = ndimage.gaussian_filter(
        inside.astype(np.float64), sigma=sigma, mode="constant", cval=0.0
    )
    weighted = ndimage.gaussian_filter(
        original * inside, sigma=sigma, mode="constant", cval=0.0
    )
    mixed = np.divide(
        weighted,
        weights,
        out=np.zeros_like(weighted),
        where=weights > np.finfo(np.float64).eps,
    )
    before = float(np.sum(original[inside], dtype=np.float64))
    after = float(np.sum(mixed[inside], dtype=np.float64))
    if after > 0.0:
        mixed *= before / after
    scoped = np.where(inside, mixed, DOSE.default).astype(DOSE.dtype)
    return structure.with_field(key, scoped)


def _measurements(
        structure: Structure, temperature: float, duration: float
) -> dict[str, Quantity]:
    return {
        "temperature": Quantity(temperature, "C"),
        "duration": Quantity(duration, "s"),
        "thermal_budget": Quantity(
            float(structure.field(THERMAL_BUDGET.key()).max()), "K*s"
        ),
    }


def _budget_note(temperature: float, duration: float) -> str:
    return (
        f"{temperature:.0f} C for {duration:.0f} s "
        f"(+{(temperature + 273.15) * duration:.0f} K*s)"
    )


def _run_soft(ctx: StepContext) -> StepResult:
    temperature = float(ctx["temperature"])
    duration = float(ctx["duration"])
    structure = accumulate_budget(
        ctx.structure, temperature=temperature, duration=duration
    )
    return StepResult(
        structure=structure,
        provides=frozenset({ANNEALED}),
        field_specs={THERMAL_BUDGET.name: THERMAL_BUDGET},
        measurements=_measurements(structure, temperature, duration),
        logs=(
            "soft bake: "
            + _budget_note(temperature, duration)
            + "; material-scoped fields are unchanged",
        ),
    )


def _run_post_exposure(ctx: StepContext) -> StepResult:
    temperature = float(ctx["temperature"])
    duration = float(ctx["duration"])
    length = float(ctx["diffusion_length"])
    material = MaterialId(str(ctx["material"]))
    dose_key = DOSE.key(material)
    had_dose = ctx.structure.has_field(dose_key)
    structure = accumulate_budget(
        ctx.structure, temperature=temperature, duration=duration
    )
    structure = diffuse_dose(structure, material, diffusion_length=length)
    latent_note = (
        f"{material}.dose diffused over {length:.1f} nm; its integral and field identity remain"
        if had_dose
        else f"no {material}.dose field was present; all latent fields remain unchanged"
    )
    measurements = _measurements(structure, temperature, duration)
    measurements["diffusion_length"] = Quantity(length, "nm")
    return StepResult(
        structure=structure,
        provides=frozenset({ANNEALED}),
        field_specs={
            THERMAL_BUDGET.name: THERMAL_BUDGET,
            DOSE.name: DOSE,
        },
        measurements=measurements,
        logs=(
            "post-exposure bake: "
            + _budget_note(temperature, duration)
            + f"; {latent_note}",
        ),
    )


def _behaviour_change(ctx: StepContext, material: MaterialId, target: MaterialId) -> str:
    was, now = ctx.library.get(material), ctx.library.get(target)
    if was is None or now is None:
        return "no library entries to compare"
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


def _run_hard(ctx: StepContext) -> StepResult:
    temperature = float(ctx["temperature"])
    duration = float(ctx["duration"])
    material = MaterialId(str(ctx["material"]))
    entry = ctx.library.get(material)
    if entry is None or entry.hard_bake is None:
        raise ValueError(
            f"material {material!r} has no hard_bake model; the target and activation "
            "temperature must come from its library file"
        )
    target = entry.hard_bake.target
    if target not in ctx.library:
        raise MissingMaterialsError(
            (MissingMaterial(target, seen_in="bake.hard"),)
        )

    structure = accumulate_budget(
        ctx.structure, temperature=temperature, duration=duration
    )
    provides = {ANNEALED}
    retires: set[str] = set()
    activation = entry.hard_bake.activation_temperature
    if material not in structure.phi:
        transition = f"no {material} was present to transform"
    elif temperature < activation:
        transition = (
            f"below {material}'s {activation:.0f} C activation; it remains {material}"
        )
    else:
        measure = structure.measure(structure.inside(material))
        structure = transform(structure, material, target)
        provides.add(capability.of_material(target))
        retires.add(capability.of_material(material))
        transition = (
            f"{material} -> {target} ({measure:.0f} nm^{structure.grid.ndim}); "
            f"{_behaviour_change(ctx, material, target)}"
        )
    return StepResult(
        structure=structure,
        provides=frozenset(provides),
        retires=frozenset(retires),
        field_specs={THERMAL_BUDGET.name: THERMAL_BUDGET},
        measurements=_measurements(structure, temperature, duration),
        logs=(
            "hard bake: "
            + _budget_note(temperature, duration)
            + f"; target {target} from {material}'s library model; {transition}",
        ),
    )


_RESIST = ParamSpec(
    "material",
    str,
    default=str(RESIST),
    description="Resist whose latent image is baked",
    material=MaterialFilter(tags=("resist",), what="resists"),
)

_HARD_BAKE_SOURCE = ParamSpec(
    "material",
    str,
    default=str(RESIST),
    description="Material carrying the hard-bake transition",
    material=MaterialFilter(
        submodel="hard_bake", what="materials with a hard-bake transition"
    ),
)

SOFT_BAKE = FunctionStep(
    step_id="bake.soft",
    display_name="Soft bake",
    fidelity=DIDACTIC,
    schema=(
        ParamSpec("temperature", float, unit="C", default=90.0, minimum=-273.15,
                  maximum=2000.0, description="Hotplate temperature"),
        ParamSpec("duration", float, unit="s", default=60.0, minimum=0.0,
                  description="Time at temperature"),
    ),
    required=frozenset(),
    provided=frozenset({ANNEALED}),
    run_function=_run_soft,
    description=(
        "Adds thermal budget and deliberately leaves every material-scoped field unchanged. "
        "That is the field rule which distinguishes this step: an exposed or dose latent image "
        "comes out bit-for-bit as it went in."
        "\n\n"
        "Temperature and duration still accumulate in the sample-wide thermal-budget field, so "
        "later models can inspect the complete history. No reflow or solvent-loss kinetics are "
        "invented from those two numbers."
        "\n\n"
        "Needs: a sample."
    ),
)

POST_EXPOSURE_BAKE = FunctionStep(
    step_id="bake.post_exposure",
    display_name="Post-exposure bake",
    fidelity=DIDACTIC,
    schema=(
        _RESIST,
        ParamSpec("temperature", float, unit="C", default=110.0, minimum=-273.15,
                  maximum=2000.0, description="Hotplate temperature"),
        ParamSpec("duration", float, unit="s", default=60.0, minimum=0.0,
                  description="Time at temperature"),
        ParamSpec("diffusion_length", float, unit="nm", default=5.0, minimum=0.0,
                  description="Explicit latent-dose diffusion length"),
    ),
    required=frozenset(),
    provided=frozenset({ANNEALED}),
    run_function=_run_post_exposure,
    description=(
        "Diffuses an existing dose field inside the selected resist while preserving its "
        "integral and identity. A binary exposed field is retained bit-for-bit. The diffusion "
        "length is explicit because no calibrated temperature/time kinetics are in the library."
        "\n\n"
        "The global thermal budget accumulates independently. If the selected resist carries no "
        "dose field, the bake still records that budget and reports that it had no continuous "
        "latent image to diffuse; it never manufactures one."
        "\n\n"
        "Needs: a sample; a dose field is optional and remains present when supplied."
    ),
)

HARD_BAKE = FunctionStep(
    step_id="bake.hard",
    display_name="Hard bake",
    fidelity=DIDACTIC,
    schema=(
        _HARD_BAKE_SOURCE,
        ParamSpec("temperature", float, unit="C", default=180.0, minimum=-273.15,
                  maximum=2000.0, description="Hotplate or furnace temperature"),
        ParamSpec("duration", float, unit="s", default=120.0, minimum=0.0,
                  description="Time at temperature"),
    ),
    required=frozenset(),
    provided=frozenset({ANNEALED}),
    run_function=_run_hard,
    description=(
        "At or above the source material's library-backed activation temperature, swaps its "
        "identity to the library-backed target without moving its geometry. There is no typed "
        "target or threshold override, and a missing target refuses before any result is made."
        "\n\n"
        "Every downstream etch and solvent response then follows from the new MaterialType. "
        "Below activation the identity remains unchanged, while either path still accumulates "
        "the sample's thermal budget. Reflow is deliberately not modelled."
        "\n\n"
        "Needs: a sample and a source material with a complete hard_bake library model."
    ),
)

__all__ = [
    "ANNEALED",
    "HARD_BAKE",
    "POST_EXPOSURE_BAKE",
    "SOFT_BAKE",
    "THERMAL_BUDGET",
    "accumulate_budget",
    "diffuse_dose",
    "transform",
]
