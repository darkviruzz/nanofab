# Handoff: milestone M5 (delivery — plugins, packaging, the last processes, the wafer view)

- Written 2026-08-26, at the end of M4
- Specification: `docs/plans/v2-structure-model.md` §5.4, §6, §8, §11, §14, with the
  corrections in §17 (M0/M1), §18 (M2), §19 (M3) and §20 (M4); decisions in
  ADR-0002…0004; vocabulary in `CONTEXT.md`
- **DoD (plan §14)**: entry-point plugins, PyInstaller monolith, particles/clean,
  anneal, wafer materialization UI (position fan). *Packaged exe runs S1–S4.*

Read `memory.md` from 2026-08-25 onward first; this file only covers what M5
needs that the plan does not already say.

## 1. What you are building on

`nanofab_v3` is M0 + M1 + M2 + M3 + M4 complete: **314 tests green**, `python -m
compileall nanofab_v3 tests` clean. Validation is both, per `AGENTS.md` §4.

```
nanofab_v3/
  model/      Grid, Structure, FieldKey/FieldSpec, Occurrence/Lineage,
              ValidationReport, Quantity, capability
  kernel/     csg, constructors, contours, measures, stencil, motion, reinit,
              occurrences, gate, invariants, flux, predicates, regions
  materials/  MaterialType, MaterialLibrary, didactic_library      (6 materials)
  processes/  contract, rates, substrate, lithography, deposition, etching,
              removal, registry, engine                           (18 steps)
  runtime/    revision, run, replay        Revision/RevisionChain, Recipe/Run,
                                           effective_params, materialize
  io/         manifest, exchange, store    .npz + JSON, FileRevisionStore,
                                           ReplayCache
  ui/         scene, session, canvas, panels, window
```

M4 was the first milestone that was not proving the model works. **M5 is the
first that is not building the model at all** — every line of it is either
packaging, a view, or one of the four processes plan §6 lists and M3/M4
deliberately left out. The failure mode changes again: M0–M3 could be wrong in
ways a test caught, M4 in ways a person scrubbing a chain notices, and M5 in ways
that only appear **in the frozen exe on somebody else's machine**. Budget for
that: the packaging step is not a build command, it is a test surface.

`ui_backups/2026-08-25_v0.2.0_nanofab-manager/nanofab_manager.spec` is a working
PyInstaller recipe for the *old* app and is worth reading before writing a new
one — but it is a record, not a branch (`AGENTS.md` §7).

## 2. The seams M5 plugs into

Every one of these exists, is tested, and was built for this milestone.

```python
processes.registry.ProcessRegistry.register(step)     # the plugin seam
processes.registry.builtin_registry() -> ProcessRegistry
```

Plan §11's "registry + entry points from day 1" is **half** true: the registry
exists and every builtin goes through `register()`, which is the mechanism a
plugin will use. What does not exist is discovery — `builtin_registry()` is a
plain function with a hard-coded list, and nothing reads
`importlib.metadata.entry_points`. That is deliberate (a seam exercised by every
test beats a discovery mechanism designed against nothing) and it is yours.
`register()` already refuses a duplicate `step_id` and lints for a
process-global RNG (§5.2), so the two rules a plugin can break are enforced at
the door.

```python
runtime.Run(recipe, registry=..., library=..., cache=..., positions=[...])
    .add_position((x, y)) / .chain(position) / .positions / .structures()
runtime.positions_on_radius(radius, count) -> tuple[Position, ...]
runtime.RadialProfile / runtime.LinearTilt          # parameters over the wafer
runtime.effective_params(recipe, position, step)
```

**The wafer materialization engine is done.** A `Run` covers an extensible
position set, materializes each on first access, and caches per position. What
M5 owes plan §14 is the *view*: a position fan the operator can click, and a way
to compare two positions' final structures. `Run.structures()` returns exactly
that dict, and adding a position later is the ordinary path rather than a re-run
— which is what ADR-0004 rejected eager fan-out to get.

```python
processes.contract.StepResult(structure, ..., artifacts=(), measurements={})
runtime.Revision.artifacts: tuple[ArtifactRef, ...]
runtime.apply_step(..., artifacts=[ArtifactRef(...)])
```

The artifact plumbing inspection steps were waiting on. **One wire is missing on
purpose**: `apply_step` takes `artifacts` as an argument and no registered step
produces any, so `StepResult.artifacts` does not reach `Revision.artifacts`. It
is a one-line change and doing it before the first producing step would have
been untested plumbing (memory.md 2026-08-26, risk 3). SEM / profilometer /
ellipsometer are the first producers, and they are §6 rows M3 left out.

```python
kernel.constructors.ball(grid, center, radius)      # a particle
kernel.predicates.reachable_occurrences(structure, material)
kernel.regions.remove_region(structure, mask, materials=(...))
```

Particles and clean, in three calls. §6: *"Particles: seeded disk constructors of
a particle material"*, *"Clean: remove particle material where reachable
(micromasking = unreachable survivors)"*. The whole didactic point is that a
particle under a later film is **unreachable**, so clean leaves it and the
defect it caused stays — which the reachability predicate already answers.
Particles are also the **first stochastic step in the codebase**: everything
about §5.2's RNG contract has been tested against a step written in a test file
(`tests/test_runtime.py`), never against a registered one.

```python
io.manifest.code_version() -> str                   # currently __version__
io.store.recipe_hash(steps) / cache_key(recipe, position, index)
runtime.RecipeStep.fingerprint() -> str
```

ADR-0004's cache key. Read §3 before touching any of it.

## 3. The one design decision M5 has to make first

**What is the "code version" in the cache key, once a plugin can change the
answer?**

ADR-0004 keys every cached revision on `(recipe hash, position, step index, code
version)`, and promises determinism "per machine + code version". M4 implemented
`code_version()` as `nanofab_v3.__version__` and wrote down that bumping it is
"the intended and only mechanism" for retiring a cache. That is honest while the
only code that can change is this package's. It stops being honest the moment a
plugin ships a step: a third-party `deposit.mocvd` can change its rate model
without `nanofab_v3.__version__` moving, and every revision cached with the old
one is then served as if it were current. Nothing errors; the numbers are just
quietly from the previous version.

The same hole is already open one step smaller, without plugins: editing a
builtin step's own wrapper during development does not move `__version__`
either, so a warm cache survives a code change it should not.

**Recommendation: two axes, and put the plugin one in the *recipe* hash rather
than in the code version.**

- `code_version()` stays `__version__` and covers the parts a recipe cannot
  name: the kernel, numpy/scipy, the interpreter. Bumped by hand, retires
  everything. That is the axis ADR-0004's "cross-machine float drift" paragraph
  is about, and it should stay coarse.
- `RecipeStep.fingerprint()` gains the **registered step's implementation
  digest** — its `step_id`, `fidelity`, parameter schema, capability contract,
  and `inspect.getsource` of its own wrapper. Then editing a step invalidates
  exactly the recipes that use it, and editing an unused plugin invalidates
  nothing. Measured: **3.0 ms per step, 53 ms for all 18**, so a six-step
  recipe pays ~18 ms per `recipe_hash` call and it memoises per step object.

State the limit honestly in the docstring, because it is not obvious: the digest
covers the step's **wrapper**, not the kernel it calls. `deposit.evaporate`'s
`run_function` is 16 lines; a change in `kernel/flux.py` does not move it. That
is the division of labour — the wrapper is what a plugin owns, the kernel is what
`__version__` owns — and it only works if both are actually maintained.

A frozen build has no source for `inspect.getsource`, exactly as
`registry._uses_global_rng` already documents. Decide there and say so: falling
back to the schema and capability contract alone is defensible for an exe whose
plugin set is fixed at build time, and it is the same argument §5.2's lint
already makes about being best-effort.

## 4. Traps M0–M4 hit that will bite M5 in the same places

All are written up in plan §17–§20; the short version, plus the ones that recur.

1. **A number measured on one scene is a statement about that scene.** §20's own
   theme, and M5 is where it costs the most, because the thing being measured is
   a *packaged application on somebody else's machine*. Do not accept "starts in
   2 s" from a warm dev box as a startup budget; measure the exe, cold, once.
2. **A correct set operation can be a useless field.** Fifth milestone running
   (§17.2, §18.7, §19.2, §20.5). M5's exposure is **particles**: a disk
   constructor placed on an existing stack has to be carved against it
   (`constructors.add_material` does this) and a particle that lands *inside*
   existing solid is a set operation that succeeds and means nothing. Decide
   what a particle on a surface means geometrically before writing the step.
3. **Never read geometry off `structure.solid_phi`** where two materials touch;
   use `motion.union_front`. Fourth milestone this has bitten. Anneal, if it ever
   moves geometry (curvature-driven reflow is plan §16, deliberately open), is
   the next candidate.
4. **An extension is only valid near the front** (§18.5, §19.5, §20.6). The
   wafer view's exposure: a position fan that rebuilds a `SceneSnapshot` per
   position per frame is 107 ms × N. Build per selection, not per paint.
5. **Ordinary geometry breaks tolerances tuned on smooth scenes** (§18.6). A
   particle is a disk of a few cells; check what the band invariant does to one
   before tightening anything.
6. **Eviction without a store is deletion** (§20.7). The same shape will come
   back in any cache-eviction policy M5 adds for a many-position run.

## 5. Budget: what you are adding to

Measured at the reference grid (540×1200 at 1 nm); plan §17.7, §18.8, §19.6 and
§20.8 have the full tables.

| | |
|---|---|
| S1 solved, six steps | 7.6 s |
| the same, replayed from a warm cache | **0.11 s** (68×) |
| one revision saved / loaded | 14–71 ms / 7.5–34 ms |
| a six-step chain on disk | 0.50 MB |
| `SceneSnapshot.build` / canvas repaint | 107.5 / 11.9 ms |
| per-step implementation digest (§3) | 3.0 ms |
| complete directional step, 4 nm | 0.6–0.7 s |
| heavy 60 s directional etch | ~10 s |

Two things follow. **A position fan is a background-job problem, not a rendering
one**: nine positions of a 20-step recipe is ~4 minutes of solver and 1 second of
I/O, so the view has to show partial results and the plan already calls for job
management (docs §9.2). **A warm cache is the whole feature** — 68× — so the
fan's second look at a position must hit it, which means the fan and the cache
share a directory rather than each having their own.

What still dominates is the upwind stencil over the whole domain (§17.7,
unchanged through four milestones). A true narrow-band solver remains the
structural fix that is deliberately not built, and M5 is the wrong place to
start: it would invalidate every cached revision on the same day the exe ships.

## 6. Suggested order

1. **The cache key** (§3). Settle it before anything else, because particles are
   the first step whose *output* depends on the seed, so they are the first place
   a stale cache entry is visibly wrong rather than merely wrong.
2. **Particles and clean** (§6). `ball` constructors from `ctx.rng`, a particle
   material in the library, `reachable_occurrences` for clean. The didactic
   payload is micromasking: a particle buried under a film is unreachable, clean
   leaves it, and the defect stays. That is an acceptance scenario in its own
   right (call it S5) and it is the honest test of §5.2's RNG contract, which no
   *registered* step has ever exercised.
3. **Inspection steps** (§6). SEM / profilometer / ellipsometer: return the input
   structure unchanged plus artifacts and measurements. Wire
   `StepResult.artifacts` through to `Revision.artifacts` here — §2 says why it
   is not wired yet. This is what makes "etch, inspect, etch, inspect" four plain
   steps (interview Q6), which the chain has been able to express since M4 and
   has never been asked to.
4. **Anneal** (§6). Field and material-model updates only; reflow geometry is
   plan §16 and stays open. The interesting part is that it is the first step
   that changes a `MaterialType`'s behaviour rather than the structure, and
   `StepContext.library` is passed in rather than stored, so decide where an
   annealed material's new rates live.
5. **Entry-point plugins** (§11, §5.4). `importlib.metadata.entry_points` feeding
   the same `register()` every builtin uses. Ship one in-tree example plugin, in
   its own package, that a test installs — a discovery mechanism with no second
   implementer is a discovery mechanism that does not work yet.
6. **The wafer view** (§8, §14). The position fan over `Run`. The engine is done;
   this is a view plus a job runner.
7. **PyInstaller** (§11). One exe, builtins and numpy/scipy frozen. **DoD is that
   the exe runs S1–S4**, so the acceptance scenarios need a path that does not go
   through pytest — a `--selftest` flag or a menu entry. Decide which and say so.

## 7. Conventions that are not optional

- `memory.md` gets an entry per `AGENTS.md` §5 (date, what, why, how validated).
  M0–M4's entries are the template; the *decisions taken where the plan left
  detail open* section is the part that earns its keep later.
- Focused commits, `feat:` / `test:` / `docs:` / `fix:` / `chore:`.
- If the plan turns out to be wrong again, amend it the way §17–§20 do: leave the
  agreed text, add the correction **with the measurement that showed it**, and
  point at it from the affected line. Four milestones have now found something;
  assume M5 will too, and note that §20's findings were about *values and costs*
  rather than structure — M5's will most likely be about the exe.
- `ui_backups/` snapshots are records, not branches — never edit one in place
  (`AGENTS.md` §7). Before the exe ships, the current source state is worth a
  snapshot of its own.
- The two named 2D kernel seams stay two (`contours`, `flux`); `ui.scene` is the
  third 2D module and is outside the kernel by decision. If M5 needs a fourth,
  name it and check it the way those three do.
- **`nanofab_v3.ui.scene` and `ui.session` import no Qt**, and
  `tests/test_ui.py` asserts it in a subprocess. That is ADR-0001's finding as a
  rule rather than a convention: anything that decides geometry, and everything
  that drives a run, stays on the Qt-free side. A wafer view is a view.
