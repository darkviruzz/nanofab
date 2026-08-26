"""The wafer fan: a job runner over `Run`'s positions (plan §8, §14).

**The engine was finished in M4.** `runtime.Run` covers an extensible position
set, materializes each on first access and caches per position;
`runtime.positions_on_radius` lays out a ring. What M5 owes plan §14 is the
*view*, and a view over nine positions of a twenty-step recipe is a **background
job problem rather than a rendering one**: measured against handoff §5, that is
about four minutes of solver and one second of I/O. So this module is the job
runner, and the Qt widget on top of it paints what the runner has so far.

Qt-free, and not by accident: `ui.scene` and `ui.session` import no Qt because
anything that decides geometry and everything that drives a run stays on the
Qt-free side (ADR-0001, asserted in `tests/test_ui.py`). A wafer fan drives runs.
It is a view of *positions*, and the positions are model.

## Why it polls rather than emits

The runner works on a worker thread and the widget reads `snapshot()` on a timer.
That is one shared, lock-guarded dict rather than a signal per event, and it
buys the thing this view actually needs: **partial results are the normal state,
not an error path.** A position that is still solving, one that finished, and one
that failed are three values of the same field, so the widget paints the fan the
same way whether the run started a second ago or is finished — there is no
"loading" mode to get out of.

The other reason is the boundary: a Qt signal would put Qt in this file. A
`threading.Event` and a dict do not.

## What sharing the cache buys

A warm cache replays a six-step chain in 0.11 s against 7.6 s to solve it — 68×
(handoff §5). So the fan takes a `cache` and hands it to `Run`, and a second look
at a position is a cache read rather than a solve. The cache is keyed on (recipe
hash, position, step index, code version) with the recipe hash now carrying each
step's implementation digest (plan §21.1), so `io.replay_cache_for` is what
builds it: one directory for the fan and the session both, never two.
"""

from __future__ import annotations

import math
import os
import tempfile
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from nanofab_v3.materials import MaterialLibrary
from nanofab_v3.model.artifact import ArtifactSink
from nanofab_v3.model.structure import Structure
from nanofab_v3.processes.registry import ProcessRegistry
from nanofab_v3.runtime.replay import Run
from nanofab_v3.runtime.revision import CENTER, RevisionChain
from nanofab_v3.runtime.run import Position, Recipe, ReplayStore, positions_on_radius


def default_cache_dir() -> "Path":
    """The one directory a fan and a session both put replay cache entries in.

    Handoff §5: a warm cache replays a chain 68x faster than solving it, so the
    fan's second look at a position has to hit what the session already computed
    — which means **one** directory rather than one each. This is where it is
    decided, in the Qt-free module, so a headless self-test and the application
    agree without either knowing about the other.

    `$NANOFAB_CACHE` overrides it; otherwise `$XDG_CACHE_HOME` or `~/.cache`, and
    a temp directory when neither is writable (a frozen exe on a locked-down
    machine, which is exactly the case handoff §4 says to expect to be wrong
    about).
    """
    override = os.environ.get("NANOFAB_CACHE")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    candidate = Path(base) / "nanofab_v3" / "replay"
    try:
        candidate.mkdir(parents=True, exist_ok=True)
    except OSError:  # pragma: no cover - depends on the machine
        return Path(tempfile.gettempdir()) / "nanofab_v3-replay"
    return candidate


PENDING = "pending"
"""Queued; nothing has been computed for this position yet."""

RUNNING = "running"
"""Being materialized right now — `steps_done` says how far."""

DONE = "done"
"""Materialized; `chain` is its revision chain."""

FAILED = "failed"
"""A step raised or failed the commit gate; `error` says what."""

STATES = (PENDING, RUNNING, DONE, FAILED)


@dataclass(frozen=True)
class PositionStatus:
    """Where one wafer position has got to.

    Attributes:
        position: The position in mm.
        state: One of `STATES`.
        steps_done: Revisions computed so far, `0` while pending.
        steps_total: How many the recipe has.
        error: Why it failed, empty otherwise.
        chain: The revision chain, once there is one. `None` until then — which
            is what makes "show partial results" a matter of drawing the
            positions that have one rather than a mode the view is in.
        seconds: Wall-clock seconds this position took, so far or in total.
    """

    position: Position
    state: str = PENDING
    steps_done: int = 0
    steps_total: int = 0
    error: str = ""
    chain: RevisionChain | None = None
    seconds: float = 0.0

    @property
    def radius(self) -> float:
        """Distance from the wafer centre, in mm."""
        return math.hypot(self.position[0], self.position[1])

    @property
    def fraction(self) -> float:
        """How much of the recipe is done, 0 to 1."""
        if self.steps_total <= 0:
            return 0.0
        return min(1.0, self.steps_done / self.steps_total)

    @property
    def structure(self) -> Structure | None:
        """The final structure at this position, or `None` if there is none yet.

        A *partial* chain answers with what it has: a position stopped halfway
        through a twenty-step recipe still has a picture, and refusing to show it
        until the run finished is the thing the handoff (§5) says not to do.
        """
        return None if self.chain is None else self.chain.structure

    def describe(self) -> str:
        """One line for a list or a tooltip."""
        # `+ 0.0` because `positions_on_radius` rounds and cos(pi) gives -0.0,
        # which formats as "-0" and reads like a different position.
        where = f"({self.position[0] + 0.0:.0f}, {self.position[1] + 0.0:.0f}) mm"
        if self.state == DONE:
            return f"{where}: {self.steps_done} steps, {self.seconds:.1f} s"
        if self.state == FAILED:
            return f"{where}: failed at step {self.steps_done} — {self.error}"
        if self.state == RUNNING:
            return f"{where}: step {self.steps_done + 1} of {self.steps_total}"
        return f"{where}: queued"


Watcher = Callable[[PositionStatus], None]
"""Called on the worker thread whenever a position's status changes."""


@dataclass
class WaferFan:
    """A `Run` over several positions, materialized in the background.

    The runner half of plan §14's "wafer materialization UI". It owns a `Run`,
    walks its positions on a worker thread, and keeps a status per position that
    a view can read at any moment without blocking.

    Attributes:
        run: The `runtime.Run` this drives. Adding a position to the fan adds it
            to the run, which is the ordinary path rather than a re-run
            (ADR-0004).
        watcher: Called on the worker thread on every status change. Optional,
            and a view that polls `snapshot()` needs none.
    """

    run: Run
    watcher: Watcher | None = None
    _status: dict[Position, PositionStatus] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    _worker: threading.Thread | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        for position in self.run.positions:
            self._status[position] = PositionStatus(
                position=position, steps_total=len(self.run.recipe)
            )

    # -- building the fan ----------------------------------------------------

    @classmethod
    def on_radius(
        cls,
        recipe: Recipe,
        radius: float,
        count: int,
        *,
        registry: ProcessRegistry | None = None,
        library: MaterialLibrary | None = None,
        cache: ReplayStore | None = None,
        sink: ArtifactSink | None = None,
        center: bool = True,
        strict: bool = False,
    ) -> "WaferFan":
        """A fan of `count` positions on a ring of `radius` mm, plus the centre.

        The usual wafer map, and deterministic: `positions_on_radius` returns the
        same tuple in the same order for the same arguments, so two sessions
        comparing "the fan at 60 mm" are comparing the same positions and hitting
        the same cache entries.

        `strict=False` because a fan is not a test: a position whose commit gate
        found a broken invariant becomes a chain with the report on it, exactly
        as an interactive session does (plan §4.5, "visible, never silent"). A
        run that aborted the whole wafer because one edge position went odd would
        hide the finding the fan exists to show.
        """
        positions = list(positions_on_radius(radius, count))
        if center:
            positions.insert(0, CENTER)
        return cls(
            Run(
                recipe,
                registry=registry,
                library=library,
                cache=cache,
                sink=sink,
                positions=positions,
                strict=strict,
            )
        )

    def add_position(self, position: Sequence[float]) -> Position:
        """Extend the fan; the new position is pending until the next `start`."""
        point = self.run.add_position(position)
        with self._lock:
            self._status.setdefault(
                point, PositionStatus(position=point, steps_total=len(self.run.recipe))
            )
        return point

    # -- reading it ----------------------------------------------------------

    @property
    def positions(self) -> tuple[Position, ...]:
        return self.run.positions

    def snapshot(self) -> Mapping[Position, PositionStatus]:
        """Every position's status right now — what a view paints.

        A copy under the lock, so a widget iterating it cannot see a half-written
        dict and never holds the lock while it paints.
        """
        with self._lock:
            return dict(self._status)

    def status(self, position: Sequence[float]) -> PositionStatus:
        point = (float(position[0]), float(position[1]))
        with self._lock:
            return self._status[point]

    @property
    def is_running(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    @property
    def done(self) -> tuple[Position, ...]:
        """The positions that finished — the partial result, whenever it is read."""
        return tuple(
            point for point, status in self.snapshot().items() if status.state == DONE
        )

    def structures(self) -> dict[Position, Structure]:
        """The final structure at every position that has one.

        Deliberately not `Run.structures()`, which materializes what it does not
        have and blocks until it is finished. This answers with what exists.
        """
        return {
            point: status.structure
            for point, status in self.snapshot().items()
            if status.structure is not None
        }

    # -- running it ----------------------------------------------------------

    def start(self, *, positions: Iterable[Sequence[float]] | None = None) -> None:
        """Materialize the pending positions on a worker thread.

        Returns immediately. Starting a fan that is already running is a no-op
        rather than an error: a view whose refresh timer fires during a long
        position should not have to know.
        """
        if self.is_running:
            return
        self._cancel.clear()
        queue = (
            [self.add_position(p) for p in positions]
            if positions is not None
            else [
                point
                for point, status in self.snapshot().items()
                if status.state in (PENDING, FAILED)
            ]
        )
        self._worker = threading.Thread(
            target=self._materialize_all, args=(queue,), daemon=True, name="wafer-fan"
        )
        self._worker.start()

    def run_blocking(self, *, positions: Iterable[Sequence[float]] | None = None) -> None:
        """The same work on the calling thread — for tests, scripts and the CLI.

        The same code path as `start`, so a headless self-test exercises what the
        UI exercises rather than a second implementation of it.
        """
        self._cancel.clear()
        queue = (
            [self.add_position(p) for p in positions]
            if positions is not None
            else [
                point
                for point, status in self.snapshot().items()
                if status.state in (PENDING, FAILED)
            ]
        )
        self._materialize_all(queue)

    def cancel(self) -> None:
        """Ask the worker to stop after the position it is on.

        Between positions rather than between steps, because a half-materialized
        chain that was abandoned mid-step would still be written to the cache and
        served as complete on the next look.
        """
        self._cancel.set()

    def join(self, timeout: float | None = None) -> None:
        """Wait for the worker, if there is one — tests and shutdown."""
        if self._worker is not None:
            self._worker.join(timeout)

    # -- the worker ----------------------------------------------------------

    def _materialize_all(self, queue: Sequence[Position]) -> None:
        for point in queue:
            if self._cancel.is_set():
                return
            self._materialize(point)

    def _materialize(self, point: Position) -> None:
        import time

        started = time.perf_counter()
        self._update(point, state=RUNNING, steps_done=0, error="", chain=None)

        def progress(index: int, _revision) -> None:
            self._update(
                point,
                state=RUNNING,
                steps_done=index + 1,
                seconds=time.perf_counter() - started,
            )

        try:
            chain = self.run.chain(point, progress=progress)
        except Exception as error:  # noqa: BLE001 - one position's failure is its own
            self._update(
                point,
                state=FAILED,
                error=f"{type(error).__name__}: {error}",
                seconds=time.perf_counter() - started,
            )
            return
        self._update(
            point,
            state=DONE,
            steps_done=len(chain),
            chain=chain,
            seconds=time.perf_counter() - started,
        )

    def _update(self, point: Position, **changes) -> None:
        with self._lock:
            current = self._status.get(
                point, PositionStatus(position=point, steps_total=len(self.run.recipe))
            )
            updated = replace(current, **changes)
            self._status[point] = updated
        if self.watcher is not None:
            self.watcher(updated)


def compare(
    fan: WaferFan, left: Sequence[float], right: Sequence[float]
) -> dict[str, float]:
    """How two positions' final structures differ, per material, in nm^ndim.

    Plan §14 asks for "a way to compare two positions' final structures" and this
    is the smallest honest one: the measure of each material at each, and the
    difference. A radial rate profile shows up as a metal that is thinner at the
    edge; a bow-induced incidence offset shows up as a sidewall that is not.

    A material present at one position and not the other counts as zero there
    rather than being left out, because "the edge has no metal at all" is the
    finding and a missing key would hide it.
    """
    first, second = fan.status(left).structure, fan.status(right).structure
    if first is None or second is None:
        raise ValueError("both positions have to be materialized before comparing them")
    materials = sorted({*first.materials, *second.materials})
    return {
        str(material): (
            (second.measure(second.inside(material)) if material in second.phi else 0.0)
            - (first.measure(first.inside(material)) if material in first.phi else 0.0)
        )
        for material in materials
    }
