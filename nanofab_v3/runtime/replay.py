"""Running a recipe, and materializing a wafer position by replay (plan §8).

This is where the four things M4 builds meet: a `Recipe` (§8) is run step by step
through `processes.engine` (§5), each `StepOutcome` becomes a `Revision` (§3.6)
appended to a chain, and the chain spills what it is not holding through a store
(§9). Materializing a position is the same loop with a cache in front of it.

## Why replay is sound, stated once

Plan §5.2 and ADR-0004: a step's outcome is a pure function of (input structure,
recipe params, wafer position, step index, code version). Everything stochastic
draws from `StepContext.rng`, seeded by `engine.step_seed(recipe_id, position,
index)`. So replaying a chain reproduces it bit-for-bit, and replaying it at a
position that was never run produces exactly the sample that position would have
had. The determinism boundary is stated honestly in ADR-0004 and lives in the
cache key: one machine, one code version.

What replay does **not** reproduce is wall-clock time. `HistoryEntry.started_at`
and `duration_s` are records of a run, not model state, which is why the
determinism tests compare structures and capabilities and never those.

## What a cache hit is allowed to be

A hit is a revision computed for *this* recipe hash, *this* position, *this* step
index, under *this* code version. Three of the four are in the key by ADR-0004;
the fourth — the recipe hash — is what makes editing any parameter of any earlier
step retire everything downstream of it, without anything having to reason about
which steps a change could have affected.

The cached prefix is walked forward and stops at the first miss, because a chain
is sequential: step k needs the structure after step k-1, so a hit at k with a
miss at k-1 is not a shortcut, it is a gap.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping, Sequence

from nanofab_v3.materials import MaterialLibrary, didactic_library
from nanofab_v3.model.artifact import ArtifactSink
from nanofab_v3.model.structure import Structure
from nanofab_v3.processes.contract import ProcessStep
from nanofab_v3.processes.engine import StepOutcome, run_step
from nanofab_v3.processes.registry import ProcessRegistry, builtin_registry
from nanofab_v3.runtime.revision import (
    CENTER,
    ArtifactRef,
    HistoryEntry,
    Revision,
    RevisionChain,
    RevisionStore,
    Stopwatch,
)
from nanofab_v3.runtime.run import Position, Recipe, RecipeStep, ReplayStore, as_positions

Progress = Callable[[int, "Revision"], None]
"""Called after each step with `(index, revision)` — what a UI's run log reads."""


class StepFailed(RuntimeError):
    """A step's commit gate reported a broken invariant and `strict` was set."""


def apply_step(
    step: ProcessStep,
    structure: Structure,
    params: Mapping[str, Any],
    *,
    index: int,
    parent: int | None,
    capabilities: Iterable[str] = (),
    library: MaterialLibrary | None = None,
    recipe_id: str = "recipe",
    position: Position = CENTER,
    sink: ArtifactSink | None = None,
    artifacts: Sequence[ArtifactRef] = (),
    **kwargs: Any,
) -> Revision:
    """Run one step and wrap its outcome as the revision it produced.

    `params` must already be resolved for this position (`effective_params`) —
    this function is downstream of plan §8's seam and passes them straight to the
    solver.

    `sink` is where a step may put a heavy output; whatever it produced lands on
    the revision, joined by anything the caller passed as `artifacts` (an
    externally produced picture of this revision, say). Until M5 no registered
    step produced any, so this wire had nothing to carry — see `memory.md`
    2026-08-26, risk 3, for why it was left until the inspection steps existed to
    exercise it.
    """
    watch = Stopwatch()
    outcome: StepOutcome = run_step(
        step,
        structure,
        params,
        library=library,
        capabilities=capabilities,
        recipe_id=recipe_id,
        position=position,
        index=index,
        artifacts=sink,
        **kwargs,
    )
    history = HistoryEntry(
        index=index,
        step_id=step.step_id,
        display_name=getattr(step, "display_name", step.step_id),
        # The *validated* parameters, not the ones handed in: defaults are filled
        # and every `Quantity` is a plain number, which is what actually ran and
        # therefore what a saved file and a replay have to reproduce.
        params=_snapshot(step, params),
        recipe_id=recipe_id,
        position=position,
        started_at=watch.started_at,
        duration_s=watch.elapsed,
    )
    return Revision.of(
        outcome,
        index=index,
        parent=parent,
        history=history,
        artifacts=tuple(outcome.artifacts) + tuple(artifacts),
    )


def _snapshot(step: ProcessStep, params: Mapping[str, Any]) -> dict[str, Any]:
    """The resolved parameter set, defaults included, in JSON-able values."""
    from nanofab_v3.processes.contract import validate_params

    resolved = validate_params(step.parameter_schema(), params)
    return {name: value for name, value in sorted(resolved.items())}


def run_recipe(
    recipe: Recipe,
    *,
    registry: ProcessRegistry | None = None,
    library: MaterialLibrary | None = None,
    position: Position = CENTER,
    store: RevisionStore | None = None,
    sink: ArtifactSink | None = None,
    resident: int = 3,
    strict: bool = True,
    progress: Progress | None = None,
) -> RevisionChain:
    """Run a whole recipe at one wafer position, building its revision chain.

    `strict` fails on the first step whose commit gate reports a broken
    invariant. That is the right default for a test and for a batch replay; an
    interactive session sets it `False` and shows the report instead, which is
    what plan §4.5 means by "a suspicious step is visible, never silent".
    """
    return _materialize(
        recipe,
        position,
        registry=registry or builtin_registry(),
        library=library or didactic_library(),
        cache=None,
        store=store,
        sink=sink,
        resident=resident,
        strict=strict,
        progress=progress,
    )


def materialize(
    recipe: Recipe,
    position: Position,
    *,
    registry: ProcessRegistry | None = None,
    library: MaterialLibrary | None = None,
    cache: ReplayStore | None = None,
    store: RevisionStore | None = None,
    sink: ArtifactSink | None = None,
    resident: int = 3,
    strict: bool = True,
    progress: Progress | None = None,
) -> RevisionChain:
    """Plan §8's materialization: this position's chain, replayed and cached.

    Adding a wafer position later replays the recipe from substrate selection
    with that position's parameters. Deterministic by plan §5.2, so the result is
    exactly what the position would have been; cached per ADR-0004's key, so
    doing it twice costs one `np.load` per step instead of one solve.
    """
    return _materialize(
        recipe,
        position,
        registry=registry or builtin_registry(),
        library=library or didactic_library(),
        cache=cache,
        store=store,
        sink=sink,
        resident=resident,
        strict=strict,
        progress=progress,
    )


def _materialize(
    recipe: Recipe,
    position: Position,
    *,
    registry: ProcessRegistry,
    library: MaterialLibrary,
    cache: ReplayStore | None,
    store: RevisionStore | None,
    sink: ArtifactSink | None,
    resident: int,
    strict: bool,
    progress: Progress | None,
) -> RevisionChain:
    chain = RevisionChain(
        recipe_id=recipe.recipe_id, position=position, store=store, resident=resident
    )
    structure = recipe.initial()
    capabilities: frozenset[str] = frozenset()
    start = 0

    if cache is not None:
        for index in range(len(recipe)):
            hit = cache.get(position, index)
            if hit is None:
                break
            chain.append(hit)
            structure, capabilities = hit.structure, hit.capabilities
            start = index + 1
            if progress is not None:
                progress(index, hit)

    for index in range(start, len(recipe)):
        entry: RecipeStep = recipe[index]
        revision = apply_step(
            registry[entry.step_id],
            structure,
            entry.resolve(position),
            index=index,
            parent=index - 1 if index else None,
            capabilities=capabilities,
            library=library,
            recipe_id=recipe.recipe_id,
            position=position,
            sink=sink,
        )
        if strict and not revision.ok:
            raise StepFailed(
                f"step {index} ({entry.step_id}) failed the commit gate: "
                + "; ".join(revision.validation.failures)
            )
        chain.append(revision)
        if cache is not None:
            cache.put(position, revision)
        if progress is not None:
            progress(index, revision)
        structure, capabilities = revision.structure, revision.capabilities

    return chain


class Run:
    """One recipe over an extensible set of wafer positions (plan §8, ADR-0004).

    Each position owns an independent revision chain, materialized on first
    access and kept afterwards. Adding a position later is not a special case —
    it is the ordinary path, which is exactly what ADR-0004 rejected eager
    fan-out to get.

    Attributes:
        recipe: What every position runs.
        registry: Where step ids are looked up.
        library: The `MaterialType` library the steps read.
        cache: The persistent replay cache, or `None` to recompute every time.
        sink: Where a step may put a heavy output, or `None` for nowhere.
        resident: How many revisions each chain keeps in RAM.
    """

    def __init__(
        self,
        recipe: Recipe,
        *,
        registry: ProcessRegistry | None = None,
        library: MaterialLibrary | None = None,
        cache: ReplayStore | None = None,
        sink: ArtifactSink | None = None,
        positions: Iterable[Sequence[float]] | None = None,
        resident: int = 3,
        strict: bool = True,
    ) -> None:
        self.recipe = recipe
        self.registry = registry or builtin_registry()
        self.library = library or didactic_library()
        self.cache = cache
        self.sink = sink
        self.resident = resident
        self.strict = strict
        self._chains: dict[Position, RevisionChain] = {}
        self._positions: list[Position] = list(as_positions(positions))

    @property
    def positions(self) -> tuple[Position, ...]:
        """The positions this run covers, in the order they were added."""
        return tuple(self._positions)

    def add_position(self, position: Sequence[float]) -> Position:
        """Extend the run by one position; it materializes when first read."""
        point = (float(position[0]), float(position[1]))
        if point not in self._positions:
            self._positions.append(point)
        return point

    def materialized(self, position: Sequence[float]) -> bool:
        """Whether this position's chain has been computed in this process."""
        return (float(position[0]), float(position[1])) in self._chains

    def chain(
        self, position: Sequence[float] = CENTER, *, progress: Progress | None = None
    ) -> RevisionChain:
        """This position's revision chain, materializing it if it is not there."""
        point = self.add_position(position)
        existing = self._chains.get(point)
        if existing is not None:
            return existing
        chain = materialize(
            self.recipe,
            point,
            registry=self.registry,
            library=self.library,
            cache=self.cache,
            store=None if self.cache is None else self.cache.for_position(point),
            sink=self.sink,
            resident=self.resident,
            strict=self.strict,
            progress=progress,
        )
        self._chains[point] = chain
        return chain

    def structures(self) -> dict[Position, Structure]:
        """The final structure at every position covered so far — the wafer map."""
        return {point: self.chain(point).structure for point in self.positions}  # type: ignore[misc]
