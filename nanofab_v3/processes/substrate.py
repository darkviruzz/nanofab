"""Substrate selection and the domain it lives in (plan §6 first row, roadmap M7).

The one step that has no input geometry: it *makes* the `Grid`, places the wafer
as a half-space, and leaves the headroom every later deposition needs. Plan §3.1
puts both decisions here — "the domain is created at substrate selection with
configurable empty space above the stack" — and that is what replaces v1's magic
`0.42 * extent` cut plane and its boundary-edge filtering.

## What a substrate is, and what the domain is (roadmap E1, E7, §1)

They are not the same size and this module is where they stop pretending to be.
A 100 mm wafer is 525 µm thick; roadmap §1 measured what drawing that would cost
— `rows x columns x 4` bytes per material, so ~2.4 GB per revision at 100 µm and
15 GB at 625 — and concluded that it cannot be a domain. So:

- the **substrate** is a `SubstrateSpec`: form factor, material, real dimensions
  in millimetres, surface finish. It goes into `Structure.metadata`, where a
  later step can read it — which is what makes "you have etched through the
  wafer" answerable at all (E7);
- the **domain** is the nanometre-scale window the cross-section is drawn in. It
  follows the sample (`kernel.domain`) and shows the part where something is
  happening. The 525 µm are *known*, not drawn.

`semi_infinite` is the form factor for "the thickness does not matter here". It
is a value of the same field rather than a second step, so a recipe format never
splits in two (E1) — and it is the encoding that makes the through-etch check
silently inapplicable instead of guessing a number.

## Presets (E2, E3)

`SUBSTRATE_PRESETS` is a fixed table in code rather than JSON beside the material
library, and the difference is what the numbers *are*: a wafer diameter is a
standard, a rate is a measurement. Nobody needs to correct SEMI D1 without a
rebuild, and a substrate this table does not list is already expressible — pick a
form factor and type the dimensions. (If a lab ever does need its own, the seam
is the same shape as roadmap E14's and is one file away.)

A preset carries a **suggested domain** as well as the substrate, which is E2:
choosing "100 mm fused silica" and separately choosing a 50 µm-wide cross-section
is the mistake that becomes impossible when one choice drives both. It stays a
*suggestion* — the step uses the grid it was given unless the preset's domain is
asked for — because a step that silently replaced the domain a recipe specified
would be a step whose output depended on something not in its parameters.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from nanofab_v3.kernel import constructors as ctor
from nanofab_v3.materials import FUSED_SILICA, SILICON, MaterialId
from nanofab_v3.model import capability
from nanofab_v3.model.grid import Grid
from nanofab_v3.model.quantity import Quantity
from nanofab_v3.model.structure import Structure
from nanofab_v3.materials.selection import MaterialFilter
from nanofab_v3.processes.contract import (
    IDEAL,
    FunctionStep,
    ParamSpec,
    StepContext,
    StepResult,
)

MM = 1.0e6
"""Nanometres per millimetre. Substrates are quoted in mm; the model works in nm."""

# -- form factors (roadmap E1) ------------------------------------------------

WAFER = "wafer"
"""A round substrate, quoted by diameter."""

MASK = "mask"
"""A square mask blank, quoted by side length — SEMI's photomask geometry."""

CHIP = "chip"
"""A rectangular piece, quoted by two sides. A cleaved coupon, a die."""

SEMI_INFINITE = "semi_infinite"
"""Thickness unknown or irrelevant — E1's encoding, and *not* a second step.

The through-etch check (E7) does not apply to a substrate whose thickness nobody
stated, which is the honest behaviour: the alternative is inventing a number and
then failing against it.
"""

FORM_FACTORS = (WAFER, MASK, CHIP, SEMI_INFINITE)

POLISHED = "polished"
DOUBLE_SIDE_POLISHED = "double-side-polished"
ETCHED = "etched"
AS_CUT = "as-cut"
SURFACE_FINISHES = (POLISHED, DOUBLE_SIDE_POLISHED, ETCHED, AS_CUT)
"""Recorded, not modelled: no process reads it yet, and `metadata` is where a
fact about the sample waits until one does."""

# -- metadata keys ------------------------------------------------------------

MATERIAL_KEY = "substrate.material"
FORM_FACTOR_KEY = "substrate.form_factor"
THICKNESS_KEY = "substrate.thickness"
"""Real substrate thickness in nm — absent for `semi_infinite`."""
SURFACE_KEY = "substrate.surface"
"""Where the original surface sat in domain coordinates, in nm."""
DIAMETER_KEY = "substrate.diameter"
SIZE_X_KEY = "substrate.size_x"
SIZE_Y_KEY = "substrate.size_y"
FINISH_KEY = "substrate.surface_finish"
PRESET_KEY = "substrate.preset"


@dataclass(frozen=True)
class DomainSuggestion:
    """The cross-section a preset proposes: width, headroom and resolution in nm."""

    width: float = 1200.0
    headroom: float = 400.0
    spacing: float = 1.0


@dataclass(frozen=True)
class SubstratePreset:
    """One entry of the semi-standard list (E3) — a substrate and its domain.

    Attributes:
        key: Stable id, what a recipe stores.
        section: `"wafer"` or `"mask"` — E3's two-part dropdown.
        label: What the dropdown shows.
        form_factor: One of `FORM_FACTORS`.
        material: The `MaterialId` it is made of.
        thickness_mm: Real thickness in millimetres.
        diameter_mm: Diameter for a round substrate, else `None`.
        side_mm: Side length for a square one, else `None`.
        domain: The cross-section this preset proposes (E2).
    """

    key: str
    section: str
    label: str
    form_factor: str
    material: MaterialId
    thickness_mm: float
    diameter_mm: float | None = None
    side_mm: float | None = None
    domain: DomainSuggestion = DomainSuggestion()

    @property
    def sort_key(self) -> tuple[str, float, float]:
        """E3's order: by material, then ascending size, then ascending thickness."""
        size = self.diameter_mm if self.diameter_mm is not None else (self.side_mm or 0.0)
        return (str(self.material), float(size), float(self.thickness_mm))


_MASK_DOMAIN = DomainSuggestion(width=2400.0, headroom=400.0, spacing=2.0)
"""A mask blank is written with coarser features than a wafer is patterned with,
so its default cross-section is wider and its cells are bigger. A didactic
choice, and the reason it is a *default* rather than a rule: `spacing` is plan
§3.1's visible model parameter, and doubling it buys four times the speed at half
the resolution."""


def _mask(code: str, side_mm: float, thickness_mm: float) -> SubstratePreset:
    """One SEMI photomask blank, named by its short code.

    The code reads as two inch measurements: `6025` is a 6-inch square 0.250 inch
    thick. The metric values are the ones the industry quotes, which is why they
    are written out rather than converted — 152.0 mm is what a 6-inch blank is
    called, not 152.4.
    """
    return SubstratePreset(
        key=f"mask_{code}",
        section="mask",
        label=f"Mask blank {code} — {side_mm:.1f} mm square, {thickness_mm:.2f} mm",
        form_factor=MASK,
        material=FUSED_SILICA,
        thickness_mm=thickness_mm,
        side_mm=side_mm,
        domain=_MASK_DOMAIN,
    )


def _wafer(
    key: str, material: MaterialId, diameter_mm: float, thickness_mm: float, name: str
) -> SubstratePreset:
    return SubstratePreset(
        key=key,
        section="wafer",
        label=f"{name} wafer — {diameter_mm:.1f} mm, {thickness_mm:.3f} mm",
        form_factor=WAFER,
        material=material,
        thickness_mm=thickness_mm,
        diameter_mm=diameter_mm,
    )


SUBSTRATE_PRESETS: tuple[SubstratePreset, ...] = tuple(
    sorted(
        (
            _wafer("wafer_si_50", SILICON, 50.8, 0.279, "Silicon 2\""),
            _wafer("wafer_si_76", SILICON, 76.2, 0.375, "Silicon 3\""),
            _wafer("wafer_si_100", SILICON, 100.0, 0.525, "Silicon 4\""),
            _wafer("wafer_si_150", SILICON, 150.0, 0.675, "Silicon 6\""),
            _wafer("wafer_si_200", SILICON, 200.0, 0.725, "Silicon 8\""),
            _wafer("wafer_fs_50", FUSED_SILICA, 50.8, 0.500, "Fused silica 2\""),
            _wafer("wafer_fs_100", FUSED_SILICA, 100.0, 1.000, "Fused silica 4\""),
            _wafer("wafer_fs_150", FUSED_SILICA, 150.0, 1.000, "Fused silica 6\""),
            _mask("5006", 126.6, 1.52),
            _mask("5009", 126.6, 2.30),
            _mask("5018", 126.6, 4.60),
            _mask("6009", 152.0, 2.30),
            _mask("6012", 152.0, 3.05),
            _mask("6025", 152.0, 6.35),
            _mask("9012", 228.6, 3.05),
            _mask("9020", 228.6, 5.00),
            _mask("9025", 228.6, 6.35),
        ),
        key=lambda preset: preset.sort_key,
    )
)
"""The semi-standard list, sorted as E3 asks: by material, then size, then thickness.

Sorted once here rather than in the widget, so the dropdown, a recipe file and a
test all see the same order — and so "which is the default" is a fact about the
table rather than about whichever list happened to be built first.
"""

DEFAULT_PRESET = "wafer_fs_100"
"""E3's default: round, 100 mm, 1 mm, fused silica."""

PRESETS_BY_KEY = {preset.key: preset for preset in SUBSTRATE_PRESETS}


def presets_by_section() -> dict[str, tuple[SubstratePreset, ...]]:
    """`{"wafer": (...), "mask": (...)}` in E3's order — what the dropdown renders."""
    sections: dict[str, list[SubstratePreset]] = {}
    for preset in SUBSTRATE_PRESETS:
        sections.setdefault(preset.section, []).append(preset)
    return {section: tuple(entries) for section, entries in sections.items()}


@dataclass(frozen=True)
class SubstrateSpec:
    """What the substrate *is*, in nm — the metadata half of this module.

    Distinct from the preset: a preset is an entry in a list, a spec is the answer
    somebody gave, whether they took it from the list or typed it.
    """

    material: MaterialId = SILICON
    form_factor: str = WAFER
    thickness: float | None = None
    diameter: float | None = None
    size_x: float | None = None
    size_y: float | None = None
    surface_finish: str = POLISHED
    preset: str = ""

    def __post_init__(self) -> None:
        if self.form_factor not in FORM_FACTORS:
            raise ValueError(
                f"form factor must be one of {FORM_FACTORS}, got {self.form_factor!r}"
            )
        if self.surface_finish not in SURFACE_FINISHES:
            raise ValueError(
                f"surface finish must be one of {SURFACE_FINISHES}, got {self.surface_finish!r}"
            )
        if self.form_factor == SEMI_INFINITE and self.thickness is not None:
            raise ValueError(
                "a semi-infinite substrate has no thickness; that is what the form "
                "factor encodes (roadmap E1)"
            )
        if self.thickness is not None and self.thickness <= 0.0:
            raise ValueError(f"substrate thickness must be positive, got {self.thickness}")

    @classmethod
    def from_preset(cls, key: str) -> "SubstrateSpec":
        """The spec one entry of `SUBSTRATE_PRESETS` describes, in nm."""
        try:
            preset = PRESETS_BY_KEY[key]
        except KeyError:
            raise ValueError(
                f"no substrate preset {key!r}; the list has {sorted(PRESETS_BY_KEY)}"
            ) from None
        return cls(
            material=preset.material,
            form_factor=preset.form_factor,
            thickness=preset.thickness_mm * MM,
            diameter=None if preset.diameter_mm is None else preset.diameter_mm * MM,
            size_x=None if preset.side_mm is None else preset.side_mm * MM,
            size_y=None if preset.side_mm is None else preset.side_mm * MM,
            preset=preset.key,
        )

    def metadata(self, surface: float) -> dict[str, float | str]:
        """This spec as `Structure.metadata`, with where its surface was placed.

        A `None` becomes an **absent key** rather than a stored null: "nobody said"
        and "it is zero" are different statements, and the through-etch check
        depends on being able to tell them apart.
        """
        values: dict[str, float | str] = {
            MATERIAL_KEY: str(self.material),
            FORM_FACTOR_KEY: self.form_factor,
            FINISH_KEY: self.surface_finish,
            SURFACE_KEY: float(surface),
        }
        for key, value in (
            (THICKNESS_KEY, self.thickness),
            (DIAMETER_KEY, self.diameter),
            (SIZE_X_KEY, self.size_x),
            (SIZE_Y_KEY, self.size_y),
        ):
            if value is not None:
                values[key] = float(value)
        if self.preset:
            values[PRESET_KEY] = self.preset
        return values

    def describe(self) -> str:
        """One line for the run log."""
        if self.form_factor == SEMI_INFINITE:
            size = "semi-infinite"
        elif self.diameter is not None:
            size = f"{self.diameter / MM:.1f} mm round"
        elif self.size_x is not None:
            other = self.size_y if self.size_y is not None else self.size_x
            size = f"{self.size_x / MM:.1f} x {other / MM:.1f} mm"
        else:
            size = "unstated size"
        thick = "" if self.thickness is None else f", {self.thickness / MM:.3f} mm thick"
        return f"{self.material} {self.form_factor}, {size}{thick}, {self.surface_finish}"


def cross_section_grid(
    *, width: float, thickness: float, headroom: float, spacing: float = 1.0
) -> Grid:
    """A 2D cross-section domain: substrate `thickness` below, `headroom` above.

    The surface sits at `y = thickness`, so a stack builds upward from a round
    number and the headroom is exactly what is left. `spacing` is the visible
    model parameter of plan §3.1 — the realism/speed trade — and the default is
    the plan's 1 nm.

    `thickness` here is **how much substrate to draw**, not how thick the wafer
    is. Since M7 those are different numbers (see the module docstring): the
    drawn depth is a window that `kernel.domain` grows as an etch needs it, and
    the real thickness is metadata that decides when to stop.

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
    grid: Grid,
    material: MaterialId = SILICON,
    *,
    surface: float,
    spec: SubstrateSpec | None = None,
) -> Structure:
    """A blanket wafer filling everything below `surface` (plan §4.1).

    A half-space, which is the one primitive that is *exactly* representable on
    the grid — a linear function, sampled exactly, with bilinear reconstruction
    exact between the samples. Every measurement in the acceptance scenarios is
    taken against this surface, so it being exact is what makes the numbers mean
    the process rather than the constructor.

    `spec` is what the substrate *is* (M7); without one the structure carries no
    substrate metadata and the through-etch check does not apply, which is the
    same rule `semi_infinite` states explicitly.
    """
    normal = tuple(1.0 if axis == 0 else 0.0 for axis in range(grid.ndim))
    point = tuple(surface if axis == 0 else 0.0 for axis in range(grid.ndim))
    structure = ctor.add_material(
        Structure(grid), material, ctor.half_space(grid, normal=normal, point=point)
    )
    if spec is None:
        return structure
    return structure.with_metadata(**spec.metadata(surface))


# -- the through-etch check (roadmap E7) --------------------------------------


def etched_depth(structure: Structure) -> float | None:
    """How far below its original surface the substrate has been taken, in nm.

    `None` when the structure carries no substrate metadata — a hand-built scene,
    or a `semi_infinite` one — because "how deep have you gone into something
    nobody described" has no answer worth inventing.

    Measured per column as the top of the remaining substrate, taking the deepest:
    a trench is what eats through a wafer, and it is deeper than the field average
    by exactly the amount that matters. A column with no substrate left at all
    counts as etched to the bottom of the domain and beyond, which is right — the
    hole goes at least that far.
    """
    material = structure.meta(MATERIAL_KEY)
    surface = structure.meta(SURFACE_KEY)
    if material is None or surface is None or str(material) not in structure.phi:
        return None
    grid = structure.grid
    # `<= 0`, the same rule `Structure.solid_mask` follows: a cell exactly on the
    # zero level is solid. With a strict `<` a freshly placed wafer would read as
    # already one cell into its own etch.
    inside = structure.phi_of(MaterialId(str(material))) <= 0.0
    rows = np.arange(grid.shape[0]).reshape(-1, *([1] * (inside.ndim - 1)))
    highest = np.where(inside.any(axis=0), np.max(np.where(inside, rows, -1), axis=0), -1)
    tops = grid.origin[0] + grid.spacing * highest.astype(np.float64)
    return float(surface) - float(np.min(tops))


def through_etched(structure: Structure) -> str | None:
    """The sentence to fail with when the substrate has been etched through (E7).

    `None` when it has not been, or when nobody stated a thickness — which is
    what `semi_infinite` is for, and why it is a form factor rather than a
    missing value somebody has to remember to check.

    Backlog B2 turns this around: a hole through the wafer opens to the back side
    and becomes a via rather than an error. The thickness being real data from the
    first commit is what makes that a change of behaviour instead of a change of
    schema.
    """
    thickness = structure.meta(THICKNESS_KEY)
    if thickness is None:
        return None
    depth = etched_depth(structure)
    if depth is None or depth <= float(thickness):
        return None
    return (
        f"the substrate is etched through: {_length(depth)} of a "
        f"{_length(float(thickness))} {structure.meta(FORM_FACTOR_KEY, 'substrate')}"
    )


def _length(nanometres: float) -> str:
    """A length in the unit somebody would say it in — nm, µm or mm.

    Because "0.0001 mm of a 0.0001 mm chip" is a true sentence that tells nobody
    anything, and this one is read off a failure message.
    """
    if abs(nanometres) < 1_000.0:
        return f"{nanometres:.1f} nm"
    if abs(nanometres) < MM:
        return f"{nanometres / 1_000.0:.2f} um"
    return f"{nanometres / MM:.3f} mm"


# -- the step -----------------------------------------------------------------


def _spec_from_params(ctx: StepContext) -> tuple[SubstrateSpec, MaterialId]:
    """The spec a recipe's parameters describe, preset first and overrides after."""
    preset = str(ctx["preset"]).strip()
    spec = SubstrateSpec.from_preset(preset) if preset else SubstrateSpec()

    # Empty means "whatever the preset says", for the same reason `thickness=0`
    # does: a parameter whose default is a real value cannot say "I did not
    # choose", so a preset would be overridden by a field nobody touched.
    material = str(ctx["material"]).strip()
    form_factor = str(ctx["form_factor"]).strip()
    changes: dict[str, object] = {}
    if material:
        changes["material"] = MaterialId(material)
    if form_factor:
        changes["form_factor"] = form_factor
    for name, key in (
        ("thickness", "thickness"),
        ("diameter", "diameter"),
        ("size_x", "size_x"),
        ("size_y", "size_y"),
    ):
        value = float(ctx[key])
        if value > 0.0:
            changes[name] = value * MM
    changes["surface_finish"] = str(ctx["surface_finish"])
    if changes.get("form_factor", spec.form_factor) == SEMI_INFINITE:
        changes["thickness"] = None
    spec = SubstrateSpec(
        material=changes.get("material", spec.material),  # type: ignore[arg-type]
        form_factor=str(changes.get("form_factor", spec.form_factor)),
        thickness=changes.get("thickness", spec.thickness),  # type: ignore[arg-type]
        diameter=changes.get("diameter", spec.diameter),  # type: ignore[arg-type]
        size_x=changes.get("size_x", spec.size_x),  # type: ignore[arg-type]
        size_y=changes.get("size_y", spec.size_y),  # type: ignore[arg-type]
        surface_finish=str(changes["surface_finish"]),
        preset=spec.preset,
    )
    return spec, spec.material


def _grid_for(ctx: StepContext, spec: SubstrateSpec) -> Grid:
    """The domain to build the substrate in — E2, and the reason it is not silent.

    The grid the step was handed, unless the recipe asked for a different one.
    A preset *suggests* a cross-section and the suggestion is applied when the
    recipe names the preset and does not override the domain itself; a recipe
    with no preset keeps the domain it came with, which is what every chain
    written before M7 does.
    """
    given = ctx.structure.grid
    width = float(ctx["domain_width"])
    headroom = float(ctx["headroom"])
    spacing = float(ctx["spacing"])
    suggestion = PRESETS_BY_KEY[spec.preset].domain if spec.preset else None
    if suggestion is None and not (width or headroom or spacing):
        return given
    if suggestion is not None:
        width = width or suggestion.width
        headroom = headroom or suggestion.headroom
        spacing = spacing or suggestion.spacing
    spacing = spacing or given.spacing
    width = width or (given.shape[-1] - 1) * given.spacing
    surface = float(ctx["surface"])
    headroom = headroom or max(
        given.spacing, (given.shape[0] - 1) * given.spacing - surface
    )
    return cross_section_grid(
        width=width, thickness=max(surface, spacing), headroom=headroom, spacing=spacing
    )


def _run_select(ctx: StepContext) -> StepResult:
    spec, material = _spec_from_params(ctx)
    grid = _grid_for(ctx, spec)
    surface = float(ctx["surface"])
    structure = select_substrate(grid, material, surface=surface, spec=spec)
    measurements = {"surface": Quantity(surface, "nm")}
    if spec.thickness is not None:
        measurements["thickness"] = Quantity(spec.thickness / MM, "mm")
    return StepResult(
        structure=structure,
        provides=frozenset({capability.of_material(material), capability.DOMAIN}),
        measurements=measurements,
        logs=(
            f"substrate {spec.describe()}; surface at {surface:.1f} nm in a "
            f"{(grid.shape[0] - 1) * grid.spacing:.0f} x "
            f"{(grid.shape[-1] - 1) * grid.spacing:.0f} nm domain at {grid.spacing:g} nm/cell",
        ),
    )


SELECT_SUBSTRATE = FunctionStep(
    step_id="substrate.select",
    display_name="Select substrate",
    fidelity=IDEAL,
    schema=(
        ParamSpec(
            "preset",
            str,
            default="",
            description=(
                "Semi-standard substrate. Empty means 'none — use the fields below and "
                "keep the domain this recipe was built with'."
            ),
        ),
        ParamSpec(
            "material",
            str,
            default="",
            # E22: what a sample is *built on*. Resists and contaminants are
            # things that arrive on a substrate, never one.
            material=MaterialFilter(
                tags=("semiconductor", "oxide", "metal_oxide", "dielectric", "metal"),
                what="substrate materials",
            ),
            description="Wafer material; empty takes the preset's, or silicon without one",
        ),
        ParamSpec(
            "form_factor",
            str,
            default="",
            choices=("",) + FORM_FACTORS,
            description=(
                "Shape the substrate is quoted as; empty takes the preset's. "
                "'semi_infinite' means the thickness does not matter here, and "
                "switches off the through-etch check."
            ),
        ),
        ParamSpec(
            "surface",
            float,
            unit="nm",
            default=None,
            minimum=0.0,
            description="Height of the wafer surface in the domain",
        ),
        ParamSpec(
            "thickness",
            float,
            unit="mm",
            default=0.0,
            minimum=0.0,
            description=(
                "Real substrate thickness. Metadata, not domain depth: it is known, not "
                "drawn (roadmap §1). 0 takes the preset's, or leaves it unstated."
            ),
        ),
        ParamSpec("diameter", float, unit="mm", default=0.0, minimum=0.0,
                  description="Diameter of a round substrate; 0 takes the preset's"),
        ParamSpec("size_x", float, unit="mm", default=0.0, minimum=0.0,
                  description="Side length of a square or rectangular substrate"),
        ParamSpec("size_y", float, unit="mm", default=0.0, minimum=0.0,
                  description="The other side length; 0 makes it square"),
        ParamSpec("surface_finish", str, default=POLISHED, choices=SURFACE_FINISHES,
                  description="Recorded on the sample; no process reads it yet"),
        ParamSpec("domain_width", float, unit="nm", default=0.0, minimum=0.0,
                  description="Width of the cross-section; 0 takes the preset's"),
        ParamSpec("headroom", float, unit="nm", default=0.0, minimum=0.0,
                  description="Empty space above the surface; 0 takes the preset's"),
        ParamSpec("spacing", float, unit="nm", default=0.0, minimum=0.0,
                  description="Cell size — the realism/speed trade of plan §3.1"),
    ),
    required=frozenset(),
    provided=frozenset({capability.DOMAIN}),
    run_function=_run_select,
    description=(
        "Places the wafer and makes the domain. Always the first step of a chain: before it "
        "there is no grid and no geometry at all, so nothing else has anything to act on."
        "\n\n"
        "The substrate and the domain are two different sizes, and this is where they part. "
        "`preset` picks a semi-standard wafer or mask blank and fills in the rest. "
        "`form_factor`, `material`, `thickness`, `diameter` and `size_x`/`size_y` are the "
        "substrate as it really is, in millimetres — kept as metadata rather than drawn, "
        "because a 525 um wafer at 1 nm per cell would be gigabytes a revision. `surface`, "
        "`domain_width`, `headroom` and `spacing` are the nanometre-scale cross-section you "
        "actually see: a window that follows the sample as later steps move it."
        "\n\n"
        "`thickness` is what decides when an etch has gone through the wafer. Set `form_factor` "
        "to `semi_infinite` when the thickness does not matter, and no such check is made."
        "\n\n"
        "Needs: nothing. It is what everything else needs."
    ),
)
"""Place the wafer and make the domain. Requires nothing — it is where a chain starts.

It is the only step that provides `capability.DOMAIN`, which is what roadmap E4's
"the substrate must be step #0" is enforced with: before it there is no geometry
at all, so `ProcessRegistry.blocked_reason` has a sentence to say rather than a
later step quietly doing nothing to an empty domain.
"""
