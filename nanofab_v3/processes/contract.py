"""The process contract: what every step is, and what it promises (plan §5.1-§5.3).

Interview decision I7: *every process is a standalone function
`Structure -> Structure (+ outputs)`; processes share kernel primitives; several
processes may model the same technique at different fidelity.* This module is the
typed envelope around that sentence, and the shape of the envelope is what makes
the last clause work — two steps can wrap the same kernel call, declare different
fidelities and different capabilities, and the engine tells them apart without
either knowing the other exists.

Three parts:

- **`ParamSpec`** — a typed, united parameter, validated at the boundary. Plan
  §3.1's rule that the kernel works in plain floats is enforced here: a `Quantity`
  never reaches the solver, a validated float does.
- **`StepContext` / `StepResult`** — what a step is handed and what it hands back.
  The context carries the *already resolved* local parameters for one wafer
  position (§8), so the solver stays position-blind, and a seeded RNG, which is
  the determinism invariant of §5.2 and ADR-0004.
- **`ProcessStep`** — the protocol itself, structural rather than a base class so
  a plugin never has to import a class from here to be a step.

What is deliberately **not** here: the revision chain. A step consumes a
`Structure` and produces one; the append-only `Revision` with its history and
artifacts is milestone M4 (plan §3.6). `processes.engine` is the thin runner that
carries a step through the commit gate in the meantime.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

import numpy as np

from nanofab_v3.materials import MaterialLibrary
from nanofab_v3.model.field import FieldSpec
from nanofab_v3.model.quantity import Quantity
from nanofab_v3.model.structure import Structure

IDEAL = "ideal"
"""Fidelity tier: exact set operations, no rate and no time (plan §3.3)."""

DIDACTIC = "didactic"
"""Fidelity tier: rate- and flux-driven, qualitatively right (plan §1, tier a)."""

PHYSICAL = "physical"
"""Fidelity tier: a calibrated rate model — reachable by swapping models (tier b)."""

FIDELITIES = (IDEAL, DIDACTIC, PHYSICAL)


class ParameterError(ValueError):
    """A step parameter is missing, of the wrong type, or out of range."""


class CapabilityError(RuntimeError):
    """A step was run against a revision that does not satisfy its `requires`."""


@dataclass(frozen=True)
class ParamSpec:
    """One typed process parameter, with its unit and its admissible range.

    Carried over from v1's `step_api` as a concept (plan §12) and narrowed: a
    parameter has exactly one type, and a range that is checked rather than
    documented. The unit is a string because the kernel does not convert — a
    number arriving in the wrong unit is a recipe bug, not a conversion the model
    should silently perform (plan §3.1).

    Attributes:
        name: Keyword the step reads it under.
        kind: `float`, `int`, `str` or `bool`.
        unit: Unit the value is expressed in; `""` for dimensionless.
        default: Value used when the recipe does not set it; `None` makes the
            parameter required.
        minimum / maximum: Inclusive bounds for the numeric kinds.
        choices: Admissible values, for the enumerated ones.
        description: What it means, for the UI.
    """

    name: str
    kind: type = float
    unit: str = ""
    default: Any = None
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[Any, ...] | None = None
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("parameter name must be a non-empty string")
        if self.kind not in (float, int, str, bool):
            raise ValueError(f"unsupported parameter kind {self.kind!r}")

    @property
    def required(self) -> bool:
        """Whether a recipe has to supply this parameter."""
        return self.default is None

    def validate(self, value: Any) -> Any:
        """Coerce and range-check one value, or raise `ParameterError`.

        A `Quantity` is accepted and unwrapped **only if its unit matches**: that
        is the API boundary plan §3.1 asks for, and the one place where a unit is
        ever compared. Past it the value is a plain float.
        """
        if isinstance(value, Quantity):
            if value.unit != self.unit:
                raise ParameterError(
                    f"{self.name}: expected a quantity in {self.unit!r}, got {value.unit!r}"
                )
            value = value.value
        if self.kind is bool:
            if not isinstance(value, (bool, np.bool_)):
                raise ParameterError(f"{self.name}: expected a bool, got {value!r}")
            return bool(value)
        if self.kind is str:
            if not isinstance(value, str):
                raise ParameterError(f"{self.name}: expected a string, got {value!r}")
            coerced: Any = value
        else:
            if isinstance(value, bool):
                raise ParameterError(f"{self.name}: expected a number, got {value!r}")
            try:
                coerced = self.kind(value)
            except (TypeError, ValueError):
                raise ParameterError(
                    f"{self.name}: expected {self.kind.__name__}, got {value!r}"
                ) from None
            if not math.isfinite(float(coerced)):
                raise ParameterError(f"{self.name}: must be finite, got {value!r}")
            if self.minimum is not None and float(coerced) < self.minimum:
                raise ParameterError(
                    f"{self.name}: {coerced} {self.unit} is below the minimum {self.minimum}"
                )
            if self.maximum is not None and float(coerced) > self.maximum:
                raise ParameterError(
                    f"{self.name}: {coerced} {self.unit} is above the maximum {self.maximum}"
                )
        if self.choices is not None and coerced not in self.choices:
            raise ParameterError(f"{self.name}: {coerced!r} is not one of {self.choices}")
        return coerced


def validate_params(
    schema: Sequence[ParamSpec], params: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Check a recipe's parameters against a schema, filling in the defaults.

    Unknown keys are an error rather than being ignored: a misspelt parameter
    that silently takes its default is the failure mode that makes a recipe look
    reproducible and behave otherwise.
    """
    given = dict(params or {})
    resolved: dict[str, Any] = {}
    for spec in schema:
        if spec.name in given:
            resolved[spec.name] = spec.validate(given.pop(spec.name))
        elif spec.required:
            raise ParameterError(f"missing required parameter {spec.name!r}")
        else:
            resolved[spec.name] = spec.validate(spec.default)
    if given:
        known = sorted(spec.name for spec in schema)
        raise ParameterError(f"unknown parameter(s) {sorted(given)}; this step takes {known}")
    return resolved


@dataclass(frozen=True)
class StepContext:
    """Everything a step is allowed to read (plan §5.1).

    Attributes:
        structure: The input `Structure` — the revision the step starts from.
        params: Parameters already validated against the step's own schema, and
            already **resolved for this wafer position** (plan §8): the solver
            never sees a parameter that varies over the wafer, only the local
            value, which is what keeps it position-blind.
        library: The `MaterialType` library (plan §3.4). Passed in, never stored
            in the `Structure`.
        capabilities: What the input revision promises (plan §5.3).
        rng: The seeded generator anything stochastic must draw from — seeded
            from (recipe id, position, step index) by the runner, which is what
            makes replay materialization sound (ADR-0004, §5.2).
        position: The wafer position this chain belongs to, in mm; `(0.0, 0.0)`
            is the default "center" of interview decision I2.
    """

    structure: Structure
    params: Mapping[str, Any] = dataclass_field(default_factory=dict)
    library: MaterialLibrary = dataclass_field(default_factory=MaterialLibrary)
    capabilities: frozenset[str] = dataclass_field(default_factory=frozenset)
    rng: np.random.Generator = dataclass_field(
        default_factory=lambda: np.random.default_rng(0)
    )
    position: tuple[float, float] = (0.0, 0.0)

    def __getitem__(self, name: str) -> Any:
        """Shorthand for a validated parameter."""
        return self.params[name]

    @property
    def grid(self):  # noqa: ANN201 - Grid, but importing it here buys nothing
        """The grid the input structure lives on — the sole spatial authority."""
        return self.structure.grid


@dataclass(frozen=True)
class StepResult:
    """What a step hands back (plan §5.1).

    Attributes:
        structure: The output `Structure`. Steps are pure: the input is not
            mutated, and an inspection step returns it unchanged.
        swept: `∫ rate * flux * dt` along the front, in nm^ndim, for the balance
            check — `None` when the step moved no front at all, which is the
            honest answer for an ideal-tier region operation as well as for an
            inspection.
        provides: Capabilities the step claims to have produced (§5.3). Structural
            ones are checked by the gate; free-form ones are taken on trust.
        retires: Capabilities the step explicitly gives up — needed only for the
            free-form ones (a material's capability retires itself when the
            material goes).
        field_specs: `FieldSpec` per field name the step wrote, for the gate's
            scoping rule (plan §3.3). Without this a `dose` field reset would
            fall back to 0.0 with a note in the report.
        measurements: What the step measured, as `Quantity` — the API boundary.
        artifacts: URI references to heavy outputs (docs §4.2.2, unchanged).
        logs: Lines for the run log.
    """

    structure: Structure
    swept: float | None = None
    provides: frozenset[str] = dataclass_field(default_factory=frozenset)
    retires: frozenset[str] = dataclass_field(default_factory=frozenset)
    field_specs: Mapping[str, FieldSpec] = dataclass_field(default_factory=dict)
    measurements: Mapping[str, Quantity] = dataclass_field(default_factory=dict)
    artifacts: tuple[str, ...] = ()
    logs: tuple[str, ...] = ()


@runtime_checkable
class ProcessStep(Protocol):
    """One registered process (plan §5.1).

    Structural, not a base class: a step is anything with these five members, so
    a plugin is a plain object and the registry never becomes an inheritance
    hierarchy. `runtime_checkable` gives the registry an `isinstance` gate for
    the *shape*; what it cannot check — that `run` is pure and draws only from
    `ctx.rng` — is what `registry`'s determinism lint is for (§5.2).

    Attributes:
        step_id: Stable key, unique in a registry, e.g. `"develop.ideal"`.
        display_name: What the UI's step list shows.
        fidelity: One of `FIDELITIES` — the axis several steps modelling the same
            technique differ on (§5.4).
    """

    step_id: str
    display_name: str
    fidelity: str

    def parameter_schema(self) -> tuple[ParamSpec, ...]:
        """The typed parameters this step takes."""

    def requires(self) -> frozenset[str]:
        """Capabilities the input revision must carry (§5.3)."""

    def provides(self) -> frozenset[str]:
        """Capabilities this step produces (§5.3)."""

    def run(self, ctx: StepContext) -> StepResult:
        """Do the work. Pure: no Qt, no global state, no `np.random`."""


@dataclass(frozen=True)
class FunctionStep:
    """A `ProcessStep` assembled from a plain function — interview decision I7 literally.

    "Every process is a standalone function `Structure -> Structure (+ outputs)`"
    is a statement about where the work lives, not about how it is registered.
    Each module in this package writes the function first — callable directly
    from a test or a notebook, with typed keyword arguments and no context object
    — and wraps it here with the metadata the registry and the UI need.

    The pay-off is §5.4's: two entries can wrap the *same* function at different
    fidelities, or two functions at the same one, and the difference is data
    rather than a class hierarchy.

    Attributes:
        step_id: Stable key, unique in a registry.
        display_name: Label for the step list.
        fidelity: One of `FIDELITIES`.
        schema: The typed parameters.
        required / provided: The capability contract (§5.3).
        run_function: `StepContext -> StepResult`, the wrapper around the plain
            function; it is what unpacks `ctx.params` into keyword arguments.
        stochastic: Whether the step draws random numbers. Declared so the
            registry can lint it against §5.2's context-RNG contract.
    """

    step_id: str
    display_name: str
    fidelity: str
    schema: tuple[ParamSpec, ...]
    required: frozenset[str]
    provided: frozenset[str]
    run_function: Any
    stochastic: bool = False

    def __post_init__(self) -> None:
        if self.fidelity not in FIDELITIES:
            raise ValueError(f"fidelity must be one of {FIDELITIES}, got {self.fidelity!r}")
        if not self.step_id.strip():
            raise ValueError("step_id must be a non-empty string")

    def parameter_schema(self) -> tuple[ParamSpec, ...]:
        return self.schema

    def requires(self) -> frozenset[str]:
        return self.required

    def provides(self) -> frozenset[str]:
        return self.provided

    def run(self, ctx: StepContext) -> StepResult:
        return self.run_function(ctx)
