"""Turning a `MaterialLibrary` into what the kernel takes (plan §5.4).

`materials/` is pure data and imports nothing from `kernel/` — it cannot, since
`kernel.motion` imports `MaterialId` from it, and the reverse would be a cycle.
This module is the seam on the other side: it is where a `MaterialType`'s rate
table becomes a `SurfaceRates`, its `SputterResponse` becomes a
`flux.AngularYield`, and its per-material etch rates become the `release` map the
redeposition bounce needs.

That is exactly the division plan §5.4 asks for — "duplication lives in thin
process wrappers, physics lives once in the kernel". Nothing here decides
anything; it only translates, so the same library serves a didactic scene and a
calibrated one without either the kernel or the library changing.
"""

from __future__ import annotations

import numpy as np

from nanofab_v3.kernel import flux, motion
from nanofab_v3.materials import MaterialId, MaterialLibrary, MaterialType
from nanofab_v3.model.grid import PHI_DTYPE
from nanofab_v3.model.structure import Structure


def surface_rates(
    library: MaterialLibrary,
    structure: Structure,
    process_class: str,
    *,
    scale: float = 1.0,
    default: float = 0.0,
    only: MaterialId | None = None,
) -> motion.SurfaceRates:
    """`SurfaceRates` for the materials present, from the library's rate table.

    `scale` multiplies every rate — a machine setting (beam current, bath
    temperature) expressed as a factor on the material's blanket rate, which is
    the one knob a didactic tier deserves.

    `only` restricts the motion to a single material: everything else gets
    `default`, which is 0.0, so it does not move. That is how a *selective*
    process is expressed — a solvent that attacks the resist and nothing else is
    a rate table with one entry, not a special case in the solver. Plan §4.2 said
    mask behaviour emerges from rates; so does selectivity.
    """
    rates = {
        material: library[material].rate_for(process_class) * float(scale)
        for material in structure.materials
        if material in library
    }
    if only is not None:
        rates = {material: rate for material, rate in rates.items() if material == only}
    return motion.SurfaceRates(rates=rates, default=float(default))


def dissolve_rates(
    library: MaterialLibrary,
    structure: Structure,
    solvent: str,
    *,
    scale: float = 1.0,
) -> motion.SurfaceRates:
    """`SurfaceRates` for a solvent bath — nonzero only where the bath bites.

    `MaterialType.dissolve_rate` answers 0.0 for a material that is inert in this
    bath, which is a statement about the material rather than about the recipe.
    That is what makes a lift-off a *bath*, applied to the whole sample, rather
    than a list of things to remove.
    """
    return motion.SurfaceRates(
        rates={
            material: library[material].dissolve_rate(solvent) * float(scale)
            for material in structure.materials
            if material in library
        },
        default=0.0,
    )


def develop_rates(
    library: MaterialLibrary,
    structure: Structure,
    material: MaterialId,
    dose: np.ndarray,
) -> tuple[np.ndarray, float]:
    """`(rate map in nm/s, its bound)` from `develop_rate(dose)` (plan §3.4, §6).

    The one process in the didactic set whose rate is a **field** rather than a
    number: the front moves at a speed the resist's own dose profile decides. The
    solver takes it through the `flux` seam — `advect_front(flux=...)` multiplies
    a per-cell array onto the material rate, so handing it `develop_rate(dose) /
    bound` with `SurfaceRates({resist: bound})` is exactly the same speed field
    with the factors regrouped, and nothing in the motion kernel has to learn
    about dose.

    The bound has to come from the model rather than from the dose field, for the
    reason `SurfaceRates.bound` and `FluxModel2D.max_arrival` both exist: the CFL
    sub-step count must not depend on where the front happens to be, or a split
    dose would take different sub-steps from an unsplit one.
    """
    entry = library[material]
    if entry.develop is None:
        raise ValueError(f"material {material!r} has no develop model")
    rate_map = entry.develop_rate(dose)
    return rate_map, float(entry.develop.bound)


def angular_yield(entry: MaterialType) -> flux.AngularYield:
    """The material's `SputterResponse` as the kernel's `AngularYield`.

    `UnitYield` when the material carries no response: the projected area and
    nothing else, which is right for deposition (an arriving atom sticks whatever
    the angle) and the honest default for a didactic etch.
    """
    if entry.sputter_response is None:
        return flux.UnitYield()
    return flux.SputterYield(
        rise=entry.sputter_response.rise, fall=entry.sputter_response.fall
    )


def dominant_yield(
    library: MaterialLibrary, structure: Structure, process_class: str
) -> flux.AngularYield:
    """The angular yield of the material this process removes fastest.

    A single `FluxModel2D` carries one yield model, because the arrival is
    computed per front cell before anything knows which material that cell
    belongs to. Picking the fastest-etched material's response is the didactic
    choice with the least surprise: it is the material whose faceting the picture
    is about, and the one whose rate sets the CFL bound anyway.

    The honest limitation, recorded rather than hidden: a scene where two
    materials with very different yield curves are etched side by side gets one
    curve. A per-material arrival would mean one visibility solve per material,
    which is the cost plan §4.3 is built to avoid, and tier (b) is where that
    trade would be worth revisiting.
    """
    candidates = [
        (library[material].rate_for(process_class), material)
        for material in structure.materials
        if material in library
    ]
    fastest = max(candidates, default=(0.0, None))[1]
    if fastest is None:
        return flux.UnitYield()
    return angular_yield(library[fastest])


def release_map(
    library: MaterialLibrary, structure: Structure, process_class: str
) -> np.ndarray | None:
    """Per-cell `release` for the redeposition bounce — the seam of §18/M2 note 8.

    `kernel.flux` knows only geometry, so without this a hard mask standing in an
    ion beam would redeposit material it is not losing. Each cell releases in
    proportion to **its own material's rate relative to the fastest one**, which
    is the geometry-blind fact the flux model cannot derive: a mask at rate 0
    releases nothing, and the material being etched releases everything.

    `None` when every material in the scene has the same rate — the flux model's
    own default then means the same thing and costs nothing.
    """
    grid = structure.grid
    rates = {
        material: library[material].rate_for(process_class)
        for material in structure.materials
        if material in library
    }
    if not rates:
        return None
    fastest = max(rates.values())
    if fastest <= 0.0 or len(set(rates.values())) == 1:
        return None
    table = np.array(
        [rates.get(material, 0.0) / fastest for material in structure.materials],
        dtype=PHI_DTYPE,
    )
    return table[structure.nearest_material_index]
