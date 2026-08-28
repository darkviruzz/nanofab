"""`MaterialType` library entries and the `MaterialId` that keys them.

Plan `docs/plans/v2-structure-model.md` §3.4: a `MaterialType` is pure data — a
library entry with no geometry. A *material in a `Structure`* is nothing but a
`MaterialId` owning one signed-distance field and, optionally, material-scoped
`Field`s (ADR-0003: no other per-material state is stored).

What lives here, and why it is the thinnest module in the package that everything
else needs: **this is where a process stops being geometry**. `kernel.motion`
asks "how fast does the front move in this material" and `kernel.flux` asks "how
does this surface respond off normal incidence"; both questions are answered by a
number a material carries, not by anything the solver knows. Keeping those
numbers here is what lets one kernel serve a didactic scene and a calibrated one
(plan §1's fidelity tiers b and c) without a line of solver code changing.

**This module imports nothing from `nanofab_v3.kernel`.** `kernel.motion` imports
`MaterialId` from here, so the reverse import would be a cycle — and the reverse
import is tempting, because `SurfaceRates` and `flux.AngularYield` are exactly
the shapes these models have to produce. The seam is instead in
`nanofab_v3.processes.rates`, which is the layer whose job is composing the two
(plan §5.4: "duplication lives in thin process wrappers, physics lives once in
the kernel"). `SputterResponse` below is the two numbers `flux.SputterYield`
needs, held here where the *material* owns them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from types import MappingProxyType
from typing import Mapping, NewType

import numpy as np

MaterialId = NewType("MaterialId", str)
"""Key of one material inside a `Structure` (and of its `MaterialType`)."""

# -- process classes ---------------------------------------------------------
#
# The axis a material's rate table is keyed on. Not "which machine" — which
# *character* of process (`CONTEXT.md`'s process-character section), because that
# is what a rate actually depends on: a wet etchant and a developer are both
# isotropic chemistry, an ion beam and a sputter source are both momentum.

WET_ETCH = "wet_etch"
"""Isotropic chemical removal in a liquid — reachability-gated (plan §4.4)."""

DRY_ETCH = "dry_etch"
"""Plasma removal (RIE): a directional ion lobe plus a chemical component."""

ION_BEAM = "ion_beam"
"""Purely physical sputtering (IBE): momentum transfer, angle-dependent yield."""

DEPOSIT = "deposit"
"""Arrival of new material — the blanket rate on an open, normal-facing surface."""

DEVELOP = "develop"
"""Removal of exposed resist by a developer; see `DevelopModel` for the dose form."""

DISSOLVE = "dissolve"
"""Removal of a whole material by a solvent — strip, lift-off (see `DissolveModel`)."""

# The classes above are the *character* axis the didactic set of plan §6 is
# written against, and M6 left every one of their names and numbers alone: S1-S5
# and the whole test suite hang on them (roadmap §3, "additiv erweitern, nichts
# umbenennen").
#
# What M6 added is a second group, below. These are keyed on a *chemistry* rather
# than on a character, because that is what the student process table of roadmap
# §3 measures: the same RIE machine etches chromium 25x faster in chlorine than
# in fluorine, and one `dry_etch` number per material cannot say that. Their
# numbers come from that table and nowhere else, which is also why they are
# separate keys — mixing a measured rate and a didactic one under one name would
# make the library's own provenance unreadable (see `rate_notes`).

ICP_FLUORINE = "icp_fluorine"
"""ICP etching in fluorine chemistry — the table's row 2, and *directional*.

The direction is not in this number. The table distinguishes "horizontal =
vertical" from "vertical", and a rate here is a scalar by construction — "the
rate at which an open, normal-facing surface moves" (`rate_for` below) — so what
makes this one vertical is the narrow angular distribution the step gives the
flux model (plan §4.3), never a second rate.
"""

RIE_CHLORINE = "rie_chlorine"
"""RIE in chlorine chemistry — the table's row 3, isotropic (horizontal = vertical)."""

RIE_OXYGEN = "rie_oxygen"
"""RIE in oxygen — the table's row 4, isotropic. A resist strip: it attacks polymer."""

WET_ETCH_CR = "wet_etch_cr"
"""Chromium etchant (ceric ammonium nitrate) — the table's row 5, isotropic.

Separate from `WET_ETCH` for the reason the whole second group exists: a bath is
selective, and "the wet etch rate of chromium" is meaningless without naming the
bath. The table gives two baths, so there are two keys.
"""

WET_ETCH_OXIDE = "wet_etch_oxide"
"""Buffered oxide etch — the table's row 6, isotropic. Attacks SiO2 and, slowly, resist."""

SPUTTER_DEPOSIT = "sputter_deposit"
"""Sputter deposition at the table's rates — rows 7-9, one per target material.

A deposition rate sits on the material being *deposited* (it is a property of the
source), where an etch rate sits on the material being attacked. Both are the
same mapping, which is why the table needed no change to the schema.
"""

# -- what a material *is* ------------------------------------------------------
#
# Roadmap E21. Substance classes, never roles: chromium is a hard mask *and* a
# deposition material *and* something an ion beam etches, so a `mask` or
# `deposit` tag would be a second, competing truth about a thing the capabilities
# and the rate table already say. What a tag answers is the question a rate
# cannot — "is this a metal" — which is what an *ideal* step needs, because an
# ideal step reads no rate at all (E22).

METAL_TAG = "metal"
OXIDE_TAG = "oxide"
METAL_OXIDE_TAG = "metal_oxide"
DIELECTRIC_TAG = "dielectric"
SEMICONDUCTOR_TAG = "semiconductor"
RESIST_TAG = "resist"
CONTAMINATION_TAG = "contamination"

MATERIAL_TAGS = (
    METAL_TAG,
    OXIDE_TAG,
    METAL_OXIDE_TAG,
    DIELECTRIC_TAG,
    SEMICONDUCTOR_TAG,
    RESIST_TAG,
    CONTAMINATION_TAG,
)
"""Every substance class a `MaterialType` may claim. Closed, and validated.

Closed because an open vocabulary is a vocabulary with three spellings of
"dielectric" in it, and a dropdown filtered on `dielectrics` would then quietly
lose the file that said `Dielectric`. A new class is a decision, and a decision
has a place to be written down."""

PROCESS_CLASSES = (
    WET_ETCH,
    DRY_ETCH,
    ION_BEAM,
    DEPOSIT,
    DEVELOP,
    DISSOLVE,
    ICP_FLUORINE,
    RIE_CHLORINE,
    RIE_OXYGEN,
    WET_ETCH_CR,
    WET_ETCH_OXIDE,
    SPUTTER_DEPOSIT,
)
"""Every rate key a `MaterialType` understands, for validation and for the UI."""


# -- the small model objects a MaterialType carries ---------------------------


@dataclass(frozen=True)
class SputterResponse:
    """The material's own angle-dependent sputter yield, as two numbers.

    Yamamura's form, normalised to normal incidence (the same one
    `kernel.flux.SputterYield` evaluates):

        Y(theta)/Y(0) = cos^-rise(theta) * exp(-fall * (1/cos(theta) - 1))

    Held here rather than as a `flux.AngularYield` because *the material* is what
    decides how steeply its yield climbs off normal — a soft polymer facets
    differently from silicon under the same beam. `processes.rates.angular_yield`
    turns it into the kernel object; see this module's docstring for why the
    conversion is not done here.

    Attributes:
        rise: How steeply the yield climbs off normal incidence.
        fall: How quickly reflection wins near grazing. The peak sits at
            `cos(theta) = fall / rise`, i.e. 60 degrees for the default 1/2.
    """

    rise: float = 2.0
    fall: float = 1.0

    def __post_init__(self) -> None:
        if not (math.isfinite(self.rise) and self.rise > 0.0):
            raise ValueError(f"rise must be a positive finite number, got {self.rise}")
        if not (math.isfinite(self.fall) and self.fall >= 0.0):
            raise ValueError(f"fall must be a non-negative finite number, got {self.fall}")


@dataclass(frozen=True)
class DevelopModel:
    """`develop_rate(dose)` — the resist's dissolution rate in the developer.

    The plan's ideal/physical split (§3.3) is a split in *this* object's presence:
    ideal development consumes the `exposed` field and never asks a rate, while
    physical development advects the front at `develop_rate(dose)`. Both act on
    the same `Structure`; only the field they read and the tier they run at
    differ.

    A didactic contrast curve rather than a calibrated one (plan §1, tier a): the
    rate rises from `dark_rate` to `clear_rate` as the dose approaches
    `clearing_dose`, with `contrast` deciding how sharp the transition is. A large
    `contrast` is a high-gamma resist and approaches the ideal-tier step function,
    which is the honest statement of what the ideal tier is: this model with
    infinite contrast.

    Attributes:
        clearing_dose: Dose at which the resist develops at `clear_rate`, in
            mJ/cm^2 (`Dose to clear`, `D_0`).
        clear_rate: Development rate at and above the clearing dose, in nm/s.
        dark_rate: Rate in wholly unexposed resist, in nm/s — the finite
            selectivity every real developer has, and what thins an unexposed
            film during a long develop.
        contrast: Exponent of the normalised dose; the resist's gamma.
        tone: `"positive"` (exposure makes it soluble) or `"negative"`.
    """

    clearing_dose: float = 100.0
    clear_rate: float = 20.0
    dark_rate: float = 0.05
    contrast: float = 4.0
    tone: str = "positive"

    def __post_init__(self) -> None:
        if not (math.isfinite(self.clearing_dose) and self.clearing_dose > 0.0):
            raise ValueError(f"clearing_dose must be positive, got {self.clearing_dose}")
        if self.clear_rate < 0.0 or self.dark_rate < 0.0:
            raise ValueError("develop rates must be non-negative")
        if not (math.isfinite(self.contrast) and self.contrast > 0.0):
            raise ValueError(f"contrast must be positive, got {self.contrast}")
        if self.tone not in ("positive", "negative"):
            raise ValueError(f"tone must be 'positive' or 'negative', got {self.tone!r}")

    def rate(self, dose: np.ndarray | float) -> np.ndarray:
        """Development rate in nm/s for a dose field, elementwise.

        Returns an array even for a scalar dose, because every caller in the
        kernel wants a per-cell rate map and a scalar would silently broadcast
        into one anyway.
        """
        normalised = np.clip(
            np.asarray(dose, dtype=np.float64) / float(self.clearing_dose), 0.0, 1.0
        )
        if self.tone == "negative":
            normalised = 1.0 - normalised
        soluble = normalised ** float(self.contrast)
        return float(self.dark_rate) + (float(self.clear_rate) - float(self.dark_rate)) * soluble

    @property
    def bound(self) -> float:
        """The largest rate this model can produce, in nm/s — the CFL input."""
        return max(float(self.clear_rate), float(self.dark_rate))


@dataclass(frozen=True)
class DissolveModel:
    """How a solvent takes this material apart (plan §6, strip / dissolve).

    Two tiers again, and the same object serves both: the ideal tier asks only
    `dissolves_in`, and removes every *reachable* occurrence in one set operation;
    the rate tier advects the front at `rate` behind the same reachability gate.
    Insolubility is expressed by simply not carrying a `DissolveModel`, not by a
    zero rate — "the solvent does not attack this" and "it attacks it slowly" are
    different statements and a lift-off depends on the difference.

    Attributes:
        solvent: Name of the bath this material dissolves in, e.g. `"acetone"`.
            A material dissolves in exactly one named solvent here; a second bath
            is a second library entry, which is the didactic simplification this
            tier is allowed (plan §1).
        rate: Surface recession in the solvent, in nm/s, for the rate tier.
        swells: Whether the material takes up solvent and lifts mechanically —
            recorded because it is the physical reason a real lift-off works
            through cracks far too small for the plan's reachability query, and
            deliberately *not* modelled (see plan §16).
    """

    solvent: str = "acetone"
    rate: float = 50.0
    swells: bool = False

    def __post_init__(self) -> None:
        if not str(self.solvent).strip():
            raise ValueError("solvent must be a non-empty string")
        if not (math.isfinite(self.rate) and self.rate >= 0.0):
            raise ValueError(f"dissolve rate must be non-negative, got {self.rate}")


@dataclass(frozen=True)
class HardBakeModel:
    """Material identity and threshold produced by a hard bake (roadmap E31)."""

    target: MaterialId
    activation_temperature: float

    def __post_init__(self) -> None:
        target = MaterialId(str(self.target).strip())
        if not target:
            raise ValueError("hard-bake target must be a non-empty material id")
        temperature = float(self.activation_temperature)
        if not math.isfinite(temperature) or temperature < -273.15:
            raise ValueError(
                "hard-bake activation_temperature must be finite and at or above "
                f"absolute zero, got {self.activation_temperature}"
            )
        object.__setattr__(self, "target", target)
        object.__setattr__(self, "activation_temperature", temperature)


@dataclass(frozen=True)
class SpinCurve:
    """Film thickness over spin speed, as measured points — not a fitted law.

    Roadmap E17 and §3.1. The fourth submodel a `MaterialType` carries, in the
    same row as `develop`, `dissolve` and `sputter_response`, and here for the
    same reason E13 puts tone on the resist: **the thickness a resist spins to is
    a property of the resist**, at a speed the operator picks. It is not a
    property of the coating step, and it is not a rate — `rates` is keyed by
    process class and answers nm/s, and this answers nm at an rpm.

    **Interpolated, never fitted.** The classical `d ~ rpm^-1/2` does not carry
    the measured points: against the five in §3.1 it is +6.3 % at 2000 rpm and
    **-6.8 %** at 5000, so the error changes sign, and the effective exponent
    drifts from 0.588 to 0.456 because the curve flattens toward high speeds. A
    power law would claim 67 nm where 72 nm was measured. So the points are
    stored and the space between them is interpolated — **linearly in log-log**,
    which passes exactly through every measured point and gives each segment its
    own local exponent, which is the quantity §3.1 computed in the first place.

    **Outside the measured range it clamps rather than extrapolating**, and says
    so (`clamps`). A resist spun at 8000 rpm is outside what anybody measured;
    returning the 5000 rpm thickness is a statement the step can report, where an
    extrapolated number would be a fabrication with a plausible face.

    **There is no time axis, deliberately.** The table parameterises only the
    speed. That is physically reasonable — above some minimum time the thickness
    saturates — but it is an assumption, so a spin *time* is a documenting field
    on the step and does not enter the thickness. Backlog B11 has the rest: this
    curve is the generic `resist`'s, and named resists need their own.

    Attributes:
        points: `((rpm, nm), ...)`, strictly ascending in rpm. Pairs rather than
            two parallel lists so a file cannot drift into pairing a speed with
            the wrong thickness.
    """

    points: tuple[tuple[float, float], ...] = ()

    def __post_init__(self) -> None:
        try:
            points = tuple((float(speed), float(thickness)) for speed, thickness in self.points)
        except (TypeError, ValueError):
            raise ValueError(
                f"a spin curve is a sequence of (rpm, nm) pairs, got {self.points!r}"
            ) from None
        if len(points) < 2:
            raise ValueError("a spin curve needs at least two measured points")
        for speed, thickness in points:
            if not (math.isfinite(speed) and speed > 0.0):
                raise ValueError(f"spin speed must be a positive finite number, got {speed}")
            if not (math.isfinite(thickness) and thickness > 0.0):
                raise ValueError(
                    f"spun thickness must be a positive finite number, got {thickness}"
                )
        speeds = [speed for speed, _ in points]
        if speeds != sorted(set(speeds)):
            raise ValueError(f"spin curve speeds must be strictly ascending, got {speeds}")
        object.__setattr__(self, "points", points)

    @property
    def speed_range(self) -> tuple[float, float]:
        """`(slowest, fastest)` measured speed, in rpm — where the curve is a measurement."""
        return self.points[0][0], self.points[-1][0]

    def clamps(self, speed: float) -> bool:
        """Whether `speed` is outside the measured range, so the answer is a clamp."""
        low, high = self.speed_range
        return not (low <= float(speed) <= high)

    def thickness(self, speed: float) -> float:
        """Film thickness in nm at `speed` rpm; clamped outside the measured range.

        Exact at every measured point — checked before any arithmetic runs, so
        3000 rpm answers the stored 82.0 and not 82.00000000000001. A didactic
        tool whose quoted measurement comes back with a float tail invites the
        reader to wonder what else was computed.
        """
        low, high = self.speed_range
        rpm = min(max(float(speed), low), high)
        for measured, thickness in self.points:
            if rpm == measured:
                return thickness
        for (left, left_thickness), (right, right_thickness) in zip(self.points, self.points[1:]):
            if left < rpm < right:
                weight = (math.log(rpm) - math.log(left)) / (math.log(right) - math.log(left))
                return math.exp(
                    math.log(left_thickness)
                    + weight * (math.log(right_thickness) - math.log(left_thickness))
                )
        raise AssertionError(f"unreachable: {rpm} is inside {self.speed_range}")  # pragma: no cover


# -- the library entry --------------------------------------------------------


@dataclass(frozen=True)
class MaterialType:
    """A material library entry: identity, display data and models — never geometry.

    Attributes:
        material_id: Stable key, used as the `Structure.phi` key.
        name: Human-readable name for the UI.
        display_color: `#rrggbb` used by rendering (plan §10); not physics.
        rates: Blanket rate per process class, in nm/s — the rate an **open,
            normal-facing** surface of this material moves at. Every angular and
            visibility factor is the flux model's (plan §4.3's normalisation is
            what makes this sentence true), so these numbers stay comparable
            across techniques. A missing key means zero: a material nobody gave a
            rate to does not move, which is how a hard mask behaves without being
            modelled as one.
        sputter_response: Angle-dependent yield for the momentum-driven classes;
            `None` means the projected area and nothing else.
        develop: `develop_rate(dose)` — present on resists only.
        dissolve: Which solvent removes it, and how fast; `None` = insoluble.
        hard_bake: Target identity and activation temperature for a hard bake;
            `None` means no library-backed transition is known.
        spin_curve: Thickness over spin speed, measured (E17); `None` when nobody
            measured one, which excludes it from the didactic spin-coat step.
        density: g/cm^3, for later mass balances. Not read by the kernel.
        optical_n / optical_k: Refractive index and extinction coefficient at the
            exposure wavelength. `optical_k` is what a Beer-Lambert dose depth
            term needs (plan §6, "Exposure (dose)").
        absorption: Beer-Lambert absorption coefficient in 1/nm for the exposure
            wavelength, when it is known directly rather than through `optical_k`.
        notes: Where this entry as a whole came from, in one or two sentences —
            a measured table, a datasheet, or a number chosen so a scenario
            reads. Free text, never parsed.
        rate_notes: The same, per process class: `{process_class: why}`. This is
            where an **assumption** is recorded, and it is a field rather than a
            comment in the file because a comment is invisible to the program.
            The student table names "silicon oxide" for sputter etching and
            "fused silica" for the plasma chemistries, and this library carries
            both as separate materials; the value each one borrows from the other
            is marked here, so a UI can say "assumed" next to it and a reader of
            the file cannot miss it. Keys are validated against
            `PROCESS_CLASSES`, because a note attached to a misspelt class is a
            note nobody will ever see.
        tags: Substance classes from `MATERIAL_TAGS` (roadmap E21) — what this
            material *is*, never what it is for. Read by the material dropdowns
            of steps that consult no rate (E22): `resist.spin_coat_ideal` reads no
            spin curve, and chromium is still nonsense in it.
    """

    material_id: MaterialId
    name: str
    display_color: str = "#808080"
    rates: Mapping[str, float] = dataclass_field(default_factory=dict)
    sputter_response: SputterResponse | None = None
    develop: DevelopModel | None = None
    dissolve: DissolveModel | None = None
    hard_bake: HardBakeModel | None = None
    spin_curve: SpinCurve | None = None
    density: float | None = None
    optical_n: float | None = None
    optical_k: float | None = None
    absorption: float = 0.0
    notes: str = ""
    rate_notes: Mapping[str, str] = dataclass_field(default_factory=dict)
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not str(self.material_id).strip():
            raise ValueError("material_id must be a non-empty string")
        if not self.name.strip():
            raise ValueError("name must be a non-empty string")
        rates = {}
        for process_class, value in dict(self.rates).items():
            if process_class not in PROCESS_CLASSES:
                raise ValueError(
                    f"unknown process class {process_class!r} for material "
                    f"{self.material_id!r}; known classes are {PROCESS_CLASSES}"
                )
            rate = float(value)
            if not math.isfinite(rate) or rate < 0.0:
                raise ValueError(
                    f"rate {process_class}={value} of {self.material_id!r} must be "
                    "a non-negative finite number"
                )
            rates[process_class] = rate
        object.__setattr__(self, "rates", MappingProxyType(rates))
        notes = {}
        for process_class, note in dict(self.rate_notes).items():
            if process_class not in PROCESS_CLASSES:
                raise ValueError(
                    f"rate note for unknown process class {process_class!r} on material "
                    f"{self.material_id!r}; known classes are {PROCESS_CLASSES}"
                )
            notes[process_class] = str(note)
        object.__setattr__(self, "rate_notes", MappingProxyType(notes))
        if not math.isfinite(self.absorption) or self.absorption < 0.0:
            raise ValueError(f"absorption must be non-negative, got {self.absorption}")
        tags = []
        for tag in tuple(self.tags):
            if tag not in MATERIAL_TAGS:
                raise ValueError(
                    f"unknown tag {tag!r} on material {self.material_id!r}; "
                    f"the substance classes are {MATERIAL_TAGS}"
                )
            if tag not in tags:
                tags.append(tag)
        object.__setattr__(self, "tags", tuple(tags))

    # -- what the process layer asks ------------------------------------------

    def rate_for(self, process_class: str, default: float = 0.0) -> float:
        """Blanket rate in nm/s for one process class, `default` if unlisted."""
        if process_class not in PROCESS_CLASSES:
            raise ValueError(f"unknown process class {process_class!r}")
        return float(self.rates.get(process_class, default))

    def has_tag(self, *tags: str) -> bool:
        """Whether this material claims any of `tags` (roadmap E21)."""
        return bool(set(self.tags) & set(tags))

    def rate_note(self, process_class: str) -> str:
        """Where this material's rate for one class came from; `""` if unrecorded."""
        if process_class not in PROCESS_CLASSES:
            raise ValueError(f"unknown process class {process_class!r}")
        return str(self.rate_notes.get(process_class, ""))

    def develop_rate(self, dose: np.ndarray | float) -> np.ndarray:
        """`develop_rate(dose)` in nm/s (plan §3.4), zero without a develop model.

        Zero rather than an error: a developer bath contains whatever is in it,
        and a material with no develop model is simply one the developer does not
        attack. That is the same rule `rate_for` follows, and it is what lets a
        development step be handed the whole structure instead of a list of
        resists.
        """
        if self.develop is None:
            return np.zeros_like(np.asarray(dose, dtype=np.float64))
        return self.develop.rate(dose)

    def spin_thickness(self, speed: float) -> float:
        """Thickness in nm this material spins to at `speed` rpm (E17).

        Raises rather than guessing when the material has no curve: "how thick
        does an unmeasured resist spin" has no defensible answer, and a plausible
        one is the failure E15 and B11 both exist to prevent. The step catches
        this and says which file would fix it.
        """
        if self.spin_curve is None:
            raise ValueError(
                f"material {self.material_id!r} has no spin curve, so a spin speed does "
                "not determine a thickness for it"
            )
        return self.spin_curve.thickness(speed)

    def dissolves_in(self, solvent: str) -> bool:
        """Whether this material comes apart in the named bath."""
        return self.dissolve is not None and self.dissolve.solvent == solvent

    def dissolve_rate(self, solvent: str) -> float:
        """Surface recession in the named bath, in nm/s; 0.0 if it is inert there."""
        if not self.dissolves_in(solvent):
            return 0.0
        assert self.dissolve is not None
        return float(self.dissolve.rate)
