# Handoff: milestone M4 (runtime, persistence, replay, UI)

- Written 2026-08-25, at the end of M3
- Specification: `docs/plans/v2-structure-model.md` §3.6, §8, §9, §10, with the
  corrections in §17 (M0/M1), §18 (M2) and §19 (M3); decisions in ADR-0002…0004;
  vocabulary in `CONTEXT.md`
- **DoD (plan §14)**: revisions, runs, persistence, replay + cache; UI
  integration (render from φ, chain UI on capabilities). *Save/load/replay
  round-trip; interactive session usable.*

Read `memory.md` from 2026-08-24 onward first; this file only covers what M4
needs that the plan does not already say.

## 1. What you are building on

`nanofab_v3` is M0 + M1 + M2 + M3 complete: **249 tests green**, `python -m
compileall nanofab_v3 tests` clean. Validation is both, per `AGENTS.md` §4.

```
nanofab_v3/
  model/      Grid, Structure, FieldKey/FieldSpec, Occurrence/Lineage,
              ValidationReport, Quantity, capability
  kernel/     csg, constructors, contours, measures, stencil, motion, reinit,
              occurrences, gate, invariants, flux, predicates, regions
  materials/  MaterialType, MaterialLibrary, didactic_library
  processes/  contract, rates, substrate, lithography, deposition, etching,
              removal, registry, engine       (18 registered steps)
  runtime/    io/                             (empty placeholders — both yours)
```

**S1–S4 are green**, which plan §14 makes the definition of done for the whole
structure model. M4 is therefore the first milestone that is not proving the
model works — it is making it *usable*, and the failure mode changes with that:
M0–M3 could be wrong in ways a test caught, M4 can be wrong in ways only a person
scrubbing through a chain notices.

The kernel is N-D generic apart from two **named** 2D-only seams, `contours` and
`flux`. `predicates` was deliberately kept N-D (§19.1) — do not let the renderer
drag a third one in by accident: rendering is 2D by decision (plan Q7, §10), and
that is the seam to put it behind.

## 2. The seams M4 plugs into

Every one of these exists, is tested, and was built for this milestone.

```python
processes.engine.run_step(step, structure, params, *, library, capabilities,
                          recipe_id, position, index, policy, tolerances)
    -> StepOutcome(step_id, structure, report, lineage, capabilities,
                   measurements, logs)
processes.engine.run_chain(steps, structure, *, library, recipe_id, position,
                           strict) -> tuple[StepOutcome, ...]
```

`run_step` already does four of plan §5's five obligations: validate the
parameters, gate on capabilities, run the step, commit through `kernel.gate`.
**What it does not do is remember** — there is no `Revision`, no history entry,
no artifact list, no index. That is §3.6 and it is yours. `StepOutcome` is
deliberately shaped as the part of a `Revision` the process layer can produce on
its own; the natural move is for `Revision` to *wrap* one rather than replace it.

```python
processes.engine.step_seed(recipe_id, position, index) -> int
```

ADR-0004's determinism invariant, already the seed of `StepContext.rng`. A blake2b
hash rather than an arithmetic combination, so neighbouring positions do not
produce correlated streams. **Replay materialization rests entirely on this**, and
there is a standing test that a chain run twice produces bit-identical fields.

```python
kernel.gate.commit(...) -> CommitOutcome(structure, report, lineage, capabilities)
```

Complete as of M3 — all six of plan §4.5's steps. `capabilities` is what the
chain UI gates on, and `registry.blocked_reason(step_id, capabilities)` is the
sentence to put in the tooltip: it names the missing *promise about the sample*,
which is the thing an operator can act on. `registry.by_technique()` groups the
fidelity tiers of one technique, which is what lets the step list offer
"Deposition → ALD (geometric / reachability-gated)" as one entry.

```python
kernel.contours.marching_squares(grid, field, level=0.0) -> list[np.ndarray]
kernel.contours.material_contours(structure) -> dict[MaterialId, list]
Structure.material_index                     # int16, EMPTY = -1
occurrences.label_occurrences(structure)     # the derived stack summary
predicates.*                                 # the inspect overlays
```

Plan §10's whole input. `material_contours` is the sub-cell smooth path,
`material_index` the QImage fast path, and `label_occurrences` is what §3.6 means
by "where the UI wants a stack summary, it is derived" — v1's 1D layer list is
not stored and must not come back.

## 3. The one design decision M4 has to make first

**Is a `Revision` a stored `Structure`, or a position in a replayable recipe?**

Everything else hangs off it: the persistence format's granularity, the cache
key, what scrubbing back through a chain costs, and whether a 60-step run fits in
memory. Plan §3.6 lists `structure: Structure` as a field, which reads like the
first answer; plan §8 specifies lazy replay with a cache, which reads like the
second. Both are in the agreed text and they are not the same design.

The numbers that decide it, measured at the reference grid (540×1200 at 1 nm):

| | |
|---|---|
| one `phi` array | 2.59 MB |
| one revision, 2 materials + 1 field | 5.83 MB raw |
| the same revision, `savez_compressed` | **0.04 MB** (137×, lossless) |
| a 20-step chain held in RAM | ~116 MB |
| the same chain on disk | **~0.8 MB** |

The compression ratio is not luck and is worth understanding before you design
around it: a signed-distance field on a grid is piecewise linear, so it takes
very few distinct values — **2964 distinct float32 values in 648 000 cells** on a
scene that had just been ion-beam etched for 30 s. zlib eats that. Round-trip is
bit-identical, verified.

**Recommendation: a `Revision` stores its `Structure`, and the *chain* is what is
lazy.** Keep the last few revisions resident, spill the rest to the `.npz` cache
of §9, and fault them back in on demand — 10 ms per load, measured, which is
below a UI frame. That gives you §3.6's field as written *and* §8's laziness,
because the expensive thing was never the format, it was holding twenty of them
at once. Replay from substrate stays the fallback for a cache miss and the
mechanism for a new wafer position, which is exactly what ADR-0004 needs it for.

**A second decision, and it is nearly free:** revisions currently share **no**
arrays at all. Measured on the S1 chain: zero arrays shared by identity between
consecutive revisions, *including* silicon between `substrate.select` and
`resist.spin_coat`, where the content is bit-identical. The commit gate
reinitialises every material on every commit and hands back a fresh array. Making
`reinit.reinitialise` return its input when the field did not move — or having
`gate.commit` keep the parent's array when the material's region is unchanged —
would collapse a chain's footprint by roughly the fraction of materials a step
does not touch, which in a lithography chain is most of them. It also makes
`Structure`'s "arrays are shared cheaply between revisions" docstring true, which
it currently is not.

## 4. Traps M0–M3 hit that will bite M4 in the same places

All are written up in plan §17–§19; the short version, plus the ones that recur.

1. **A correct set operation can be a useless field.** Fourth milestone running.
   M3's version: a carved material field is exactly zero along interfaces between
   two *other* materials, so `phi_m <= 0` claimed the resist covered the whole
   domain (§19.2). M4's exposure to this is the **renderer** — `marching_squares`
   over `phi_m` will happily draw a contour along a phantom zero level. Use
   `regions.closed_region` where you need a region, and check any new picture
   against `label_occurrences` before believing it.
2. **Never read geometry off `structure.solid_phi`** where two materials touch;
   use `motion.union_front`. Third milestone this has bitten. The renderer and
   any new measurement are the next places.
3. **An extension is only valid near the front.** The flux collar (§18.5) and the
   reachability collar (§19.5) are the same finding twice, and both got cheaper
   by windowing. Anything M4 computes over the whole domain per frame — an
   overlay, a hit test — should ask whether it needs to.
4. **Ordinary geometry breaks tolerances tuned on smooth scenes** (§18.6). If you
   add an invariant, work out what the shape itself forces the number to be
   before tightening it.
5. **Two boxes that share a face leave a zero-valued seam** which `solid_mask`
   reads as solid (§17.1). Every scene a UI lets a user build by hand has this
   shape. The constructors' `carve=True` handles it; a hand-built `Structure`
   does not.

## 5. Budget: what you are adding to

Measured at the reference grid; plan §17.7, §18.8 and §19.6 have the full tables.

| | |
|---|---|
| `savez_compressed` one revision | 22–28 ms |
| `np.load` round-trip | 10 ms |
| blake2b content hash of one `phi` | 4.4 ms |
| `marching_squares` on the union | 21 ms |
| `material_contours`, all materials | 28 ms |
| `material_index` map | 15 ms |
| `label_occurrences` | 54 ms |
| complete directional step, 4 nm | 0.6–0.7 s |
| complete ideal-tier step (region op) | 0.2–0.3 s |
| heavy 60 s directional etch | ~10 s |
| S1 end to end, 6 steps at 241×301 | **0.53 s** |

Two things follow. **Persistence is a non-issue** — a revision is 40 KB and a
save is 30 ms, so save/load/cache can be simple and eager rather than clever.
**Rendering is not free but is not the problem either**: a full re-contour is
21–28 ms, which is a frame, so the thing to avoid is re-contouring on every mouse
move, not contouring at all. What still dominates is the upwind stencil over the
whole domain (§17.7, unchanged through three milestones), and a true narrow-band
solver remains the structural fix that is deliberately not built.

A 20-step replay at the reference grid is therefore roughly 10–20 s of solver
plus 0.6 s of I/O — inside plan §8's "seconds to ~a minute", and background-job
territory exactly as docs §9.2 already requires.

## 6. Suggested order

1. **`Revision` and the chain** (§3.6). Wrap `StepOutcome`, add `index`,
   `parent`, `HistoryEntry` (step id, params snapshot, timing) and
   `artifacts: list[ArtifactRef]`. Append-only, exactly like
   `ProcessEngine.revisions` was. Settle §3's decision here, because the next
   three items all read it.
2. **`io/` — the exchange format** (§9). `.npz` plus a JSON manifest with
   `schema_id: "structure.v2"`, grid, material ids, capabilities, history and
   content hashes; unknown keys ignored on load. Do the round-trip test first and
   make it bit-identical — it is the one property the cache's correctness rests on.
3. **`Run` and positions** (§8, ADR-0004). One recipe over a set of wafer
   positions, default `{center}`; `effective_params(recipe, position, step)`
   resolving parameterised recipe values before they reach `StepContext`. The
   solver already never sees a position, which is the invariant to keep.
4. **Replay + cache**, keyed `(recipe hash, position, step, code version)`. The
   determinism test in `tests/test_processes.py` is the thing that makes this
   sound; extend it to "replay at a new position equals a fresh run at that
   position".
5. **The UI**, last and deliberately: the `nanofab_manager` shell in
   `ui_backups/2026-08-25_v0.2.0_nanofab-manager/` carries over as *the shell* —
   step list, gating, parameter forms, run log — with gating rewired from step
   ids to capabilities (`registry.blocked_reason` gives the sentence). The
   cross-section canvas is rewritten against `SceneSnapshot v2`: contours plus
   overlays, no `QPainterPath` in anything that decides geometry. That was v1's
   central defect (ADR-0001) and the reason this rewrite exists.

## 7. Conventions that are not optional

- `memory.md` gets an entry per `AGENTS.md` §5 (date, what, why, how validated).
  M0–M3's entries are the template; the *decisions taken where the plan left
  detail open* section is the part that earns its keep later.
- Focused commits, `feat:` / `test:` / `docs:` / `fix:` / `chore:`.
- If the plan turns out to be wrong again, amend it the way §17, §18 and §19 do:
  leave the agreed text, add the correction **with the measurement that showed
  it**, and point at it from the affected line. Three milestones have now found
  something; assume M4 will too.
- `ui_backups/` snapshots are records, not branches — never edit one in place
  (`AGENTS.md` §7). The v0.2.0 UI is read *from* there and rewritten *here*.
- The two named 2D seams stay two. If the renderer needs a third, name it and
  check it the way `contours` and `flux` do.
