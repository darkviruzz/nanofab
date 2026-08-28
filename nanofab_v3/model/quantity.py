"""`Quantity` — a number with a unit, at the API boundary only (plan §3.1).

The kernel works in plain float nm and seconds for speed; `Quantity` appears
where a number leaves the solver and reaches a human: process parameters,
measurements, artifacts. It is carried over from v1 as a *concept* (plan §12),
not as code — v1's version dragged a conversion table nothing in the kernel is
allowed to consult.

Deliberately thin: no arithmetic, no unit algebra. A `Quantity` that could be
added to another `Quantity` would invite unit conversion into the model, and
converting is the API boundary's job, done once, where the unit is known.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Quantity:
    """One measured or specified number with the unit it was expressed in.

    Attributes:
        value: The number, in `unit`.
        unit: Unit string, e.g. `"nm"`, `"s"`, `"nm/s"`, `"mJ/cm^2"`. The empty
            string marks a dimensionless quantity (a ratio, a count).
    """

    value: float
    unit: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", float(self.value))
        if not math.isfinite(self.value):
            raise ValueError(f"quantity value must be finite, got {self.value}")

    def __str__(self) -> str:
        return f"{self.value:.6g} {self.unit}".strip()
