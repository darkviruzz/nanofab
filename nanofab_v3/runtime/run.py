"""Recipes, runs and wafer positions (plan §8, ADR-0004).

A **Recipe** is the ordered sequence of steps and their parameters. A **Run** is
one recipe over an extensible set of wafer positions, default `{center}`, each
position owning an independent revision chain. Adding a position later replays
the chain from substrate selection with that position's parameters — which is
deterministic by plan §5.2, so the new position is exactly what it would have
been had it been there from the start.

## The invariant this module exists to keep

*The solver never sees a wafer position.* A recipe parameter may be a function
over the wafer — a rate radial profile, a bow-induced incidence-angle offset —
and `effective_params` resolves it **before** anything reaches `StepContext`. Past
that call a parameter is a plain number and the process cannot tell one position
from another. That is what ADR-0004 buys: the 2D solver stays a 2D solver, and
"which position" is a property of materialization rather than of the structure.

The one place a position legitimately reaches the kernel is the RNG seed
(`engine.step_seed`), and it reaches it as a seed rather than as a coordinate:
two positions get uncorrelated streams, and each gets the same stream every time.

## What a wafer-parameterised value is

Anything with `at(position)`. Two built-ins cover what plan §8 names — a radial
profile for rates, a linear tilt for bow — and both are pure, hashable and
fingerprintable, because a recipe whose hash cannot see a parameter change is a
cache that serves the wrong answer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any, Iterable, Iterator, Mapping, Protocol, Sequence, runtime_checkable

import numpy as np

from nanofab_v3.model.grid import Grid
from nanofab_v3.model.structure import Structure
from nanofab_v3.runtime.revision import CENTER, Revision

Position = tuple[float, float]
"""A wafer position in mm; `CENTER` is `(0.0, 0.0)` (interview decision I2)."""


@runtime_checkable
class WaferParameter(Protocol):
    """A recipe parameter that varies over the wafer (plan §8).

    Structural, like `ProcessStep`: anything that can answer `at(position)` and
    describe itself stably is one, so an interpolant from scipy or a lookup built
    by a plugin needs no base class.
    """

    def at(self, position: Position) -> Any:
        """This parameter's value at one wafer position."""

    def fingerprint(self) -> str:
        """A stable description, for the recipe hash the cache is keyed on."""


@dataclass(frozen=True)
class RadialProfile:
    """A value sampled at radii and linearly interpolated between them (plan §8).

    "A sampled list A, B, C is just data for the interpolant" — this is that
    interpolant. A deposition rate that falls off towards the wafer edge, an etch
    rate that peaks under the showerhead: both are this, and the solver receives
    one number.

    Attributes:
        radii: Radii in mm, ascending, from the wafer centre.
        values: The value at each radius. Outside the sampled range the nearest
            end is held — extrapolating a measured profile invents data.
    """

    radii: tuple[float, ...]
    values: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.radii) != len(self.values):
            raise ValueError("a radial profile needs one value per radius")
        if not self.radii:
            raise ValueError("a radial profile needs at least one sample")
        if list(self.radii) != sorted(self.radii):
            raise ValueError("radii must ascend")

    def at(self, position: Position) -> float:
        radius = math.hypot(position[0], position[1])
        return float(np.interp(radius, self.radii, self.values))

    def fingerprint(self) -> str:
        return f"radial({list(self.radii)!r},{list(self.values)!r})"


@dataclass(frozen=True)
class LinearTilt:
    """A value with a linear gradient across the wafer (plan §8's bow/tilt).

    Wafer bow appears in the model as a per-position incidence-angle offset, and
    that is all this is: a nominal value at the centre plus a gradient per mm
    along each wafer axis.

    Attributes:
        center: The value at `(0, 0)`.
        gradient: Change per mm along the two wafer axes.
    """

    center: float
    gradient: tuple[float, float] = (0.0, 0.0)

    def at(self, position: Position) -> float:
        return float(
            self.center + self.gradient[0] * position[0] + self.gradient[1] * position[1]
        )

    def fingerprint(self) -> str:
        return f"tilt({self.center!r},{self.gradient!r})"


@dataclass(frozen=True)
class RecipeStep:
    """One entry of a recipe: which process, with which parameters.

    The parameters are the recipe's, not the solver's: a value here may be a
    `WaferParameter`, and `resolve` is what turns it into the plain number a
    `StepContext` is allowed to carry.

    Attributes:
        step_id: Which registered process to run.
        params: Parameter values, possibly varying over the wafer.
    """

    step_id: str
    params: Mapping[str, Any] = dataclass_field(default_factory=dict)

    def resolve(self, position: Position = CENTER) -> dict[str, Any]:
        """This step's parameters at one wafer position — plan §8's resolution."""
        return {
            name: value.at(position) if isinstance(value, WaferParameter) else value
            for name, value in self.params.items()
        }

    def fingerprint(self) -> str:
        """A stable description of step and parameters, for the recipe hash.

        Deliberately not `repr(self)`: a `WaferParameter` describes itself, so two
        equal profiles built separately hash the same, and a changed profile
        changes the hash. A cache key that could not see a parameter change would
        serve one recipe's answer for another.
        """
        parts = []
        for name in sorted(self.params):
            value = self.params[name]
            shown = value.fingerprint() if isinstance(value, WaferParameter) else repr(value)
            parts.append(f"{name}={shown}")
        return f"{self.step_id}({','.join(parts)})"


@dataclass(frozen=True)
class Recipe:
    """An ordered sequence of steps over one domain (`CONTEXT.md`: *Recipe*).

    Attributes:
        grid: The domain every position's chain is run on. Resolution is a
            visible model parameter (plan §3.1), so it belongs to the recipe and
            not to a default somewhere.
        steps: The steps, in order.
        recipe_id: Stable name. It seeds the RNG together with the position and
            the step index (plan §5.2), so **changing it changes the sample** of
            anything stochastic — it is an identity, not a label.
    """

    grid: Grid
    steps: tuple[RecipeStep, ...] = ()
    recipe_id: str = "recipe"

    def __post_init__(self) -> None:
        object.__setattr__(self, "steps", tuple(self.steps))

    def __len__(self) -> int:
        return len(self.steps)

    def __iter__(self) -> Iterator[RecipeStep]:
        return iter(self.steps)

    def __getitem__(self, index: int) -> RecipeStep:
        return self.steps[index]

    def with_step(self, step: RecipeStep) -> "Recipe":
        """A new recipe with one more step at the end."""
        return Recipe(self.grid, self.steps + (step,), self.recipe_id)

    def fingerprint(self) -> str:
        """A stable description of the whole recipe, for the cache key."""
        grid = f"{self.grid.origin}{self.grid.spacing}{self.grid.shape}{self.grid.axes}"
        return "|".join([self.recipe_id, grid] + [step.fingerprint() for step in self.steps])

    def initial(self) -> Structure:
        """The empty `Structure` a chain starts from — the domain before anything."""
        return Structure(self.grid)


def effective_params(
    recipe: Recipe, position: Position, step: int | RecipeStep
) -> dict[str, Any]:
    """Plan §8's resolution: one step's parameters at one wafer position.

    The seam ADR-0004 is built on. Everything upstream of this call may vary over
    the wafer; nothing downstream of it may. `step` is the index the cache key
    uses, or the `RecipeStep` itself when the caller already has it.
    """
    entry = recipe[step] if isinstance(step, int) else step
    return entry.resolve(position)


class ReplayStore(Protocol):
    """The persistent cache of plan §8, seen from the runtime.

    Declared here rather than imported from `io` so the dependency runs one way:
    `io` knows about revisions, `runtime` does not know about files.
    `io.store.ReplayCache` satisfies this structurally.
    """

    def get(self, position: Position, index: int) -> Revision | None:
        """The cached revision for one (position, step), or `None`."""

    def put(self, position: Position, revision: Revision) -> None:
        """Cache one revision under its position and index."""

    def for_position(self, position: Position) -> Any:
        """A per-position view shaped as a `RevisionStore`."""


def positions_on_radius(radius: float, count: int, *, start: float = 0.0) -> tuple[Position, ...]:
    """`count` positions evenly spaced on a circle — a wafer map's usual fan.

    Convenience for plan §8's "extensible set of positions", and deterministic:
    the same arguments give the same tuple in the same order, so a run over them
    caches and compares.
    """
    if count < 1:
        raise ValueError("a position fan needs at least one position")
    angles = [start + 2.0 * math.pi * i / count for i in range(count)]
    return tuple(
        (round(radius * math.cos(a), 9), round(radius * math.sin(a), 9)) for a in angles
    )


def as_positions(positions: Iterable[Sequence[float]] | None) -> tuple[Position, ...]:
    """Normalise whatever a caller offered into wafer positions, deduplicated."""
    if positions is None:
        return (CENTER,)
    seen: list[Position] = []
    for entry in positions:
        point = (float(entry[0]), float(entry[1]))
        if point not in seen:
            seen.append(point)
    return tuple(seen) or (CENTER,)
