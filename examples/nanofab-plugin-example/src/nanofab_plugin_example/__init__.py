"""An example NanoFab process plugin — a second implementer of plan §5.4's seam.

This package exists to be *installed*, not imported from the tree: a discovery
mechanism with only one implementer is a discovery mechanism nobody has tried.
`tests/test_plugins.py` builds a wheel of it into a temp directory and runs
discovery against it in a subprocess, which is the only way to find out whether
the entry-point group name, the object shapes and the packaging metadata agree.

It ships two entry points, one of each shape the loader accepts:

- `spin_on_glass` resolves to a `ProcessStep` — the ordinary case, one step and
  no boilerplate;
- `extras` resolves to `register(registry)` — the general case, for a package
  that adds several steps or has setup to do.

## What it demonstrates about writing a process

Interview decision I7 and plan §5.4: *physics lives once in the kernel,
duplication lives in thin process wrappers.* Neither step here implements any
geometry. `spin_on_glass` is `kernel.constructors.box` carved by `add_material`
— the same call `resist.spin_coat` makes, with a different material and a
different name — and `spin_on_glass.cure` is a field write. A plugin that
reimplemented a front solver would be a plugin that drifts from the kernel the
moment either changes.

Three rules it has to keep, all enforced at the door it comes through
(`ProcessRegistry.register`):

1. **A unique `step_id`.** Namespaced under `sog.` here, which is what keeps a
   plugin from silently redefining `resist.spin_coat` for every recipe in the
   application.
2. **No process-global RNG** (plan §5.2). Nothing here is stochastic; anything
   that were would have to draw from `ctx.rng`, and the registry's lint reads
   the wrapper's source to say so.
3. **Purity.** A step is a function of its context. `sog.spin` reads
   `ctx.structure` and `ctx.params` and touches nothing else.

## The material it brings

`sog` is not in `didactic_library()`, and that is deliberate: a plugin's material
is the plugin's, and the model handles one it has never heard of. The library
answers `None` for it (`MaterialLibrary.get`), `blanket_rates` leaves it out, and
a bath it has no rate for does not move it — which is
`tests/test_processes.py::test_a_library_a_process_has_never_heard_of_still_runs`
as a shipped consequence rather than a test fixture.
"""

from __future__ import annotations

import numpy as np

from nanofab_v3.kernel import constructors as ctor
from nanofab_v3.materials import MaterialId
from nanofab_v3.model import capability
from nanofab_v3.model.field import FieldSpec
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

__version__ = "0.1.0"

SOG = MaterialId("sog")
"""Spin-on glass — this plugin's own material, unknown to the didactic library."""

CURE = FieldSpec(
    name="cure", dtype=np.float32, default=0.0, material_scoped=True, unit=""
)
"""How far the glass has cured, 0 to 1 — scoped, so fresh glass arrives uncured."""


def spin_on(structure: Structure, material: MaterialId, *, thickness: float) -> Structure:
    """Fill everything below `thickness` above the highest solid with `material`.

    A planarising fill: one `box` carved against what is already there, which is
    the whole of the geometry and the reason a plugin does not need kernel access
    beyond the constructors. Spin-on glass planarises harder than a resist does,
    which in this model is the same operation with a different material — the
    difference lives in the library entry an application would supply for `sog`,
    not in a second solver.
    """
    grid = structure.grid
    if thickness <= 0.0:
        raise ValueError(f"thickness must be positive, got {thickness}")
    solid = structure.solid_mask
    if not solid.any():
        raise ValueError("spin_on needs something to coat")
    highest = int(np.max(np.argwhere(solid)[:, 0]))
    level = grid.origin[0] + grid.spacing * highest + float(thickness)
    upper: list[float | None] = [None] * grid.ndim
    upper[0] = level
    return ctor.add_material(structure, material, ctor.box(grid, [None] * grid.ndim, upper))


def _run_spin(ctx: StepContext) -> StepResult:
    material = MaterialId(str(ctx["material"]))
    structure = spin_on(ctx.structure, material, thickness=float(ctx["thickness"]))
    return StepResult(
        structure=structure,
        provides=frozenset({capability.of_material(material)}),
        measurements={"thickness": Quantity(float(ctx["thickness"]), "nm")},
        logs=(f"spun {ctx['thickness']:.0f} nm of {material} (planarising)",),
    )


def _run_cure(ctx: StepContext) -> StepResult:
    material = MaterialId(str(ctx["material"]))
    if material not in ctx.structure.phi:
        return StepResult(structure=ctx.structure, logs=(f"no {material} to cure",))
    fraction = min(1.0, float(ctx["duration"]) / max(float(ctx["time_constant"]), 1e-9))
    key = CURE.key(material)
    values = ctx.structure.grid.full(fraction, dtype=CURE.dtype)
    return StepResult(
        structure=ctx.structure.with_field(key, values),
        provides=frozenset({capability.of_field(material, CURE.name)}),
        field_specs={CURE.name: CURE},
        measurements={"cure": Quantity(fraction)},
        logs=(f"cured {material} to {fraction * 100:.0f}%",),
    )


SPIN_ON_GLASS = FunctionStep(
    step_id="sog.spin",
    display_name="Spin-on glass (plugin)",
    fidelity=IDEAL,
    schema=(
        ParamSpec("material", str, default=str(SOG), description="Which glass"),
        ParamSpec("thickness", float, unit="nm", default=None, minimum=0.0,
                  description="Thickness above the highest solid"),
    ),
    required=frozenset(),
    provided=frozenset(),
    run_function=_run_spin,
)

CURE_STEP = FunctionStep(
    step_id="sog.cure",
    display_name="Cure spin-on glass (plugin)",
    fidelity=DIDACTIC,
    schema=(
        ParamSpec("material", str, default=str(SOG), description="Which glass"),
        ParamSpec("duration", float, unit="s", default=None, minimum=0.0,
                  description="Time on the hotplate"),
        ParamSpec("time_constant", float, unit="s", default=300.0, minimum=1.0,
                  description="Time to a full cure"),
    ),
    required=frozenset(),
    provided=frozenset(),
    run_function=_run_cure,
)


def register(registry) -> None:
    """The callable entry-point shape: add whatever this package brings.

    `sog.spin` is registered by its own entry point, so this adds only the rest.
    A package with nothing to add per-step would put everything here instead;
    both shapes go through the same `ProcessRegistry.register`.
    """
    registry.register(CURE_STEP)


__all__ = [
    "CURE",
    "CURE_STEP",
    "SOG",
    "SPIN_ON_GLASS",
    "register",
    "spin_on",
]
