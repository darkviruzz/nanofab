"""Particles and clean (plan §6, rows 16-17) — and the first stochastic step.

Two processes and one didactic point between them:

    particles = seeded disks of a particle material, resting on the surface
    clean     = remove every particle occurrence the bath can **reach**

**Micromasking is the whole payload.** A particle that landed before a film was
deposited is under that film afterwards, and a clean has no path to it — so the
clean leaves it, and whatever it masked stays masked. Nothing here special-cases
that: it falls out of `predicates.reachable_occurrences`, the same query that
makes S3's sealed resist survive lift-off. Clean's own contribution is that it
*reports* the survivors, because "three of five particles came off" is the
finding, and a step that silently did its best would hide it.

## Two decisions this module had to make, both about where a particle is

**A particle rests on the surface; it is never placed at a random point in the
domain.** Handoff §4's trap 2, fifth milestone running: a disk placed at a
uniformly random `(y, x)` lands inside the substrate about as often as not, and
`add_material` carves it away against the material already there — a set
operation that succeeds, changes nothing, and leaves the step reporting a
particle count that does not match the geometry. So the *lateral* coordinate is
what is drawn, and the height is read off the sample: the topmost solid cell in
that column, with the disk resting on it. A particle is then always in empty
space, always touching what it landed on, and always visible in the picture.

**A column with no solid in it gets no particle.** In a cross-section built by
`substrate.select` every column carries solid (plan §17.5), so this is not the
ordinary path — but a particle over a through-etched trench has nothing to land
on, and the model has no floor below the domain to invent for it. The draw is
skipped and the step says so, which costs one particle and no geometry.

## What the RNG contract is being exercised by

Plan §5.2 requires that anything stochastic draws from `StepContext.rng`, seeded
from (recipe id, position, step index), and ADR-0004's replay materialization
rests on it. Until M5 that contract had been tested only against a step written
inside a test file; `particle.seed` is the first **registered** step to use it.
That is what makes it worth the acceptance scenario: two runs of a recipe at one
position must scatter identical particles, two positions must scatter different
ones, and adding a position later must reproduce the particles that position
would have had.
"""

from __future__ import annotations

import numpy as np

from nanofab_v3.kernel import constructors as ctor
from nanofab_v3.kernel import csg, occurrences, predicates, regions
from nanofab_v3.materials import PARTICLE, MaterialId
from nanofab_v3.model import capability
from nanofab_v3.model.quantity import Quantity
from nanofab_v3.model.structure import Structure
from nanofab_v3.processes.contract import (
    IDEAL,
    FunctionStep,
    ParamSpec,
    StepContext,
    StepResult,
)

STACK_AXIS = 0
"""The axis a cross-section stacks along — `substrate.cross_section_grid`'s `y`."""


def surface_rows(structure: Structure) -> np.ndarray:
    """Index of the topmost solid cell per lateral column, `-1` where there is none.

    The one place this module reads geometry, and it reads the **union** mask
    rather than any single material's field: what a particle lands on is whatever
    is topmost there, and at a boundary between two materials `phi` is exactly
    zero for both (plan §17.1), so asking one of them would answer for the wrong
    one at every seam.
    """
    solid = structure.solid_mask
    rows = np.arange(solid.shape[STACK_AXIS])
    indexed = np.where(solid, rows[:, None], -1)
    return indexed.max(axis=STACK_AXIS)


def scatter_particles(
    structure: Structure,
    rng: np.random.Generator,
    *,
    count: int,
    radius: float,
    radius_spread: float = 0.0,
    material: MaterialId = PARTICLE,
) -> tuple[Structure, int]:
    """Drop `count` particles onto the sample's surface; return it and how many landed.

    Each particle draws a lateral position uniformly across the domain and a
    radius uniformly from `radius * (1 ± radius_spread)`, both from `rng` and
    only from `rng` (plan §5.2). It is then placed resting on the topmost solid
    cell of that column: the disk centre sits one cell *below* surface + radius,
    so the particle and what it landed on share a cell before `add_material`
    carves the overlap away, and the particle is part of the same connected solid
    afterwards rather than a disk hovering one cell above it.

    The balls are unioned and placed in **one** `add_material` call, so two
    particles that overlap become one occurrence — which is what they are, and
    what a clean will remove or leave as one.
    """
    if count < 1:
        return structure, 0
    grid = structure.grid
    lateral = 1 if grid.ndim > 1 else 0
    low, high = grid.extent(lateral)
    tops = surface_rows(structure)
    base = grid.origin[STACK_AXIS]

    fields: list[np.ndarray] = []
    for _ in range(count):
        x = float(rng.uniform(low, high))
        size = float(radius * (1.0 + rng.uniform(-radius_spread, radius_spread)))
        if size <= 0.0:
            continue
        column = int(round((x - low) / grid.spacing))
        column = min(max(column, 0), grid.shape[lateral] - 1)
        top = int(tops[column])
        if top < 0:
            continue  # nothing to land on in this column; see the module docstring
        centre = [0.0] * grid.ndim
        centre[STACK_AXIS] = base + top * grid.spacing + size - grid.spacing
        centre[lateral] = x
        fields.append(ctor.ball(grid, centre, size))

    if not fields:
        return structure, 0
    return ctor.add_material(structure, material, csg.union(*fields)), len(fields)


def count_occurrences(structure: Structure, material: MaterialId) -> int:
    """How many connected pieces of `material` the structure holds (ADR-0003).

    Derived, never stored — which is the whole of ADR-0003, and the reason two
    particles that landed on top of each other count as one here and would have
    counted as two in any scheme that gave them ids when they were placed.
    """
    if material not in structure.phi:
        return 0
    region = predicates.cells_of(structure, material)
    _, found = occurrences.label_region(structure.grid, region)
    return int(found)


def clean(
    structure: Structure,
    material: MaterialId = PARTICLE,
    *,
    faces: tuple[tuple[str, str], ...] | None = None,
) -> tuple[Structure, int, int]:
    """Remove every reachable occurrence of `material`; report what stayed.

    Returns `(structure, removed, left)` in occurrences. Per occurrence and not
    per cell for the reason `removal.dissolve` is: a bath that reaches one cell
    of a loose particle takes the particle.

    The survivors are the finding. A particle with no path to the outside is
    **micromasked** — it is under something — and there is no clean chemistry and
    no clean time that reaches it, which is why this returns a count rather than
    trying harder.
    """
    before = count_occurrences(structure, material)
    if before == 0:
        return structure, 0, 0
    removed = predicates.reachable_occurrences(structure, material, faces=faces)
    if not removed.any():
        return structure, 0, before
    cleaned = regions.remove_region(structure, removed, materials=(material,))
    return cleaned, before - count_occurrences(cleaned, material), count_occurrences(
        cleaned, material
    )


# -- registered steps ---------------------------------------------------------


def _run_particles(ctx: StepContext) -> StepResult:
    material = MaterialId(str(ctx["material"]))
    structure, landed = scatter_particles(
        ctx.structure,
        ctx.rng,
        count=int(ctx["count"]),
        radius=float(ctx["radius"]),
        radius_spread=float(ctx["radius_spread"]),
        material=material,
    )
    pieces = count_occurrences(structure, material)
    skipped = int(ctx["count"]) - landed
    logs = [f"{landed} particles landed, {pieces} occurrences of {material}"]
    if skipped:
        logs.append(f"{skipped} particles had no surface to land on and were skipped")
    return StepResult(
        structure=structure,
        provides=frozenset({capability.of_material(material)}),
        measurements={
            "particles": Quantity(float(landed)),
            "occurrences": Quantity(float(pieces)),
        },
        logs=tuple(logs),
    )


def _run_clean(ctx: StepContext) -> StepResult:
    material = MaterialId(str(ctx["material"]))
    structure, removed, left = clean(ctx.structure, material)
    masked = (
        structure.measure(predicates.cells_of(structure, material))
        if material in structure.phi
        else 0.0
    )
    logs = [f"clean removed {removed} {material} occurrences"]
    if left:
        logs.append(
            f"{left} left behind: unreachable under later material "
            f"({masked:.0f} nm^{structure.grid.ndim} micromasked)"
        )
    return StepResult(
        structure=structure,
        retires=frozenset(),
        measurements={
            "removed": Quantity(float(removed)),
            "micromasked": Quantity(float(left)),
            "micromasked_area": Quantity(masked, f"nm^{structure.grid.ndim}"),
        },
        logs=tuple(logs),
    )


_MATERIAL = ParamSpec(
    "material", str, default=str(PARTICLE), description="Which material the particles are"
)

PARTICLES = FunctionStep(
    step_id="particle.seed",
    display_name="Particle contamination",
    fidelity=IDEAL,
    schema=(
        _MATERIAL,
        ParamSpec("count", int, default=5, minimum=0, maximum=10000,
                  description="How many particles land on the sample"),
        ParamSpec("radius", float, unit="nm", default=8.0, minimum=0.5,
                  description="Mean particle radius"),
        ParamSpec("radius_spread", float, default=0.0, minimum=0.0, maximum=0.95,
                  description="Fractional spread of the radius, uniform"),
    ),
    required=frozenset(),
    provided=frozenset(),
    run_function=_run_particles,
    stochastic=True,
)

CLEAN = FunctionStep(
    step_id="clean.particles",
    display_name="Clean (particle removal)",
    fidelity=IDEAL,
    schema=(_MATERIAL,),
    required=frozenset(),
    provided=frozenset(),
    run_function=_run_clean,
)
