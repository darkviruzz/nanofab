"""The process registry (plan §5.4) and the determinism lint (§5.2).

Interview decision Q2: *modular registry in source, monolith in delivery.*
In-tree builtins register through the same mechanism a plugin will
(`builtin_registry()` below is a plain function that fills one), so the seam that
entry points plug into exists from M3 and is exercised by every test — rather
than being designed in M5 against nothing.

Two jobs beyond storage:

- **Gating.** `runnable(capabilities)` is what the UI's step list reads. It is
  plan §5.3's whole promise: a step is runnable when the current revision carries
  everything it requires, and `blocked_reason` says which capability is missing —
  "exactly like today's gating UI, with better reasons".
- **The determinism lint.** §5.2 requires that anything stochastic draws from the
  context RNG, and asks for a best-effort registration check. `_uses_global_rng`
  reads the step's own source for a module-level random generator and refuses to
  register it. It is best-effort by construction — a plugin can defeat it — and
  it catches the mistake that actually happens, which is `np.random.normal` typed
  out of habit.
"""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, field
from typing import Iterable, Iterator

from nanofab_v3.model import capability
from nanofab_v3.processes.contract import ProcessStep

_GLOBAL_RNG = re.compile(r"\b(?:np|numpy)\.random\.|(?<![\w.])random\.(?!Generator)")
"""What a step must not call: the process-global generators of §5.2."""


class RegistrationError(ValueError):
    """A step cannot be registered — duplicate id, wrong shape, or global RNG."""


def _uses_global_rng(step: ProcessStep) -> bool:
    """Best-effort: does this step's `run` reach for a process-global generator?

    Source inspection, and honest about it. A step whose source is unavailable
    (a C extension, a frozen build) passes — the alternative would be refusing
    every plugin that is not a `.py` file, which is a rule about packaging rather
    than about determinism.
    """
    try:
        source = inspect.getsource(type(step))
        function = getattr(step, "run_function", None)
        if function is not None:
            source += inspect.getsource(function)
    except (OSError, TypeError):  # pragma: no cover - no source available
        return False
    return bool(_GLOBAL_RNG.search(source))


@dataclass
class ProcessRegistry:
    """Every process the application can run, keyed by `step_id`.

    Mutable by design — registration is a startup activity, and a frozen registry
    would mean rebuilding it to load a plugin. What it does *not* allow is
    replacing a registered id: two processes claiming the same key is how a
    recipe silently changes meaning between runs, and plan §8's replay
    materialization depends on it not doing that.
    """

    steps: dict[str, ProcessStep] = field(default_factory=dict)

    def register(self, step: ProcessStep) -> ProcessStep:
        """Add a step, checking its shape and its determinism contract."""
        if not isinstance(step, ProcessStep):
            raise RegistrationError(
                f"{step!r} is not a ProcessStep: it needs step_id, display_name, "
                "fidelity, parameter_schema, requires, provides and run"
            )
        if step.step_id in self.steps:
            raise RegistrationError(f"step id {step.step_id!r} is already registered")
        if _uses_global_rng(step):
            raise RegistrationError(
                f"step {step.step_id!r} reaches for a process-global random generator; "
                "anything stochastic must draw from StepContext.rng (plan §5.2)"
            )
        self.steps[step.step_id] = step
        return step

    def __getitem__(self, step_id: str) -> ProcessStep:
        try:
            return self.steps[step_id]
        except KeyError:
            raise KeyError(
                f"no process {step_id!r}; this registry has {sorted(self.steps)}"
            ) from None

    def __contains__(self, step_id: object) -> bool:
        return step_id in self.steps

    def __iter__(self) -> Iterator[ProcessStep]:
        return iter(self.steps.values())

    def __len__(self) -> int:
        return len(self.steps)

    def runnable(self, capabilities: Iterable[str]) -> tuple[ProcessStep, ...]:
        """The steps whose `requires` the given capabilities satisfy (plan §5.3)."""
        available = set(capabilities)
        return tuple(
            step for step in self.steps.values() if not capability.unmet(step.requires(), available)
        )

    def blocked_reason(self, step_id: str, capabilities: Iterable[str]) -> str | None:
        """Why a step is not runnable, or `None` when it is.

        The sentence a gating UI shows. Compare v1, which could only say "step 4
        has not run yet"; this says what is missing about the *sample*, which is
        the thing the operator can act on.
        """
        missing = capability.unmet(self[step_id].requires(), set(capabilities))
        if not missing:
            return None
        return f"{step_id} needs {', '.join(missing)}, which this revision does not provide"

    def by_technique(self) -> dict[str, tuple[ProcessStep, ...]]:
        """Steps grouped by the technique their id names, for the UI's step list.

        `deposit.ald` and `deposit.conformal_offset` are two fidelities of one
        technique (§5.4), and this is what lets a UI offer them as one entry with
        a fidelity choice rather than as two unrelated buttons.
        """
        grouped: dict[str, list[ProcessStep]] = {}
        for step in self.steps.values():
            grouped.setdefault(step.step_id.split(".", 1)[0], []).append(step)
        return {
            family: tuple(sorted(members, key=lambda step: step.step_id))
            for family, members in sorted(grouped.items())
        }


def builtin_registry() -> ProcessRegistry:
    """The didactic process set of plan §6, registered.

    Imported here rather than at module scope so the registry module itself stays
    importable without pulling in every process — which is what a plugin host
    needs, and what keeps the import graph a tree.

    What is deliberately absent, with the milestone that owns it: inspection steps
    (SEM/profilometer/ellipsometer — they need the artifact plumbing of M4),
    particles and clean, anneal (M5, plan §14). Their absence is a scope statement,
    not an oversight: every row of §6 that S1-S4 need is here.
    """
    from nanofab_v3.processes import deposition, etching, lithography, removal, substrate

    registry = ProcessRegistry()
    for step in (
        substrate.SELECT_SUBSTRATE,
        lithography.SPIN_COAT,
        lithography.EXPOSE_IDEAL,
        lithography.EXPOSE_DOSE,
        lithography.THRESHOLD_DOSE,
        lithography.DEVELOP_IDEAL,
        lithography.DEVELOP_RATE,
        deposition.EVAPORATE,
        deposition.SPUTTER,
        deposition.CONFORMAL_OFFSET,
        deposition.ALD,
        etching.WET_ETCH_STEP,
        etching.RIE_STEP,
        etching.IBE_STEP,
        removal.DISSOLVE,
        removal.STRIP_RATE,
        removal.LIFT_OFF,
        removal.REMOVE_UNSUPPORTED,
    ):
        registry.register(step)
    return registry
