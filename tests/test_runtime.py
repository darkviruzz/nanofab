"""Revisions, runs, positions and replay — plan §3.6, §8, ADR-0004, milestone M4.

M4 is the first milestone that is not proving the model works. What it can get
wrong is different in kind: a chain that drops a revision, a cache that serves
one recipe's answer for another, a position whose parameters leaked into the
solver. So the tests here are about **identity and provenance** rather than about
geometry, and the load-bearing one is the last section's: replaying a recipe at a
wafer position that was never run has to produce exactly the sample that position
would have had, because ADR-0004 rejected eager fan-out on the strength of it.
"""

from __future__ import annotations

import inspect
from dataclasses import replace
from unittest import mock

import numpy as np
import pytest

from nanofab_v3 import FieldKey, Grid, Structure
from nanofab_v3.io import (
    DirectoryArtifactSink,
    FileRevisionStore,
    ReplayCache,
    cache_key,
    load_revision,
    recipe_hash,
    replay_cache_for,
    save_revision,
)
from nanofab_v3.materials import METAL, RESIST, SILICON, didactic_library
from nanofab_v3.model.artifact import MemoryArtifactSink
from nanofab_v3.model.quantity import Quantity
from nanofab_v3.processes import (
    IDEAL,
    PHYSICAL,
    FunctionStep,
    ParamSpec,
    ProcessRegistry,
    StepContext,
    StepResult,
    builtin_registry,
    implementation_digest,
    run_chain,
    step_seed,
)
from nanofab_v3.processes.substrate import cross_section_grid
from nanofab_v3.runtime import (
    CENTER,
    ArtifactRef,
    HistoryEntry,
    LinearTilt,
    MemoryRevisionStore,
    RadialProfile,
    Recipe,
    RecipeStep,
    Revision,
    RevisionChain,
    Run,
    StepFailed,
    apply_step,
    effective_params,
    materialize,
    positions_on_radius,
    run_recipe,
)

EDGE = (60.0, 0.0)
"""A wafer position 60 mm from the centre — where a radial profile has bitten."""


@pytest.fixture(scope="module")
def registry() -> ProcessRegistry:
    return builtin_registry()


@pytest.fixture(scope="module")
def library():
    return didactic_library()


@pytest.fixture
def grid() -> Grid:
    return cross_section_grid(width=200.0, thickness=40.0, headroom=140.0)


@pytest.fixture
def litho(grid: Grid) -> Recipe:
    """substrate -> resist -> ideal exposure -> ideal development."""
    return Recipe(
        grid=grid,
        recipe_id="litho",
        steps=(
            RecipeStep("substrate.select", {"material": SILICON, "surface": 40.0}),
            RecipeStep("resist.spin_coat", {"material": RESIST, "thickness": 60.0}),
            RecipeStep(
                "litho.expose_ideal", {"material": RESIST, "center": 100.0, "width": 60.0}
            ),
            RecipeStep("develop.ideal", {"material": RESIST}),
        ),
    )


@pytest.fixture
def graded(grid: Grid) -> Recipe:
    """The same chain with a resist thickness that thins towards the wafer edge.

    Plan §8's "rate radial profiles as per-position rates", at the one place a
    didactic recipe can show it without a stochastic step: the coat is 60 nm in
    the centre and 40 nm at 60 mm out, so two positions are visibly different
    samples produced by one recipe.
    """
    return Recipe(
        grid=grid,
        recipe_id="graded",
        steps=(
            RecipeStep("substrate.select", {"material": SILICON, "surface": 40.0}),
            RecipeStep(
                "resist.spin_coat",
                {
                    "material": RESIST,
                    "thickness": RadialProfile(radii=(0.0, 60.0), values=(60.0, 40.0)),
                },
            ),
            RecipeStep(
                "litho.expose_ideal", {"material": RESIST, "center": 100.0, "width": 60.0}
            ),
            RecipeStep("develop.ideal", {"material": RESIST}),
        ),
    )


def _phi(chain: RevisionChain, index: int, material: str) -> np.ndarray:
    return np.asarray(chain[index].structure.phi_of(material))


def _same_sample(a: RevisionChain, b: RevisionChain) -> bool:
    """Whether two chains are the same sample — structures and promises, not clocks."""
    if len(a) != len(b):
        return False
    for index in range(len(a)):
        first, second = a[index], b[index]
        if first.capabilities != second.capabilities:
            return False
        if first.structure.materials != second.structure.materials:
            return False
        for material in first.structure.materials:
            if not np.array_equal(_phi(a, index, material), _phi(b, index, material)):
                return False
        if set(first.structure.fields) != set(second.structure.fields):
            return False
        for key in first.structure.fields:
            if not np.array_equal(
                np.asarray(first.structure.field(key)), np.asarray(second.structure.field(key))
            ):
                return False
    return True


# -- 1. the revision and its chain (plan §3.6) --------------------------------


def test_a_revision_wraps_the_outcome_and_adds_where_it_sits(litho, registry, library) -> None:
    """`StepOutcome` is the part a step can produce; the chain supplies the rest."""
    chain = run_recipe(litho, registry=registry, library=library)

    assert [r.index for r in chain.summaries] == [0, 1, 2, 3]
    assert chain[0].parent is None
    assert [chain[i].parent for i in range(1, 4)] == [0, 1, 2]
    assert chain[1].history.step_id == "resist.spin_coat"
    assert chain[1].history.recipe_id == "litho"
    assert chain[1].history.position == CENTER
    assert chain[1].history.started_at
    assert chain[1].history.duration_s > 0.0


def test_the_history_snapshot_is_what_actually_ran(litho, registry, library) -> None:
    """Defaults filled, `Quantity` unwrapped: the params a replay has to reproduce.

    A recipe may leave a parameter out and a caller may pass a `Quantity`; the
    solver saw neither. Recording what the recipe *said* rather than what ran
    would make a saved file describe a chain nobody executed.
    """
    recipe = Recipe(
        grid=litho.grid,
        recipe_id="quantities",
        steps=(
            RecipeStep(
                "substrate.select",
                {"material": SILICON, "surface": Quantity(40.0, "nm")},
            ),
        ),
    )

    chain = run_recipe(recipe, registry=registry, library=library)

    assert chain[0].history.params["surface"] == 40.0
    assert isinstance(chain[0].history.params["surface"], float)
    assert "headroom_warning" not in chain[0].history.params


def test_a_chain_is_append_only(litho, registry, library) -> None:
    chain = run_recipe(litho, registry=registry, library=library)
    stray = Revision(
        index=99,
        parent=3,
        structure=chain[3].structure,
        capabilities=chain[3].capabilities,
        history=HistoryEntry(index=99, step_id="nowhere"),
    )

    with pytest.raises(ValueError, match="append-only"):
        chain.append(stray)


def test_rewinding_drops_what_no_longer_describes_what_happened(
    litho, registry, library
) -> None:
    """The one deliberate truncation: re-running from the middle discards the tail."""
    chain = run_recipe(litho, registry=registry, library=library)

    chain.rewind(2)

    assert len(chain) == 2
    assert [entry.step_id for entry in chain] == ["substrate.select", "resist.spin_coat"]
    with pytest.raises(IndexError):
        chain[2]


def test_a_chain_without_a_store_never_drops_a_revision(litho, registry, library) -> None:
    """Eviction with nowhere to spill to is deletion, so residency does not apply.

    Found while building M4: with the LRU applied unconditionally, a four-step
    chain at the default residency of three silently lost revision 0, and the
    error it raised named the store rather than the bug.
    """
    chain = run_recipe(litho, registry=registry, library=library, resident=1)

    assert chain.store is None
    assert all(chain.is_resident(index) for index in range(len(chain)))
    assert chain[0].step_id == "substrate.select"


def test_a_chain_with_a_store_spills_and_faults_back(litho, registry, library) -> None:
    """Plan §8's laziness: the chain is lazy, the revision is not (see `runtime`)."""
    store = MemoryRevisionStore()
    chain = run_recipe(litho, registry=registry, library=library, store=store, resident=1)

    assert chain.spills == 3
    assert not chain.is_resident(0)
    assert chain.faults == 0

    first = chain[0]

    assert chain.faults == 1
    assert first.step_id == "substrate.select"
    assert chain.is_resident(0)


def test_the_step_list_reads_summaries_and_faults_nothing(litho, registry, library) -> None:
    """What makes scrubbing a 60-step chain cheap: a row is bytes, not megabytes."""
    store = MemoryRevisionStore()
    chain = run_recipe(litho, registry=registry, library=library, store=store, resident=1)

    rows = [(entry.index, entry.display_name, entry.ok) for entry in chain]
    capabilities = chain.capabilities
    log = chain.logs()

    assert len(rows) == 4
    assert all(ok for _, _, ok in rows)
    assert f"material:{RESIST}" in capabilities
    assert len(log) >= 4
    assert chain.faults == 0


def test_a_failing_step_stops_a_strict_run(grid, registry, library) -> None:
    overflowing = Recipe(
        grid=grid,
        recipe_id="too-thick",
        steps=(
            RecipeStep("substrate.select", {"material": SILICON, "surface": 40.0}),
            RecipeStep("resist.spin_coat", {"material": RESIST, "thickness": 400.0}),
        ),
    )

    with pytest.raises(StepFailed, match="headroom"):
        run_recipe(overflowing, registry=registry, library=library)


# -- 2. wafer positions (plan §8) ---------------------------------------------


def test_a_radial_profile_interpolates_and_holds_its_ends() -> None:
    profile = RadialProfile(radii=(0.0, 50.0, 100.0), values=(10.0, 20.0, 15.0))

    assert profile.at(CENTER) == pytest.approx(10.0)
    assert profile.at((25.0, 0.0)) == pytest.approx(15.0)
    assert profile.at((0.0, 50.0)) == pytest.approx(20.0)
    assert profile.at((150.0, 0.0)) == pytest.approx(15.0)  # held, never extrapolated
    assert profile.at((30.0, 40.0)) == pytest.approx(20.0)  # radius, not an axis


def test_a_linear_tilt_is_a_per_position_offset() -> None:
    """Plan §8's wafer bow: an incidence-angle offset, not a geometry change."""
    tilt = LinearTilt(center=15.0, gradient=(0.05, -0.02))

    assert tilt.at(CENTER) == pytest.approx(15.0)
    assert tilt.at((100.0, 0.0)) == pytest.approx(20.0)
    assert tilt.at((0.0, 100.0)) == pytest.approx(13.0)


def test_effective_params_resolves_before_the_solver_sees_anything(graded) -> None:
    """The seam ADR-0004 rests on, asserted at the seam itself."""
    centre = effective_params(graded, CENTER, 1)
    edge = effective_params(graded, EDGE, 1)

    assert centre["thickness"] == pytest.approx(60.0)
    assert edge["thickness"] == pytest.approx(40.0)
    assert isinstance(edge["thickness"], float)
    assert not any(hasattr(value, "at") for value in edge.values())


def test_a_plain_parameter_is_the_same_everywhere(litho) -> None:
    assert effective_params(litho, CENTER, 1) == effective_params(litho, EDGE, 1)


def test_the_solver_never_receives_a_wafer_parameter(graded, registry, library) -> None:
    """Position-blindness, checked by watching what reaches `StepContext`."""
    seen: list[dict] = []

    def _watch(ctx: StepContext) -> StepResult:
        seen.append(dict(ctx.params))
        return StepResult(structure=ctx.structure)

    watcher = FunctionStep(
        step_id="inspect.watch",
        display_name="Watch",
        fidelity=IDEAL,
        schema=(),
        required=frozenset(),
        provided=frozenset(),
        run_function=_watch,
    )
    local = ProcessRegistry()
    for step in registry:
        local.steps[step.step_id] = step
    local.register(watcher)
    recipe = Recipe(
        grid=graded.grid,
        recipe_id="watched",
        steps=graded.steps + (RecipeStep("inspect.watch"),),
    )

    run_recipe(recipe, registry=local, library=library, position=EDGE)

    assert seen == [{}]
    assert all(not hasattr(value, "at") for params in seen for value in params.values())


def test_a_position_fan_is_deterministic() -> None:
    first = positions_on_radius(50.0, 4)
    again = positions_on_radius(50.0, 4)

    assert first == again
    assert len(set(first)) == 4
    assert first[0] == pytest.approx((50.0, 0.0))


# -- 3. the recipe hash and the cache key (ADR-0004) --------------------------


def test_the_recipe_hash_sees_a_changed_parameter(litho) -> None:
    """A cache key that cannot see a parameter change serves the wrong answer."""
    thicker = Recipe(
        grid=litho.grid,
        recipe_id=litho.recipe_id,
        steps=litho.steps[:1]
        + (RecipeStep("resist.spin_coat", {"material": RESIST, "thickness": 61.0}),)
        + litho.steps[2:],
    )

    assert recipe_hash(litho) == recipe_hash(litho)
    assert recipe_hash(litho) != recipe_hash(thicker)
    assert recipe_hash(litho) != recipe_hash(Recipe(litho.grid, litho.steps[:3], "litho"))


def test_the_recipe_hash_sees_a_changed_wafer_profile(graded) -> None:
    """Two equal profiles hash the same; a different one does not."""
    same = Recipe(
        grid=graded.grid,
        recipe_id=graded.recipe_id,
        steps=(
            graded.steps[0],
            RecipeStep(
                "resist.spin_coat",
                {
                    "material": RESIST,
                    "thickness": RadialProfile(radii=(0.0, 60.0), values=(60.0, 40.0)),
                },
            ),
        )
        + graded.steps[2:],
    )
    steeper = Recipe(
        grid=graded.grid,
        recipe_id=graded.recipe_id,
        steps=(
            graded.steps[0],
            RecipeStep(
                "resist.spin_coat",
                {
                    "material": RESIST,
                    "thickness": RadialProfile(radii=(0.0, 60.0), values=(60.0, 30.0)),
                },
            ),
        )
        + graded.steps[2:],
    )

    assert recipe_hash(same) == recipe_hash(graded)
    assert recipe_hash(steeper) != recipe_hash(graded)


def test_the_cache_key_separates_positions_steps_and_code_versions() -> None:
    assert cache_key("r", CENTER, 3) == cache_key("r", CENTER, 3)
    assert cache_key("r", CENTER, 3) != cache_key("r", CENTER, 4)
    assert cache_key("r", CENTER, 3) != cache_key("r", EDGE, 3)
    assert cache_key("r", CENTER, 3) != cache_key("s", CENTER, 3)


# -- 3b. the second axis: the implementation digest (M5, plan §21.1) ----------


def test_the_implementation_digest_is_stable_and_specific(registry) -> None:
    """The same step digests the same; two different steps do not."""
    evaporate = registry["deposit.evaporate"]

    assert implementation_digest(evaporate) == implementation_digest(evaporate)
    assert implementation_digest(evaporate) != implementation_digest(registry["deposit.sputter"])
    assert registry.digest("deposit.evaporate") == implementation_digest(evaporate)


def test_the_digest_moves_when_the_contract_moves(registry) -> None:
    """A changed schema, fidelity or capability contract is a changed step.

    None of these is executable, and all of them change what the step means to a
    recipe — a parameter that gained a default, a bound that got tighter, a
    promise the step no longer makes.
    """
    original = registry["deposit.evaporate"]
    base = implementation_digest(original)

    retuned = replace(
        original,
        schema=original.schema[:-1]
        + (ParamSpec("divergence", float, unit="deg", default=0.0, maximum=60.0),),
    )
    repromised = replace(original, provided=frozenset({"metal.deposited"}))
    redeclared = replace(original, fidelity=PHYSICAL)

    assert implementation_digest(retuned) != base
    assert implementation_digest(repromised) != base
    assert implementation_digest(redeclared) != base


def test_the_digest_moves_when_the_wrapper_moves(registry) -> None:
    """The point of the whole decision: an edited step retires its own cache."""
    original = registry["deposit.evaporate"]

    def _run_evaporate_but_slower(ctx):  # pragma: no cover - never run
        return original.run_function(ctx)

    edited = replace(original, run_function=_run_evaporate_but_slower)

    assert implementation_digest(edited) != implementation_digest(original)


def test_a_source_less_step_falls_back_and_says_so() -> None:
    """A frozen build has no `getsource`, and its digest is marked `nosrc:`.

    The fallback is the contract alone, which is defensible for an exe whose
    plugin set is fixed at build time. What is *not* defensible is a frozen build
    and a source install trading cache entries under a key that claims they are
    the same code, so the marker is part of the digest.
    """
    step = FunctionStep(
        step_id="test.sourceless",
        display_name="Sourceless",
        fidelity=IDEAL,
        schema=(),
        required=frozenset(),
        provided=frozenset(),
        run_function=lambda ctx: StepResult(ctx.structure),
    )
    with_source = implementation_digest(step)
    assert with_source.startswith("src:")

    with mock.patch.object(inspect, "getsource", side_effect=OSError("frozen")):
        without = implementation_digest(step)
    assert without.startswith("nosrc:")
    assert without != with_source


def test_the_recipe_hash_sees_an_edited_step_only_with_a_registry(litho, registry) -> None:
    """The hole M5 closed: `code_version()` does not move when a step is edited.

    Two registries differing in one step's implementation must hash a recipe
    that *uses* that step differently — and a recipe that does not use it
    identically, which is what keeps an unused plugin from retiring anything.
    """
    edited = ProcessRegistry()
    for step in registry:
        if step.step_id == "resist.spin_coat":

            def _thicker(ctx, _original=step.run_function):  # pragma: no cover
                return _original(ctx)

            step = replace(step, run_function=_thicker)
        edited.register(step)

    substrate_only = Recipe(litho.grid, litho.steps[:1], litho.recipe_id)

    assert recipe_hash(litho, registry=registry) != recipe_hash(litho, registry=edited)
    assert recipe_hash(substrate_only, registry=registry) == recipe_hash(
        substrate_only, registry=edited
    )
    # And without a registry the change is invisible — which is exactly why the
    # cache seam passes one (`replay_cache_for`).
    assert recipe_hash(litho) == recipe_hash(litho)
    assert recipe_hash(litho) != recipe_hash(litho, registry=registry)


def test_replay_cache_for_keys_on_the_digest(litho, registry, tmp_path) -> None:
    """The one call a cache site makes, and it carries the registry."""
    cache = replay_cache_for(tmp_path / "cache", litho, registry=registry)

    assert cache.recipe == recipe_hash(litho, registry=registry)
    assert cache.recipe != recipe_hash(litho)


def test_a_recipe_naming_an_unregistered_step_still_hashes(litho, registry) -> None:
    """A saved file reopened without its plugin is a display problem, not a failure."""
    unknown = litho.with_step(RecipeStep("plugin.absent", {"dose": 1.0}))

    assert recipe_hash(unknown, registry=registry)
    assert recipe_hash(unknown, registry=registry) != recipe_hash(litho, registry=registry)


# -- 4. replay: the property ADR-0004 rejected eager fan-out for --------------


def test_replaying_the_same_position_reproduces_it(litho, registry, library) -> None:
    first = run_recipe(litho, registry=registry, library=library)
    second = run_recipe(litho, registry=registry, library=library)

    assert _same_sample(first, second)


def test_replay_at_a_new_position_equals_a_fresh_run_at_that_position(
    graded, registry, library, tmp_path
) -> None:
    """ADR-0004's whole promise, and the one thing M4 cannot be right without.

    A run that has only ever seen the centre gains a position at the wafer edge.
    Replaying with that position's resolved parameters — through a cache warm
    with the *centre's* revisions, which is the state that would make a
    position-blind key serve the wrong sample — has to give exactly what running
    the edge from scratch gives, and it has to be a different sample from the
    centre's.
    """
    cache = ReplayCache(tmp_path / "cache", recipe_hash(graded))

    centre = materialize(graded, CENTER, registry=registry, library=library, cache=cache)
    replayed = materialize(graded, EDGE, registry=registry, library=library, cache=cache)
    fresh = run_recipe(graded, registry=registry, library=library, position=EDGE)

    assert _same_sample(replayed, fresh)
    assert not _same_sample(replayed, centre)
    # The edge took nothing from the warm centre — a key that dropped the
    # position would have served four of the centre's revisions as the edge's,
    # and every assertion above would still have to be re-derived to notice.
    assert cache.hits == 0
    # One miss per run, not one per step: the prefix walk stops at the first gap,
    # because step k needs the structure after k-1 and a hit past a miss is not a
    # shortcut.
    assert cache.misses == 2
    assert cache.stats()["writes"] == 2 * len(graded)
    assert _same_sample(
        materialize(graded, CENTER, registry=registry, library=library, cache=cache), centre
    )
    assert cache.hits == len(graded)


def test_a_stochastic_step_replays_per_position_and_not_across_them(
    grid, registry, library, tmp_path
) -> None:
    """Plan §5.2's contract at the one place randomness enters the model.

    Nothing in the didactic set is stochastic yet (particles are M5), so the step
    that proves it is built here: it writes `ctx.rng` into a field. Two positions
    must differ, and each must be reproducible — which is exactly what makes
    adding a position later sound rather than merely convenient.
    """

    def _roll(ctx: StepContext) -> StepResult:
        noise = ctx.rng.random(ctx.grid.shape).astype(np.float32)
        return StepResult(
            structure=ctx.structure.with_field(FieldKey("damage", SILICON), noise),
            provides=frozenset({f"{SILICON}.damage"}),
        )

    roller = FunctionStep(
        step_id="anneal.roll",
        display_name="Roll",
        fidelity=IDEAL,
        schema=(),
        required=frozenset({f"material:{SILICON}"}),
        provided=frozenset({f"{SILICON}.damage"}),
        run_function=_roll,
        stochastic=True,
    )
    local = ProcessRegistry()
    for step in registry:
        local.steps[step.step_id] = step
    local.register(roller)
    recipe = Recipe(
        grid=grid,
        recipe_id="rolled",
        steps=(
            RecipeStep("substrate.select", {"material": SILICON, "surface": 40.0}),
            RecipeStep("anneal.roll"),
        ),
    )

    key = FieldKey("damage", SILICON)
    centre = run_recipe(recipe, registry=local, library=library)
    centre_again = run_recipe(recipe, registry=local, library=library)
    edge = run_recipe(recipe, registry=local, library=library, position=EDGE)

    assert np.array_equal(
        np.asarray(centre[1].structure.field(key)),
        np.asarray(centre_again[1].structure.field(key)),
    )
    assert not np.array_equal(
        np.asarray(centre[1].structure.field(key)),
        np.asarray(edge[1].structure.field(key)),
    )
    assert step_seed("rolled", CENTER, 1) != step_seed("rolled", EDGE, 1)


def test_a_warm_cache_serves_the_sample_it_computed(litho, registry, library, tmp_path) -> None:
    """A hit has to be indistinguishable from the solve it replaces."""
    cache = ReplayCache(tmp_path / "cache", recipe_hash(litho))

    computed = materialize(litho, CENTER, registry=registry, library=library, cache=cache)
    assert cache.stats()["writes"] == len(litho)

    served = materialize(litho, CENTER, registry=registry, library=library, cache=cache)

    assert cache.hits == len(litho)
    assert _same_sample(computed, served)
    assert served[2].history.params == computed[2].history.params


def test_a_cache_from_another_recipe_is_not_consulted(
    litho, graded, registry, library, tmp_path
) -> None:
    """One directory, two recipes: the key keeps them apart, not the filesystem."""
    directory = tmp_path / "cache"
    materialize(
        litho,
        CENTER,
        registry=registry,
        library=library,
        cache=ReplayCache(directory, recipe_hash(litho)),
    )
    other = ReplayCache(directory, recipe_hash(graded))

    materialize(graded, CENTER, registry=registry, library=library, cache=other)

    assert other.hits == 0
    assert other.stats()["writes"] == len(graded)


# -- 5. the Run: one recipe, an extensible set of positions -------------------


def test_a_run_defaults_to_the_centre_and_grows(graded, registry, library, tmp_path) -> None:
    """Plan §8: default `{center}`, and adding a position later is the normal path."""
    run = Run(
        graded,
        registry=registry,
        library=library,
        cache=ReplayCache(tmp_path / "cache", recipe_hash(graded)),
    )

    assert run.positions == (CENTER,)
    centre = run.chain()
    assert run.materialized(CENTER)

    run.add_position(EDGE)
    assert run.positions == (CENTER, EDGE)
    assert not run.materialized(EDGE)

    edge = run.chain(EDGE)

    assert run.materialized(EDGE)
    assert not _same_sample(centre, edge)
    assert _same_sample(edge, run_recipe(graded, registry=registry, library=library, position=EDGE))


def test_each_position_owns_an_independent_chain(graded, registry, library) -> None:
    run = Run(graded, registry=registry, library=library, positions=[CENTER, EDGE])

    centre, edge = run.chain(CENTER), run.chain(EDGE)

    assert centre is not edge
    assert centre.position == CENTER
    assert edge.position == EDGE
    assert centre[1].history.position == CENTER
    assert edge[1].history.position == EDGE
    assert edge[1].history.params["thickness"] == pytest.approx(40.0)


def test_a_run_spills_into_the_cache_it_already_writes(
    graded, registry, library, tmp_path
) -> None:
    """One directory, not two: what a chain drops is what a replay wants back."""
    cache = ReplayCache(tmp_path / "cache", recipe_hash(graded))
    run = Run(graded, registry=registry, library=library, cache=cache, resident=1)

    chain = run.chain()

    assert chain.spills == len(graded) - 1
    assert not chain.is_resident(0)
    assert np.array_equal(
        _phi(chain, 0, SILICON),
        np.asarray(
            run_recipe(graded, registry=registry, library=library)[0].structure.phi_of(SILICON)
        ),
    )


# -- 6. the artifact wire (plan §5.1, milestone M5) ---------------------------


def test_what_a_step_produced_lands_on_the_revision_that_produced_it(
    grid, registry, library
) -> None:
    """The wire M4 left open on purpose (memory.md 2026-08-26, risk 3).

    `apply_step` took `artifacts` as an argument and no registered step supplied
    any, so `StepResult.artifacts` reached nothing. The inspection steps are the
    first producers, and this is the wire closed: sink -> `StepResult` ->
    `StepOutcome` -> `Revision.artifacts`.
    """
    sink = MemoryArtifactSink()
    wafer = apply_step(
        registry["substrate.select"],
        Structure(grid),
        {"material": SILICON, "surface": 40.0},
        index=0,
        parent=None,
        library=library,
    )

    looked = apply_step(
        registry["inspect.sem"],
        wafer.structure,
        {"tag": "rev-1"},
        index=1,
        parent=0,
        capabilities=wafer.capabilities,
        library=library,
        sink=sink,
    )

    assert wafer.artifacts == ()
    (ref,) = looked.artifacts
    assert ref.uri == "memory:sem-rev-1"
    assert ref.kind == "image"
    assert "sem-rev-1" in sink
    assert looked.measurements["features"].value > 0.0


def test_a_caller_can_add_an_artifact_of_its_own_alongside_the_step_s(
    grid, registry, library
) -> None:
    """The pre-M5 argument still works, and the two do not displace each other."""
    sink = MemoryArtifactSink()
    external = ArtifactRef("log", "run.log", "Run log")
    wafer = apply_step(
        registry["substrate.select"],
        Structure(grid),
        {"material": SILICON, "surface": 40.0},
        index=0,
        parent=None,
        library=library,
    )

    looked = apply_step(
        registry["inspect.profilometer"],
        wafer.structure,
        {},
        index=1,
        parent=0,
        capabilities=wafer.capabilities,
        library=library,
        sink=sink,
        artifacts=[external],
    )

    assert len(looked.artifacts) == 2
    assert external in looked.artifacts


def test_an_inspection_shares_every_array_with_its_parent(grid, registry, library) -> None:
    """Plan §20.2's rule doing what an inspection needs it to do.

    An inspection returns the input structure itself, so the gate hands back the
    parent's arrays for every material and the revision costs nothing but its
    own record. Measured on a developed stack: 25 ms for the whole commit, and no
    array copied.
    """
    wafer = apply_step(
        registry["substrate.select"],
        Structure(grid),
        {"material": SILICON, "surface": 40.0},
        index=0,
        parent=None,
        library=library,
    )

    looked = apply_step(
        registry["inspect.ellipsometer"],
        wafer.structure,
        {},
        index=1,
        parent=0,
        capabilities=wafer.capabilities,
        library=library,
    )

    assert looked.validation.shared_with_parent == wafer.structure.materials
    for material in wafer.structure.materials:
        assert looked.structure.phi_of(material) is wafer.structure.phi_of(material)


def test_a_run_hands_its_sink_to_every_position(grid, registry, library, tmp_path) -> None:
    """A wafer fan writes each position's artifacts where that position's are.

    The sink is per `Run`, and `DirectoryArtifactSink`'s prefix is what keeps two
    positions from overwriting each other's trace under the same name.
    """
    recipe = Recipe(
        grid,
        (
            RecipeStep("substrate.select", {"material": SILICON, "surface": 40.0}),
            RecipeStep("inspect.profilometer", {"tag": "final"}),
        ),
        "inspected",
    )
    sink = DirectoryArtifactSink(tmp_path / "artifacts", prefix="centre")
    run = Run(recipe, registry=registry, library=library, sink=sink)

    chain = run.chain(CENTER)
    ref = chain[1].artifacts[0]

    assert ref.uri == "centre/profile-final.npy"
    assert (tmp_path / "artifacts" / ref.uri).exists()
    assert sink.read(ref).shape[0] == 2  # x and height


def test_an_artifact_reference_survives_the_save_load_round_trip(
    grid, registry, library, tmp_path
) -> None:
    """A revision carries where its artifact is, never the artifact (docs §4.2.2)."""
    sink = DirectoryArtifactSink(tmp_path / "artifacts")
    recipe = Recipe(
        grid,
        (
            RecipeStep("substrate.select", {"material": SILICON, "surface": 40.0}),
            RecipeStep("inspect.sem", {"tag": "final"}),
        ),
        "inspected",
    )
    chain = run_recipe(recipe, registry=registry, library=library, sink=sink)
    original = chain[1]

    stem = tmp_path / "rev"
    save_revision(stem, original)
    loaded = load_revision(stem)

    assert loaded.artifacts == original.artifacts
    assert loaded.measurements.keys() == original.measurements.keys()
    # the payload is on disk, not in the file the revision was written to
    assert (tmp_path / "artifacts" / original.artifacts[0].uri).exists()
    assert stem.with_suffix(".json").stat().st_size < 8000


def test_an_empty_registry_is_not_silently_replaced_by_the_builtins(grid, library) -> None:
    """`ProcessRegistry` and `MaterialLibrary` both define `__len__` (plan §21.3).

    So an empty one is **falsy**, and `registry or builtin_registry()` swaps a
    caller's deliberate choice for the defaults without a word. Every such site
    now tests `is None`. The failure this prevents is the quiet kind: a `Run`
    built against a registry that turned out to be empty would run the builtins
    and report success.
    """
    recipe = Recipe(
        grid, (RecipeStep("substrate.select", {"material": SILICON, "surface": 40.0}),), "r"
    )

    run = Run(recipe, registry=ProcessRegistry(), library=library)

    assert len(run.registry) == 0
    with pytest.raises(KeyError, match="substrate.select"):
        run.chain(CENTER)
