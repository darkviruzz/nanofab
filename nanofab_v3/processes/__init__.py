"""Process steps: `Structure -> Structure (+ outputs)` functions (plan §5, §6).

Milestone M3. A `ProcessStep` declares a parameter schema, the capabilities it
`requires` and `provides` (plan §5.3), and runs as a pure function of (input
`Structure`, validated params, resolved local parameters, seeded RNG) — the
determinism invariant of ADR-0004.

Physics lives once in `nanofab_v3.kernel`; the modules here are thin wrappers
that compose kernel primitives, which is what lets several processes model the
same technique at different fidelity (`deposit.ald` and
`deposit.conformal_offset` are one technique and two answers).

Layout:

- `contract` — `ParamSpec`, `StepContext`, `StepResult`, the `ProcessStep`
  protocol and the `FunctionStep` envelope,
- `rates` — the seam that turns a `MaterialLibrary` into `SurfaceRates`,
  `flux.AngularYield` and the redeposition `release` map,
- `substrate`, `lithography`, `deposition`, `etching`, `removal` — the didactic
  set of plan §6,
- `registry` — plan §5.4's registry, with §5.2's determinism lint,
- `engine` — validate, gate, run, commit; the runner the acceptance scenarios use
  until M4's revision chain exists.
"""

from __future__ import annotations

from nanofab_v3.processes.contract import (
    DIDACTIC,
    FIDELITIES,
    IDEAL,
    PHYSICAL,
    CapabilityError,
    FunctionStep,
    ParameterError,
    ParamSpec,
    ProcessStep,
    StepContext,
    StepResult,
)
from nanofab_v3.processes.engine import StepOutcome, run_chain, run_step, step_seed
from nanofab_v3.processes.registry import (
    ProcessRegistry,
    RegistrationError,
    builtin_registry,
)

__all__ = [
    "DIDACTIC",
    "FIDELITIES",
    "IDEAL",
    "PHYSICAL",
    "CapabilityError",
    "FunctionStep",
    "ParamSpec",
    "ParameterError",
    "ProcessRegistry",
    "ProcessStep",
    "RegistrationError",
    "StepContext",
    "StepOutcome",
    "StepResult",
    "builtin_registry",
    "run_chain",
    "run_step",
    "step_seed",
]
