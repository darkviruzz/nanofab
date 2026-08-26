"""Running a step: validate, gate, run, commit (plan §5.1-§5.3, §4.5).

The thin runner that carries one step from a `Structure` to the next. Four
things happen in a fixed order, and each is somebody else's rule enforced here:

1. **validate** the recipe's parameters against the step's own schema
   (`contract.validate_params`) — the API boundary where a `Quantity` becomes a
   float and an out-of-range number becomes an error;
2. **gate** on capabilities (§5.3): a step whose `requires` the revision does not
   satisfy is not run at all, with a reason that names the missing promise;
3. **run** the step, pure, against a `StepContext` carrying a seeded RNG;
4. **commit** through `kernel.gate` (§4.5), which renormalises, resets scoped
   fields, checks the invariants, balances, reconstructs lineage and updates the
   capabilities.

Deliberately **not** a revision chain. The append-only `Revision` with its
history, artifacts and validation report is plan §3.6 and milestone M4; this is
what the acceptance scenarios and the process tests need in the meantime, and
what M4's runtime will grow around rather than replace.

The RNG seed is `(recipe id, position, step index)` exactly as §5.2 and ADR-0004
require, so two runs of the same chain at the same wafer position produce the
same sample, and adding a position later replays to the sample it would have had.

**A fifth thing happens, added in M6 (roadmap E15), and it happens here because
here is the only place every step passes through.** After the commit, the
committed structure's materials are checked against the library, and one the
library cannot answer for produces a warning and a log line rather than a silent
rate of zero. Putting it in each wrapper would have meant thirty places to
forget it and no coverage for a plugin's step at all; putting it after the commit
rather than before catches a material the step itself *introduced*, which is the
case that actually bit — a scattered particle nobody's recipe ever named.

**And a sixth, added in M7 (roadmap E5): the domain is fitted around the step.**
`kernel.domain` decides whether the sample still has room; this decides when to
ask. The order is what makes it work:

1. **before** the step, `domain.fit` grows the domain if the sample is about to
    touch a face and gives room back if there is far too much. The *fitted* input
    is what the step runs on **and** what the commit gate takes as its parent, so
    the two always share a grid — which is what lineage matching and array
    sharing need, and the reason the fit is here rather than after the commit;
2. **after** the step, if the sample used the domain up anyway — one step can
    move the front further than any margin — the input is grown and the step is
    run **again**, up to `DomainPolicy.retries` times. That is roadmap E5's
    "grows automatically instead of failing", and it costs an extra solve only on
    the step that needed it.

It stays deterministic, which ADR-0004 requires of everything here: the resize is
a pure function of the input structure and the policy, the retry is a pure
function of the outcome, and the RNG is re-seeded identically from (recipe,
position, index) on every attempt.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from nanofab_v3.kernel import domain as domain_kernel
from nanofab_v3.kernel import gate as commit_gate
from nanofab_v3.kernel import reinit
from nanofab_v3.materials import MaterialLibrary, didactic_library
from nanofab_v3.materials.unknown import UnknownMaterials, unknown_materials
from nanofab_v3.model.artifact import ArtifactRef, ArtifactSink
from nanofab_v3.model.occurrence import LineageReport
from nanofab_v3.model.quantity import Quantity
from nanofab_v3.model.reports import ValidationReport
from nanofab_v3.model.structure import Structure
from nanofab_v3.processes.contract import (
    CapabilityError,
    ProcessStep,
    StepContext,
    validate_params,
)
from nanofab_v3.model import capability


def step_seed(recipe_id: str, position: tuple[float, float], index: int) -> int:
    """The deterministic seed of one step (plan §5.2, ADR-0004).

    A hash rather than an arithmetic combination, so neighbouring positions and
    neighbouring step indices do not produce correlated streams — two adjacent
    wafer positions with the same particle pattern would look like a real finding
    and be an artifact of the seeding.
    """
    material = f"{recipe_id}|{position[0]!r}|{position[1]!r}|{index}".encode()
    return int.from_bytes(hashlib.blake2b(material, digest_size=8).digest(), "big")


@dataclass(frozen=True)
class StepOutcome:
    """One executed step: the new structure and everything the gate said about it.

    Attributes:
        step_id: Which process ran.
        structure: The committed `Structure`.
        report: The commit gate's `ValidationReport` (plan §4.5).
        lineage: What happened to each occurrence (plan §3.5).
        capabilities: What the new revision promises (plan §5.3).
        measurements: What the step measured, as `Quantity`.
        artifacts: What it wrote, as references (docs §4.2.2). Empty unless the
            caller gave the step somewhere to put one.
        logs: The step's own log lines, followed by the gate's and, when there
            were any, the unknown materials'.
        unknown: Materials the committed structure carries that the library
            cannot answer for (E15). Empty is the normal case. Carried as a
            value, not only as a warning, so a UI can offer to describe them and
            a headless caller can decide what an unknown material means to it.
        domain: What the domain did around this step (roadmap E5). `capped` on it
            is the one thing a shell has to surface, because that is where the
            model stops being able to show what it is computing.
        attempts: How many times the step ran. More than one means it used the
            domain up and was given more.
    """

    step_id: str
    structure: Structure
    report: ValidationReport
    lineage: LineageReport
    capabilities: frozenset[str]
    measurements: Mapping[str, Quantity] = field(default_factory=dict)
    artifacts: tuple[ArtifactRef, ...] = ()
    logs: tuple[str, ...] = ()
    unknown: UnknownMaterials = field(default_factory=UnknownMaterials)
    domain: domain_kernel.DomainChange = field(default_factory=domain_kernel.DomainChange)
    attempts: int = 1

    @property
    def ok(self) -> bool:
        """Whether the commit gate found every invariant intact."""
        return self.report.ok


def run_step(
    step: ProcessStep,
    structure: Structure,
    params: Mapping[str, Any] | None = None,
    *,
    library: MaterialLibrary | None = None,
    capabilities: Iterable[str] = (),
    recipe_id: str = "recipe",
    position: tuple[float, float] = (0.0, 0.0),
    index: int = 0,
    artifacts: ArtifactSink | None = None,
    policy: reinit.ReinitPolicy = reinit.ReinitPolicy(),
    tolerances: commit_gate.GateTolerances = commit_gate.GateTolerances(),
    domain: domain_kernel.DomainPolicy | None = None,
) -> StepOutcome:
    """Validate, gate, run and commit one process step.

    `capabilities` is the *input* revision's set. It is only ever needed for the
    free-form promises: the structural ones are re-derived by the gate from the
    structure itself, so a caller that starts a chain can pass nothing and the
    first commit will already know what the substrate provides.
    """
    library = didactic_library() if library is None else library
    available = frozenset(capabilities) | capability.derived(structure)
    missing = capability.unmet(step.requires(), available)
    if missing:
        raise CapabilityError(
            f"{step.step_id} needs {', '.join(missing)}, which this revision does not provide"
        )

    resolved = validate_params(step.parameter_schema(), params)
    domain_policy = domain_kernel.DomainPolicy() if domain is None else domain
    current, change = domain_kernel.fit(structure, domain_policy)

    attempt = 0
    while True:
        context = StepContext(
            structure=current,
            params=resolved,
            library=library,
            capabilities=available,
            rng=np.random.default_rng(step_seed(recipe_id, position, index)),
            position=position,
            artifacts=artifacts,
        )
        result = step.run(context)
        outcome = commit_gate.commit(
            result.structure,
            parent=current if current.materials else None,
            swept=result.swept,
            field_specs=result.field_specs,
            capabilities=available,
            provides=result.provides,
            retires=result.retires,
            policy=policy,
            tolerances=tolerances,
        )
        short_below, short_above = domain_kernel.out_of_room(outcome.structure)
        if not (short_below or short_above) or attempt >= domain_policy.retries:
            break
        relief = domain_kernel.extra_room(
            current.grid,
            below=short_below,
            above=short_above,
            policy=domain_policy,
            attempt=attempt,
        )
        if not relief.moved:
            change = _merged_change(change, relief)
            break
        current = domain_kernel.resize(current, below=relief.below, above=relief.above)
        change = _merged_change(change, relief)
        attempt += 1

    unknown = unknown_materials(
        library, outcome.structure.materials, seen_in=step.step_id
    )
    unknown.warn()
    return StepOutcome(
        step_id=step.step_id,
        structure=outcome.structure,
        report=outcome.report,
        lineage=outcome.lineage,
        capabilities=outcome.capabilities,
        measurements=result.measurements,
        artifacts=tuple(result.artifacts),
        logs=(
            tuple(result.logs)
            + outcome.report.describe()
            + unknown.describe()
            + change.describe(outcome.structure.grid)
        ),
        unknown=unknown,
        domain=change,
        attempts=attempt + 1,
    )


def _merged_change(
    first: domain_kernel.DomainChange, second: domain_kernel.DomainChange
) -> domain_kernel.DomainChange:
    """One `DomainChange` describing both, so the log line counts the whole step."""
    return domain_kernel.DomainChange(
        below=first.below + second.below,
        above=first.above + second.above,
        capped=first.capped or second.capped,
        wanted=first.wanted + second.wanted,
    )


def run_chain(
    steps: Sequence[tuple[ProcessStep, Mapping[str, Any]]],
    structure: Structure,
    *,
    library: MaterialLibrary | None = None,
    recipe_id: str = "recipe",
    position: tuple[float, float] = (0.0, 0.0),
    strict: bool = True,
    **kwargs: Any,
) -> tuple[StepOutcome, ...]:
    """Run a whole recipe, threading structure and capabilities through it.

    What plan §8's materialization will replay, minus the caching: a chain is a
    pure function of (steps, params, position), so running it twice gives the same
    sample and running it at a new position gives the sample that position would
    have had.

    `strict` fails on the first step whose commit gate reports a broken invariant.
    That is the right default for a test and for a batch replay; an interactive
    session sets it `False` and shows the report instead, which is what plan §4.5
    means by "a suspicious step is visible, never silent".
    """
    outcomes: list[StepOutcome] = []
    capabilities: frozenset[str] = frozenset()
    current = structure
    for index, (step, params) in enumerate(steps):
        outcome = run_step(
            step,
            current,
            params,
            library=library,
            capabilities=capabilities,
            recipe_id=recipe_id,
            position=position,
            index=index,
            **kwargs,
        )
        if strict and not outcome.ok:
            raise RuntimeError(
                f"step {index} ({step.step_id}) failed the commit gate: "
                + "; ".join(outcome.report.failures)
            )
        outcomes.append(outcome)
        capabilities = outcome.capabilities
        current = outcome.structure
    return tuple(outcomes)
