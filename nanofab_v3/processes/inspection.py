"""SEM and profilometer (plan §6, row 18) — steps that only look.

Interview decision Q6, and the reason inspection is a *step* rather than a panel:
"etch, inspect, etch, inspect" has to be four plain entries in one chain, so that
what an inspection saw is pinned to the revision it saw it on and survives being
saved, replayed and scrubbed back to. The chain has been able to express that
since M4 and had never been asked to.

Every step here returns `ctx.structure` **unchanged** — the same object, not an
equal one — and produces measurements plus, when it has somewhere to put one, an
artifact. Plan §5.1 says exactly that, and the identity matters twice over: the
commit gate's array-sharing rule (plan §20.2) then keeps the whole revision
sharing its parent's arrays, so an inspection costs no memory and moves no
interface, and `swept=None` keeps it out of the balance check, which is the
honest answer for a step that swept no front.

## What each instrument actually reports

None of these invents a number. Each one is a question the model can already
answer, dressed in the units the instrument reports it in:

- **SEM** sees the cross-section: which materials are present, how many separate
  pieces of the one being looked at, how wide and how tall it is. The artifact is
  the material index map — the same exclusive partition `ui.scene` draws from
  (plan §20.6), which is what makes "what the SEM saw" and "what the picture
  shows" the same array rather than two renderings that could drift.
- **The profilometer** drags a stylus across the surface and reports its trace,
  the step height and the roughness. `stylus_radius` is the didactic part: a
  finite tip cannot enter a trench narrower than itself, so it rolls over the
  top and **under-reports the step**. That is the instrument's characteristic
  error, not a modelling shortcut, and setting the radius to 0 turns it off.

**There was a third, and it is gone** (roadmap E35). The ellipsometer reported a
film's mean thickness and the library's optical constants for it; no demo, no
scenario and no recipe used it, and the thing it was for — "how thick is this
layer" — is what `predicates.film_thickness` answers and what the profilometer
already reports. A step nobody runs is a step nobody notices going wrong, and
this one carried its own copy of the stack-walking logic to do it. The predicate
stays: it has three callers, the profilometer among them.

## The artifact wire this module is the first user of

`StepResult.artifacts` reached nothing until M5: `apply_step` took artifacts as
an argument and no registered step produced any (memory.md 2026-08-26, risk 3).
The wire is closed here rather than earlier because plumbing with no producer is
plumbing nobody has run. A step with no `ctx.artifacts` sink emits no reference
and still measures everything — see `model.artifact` for why that is the honest
default rather than a degraded one.
"""

from __future__ import annotations

import numpy as np

from nanofab_v3.kernel import occurrences, predicates
from nanofab_v3.materials import MaterialId
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


def surface_trace(structure: Structure) -> np.ndarray:
    """Height of the topmost solid cell per lateral column, in nm.

    `-inf` where a column holds no solid at all, so a caller can tell "the
    surface is at zero" from "there is no surface here" — which a profilometer
    dragging its stylus off the edge of the sample genuinely cannot.
    """
    solid = structure.solid_mask
    rows = np.arange(solid.shape[STACK_AXIS])
    top = np.where(solid, rows[:, None], -1).max(axis=STACK_AXIS)
    height = structure.grid.origin[STACK_AXIS] + top * structure.grid.spacing
    return np.where(top >= 0, height, -np.inf)


def stylus_trace(structure: Structure, *, radius: float = 0.0) -> np.ndarray:
    """The surface as a stylus of `radius` nm would trace it.

    A tip cannot reach into a feature narrower than itself: rolling a disk of
    radius `r` along the surface, the height it reports at `x` is the highest the
    tip centre has to sit to clear every point it might touch, minus `r`. That is
    a grayscale morphological dilation by a spherical structuring element, and it
    is why a real profilometer reads a 20 nm-wide, 50 nm-deep trench as a dimple.

    `radius <= 0` is an ideal point stylus and returns the surface itself.
    """
    surface = surface_trace(structure)
    if radius <= 0.0 or not np.isfinite(surface).any():
        return surface

    spacing = structure.grid.spacing
    reach = int(radius // spacing)
    if reach < 1:
        return surface
    offsets = np.arange(-reach, reach + 1) * spacing
    cap = np.sqrt(np.maximum(radius**2 - offsets**2, 0.0))

    floor = np.min(surface[np.isfinite(surface)], initial=0.0)
    padded = np.where(np.isfinite(surface), surface, floor)
    traced = np.full_like(padded, -np.inf)
    for offset, lift in zip(range(-reach, reach + 1), cap):
        shifted = np.roll(padded, offset)
        # A rolled edge would wrap the far side of the sample into this one.
        if offset > 0:
            shifted[:offset] = padded[0]
        elif offset < 0:
            shifted[offset:] = padded[-1]
        traced = np.maximum(traced, shifted + lift)
    return np.where(np.isfinite(surface), traced - radius, surface)


def _extent(structure: Structure, material: MaterialId) -> tuple[float, float]:
    """`(width, height)` of a material's bounding box, in nm — 0 when absent."""
    if material not in structure.phi:
        return 0.0, 0.0
    cells = predicates.cells_of(structure, material)
    if not cells.any():
        return 0.0, 0.0
    spacing = structure.grid.spacing
    columns = np.flatnonzero(np.any(cells, axis=STACK_AXIS))
    rows = np.flatnonzero(np.any(cells, axis=1))
    return (
        float(columns.max() - columns.min() + 1) * spacing,
        float(rows.max() - rows.min() + 1) * spacing,
    )


def _run_sem(ctx: StepContext) -> StepResult:
    structure = ctx.structure
    named = str(ctx["material"]).strip()
    material = MaterialId(named) if named else None

    if material is None:
        cells = structure.solid_mask
        label = "the stack"
    else:
        cells = predicates.cells_of(structure, material)
        label = str(material)
    _, pieces = occurrences.label_region(structure.grid, cells)
    width, height = (
        _extent(structure, material)
        if material is not None
        else (
            float(structure.grid.shape[1]) * structure.grid.spacing,
            float(structure.grid.shape[0]) * structure.grid.spacing,
        )
    )

    artifacts = ()
    if ctx.artifacts is not None:
        artifacts = (
            ctx.artifacts.put(
                f"sem-{ctx['tag']}" if ctx["tag"] else "sem",
                structure.material_index,
                kind="image",
                label=f"SEM ({label})",
            ),
        )
    return StepResult(
        structure=structure,
        measurements={
            "features": Quantity(float(pieces)),
            "width": Quantity(width, "nm"),
            "height": Quantity(height, "nm"),
        },
        artifacts=artifacts,
        logs=(f"SEM: {pieces} feature(s) of {label}, {width:.0f} x {height:.0f} nm",),
    )


def _run_profilometer(ctx: StepContext) -> StepResult:
    structure = ctx.structure
    radius = float(ctx["stylus_radius"])
    trace = stylus_trace(structure, radius=radius)
    finite = trace[np.isfinite(trace)]
    if finite.size == 0:
        step_height = roughness = mean = 0.0
    else:
        step_height = float(finite.max() - finite.min())
        roughness = float(np.mean(np.abs(finite - finite.mean())))  # Ra
        mean = float(finite.mean())

    artifacts = ()
    if ctx.artifacts is not None:
        columns = structure.grid.coordinates(1)
        artifacts = (
            ctx.artifacts.put(
                f"profile-{ctx['tag']}" if ctx["tag"] else "profile",
                np.vstack([columns, np.where(np.isfinite(trace), trace, np.nan)]),
                kind="table",
                label="Profilometer trace",
            ),
        )
    return StepResult(
        structure=structure,
        measurements={
            "step_height": Quantity(step_height, "nm"),
            "roughness_ra": Quantity(roughness, "nm"),
            "mean_height": Quantity(mean, "nm"),
        },
        artifacts=artifacts,
        logs=(
            f"profilometer (stylus {radius:.0f} nm): step {step_height:.1f} nm, "
            f"Ra {roughness:.2f} nm",
        ),
    )


_TAG = ParamSpec(
    "tag",
    str,
    default="",
    description="Name for this inspection's artifact; blank reuses the default name",
)

SEM = FunctionStep(
    step_id="inspect.sem",
    display_name="SEM (cross-section)",
    fidelity=IDEAL,
    schema=(
        ParamSpec("material", str, default="",
                  description="Material to measure; blank means the whole stack"),
        _TAG,
    ),
    required=frozenset(),
    provided=frozenset(),
    run_function=_run_sem,
    description=(
        "A look at the sample **in cross-section**: the connected pieces of each material, "
        "counted and measured, with the material index map saved as an artifact when there is "
        "somewhere to put one."
        "\n\n"
        "The name says cross-section because that is what this view is (roadmap E35): the plane "
        "you are looking at is the one a FIB cut would expose, and calling it a top-down SEM "
        "would describe a picture this model does not have. A real FIB as a *second* section, "
        "across this one, would require three dimensions and is deliberately not here."
        "\n\n"
        "It reads the real geometry — nothing here is mocked — but it is a label map rather "
        "than a simulated electron image: no edge brightness, no material contrast, no tilt. "
        "What it is honest about is topology, which is what a picture of a lift-off is usually "
        "being asked about."
        "\n\n"
        "Changes nothing on the sample. Needs: a sample."
    ),
)

PROFILOMETER = FunctionStep(
    step_id="inspect.profilometer",
    display_name="Profilometer",
    fidelity=IDEAL,
    schema=(
        ParamSpec("stylus_radius", float, unit="nm", default=0.0, minimum=0.0,
                  description="Tip radius; 0 is an ideal point stylus"),
        _TAG,
    ),
    required=frozenset(),
    provided=frozenset(),
    run_function=_run_profilometer,
    description=(
        "Drags a stylus of radius `tip_radius` across the surface and reports the trace, the "
        "step height and the roughness."
        "\n\n"
        "The tip convolution is the didactically valuable part and is really computed: a trench "
        "narrower than the tip comes back shallower than it is, and a sharp corner comes back "
        "rounded, exactly as on a real instrument. Compare the trace against the cross-section "
        "to see how much of a measurement is the instrument."
        "\n\n"
        "Changes nothing on the sample. Needs: a sample."
    ),
)

