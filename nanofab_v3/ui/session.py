"""`Session` — one interactive run, with no Qt in it (plan §3.6, §8, §10).

The v0.2.0 shell kept the session inside `MainWindow`: the engine, the current
step, the parameter state and the dirty flags were all widget state, so nothing
about "what happens when you press Run" could be tested without a display. This
module is that state, extracted and made ordinary.

A `Session` is a recipe being built one step at a time. Running a step appends a
`Revision` to the chain **and** a `RecipeStep` to the recipe, which is what makes
the two the same thing seen twice: the chain is what happened, the recipe is what
would happen again. That is also what lets an interactive session be replayed at
another wafer position without anybody having written the recipe down separately
(plan §8).

Three rules it keeps, and each is one of M4's:

- **Append-only, with one deliberate truncation.** `rewind` drops the tail
  because a revision that no longer describes what happened is worse than no
  revision (plan §3.6).
- **`strict=False`.** An interactive session shows a failing gate rather than
  raising, which is what plan §4.5 means by "a suspicious step is visible, never
  silent". A batch replay keeps `strict=True`.
- **The picture is derived.** `scene()` builds a `SceneSnapshot` from a revision's
  `Structure`; nothing about the geometry is cached in the session, and the v1
  1D layer list does not come back (plan §3.6).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np

from nanofab_v3.io.exchange import load_chain, save_chain
from nanofab_v3.kernel.domain import DomainPolicy
from nanofab_v3.io.manifest import recipe_from_json, recipe_to_json
from nanofab_v3.materials import MaterialLibrary, MaterialType, didactic_library
from nanofab_v3.materials.unknown import UnknownMaterials, unknown_materials
from nanofab_v3.model.grid import Grid
from nanofab_v3.model.structure import Structure
from nanofab_v3.processes.contract import CapabilityError, ParameterError
from nanofab_v3.model.artifact import ArtifactSink, MemoryArtifactSink
from nanofab_v3.processes.plugins import DiscoveryReport, application_registry
from nanofab_v3.processes.registry import ProcessRegistry
from nanofab_v3.processes.substrate import cross_section_grid
from nanofab_v3.runtime.replay import apply_step, materialize
from nanofab_v3.runtime.revision import CENTER, Revision, RevisionChain, RevisionStore
from nanofab_v3.runtime.run import Position, Recipe, RecipeStep
from nanofab_v3.ui import scene as scene_builder
from nanofab_v3.ui.scene import SceneSnapshot

StepCallback = Callable[[int, int, RecipeStep], None]
"""`(index, total, step)` before each step of `run_recipe` — a progress hook."""

SESSION_MANIFEST = "session.json"
"""Name of the recipe file *inside* a saved build's revision directory."""

RECIPE_SUFFIX = ".recipe.json"
"""Suffix of a standalone recipe file — the text half of saving, on its own."""

AUTOSAVE_FILE = "last-session.recipe.json"
"""What E38 writes after every step, in the session half of the cache ladder."""

ARTIFACTS_DIR = "artifacts"
"""Where `save_build` puts what the inspection steps produced (roadmap E40)."""


class Session:
    """One wafer position's interactive run: a recipe and the chain it produced.

    Attributes:
        recipe: What has been run so far, in a form that can be replayed.
        chain: The revisions it produced (plan §3.6).
        registry: Where step ids are resolved — the builtins plus any plugins,
            unless the caller supplied one.
        library: The `MaterialType` library the steps and the renderer read.
        plugins: What entry-point discovery loaded and refused, for the run log.
        domain: How far the domain may grow around a step and where it stops
            (roadmap E5). Held here because raising the cap is something an
            operator asks for once and every later step has to run under.
        sink: Where an inspection step may put an artifact. A
            `MemoryArtifactSink` by default (roadmap E40) — see `__init__`.
        autosave: Where the recipe is written after every step, or `None` to
            switch it off (roadmap E38).
    """

    def __init__(
        self,
        grid: Grid | None = None,
        *,
        registry: ProcessRegistry | None = None,
        library: MaterialLibrary | None = None,
        domain: DomainPolicy | None = None,
        recipe_id: str = "session",
        position: Position = CENTER,
        store: RevisionStore | None = None,
        resident: int = 3,
        sink: ArtifactSink | None = None,
        autosave: "str | os.PathLike[str] | None" = None,
    ) -> None:
        # The *application* registry: builtins plus whatever entry points bring
        # (plan §11). A session is what an operator drives, and a plugin that
        # does not appear in its step list is a plugin that was not delivered.
        # `plugins.discover_plugins` never raises for a plugin's sake, so a
        # stale third-party package costs its own steps and nothing else.
        if registry is None:
            registry, discovery = application_registry()
            self.plugins = discovery
        else:
            self.plugins = DiscoveryReport()
        self.registry = registry
        # `is None`, never `or` — see `runtime.replay.Run` and plan §21.3.
        self.library = didactic_library() if library is None else library
        # Roadmap E5's cap is "raisable on request", so the policy is a session
        # value rather than a constant — the request lands here.
        self.domain = DomainPolicy() if domain is None else domain
        # Roadmap E40. `inspect.sem` and `inspect.profilometer` have written an
        # artifact only when handed a sink since M5, and nothing ever handed them
        # one — the wire was laid and never plugged in. A *directory* sink would
        # force a session nobody has saved yet to invent a path, so it is memory:
        # it costs nothing, it is already written, and `save_build` takes the
        # payloads along into the folder that is being created anyway.
        self.sink = MemoryArtifactSink() if sink is None else sink
        self.autosave = None if autosave is None else Path(autosave)
        self.recipe = Recipe(
            grid=grid if grid is not None else default_grid(), recipe_id=recipe_id
        )
        self.chain = RevisionChain(
            recipe_id=recipe_id, position=position, store=store, resident=resident
        )

    # -- state ---------------------------------------------------------------

    @property
    def position(self) -> Position:
        return self.chain.position

    @property
    def capabilities(self) -> frozenset[str]:
        """What the head revision promises — what the step list gates on."""
        return self.chain.capabilities

    @property
    def structure(self) -> Structure:
        """The head's geometry, or the empty domain before the first step."""
        current = self.chain.structure
        return self.recipe.initial() if current is None else current

    def unknown_materials(self) -> UnknownMaterials:
        """Materials on the head revision that the library cannot answer for (E15).

        Recomputed rather than remembered, for the same reason an occurrence is
        (plan §3.5): the answer changes when the library does, and an operator who
        has just described `tungsten` should not have to re-run the step to stop
        being asked about it. It is a set difference over a handful of ids.
        """
        return unknown_materials(self.library, self.structure.materials)

    def describe_material(self, entry: MaterialType) -> Path:
        """Add a `MaterialType` to this session's library and save it to disk (E15).

        Two effects on purpose. The session picks it up now — `self.library` is a
        value, so this is a rebind rather than a mutation — and
        `store.save_material` puts it in the writable root, so the next session
        and every other one start out knowing it. A material described once and
        forgotten on restart would be a worse answer than the warning.
        """
        from nanofab_v3.materials import save_material

        path = save_material(entry)
        self.library = self.library.with_entry(entry)
        return path

    def blocked_reason(self, step_id: str) -> str | None:
        """Why a step cannot run right now, in the sentence the operator reads."""
        return self.registry.blocked_reason(step_id, self.capabilities)

    def runnable_steps(self) -> tuple[str, ...]:
        return tuple(step.step_id for step in self.registry.runnable(self.capabilities))

    # -- doing things --------------------------------------------------------

    def run(self, step_id: str, params: Mapping[str, Any] | None = None) -> Revision:
        """Run one step against the head revision and append what it produced.

        Raises `CapabilityError` before anything moves when the revision does not
        satisfy the step's `requires`, and `ParameterError` when the form's
        values do not fit the schema — both from the engine, so the UI has no
        second opinion about what a legal recipe is.

        The gate is **not** strict here: a step whose invariants broke still
        becomes a revision, marked, with the report on it. Hiding it would be the
        one thing plan §4.5 asks this layer not to do.
        """
        step = self.registry[step_id]
        index = len(self.chain)
        entry = RecipeStep(step_id, dict(params or {}))
        revision = apply_step(
            step,
            self.structure,
            entry.resolve(self.position),
            index=index,
            parent=index - 1 if index else None,
            capabilities=self.capabilities,
            library=self.library,
            recipe_id=self.recipe.recipe_id,
            position=self.position,
            sink=self.sink,
            domain=self.domain,
        )
        self.recipe = self.recipe.with_step(entry)
        self.chain.append(revision)
        self.write_autosave()
        return revision

    def write_autosave(self) -> Path | None:
        """Write the recipe where a crash cannot take it (roadmap E38).

        **The recipe, not the build**, and the ratio is the argument: a recipe is
        about a kilobyte and writes in milliseconds, where one revision's
        structures are 23 MB (plan §23.7) — 230 MB for a ten-step chain, and the
        seconds during which the application does not respond, after *every*
        step. The structures are not lost by not being written here: they are in
        the replay cache, which makes a repeat 68x faster than the solve.

        Atomic, via `os.replace`, which is atomic on all three platforms. A
        half-written recipe cannot exist, so "restore the last session" can never
        be offered a file that parses into a different recipe than the one that
        ran.

        Failures are swallowed: a read-only cache directory is a reason to lose
        an autosave, never a reason to lose the step somebody just ran.
        """
        if self.autosave is None:
            return None
        try:
            self.autosave.parent.mkdir(parents=True, exist_ok=True)
            scratch = self.autosave.with_suffix(self.autosave.suffix + ".part")
            scratch.write_text(
                json.dumps(recipe_to_json(self.recipe), indent=1, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(scratch, self.autosave)
        except OSError:  # pragma: no cover - depends on the machine
            return None
        return self.autosave

    def repeat(self, index: int) -> Revision:
        """Run the step that produced revision `index` again, at the head (E12).

        The chain is not touched: repeating is *appending*, which is what a real
        second exposure or a second etch is. That it produces a different result
        than the first — a second 10 s etch is 20 s of etching — is the honest
        answer and is why this is not a "re-run" that replaces anything.
        """
        entry = self.recipe[index]
        return self.run(entry.step_id, dict(entry.params))

    def parameters_of(self, index: int) -> dict[str, Any]:
        """What the step that produced revision `index` was given.

        From the *recipe*, not from the revision's history: the history records
        the validated values that actually ran, and a form wants the values
        somebody typed — including the ones they left as defaults.
        """
        return dict(self.recipe[index].params)

    def rewind(self, index: int) -> None:
        """Drop revision `index` and everything after it, recipe included (E12).

        Truncation, never branching: `ui/window.py`'s first line has said "a
        snapshot is a record, not a branch" since M4, and E12 keeps it. Adjusting
        a step is therefore this plus running it again with different values, and
        the history that led somewhere else is gone rather than kept beside the
        one that led here.
        """
        self.chain.rewind(index)
        self.recipe = Recipe(
            grid=self.recipe.grid,
            steps=self.recipe.steps[:index],
            recipe_id=self.recipe.recipe_id,
        )
        self.write_autosave()

    def reset(self, grid: Grid | None = None) -> None:
        """Start over on a fresh domain, keeping the registry and the library."""
        self.recipe = Recipe(
            grid=grid if grid is not None else self.recipe.grid,
            recipe_id=self.recipe.recipe_id,
        )
        self.chain = RevisionChain(
            recipe_id=self.recipe.recipe_id,
            position=self.position,
            store=self.chain.store,
            resident=self.chain.resident,
        )

    def at_position(self, position: Position, **kwargs: Any) -> RevisionChain:
        """This session's recipe replayed at another wafer position (plan §8).

        The reason the session appends to a recipe rather than only to a chain:
        an operator who built a run by hand at the wafer centre can ask what the
        edge would have done, and the answer is deterministic rather than a
        second manual run.
        """
        return materialize(
            self.recipe,
            position,
            registry=self.registry,
            library=self.library,
            **kwargs,
        )

    # -- looking at it -------------------------------------------------------

    def scene(
        self, index: int | None = None, *, overlays: Sequence[str] = ()
    ) -> SceneSnapshot:
        """A `SceneSnapshot` of one revision — the renderer's whole input."""
        if index is None or not len(self.chain):
            structure = self.structure
            caption = f"{self.recipe.recipe_id} · empty domain"
            if len(self.chain):
                summary = self.chain.summary(-1)
                caption = f"#{summary.index} {summary.display_name}"
        else:
            summary = self.chain.summary(index)
            structure = self.chain[index].structure
            caption = f"#{summary.index} {summary.display_name}"
        return scene_builder.build(
            structure, library=self.library, overlays=overlays, caption=caption
        )

    def log_lines(self, revision: Revision) -> tuple[str, ...]:
        """One step's contribution to the run log: what it did, and what the gate said."""
        head = revision.history.describe()
        measurements = [
            f"    {name} = {quantity}" for name, quantity in revision.measurements.items()
        ]
        lineage = [f"    {line}" for line in revision.lineage.describe()]
        return (head,) + tuple(f"    {line}" for line in revision.logs) + tuple(
            measurements
        ) + tuple(lineage)

    # -- saving --------------------------------------------------------------

    def save_recipe(self, path: str | os.PathLike[str]) -> Path:
        """Write **only** the recipe: one JSON file, no structures (plan §9).

        The cheap half of saving, and the one worth doing often. A recipe is a few
        kilobytes of text that a person can read, diff, mail and edit; a build is
        every `phi` of every revision, which for the etch-stop demo is a couple of
        hundred megabytes and half a minute. Keeping them one operation meant
        paying the second price for the first thing.

        `.recipe.json` is appended when the name has no suffix, so a file dialog
        that returns a bare name still produces something whose type is legible in
        a directory listing.
        """
        target = Path(path)
        if not target.suffix:
            target = target.with_suffix(RECIPE_SUFFIX)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(recipe_to_json(self.recipe), indent=1, sort_keys=True),
            encoding="utf-8",
        )
        return target

    def save_build(self, path: str | os.PathLike[str]) -> tuple[Path, Path]:
        """Write the recipe **and** every computed revision, side by side.

        `foo` produces `foo.recipe.json` and `foo/` — the recipe as its own file,
        readable and loadable without touching the structures, and next to it a
        directory with one file pair per step. Returns both.

        The directory keeps its **own** copy of the recipe (`session.json`, where
        it has always been), so it stays loadable if somebody moves it away from
        its sibling. Two copies of one recipe is normally the drift this
        repository refuses; here it is the difference between a folder that is a
        saved session and a folder that is half of one, and the pair is written in
        a single operation from a single source.
        """
        target = Path(path)
        if target.suffix == RECIPE_SUFFIX or target.name.endswith(RECIPE_SUFFIX):
            target = target.parent / target.name[: -len(RECIPE_SUFFIX)]
        recipe_file = self.save_recipe(target.with_suffix(RECIPE_SUFFIX))
        directory = self.save(target)
        self.save_artifacts(directory)
        return recipe_file, directory

    def save_artifacts(self, directory: str | os.PathLike[str]) -> tuple[Path, ...]:
        """Write what the inspection steps produced into the build's folder (E40).

        The second half of E40, and the reason the sink is a memory one: a
        session accumulates payloads for free while it runs, and they become
        files at the moment a folder exists to put them in. A session nobody
        saves keeps them in memory and loses them, which is the right trade — a
        profilometer trace is cheap to produce again and expensive to have
        invented a path for.
        """
        sink = self.sink
        payloads = getattr(sink, "payloads", None)
        if not payloads:
            return ()
        root = Path(directory) / ARTIFACTS_DIR
        root.mkdir(parents=True, exist_ok=True)
        written = []
        for name, payload in payloads.items():
            path = root / f"{name}.npy"
            np.save(path, np.asarray(payload))
            written.append(path)
        return tuple(written)

    def save(self, directory: str | os.PathLike[str]) -> Path:
        """Write the recipe and every revision into one directory (plan §9).

        The original shape of saving, kept because `load` reads it and because a
        directory that carries its own recipe is self-contained. `save_build` is
        this plus the sibling `.recipe.json`, and is what the UI calls.
        """
        directory = Path(directory)
        save_chain(directory, self.chain)
        (directory / SESSION_MANIFEST).write_text(
            json.dumps(recipe_to_json(self.recipe), indent=1, sort_keys=True),
            encoding="utf-8",
        )
        return directory

    def load_recipe(self, path: str | os.PathLike[str]) -> tuple[RecipeStep, ...]:
        """Read a recipe in, **without running it**, and return its steps.

        The chain is emptied and the domain becomes the recipe's own; nothing is
        computed. That is the point: the etch-stop demo is 25 s of solver and the
        chromium grating 11, so a load that ran what it read would make opening a
        file a decision rather than a look.

        What comes back is the steps, so the caller can list them — a recipe with
        no revisions shows an empty revision panel, and the operator has to be
        told what they just opened and that running it is a separate act.
        """
        recipe = recipe_from_json(
            json.loads(Path(path).read_text(encoding="utf-8"))
        )
        self.reset(recipe.grid)
        self.recipe = recipe
        return recipe.steps

    def peek_recipe(self, path: str | os.PathLike[str]) -> tuple[RecipeStep, ...]:
        """The steps in a recipe file, **without** touching this session.

        What the restore prompt needs: "there are six steps waiting" has to be
        answerable before anybody has agreed to anything, and `load_recipe`
        resets the chain.
        """
        recipe = recipe_from_json(json.loads(Path(path).read_text(encoding="utf-8")))
        return recipe.steps

    def run_recipe(self, on_step: "StepCallback | None" = None) -> tuple[Revision, ...]:
        """Run every step of the loaded recipe that has no revision yet.

        Resumable by construction — it starts at `len(self.chain)` — so a run
        stopped by a failing step continues from there once the parameters are
        fixed, instead of starting over. `on_step(index, total, step)` is called
        before each one, which is how the window keeps its status bar and log
        alive without this method knowing what a window is.

        `run` appends to the recipe as well as to the chain, and here the step is
        already in the recipe. So the steps after `index` are lifted off, `run`
        re-appends the one it just ran, and they go back.

        The two paths are written out rather than shared through a `finally`,
        because they restore different things. `run` raises **before** it appends
        — a capability or a parameter is checked ahead of anything moving — so on
        failure the recipe is the truncated prefix and what has to come back is
        the whole original, the failing step included. A `finally` that reattached
        only the tail would quietly delete the step somebody has to go and fix.
        """
        produced: list[Revision] = []
        while len(self.chain) < len(self.recipe.steps):
            index = len(self.chain)
            before = self.recipe.steps
            step = before[index]
            if on_step is not None:
                on_step(index, len(before), step)
            self._replace_steps(before[:index])
            try:
                produced.append(self.run(step.step_id, step.params))
            except BaseException:
                self._replace_steps(before)
                raise
            self._replace_steps(self.recipe.steps + before[index + 1 :])
        return tuple(produced)

    def _replace_steps(self, steps: tuple[RecipeStep, ...]) -> None:
        """Swap the recipe's step list, keeping its grid and id."""
        self.recipe = Recipe(
            grid=self.recipe.grid, steps=tuple(steps), recipe_id=self.recipe.recipe_id
        )

    @property
    def pending(self) -> tuple[RecipeStep, ...]:
        """Recipe steps with no revision yet — what `run_recipe` would run."""
        return self.recipe.steps[len(self.chain) :]

    @classmethod
    def load(
        cls,
        directory: str | os.PathLike[str],
        *,
        registry: ProcessRegistry | None = None,
        library: MaterialLibrary | None = None,
        store: RevisionStore | None = None,
        resident: int = 3,
    ) -> "Session":
        """Read a saved session back, ready to be continued or replayed."""
        directory = Path(directory)
        recipe = recipe_from_json(
            json.loads((directory / SESSION_MANIFEST).read_text(encoding="utf-8"))
        )
        session = cls(
            recipe.grid,
            registry=registry,
            library=library,
            recipe_id=recipe.recipe_id,
            store=store,
            resident=resident,
        )
        session.recipe = recipe
        session.chain = load_chain(directory, store=store, resident=resident)
        return session


def default_grid() -> Grid:
    """The domain a fresh session starts on — 300 nm wide with room to grow up."""
    return cross_section_grid(width=300.0, thickness=40.0, headroom=200.0)


def demo_recipe(registry: ProcessRegistry | None = None) -> tuple[Grid, tuple[RecipeStep, ...]]:
    """S1's naive lift-off, as the steps a session would run (plan §1).

    What the application opens with, so the first thing anybody sees is a chain
    that produces a pattern rather than an empty domain. It is the acceptance
    scenario itself, not a mock-up of one.

    Since M8 there are four demos and they live in `ui.demos` with the sentence
    that says what to watch for in each. This stays as the shorthand for the
    first of them — and **delegates** rather than repeating it, because two
    definitions of one recipe is exactly the drift this repository keeps refusing
    everywhere else.
    """
    from nanofab_v3.ui.demos import lift_off

    demo = lift_off()
    return demo.grid, demo.steps


def autosaved_recipe_path() -> Path:
    """Where `write_autosave` puts the recipe — the session half of the cache."""
    from nanofab_v3.ui.wafer import session_cache_dir

    return session_cache_dir() / AUTOSAVE_FILE


__all__ = [
    "ARTIFACTS_DIR",
    "AUTOSAVE_FILE",
    "CapabilityError",
    "ParameterError",
    "RECIPE_SUFFIX",
    "SESSION_MANIFEST",
    "Session",
    "autosaved_recipe_path",
    "default_grid",
    "demo_recipe",
]
