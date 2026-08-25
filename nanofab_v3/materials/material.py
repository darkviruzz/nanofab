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

PROCESS_CLASSES = (WET_ETCH, DRY_ETCH, ION_BEAM, DEPOSIT, DEVELOP, DISSOLVE)
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
        density: g/cm^3, for later mass balances. Not read by the kernel.
        optical_n / optical_k: Refractive index and extinction coefficient at the
            exposure wavelength. `optical_k` is what a Beer-Lambert dose depth
            term needs (plan §6, "Exposure (dose)").
        absorption: Beer-Lambert absorption coefficient in 1/nm for the exposure
            wavelength, when it is known directly rather than through `optical_k`.
    """

    material_id: MaterialId
    name: str
    display_color: str = "#808080"
    rates: Mapping[str, float] = dataclass_field(default_factory=dict)
    sputter_response: SputterResponse | None = None
    develop: DevelopModel | None = None
    dissolve: DissolveModel | None = None
    density: float | None = None
    optical_n: float | None = None
    optical_k: float | None = None
    absorption: float = 0.0

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
        if not math.isfinite(self.absorption) or self.absorption < 0.0:
            raise ValueError(f"absorption must be non-negative, got {self.absorption}")

    # -- what the process layer asks ------------------------------------------

    def rate_for(self, process_class: str, default: float = 0.0) -> float:
        """Blanket rate in nm/s for one process class, `default` if unlisted."""
        if process_class not in PROCESS_CLASSES:
            raise ValueError(f"unknown process class {process_class!r}")
        return float(self.rates.get(process_class, default))

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

    def dissolves_in(self, solvent: str) -> bool:
        """Whether this material comes apart in the named bath."""
        return self.dissolve is not None and self.dissolve.solvent == solvent

    def dissolve_rate(self, solvent: str) -> float:
        """Surface recession in the named bath, in nm/s; 0.0 if it is inert there."""
        if not self.dissolves_in(solvent):
            return 0.0
        assert self.dissolve is not None
        return float(self.dissolve.rate)
