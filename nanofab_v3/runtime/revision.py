"""`Revision` and the append-only chain (plan §3.6).

A revision is one version of the sample: the `Structure` a step produced, plus
everything the commit gate said about producing it. `processes.engine.StepOutcome`
is deliberately shaped as the part of that a step can produce on its own, so a
`Revision` **wraps** an outcome rather than replacing it — what it adds is the
part only the chain knows: where in the chain it sits, what it came from, when it
ran and with which parameters, and which artifacts hang off it.

## A revision stores its structure; the chain is what is lazy

Plan §3.6 lists `structure: Structure` as a field and plan §8 specifies lazy
replay with a cache. Both are agreed text and they are not the same design, so
M4 had to pick one. Measured at the reference grid (540x1200 at 1 nm):

| | |
|---|---|
| one revision, 2 materials + 1 field, in RAM | 5.83 MB |
| the same revision, `savez_compressed` | 0.04 MB |
| `np.load` round-trip | 10 ms |

The expensive thing was never the format — it was holding twenty structures at
once. So a `Revision` holds its `Structure`, exactly as §3.6 writes it, and
`RevisionChain` keeps the recently touched ones resident, spills the rest through
a `RevisionStore`, and faults them back on demand in less than a UI frame. Replay
from the substrate stays the fallback for a cache miss and the mechanism for a
new wafer position, which is what ADR-0004 needs it for.

What is *always* resident is the summary — index, parent, step id, capabilities,
whether the gate was happy. A step list, a gating decision and a run log read
that and never touch a structure, which is what keeps scrubbing a 60-step chain
cheap.

Append-only, exactly like `ProcessEngine.revisions` was: a chain grows at the end
and nothing is ever replaced. Re-running from the middle truncates deliberately
(`rewind`), because a revision that no longer describes what happened is worse
than no revision at all.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime, timezone
from typing import Any, Iterator, Mapping, Protocol, Sequence

from nanofab_v3.model.artifact import ArtifactRef
from nanofab_v3.model.occurrence import LineageReport
from nanofab_v3.model.quantity import Quantity
from nanofab_v3.kernel.domain import DomainChange
from nanofab_v3.model.reports import ValidationReport
from nanofab_v3.model.structure import Structure
from nanofab_v3.processes.engine import StepOutcome

CENTER = (0.0, 0.0)
"""The default wafer position of interview decision I2, in mm."""

__all__ = [
    "CENTER",
    "ArtifactRef",
    "HistoryEntry",
    "MemoryRevisionStore",
    "Revision",
    "RevisionChain",
    "RevisionStore",
    "RevisionSummary",
    "Stopwatch",
    "now_iso",
]


@dataclass(frozen=True)
class HistoryEntry:
    """Which step, when, with what parameters, produced this revision (docs §4.2.6).

    The params snapshot is the **resolved** one: after `effective_params` picked
    this wafer position's values (plan §8) and after `validate_params` turned
    every `Quantity` into a plain number (plan §3.1). That is the parameter set
    the solver actually saw, so it is the one a replay has to reproduce and the
    one a saved file has to carry — a recipe-level parameter that is a function
    over the wafer cannot be written into a manifest, and its value here can.

    Attributes:
        index: Position in the chain, `0` for the first revision.
        step_id: Which registered process ran.
        display_name: Its label, denormalised so a run log survives a registry
            that no longer has the step.
        params: The resolved parameters, plain JSON-able values.
        recipe_id: Which recipe this chain is running.
        position: The wafer position this chain belongs to, in mm.
        started_at: ISO-8601 UTC timestamp of when the step started.
        duration_s: Wall-clock seconds the step took.
    """

    index: int
    step_id: str
    display_name: str = ""
    params: Mapping[str, Any] = dataclass_field(default_factory=dict)
    recipe_id: str = "recipe"
    position: tuple[float, float] = CENTER
    started_at: str = ""
    duration_s: float = 0.0

    def describe(self) -> str:
        """One line for the run log."""
        name = self.display_name or self.step_id
        shown = ", ".join(f"{k}={v}" for k, v in sorted(self.params.items()))
        return f"#{self.index} {name} ({shown})" if shown else f"#{self.index} {name}"


def now_iso() -> str:
    """The current UTC time, ISO-8601, seconds resolution.

    One place, so a timestamp in a manifest and a timestamp in a run log are the
    same string. Timestamps are the one part of a revision a replay does **not**
    reproduce — they are wall clock, not model state — which is why the
    determinism tests compare structures and capabilities and never these.
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Revision:
    """One version of the sample, and the whole record of how it got there.

    Plan §3.6's object, with `StepOutcome` wrapped rather than duplicated.

    Attributes:
        index: Position in the chain.
        parent: Index of the revision this one was produced from, `None` for the
            first.
        structure: The committed geometry and per-cell state (plan §3.2).
        capabilities: What this revision promises (plan §5.3) — the set the next
            step's `requires` is gated against.
        history: Which step produced it, when, with what parameters.
        artifacts: URI references to heavy outputs.
        validation: The commit gate's verdict (plan §4.5).
        lineage: What happened to each occurrence (plan §3.5).
        measurements: What the step measured, as `Quantity` — the API boundary.
        logs: The step's log lines, followed by the gate's.
        domain: What the domain did around this step (roadmap E5). Carried as a
            value rather than left in the log text, because `capped` is a
            *question for the operator* — raise the cap or accept a clipped
            sample — and a shell should not have to read prose to find it.
    """

    index: int
    parent: int | None
    structure: Structure
    capabilities: frozenset[str]
    history: HistoryEntry
    artifacts: tuple[ArtifactRef, ...] = ()
    validation: ValidationReport = dataclass_field(default_factory=ValidationReport)
    lineage: LineageReport = dataclass_field(default_factory=LineageReport)
    measurements: Mapping[str, Quantity] = dataclass_field(default_factory=dict)
    logs: tuple[str, ...] = ()
    domain: DomainChange = dataclass_field(default_factory=DomainChange)

    @property
    def step_id(self) -> str:
        """Which process produced this revision."""
        return self.history.step_id

    @property
    def ok(self) -> bool:
        """Whether the commit gate found every invariant intact."""
        return self.validation.ok

    @classmethod
    def of(
        cls,
        outcome: StepOutcome,
        *,
        index: int,
        parent: int | None,
        history: HistoryEntry,
        artifacts: Sequence[ArtifactRef] = (),
    ) -> "Revision":
        """Wrap a `StepOutcome` as the revision it is a part of."""
        return cls(
            index=index,
            parent=parent,
            structure=outcome.structure,
            capabilities=outcome.capabilities,
            history=history,
            artifacts=tuple(artifacts),
            validation=outcome.report,
            lineage=outcome.lineage,
            measurements=dict(outcome.measurements),
            logs=tuple(outcome.logs),
            domain=outcome.domain,
        )

    def summary(self) -> "RevisionSummary":
        """The part of this revision a step list and a run log need."""
        return RevisionSummary(
            index=self.index,
            parent=self.parent,
            step_id=self.history.step_id,
            display_name=self.history.display_name or self.history.step_id,
            capabilities=self.capabilities,
            ok=self.ok,
            warnings=self.validation.warnings,
            failures=self.validation.failures,
            materials=self.structure.materials,
        )


@dataclass(frozen=True)
class RevisionSummary:
    """What a chain remembers about a revision it is not currently holding.

    Bytes rather than megabytes, so it stays resident for every index. The step
    list, the gating decision and the run log are built from these; the structure
    is faulted in only when something actually has to look at the geometry.
    """

    index: int
    parent: int | None
    step_id: str
    display_name: str
    capabilities: frozenset[str]
    ok: bool
    warnings: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()
    materials: tuple[str, ...] = ()


class RevisionStore(Protocol):
    """Where a chain spills the revisions it is not holding (plan §8, §9).

    A protocol rather than a class so `runtime` does not depend on `io`: the
    chain knows it can hand a revision away and ask for it back, and nothing
    else. `io.store.FileRevisionStore` is the `.npz`-plus-manifest
    implementation; a test uses a dict in memory; a future external-solver
    exchange is the same seam again.
    """

    def put(self, index: int, revision: Revision) -> None:
        """Store a revision under its index in this chain."""

    def get(self, index: int) -> Revision | None:
        """The revision stored under `index`, or `None` if it is not there."""


@dataclass
class RevisionChain:
    """The append-only revision chain of one wafer position (plan §3.6, §8).

    Mutable by design: a chain is what a session grows, and the append-only rule
    is about what may happen to a revision once it is in (nothing), not about
    rebuilding the container to add one.

    Attributes:
        recipe_id: Which recipe this chain runs.
        position: The wafer position it belongs to, in mm (plan §8: each position
            owns an independent chain).
        store: Where revisions are spilled and faulted back from. `None` keeps
            **everything** resident — eviction without somewhere to spill to
            would be deletion, so a chain without a store ignores `resident`.
        resident: How many revisions stay in RAM once there is a store. Three is
            the default because the operations that touch a structure are "the
            current one", "the one before it" (the gate's parent) and "the one
            being looked at".
    """

    recipe_id: str = "recipe"
    position: tuple[float, float] = CENTER
    store: RevisionStore | None = None
    resident: int = 3
    _summaries: list[RevisionSummary] = dataclass_field(default_factory=list, repr=False)
    _held: dict[int, Revision] = dataclass_field(default_factory=dict, repr=False)
    _order: list[int] = dataclass_field(default_factory=list, repr=False)
    faults: int = dataclass_field(default=0, repr=False)
    spills: int = dataclass_field(default=0, repr=False)

    def __post_init__(self) -> None:
        if self.resident < 1:
            raise ValueError("a chain has to hold at least the revision it just made")

    # -- growing -------------------------------------------------------------

    def append(self, revision: Revision) -> Revision:
        """Add the next revision, spilling whatever falls out of residency."""
        if revision.index != len(self._summaries):
            raise ValueError(
                f"revision {revision.index} does not follow {len(self._summaries) - 1}; "
                "a chain is append-only"
            )
        self._summaries.append(revision.summary())
        self._hold(revision)
        return revision

    def rewind(self, index: int) -> None:
        """Drop every revision from `index` on — the one deliberate truncation.

        Re-running a step from the middle of a chain does not overwrite the
        revisions after it; it discards them, because a revision that no longer
        describes what happened is worse than no revision at all.
        """
        if not 0 <= index <= len(self._summaries):
            raise IndexError(f"no revision {index} in a chain of {len(self._summaries)}")
        del self._summaries[index:]
        for held in [i for i in self._held if i >= index]:
            self._held.pop(held)
            self._order.remove(held)

    # -- reading -------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._summaries)

    def __iter__(self) -> Iterator[RevisionSummary]:
        """Iterating a chain gives summaries: cheap, and never faults anything."""
        return iter(self._summaries)

    def __getitem__(self, index: int) -> Revision:
        """The full revision at `index`, faulting it back in if it was spilled."""
        index = self._resolve(index)
        held = self._held.get(index)
        if held is not None:
            self._touch(index)
            return held
        if self.store is None:
            raise KeyError(
                f"revision {index} was dropped and this chain has no store to fault it from"
            )
        revision = self.store.get(index)
        if revision is None:
            raise KeyError(f"revision {index} is neither resident nor in the store")
        self.faults += 1
        self._hold(revision)
        return revision

    def summary(self, index: int) -> RevisionSummary:
        """The always-resident summary of `index` — never faults."""
        return self._summaries[self._resolve(index)]

    @property
    def summaries(self) -> tuple[RevisionSummary, ...]:
        """Every summary, oldest first."""
        return tuple(self._summaries)

    @property
    def head(self) -> Revision | None:
        """The most recent revision, or `None` for an empty chain."""
        return None if not self._summaries else self[len(self._summaries) - 1]

    @property
    def capabilities(self) -> frozenset[str]:
        """What the chain's head promises — read from the summary, no fault."""
        if not self._summaries:
            return frozenset()
        return self._summaries[-1].capabilities

    @property
    def structure(self) -> Structure | None:
        """The head's `Structure`, or `None` for an empty chain."""
        head = self.head
        return None if head is None else head.structure

    def is_resident(self, index: int) -> bool:
        """Whether `index` can be read without touching the store."""
        return self._resolve(index) in self._held

    def logs(self) -> tuple[str, ...]:
        """The run log: every revision's history line, warnings and failures.

        Built from summaries, so showing a run log never faults a structure back
        in. The per-step log *lines* live on the revision itself, where they cost
        nothing to keep but are not worth spilling and re-reading for a scroll.
        """
        lines: list[str] = []
        for entry in self._summaries:
            lines.append(f"#{entry.index} {entry.display_name}")
            lines += [f"    FAIL {message}" for message in entry.failures]
            lines += [f"    warn {message}" for message in entry.warnings]
        return tuple(lines)

    # -- residency -----------------------------------------------------------

    def _resolve(self, index: int) -> int:
        count = len(self._summaries)
        resolved = index + count if index < 0 else index
        if not 0 <= resolved < count:
            raise IndexError(f"no revision {index} in a chain of {count}")
        return resolved

    def _hold(self, revision: Revision) -> None:
        self._held[revision.index] = revision
        self._touch(revision.index)
        # Eviction without somewhere to spill to is deletion, so a chain with no
        # store holds everything however small `resident` is. The residency
        # window is a memory policy, and a memory policy that loses revisions is
        # a different feature.
        if self.store is None:
            return
        while len(self._order) > self.resident:
            self._evict(self._order[0])

    def _touch(self, index: int) -> None:
        if index in self._order:
            self._order.remove(index)
        self._order.append(index)

    def _evict(self, index: int) -> None:
        revision = self._held.pop(index)
        self._order.remove(index)
        if self.store is not None:
            self.store.put(index, revision)
            self.spills += 1


class MemoryRevisionStore:
    """A `RevisionStore` that keeps everything in this process.

    Not a cache: it is what makes a chain's residency policy testable without a
    filesystem, and what a session that never saves uses so that scrubbing back
    is possible at all. The `.npz` store in `io` is the one that survives the
    process.
    """

    def __init__(self) -> None:
        self._revisions: dict[int, Revision] = {}

    def put(self, index: int, revision: Revision) -> None:
        self._revisions[index] = revision

    def get(self, index: int) -> Revision | None:
        return self._revisions.get(index)

    def __len__(self) -> int:
        return len(self._revisions)

    def __contains__(self, index: object) -> bool:
        return index in self._revisions


class Stopwatch:
    """Wall-clock timing for one step, as `HistoryEntry` records it."""

    def __init__(self) -> None:
        self.started_at = now_iso()
        self._start = time.perf_counter()

    @property
    def elapsed(self) -> float:
        """Seconds since the stopwatch was made."""
        return time.perf_counter() - self._start
