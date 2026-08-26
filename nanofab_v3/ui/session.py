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
from typing import Any, Iterable, Mapping, Sequence

from nanofab_v3.io.exchange import load_chain, save_chain
from nanofab_v3.kernel.domain import DomainPolicy
from nanofab_v3.io.manifest import recipe_from_json, recipe_to_json
from nanofab_v3.materials import MaterialLibrary, MaterialType, didactic_library
from nanofab_v3.materials.unknown import UnknownMaterials, unknown_materials
from nanofab_v3.model.grid import Grid
from nanofab_v3.model.structure import Structure
from nanofab_v3.processes.contract import CapabilityError, ParameterError
from nanofab_v3.model.artifact import ArtifactSink
from nanofab_v3.processes.plugins import DiscoveryReport, application_registry
from nanofab_v3.processes.registry import ProcessRegistry
from nanofab_v3.processes.substrate import cross_section_grid
from nanofab_v3.runtime.replay import apply_step, materialize
from nanofab_v3.runtime.revision import CENTER, Revision, RevisionChain, RevisionStore
from nanofab_v3.runtime.run import Position, Recipe, RecipeStep
from nanofab_v3.ui import scene as scene_builder
from nanofab_v3.ui.scene import SceneSnapshot

SESSION_MANIFEST = "session.json"
"""Name of the recipe file next to a saved session's revision directory."""


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
        sink: Where an inspection step may put an artifact, or `None`.
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
        self.sink = sink
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
        return revision

    def rewind(self, index: int) -> None:
        """Drop revision `index` and everything after it, recipe included."""
        self.chain.rewind(index)
        self.recipe = Recipe(
            grid=self.recipe.grid,
            steps=self.recipe.steps[:index],
            recipe_id=self.recipe.recipe_id,
        )

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

    def save(self, directory: str | os.PathLike[str]) -> Path:
        """Write the whole session: the recipe and every revision (plan §9)."""
        directory = Path(directory)
        save_chain(directory, self.chain)
        (directory / SESSION_MANIFEST).write_text(
            json.dumps(recipe_to_json(self.recipe), indent=1, sort_keys=True),
            encoding="utf-8",
        )
        return directory

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
    """
    from nanofab_v3.materials import METAL, RESIST, SILICON

    grid = cross_section_grid(width=300.0, thickness=40.0, headroom=200.0)
    steps = (
        RecipeStep("substrate.select", {"material": SILICON, "surface": 40.0}),
        RecipeStep("resist.spin_coat", {"material": RESIST, "thickness": 90.0}),
        RecipeStep(
            "litho.expose_ideal",
            {"material": RESIST, "pattern": "window", "center": 150.0, "width": 100.0},
        ),
        RecipeStep("develop.ideal", {"material": RESIST}),
        RecipeStep("deposit.evaporate", {"material": METAL, "thickness": 20.0}),
        RecipeStep("strip.lift_off", {"material": RESIST}),
    )
    return grid, steps


__all__ = [
    "CapabilityError",
    "ParameterError",
    "SESSION_MANIFEST",
    "Session",
    "default_grid",
    "demo_recipe",
]
