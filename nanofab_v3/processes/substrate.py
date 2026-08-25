"""Substrate selection and the domain it lives in (plan §6, first row).

The one step that has no input geometry: it *makes* the `Grid`, places the wafer
as a half-space, and leaves the headroom every later deposition needs. Plan §3.1
puts both decisions here — "the domain is created at substrate selection with
configurable empty space above the stack" — and that is what replaces v1's magic
`0.42 * extent` cut plane and its boundary-edge filtering.
"""

from __future__ import annotations

from nanofab_v3.kernel import constructors as ctor
from nanofab_v3.materials import SILICON, MaterialId
from nanofab_v3.model import capability
from nanofab_v3.model.grid import Grid
from nanofab_v3.model.structure import Structure
from nanofab_v3.processes.contract import (
    IDEAL,
    FunctionStep,
    ParamSpec,
    StepContext,
    StepResult,
)


def cross_section_grid(
    *, width: float, thickness: float, headroom: float, spacing: float = 1.0
) -> Grid:
    """A 2D cross-section domain: substrate `thickness` below, `headroom` above.

    The surface sits at `y = thickness`, so a stack builds upward from a round
    number and the headroom is exactly what is left. `spacing` is the visible
    model parameter of plan §3.1 — the realism/speed trade — and the default is
    the plan's 1 nm.

    Named a *cross-section* rather than a domain because that is the decision it
    encodes: the first axis stacks, the second continues sideways. Every guard in
    the package reads that convention (`gate`'s headroom face, `predicates`' open
    face), and this is where it is set.
    """
    for name, value in (("width", width), ("thickness", thickness), ("headroom", headroom)):
        if value <= 0.0:
            raise ValueError(f"{name} must be positive, got {value}")
    if spacing <= 0.0:
        raise ValueError(f"spacing must be positive, got {spacing}")
    rows = int(round((thickness + headroom) / spacing)) + 1
    columns = int(round(width / spacing)) + 1
    return Grid(origin=(0.0, 0.0), spacing=spacing, shape=(rows, columns), axes=("y", "x"))


def select_substrate(
    grid: Grid, material: MaterialId = SILICON, *, surface: float
) -> Structure:
    """A blanket wafer filling everything below `surface` (plan §4.1).

    A half-space, which is the one primitive that is *exactly* representable on
    the grid — a linear function, sampled exactly, with bilinear reconstruction
    exact between the samples. Every measurement in the acceptance scenarios is
    taken against this surface, so it being exact is what makes the numbers mean
    the process rather than the constructor.
    """
    normal = tuple(1.0 if axis == 0 else 0.0 for axis in range(grid.ndim))
    point = tuple(surface if axis == 0 else 0.0 for axis in range(grid.ndim))
    return ctor.add_material(
        Structure(grid), material, ctor.half_space(grid, normal=normal, point=point)
    )


def _run_select(ctx: StepContext) -> StepResult:
    material = MaterialId(str(ctx["material"]))
    structure = select_substrate(ctx.structure.grid, material, surface=ctx["surface"])
    return StepResult(
        structure=structure,
        provides=frozenset({capability.of_material(material)}),
        logs=(f"substrate {material} with its surface at {ctx['surface']:.1f} nm",),
    )


SELECT_SUBSTRATE = FunctionStep(
    step_id="substrate.select",
    display_name="Select substrate",
    fidelity=IDEAL,
    schema=(
        ParamSpec("material", str, default=str(SILICON), description="Wafer material"),
        ParamSpec(
            "surface",
            float,
            unit="nm",
            default=None,
            minimum=0.0,
            description="Height of the wafer surface in the domain",
        ),
    ),
    required=frozenset(),
    provided=frozenset(),
    run_function=_run_select,
)
"""Place the wafer. Requires nothing — it is where a chain starts."""
