"""The process registry (plan §5.4) and the determinism lint (§5.2).

Interview decision Q2: *modular registry in source, monolith in delivery.*
In-tree builtins register through the same mechanism a plugin will
(`builtin_registry()` below is a plain function that fills one), so the seam that
entry points plug into exists from M3 and is exercised by every test — rather
than being designed in M5 against nothing.

Three jobs beyond storage:

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
- **The implementation digest** (`implementation_digest`, M5). What a step *is*,
  as a string that changes when its behaviour could have: id, fidelity, parameter
  schema, capability contract and the source of its own wrapper. ADR-0004 keys a
  cached revision on `(recipe hash, position, step index, code version)`, and
  M4's `code_version()` is `nanofab_v3.__version__` — which cannot see a plugin
  at all, and does not move when a builtin's wrapper is edited during
  development. The digest goes into the **recipe** hash (plan §21.1), so editing
  a step retires exactly the recipes that use it and editing an unused plugin
  retires nothing.
"""

from __future__ import annotations

import hashlib
import inspect
import re
from dataclasses import dataclass, field
from typing import Iterable, Iterator, Mapping

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


def _wrapper_source(step: ProcessStep) -> str | None:
    """The source of the step's own wrapper, or `None` when there is none to read.

    Deliberately the *wrapper*: the type of the step object and, for a
    `FunctionStep`, the function it delegates to. Not the kernel behind it —
    see `implementation_digest` for why that division is the whole design and
    also its limit.
    """
    try:
        source = inspect.getsource(type(step))
        function = getattr(step, "run_function", None)
        if function is not None:
            source += inspect.getsource(function)
    except (OSError, TypeError):
        return None
    return source


def _contract_text(step: ProcessStep) -> str:
    """The step's declared contract, as stable text.

    Everything a recipe can see about a step without running it: what it is
    called, at which fidelity, which parameters it takes with which units,
    bounds and defaults, and what it requires and provides. A change to any of
    these changes what the step *means* to a recipe, so all of them are in the
    digest even though none of them is executable.
    """
    parameters = [
        "|".join(
            [
                spec.name,
                spec.kind.__name__,
                spec.unit,
                repr(spec.default),
                repr(spec.minimum),
                repr(spec.maximum),
                repr(spec.choices),
            ]
        )
        for spec in step.parameter_schema()
    ]
    return "\n".join(
        [
            f"id={step.step_id}",
            f"fidelity={step.fidelity}",
            "params=" + ";".join(parameters),
            "requires=" + ",".join(sorted(step.requires())),
            "provides=" + ",".join(sorted(step.provides())),
        ]
    )


def implementation_digest(step: ProcessStep) -> str:
    """What this step *is*, as a string that moves when its behaviour could have.

    The second axis of the cache key decided in M5 (plan §21.1). ADR-0004 keys a
    cached revision on `(recipe hash, position, step index, code version)` and
    promises determinism "per machine + code version". `code_version()` is
    `nanofab_v3.__version__`, and it stays that way: it is the coarse axis, and
    it covers what a recipe cannot name — the kernel, numpy/scipy, the
    interpreter. What it cannot cover is a **step**: a plugin's
    `deposit.mocvd` can change its rate model without this package's version
    moving, and every revision cached under the old one would then be served as
    current. Nothing errors; the numbers are quietly from the previous version.
    The same hole is open without plugins, because editing a builtin's wrapper
    during development does not move `__version__` either.

    So the per-step axis goes into the *recipe* hash, where it invalidates
    exactly the recipes that use the step and leaves an unused plugin alone.

    **The limit, stated because it is not obvious: this covers the step's
    wrapper, not the kernel it calls.** `deposit.evaporate`'s `run_function` is
    16 lines of parameter unpacking around `kernel.flux`; a change inside
    `kernel/flux.py` does not move this digest. That is the division of labour —
    the wrapper is what a plugin owns, the kernel is what `__version__` owns —
    and it only works if both are actually maintained.

    A source-less step (a C extension, a frozen build — the same case
    `_uses_global_rng` already documents) falls back to the contract alone, and
    **says so in the digest**: a build with no source produces a different digest
    than the same step read from `.py`, so a frozen exe and a source install do
    not trade cache entries under a key that claims they are the same code. For
    an exe whose plugin set is fixed at build time that fallback is the whole
    story anyway, since nothing can change between two runs of it.
    """
    source = _wrapper_source(step)
    body = _contract_text(step)
    marker = "src" if source is not None else "nosrc"
    digest = hashlib.blake2b(digest_size=8)
    digest.update(body.encode())
    digest.update(b"\x00")
    digest.update((source or "").encode())
    return f"{marker}:{digest.hexdigest()}"


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
    _digests: dict[str, str] = field(default_factory=dict, repr=False, compare=False)

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
        self._digests.pop(step.step_id, None)
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

    def digest(self, step_id: str) -> str:
        """This step's `implementation_digest`, computed once per registry.

        Memoised because a recipe hash asks for it once per step and a wafer fan
        asks for the hash once per position. Measured over the 18 builtins:
        **3.6 ms per step cold** (64-69 ms for all of them; the first
        `inspect.getsource` on a module pays for reading it into `linecache`)
        against **0.00015 ms** once memoised. So a six-step recipe pays ~21 ms
        the first time it is hashed and nothing on every hash after — which is
        what makes it affordable for a position fan, where the hash is taken
        once per position.
        """
        cached = self._digests.get(step_id)
        if cached is None:
            cached = implementation_digest(self[step_id])
            self._digests[step_id] = cached
        return cached

    def digests(self) -> Mapping[str, str]:
        """`{step_id: digest}` for every registered step — what a recipe hash reads.

        A recipe names steps by id, so this is the mapping that turns "which
        steps does this recipe use" into "which implementations of them".
        """
        return {step_id: self.digest(step_id) for step_id in self.steps}

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

    Complete as of M5: every row of plan §6 is registered here. What M3 left out
    with a milestone against it — inspection, particles and clean, anneal — is in
    the last block, and `discover_plugins` is what adds anything else (plan §5.4,
    §11).
    """
    from nanofab_v3.processes import (
        anneal,
        contamination,
        deposition,
        etching,
        inspection,
        lithography,
        removal,
        substrate,
    )

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
        contamination.PARTICLES,
        contamination.CLEAN,
        inspection.SEM,
        inspection.PROFILOMETER,
        inspection.ELLIPSOMETER,
        anneal.ANNEAL,
    ):
        registry.register(step)
    return registry
