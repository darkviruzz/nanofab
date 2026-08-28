# ADR-0001: Cross-section geometry model for iterative process steps

- Status: Proposed
- Date: 2026-08-24
- Scope: `cross_section_general_prototype.py`, with a follow-on for `nanofab_modular/domain.py`
- Supersedes: nothing (first ADR in this repo)

## Context

The prototype must support isotropic etching, anisotropic etching and deposition,
and it must support an **iterative** workflow: remove a little material, inspect,
remove a little more, inspect — without accumulating geometric artifacts.

This ADR records what the current model does, what was measured, and what has to
change. All numbers below were produced against the prototype's own default scene
(`build_base_state(cap_corner_radius_nm=18, trench_depth_nm=60, trench_radius_nm=40)`,
`arc_chord_nm=4.0`) with PySide6 6.11.2 offscreen.

### The model as implemented

There are **two** geometry representations and a **one-way** conversion between them:

1. **Analytic (authoritative on paper)** — `CrossSectionState.regions: list[Region2D]`,
   each holding an `InterfaceLoop` = ordered `list[Segment2D]` of `LineSegment` |
   `ArcSegment`. Exact, arc-preserving, CCW-normalised.
2. **Working (authoritative in practice)** — `material_paths: dict[material_id, QPainterPath]`,
   produced once by `material_paths_from_regions()`.

Every process operation (`deposit_blanket`, `deposit_conformal`, `etch_isotropic`,
`etch_anisotropic`, `deposit_directional`, `etch_selective`, `lift_off`) takes and
returns `material_paths`. **None of them writes back to `state.regions`, and there is
no `paths → regions` inverse.** `loop_to_path()` also flattens arcs to polylines at
`arc_chord_nm` immediately, so the booleans never see a curve in the first place.

## Findings

### F1 — There is no persistent state; the scene is rebuilt from scratch on every render

`PrototypeModel.build_scene()` calls `build_base_state(...)` as its first statement.
Every slider move and every toggle re-derives the whole scene from virgin substrate
and applies exactly one process for `process_time_s`. `CrossSectionCardWindow` wires
all controls to `refresh_scene`; there is no *Apply step* action. The only way to
chain two operations is the hard-coded `MODE_COMBINED` branch.

An iterative process is therefore not merely artifact-prone here — it is
**not expressible**.

### F2 — Anisotropic etch and directional deposition stall after the first iteration

`_extract_directional_surface_chains()` iterates `self.state.regions` — the *frozen
base loops* — and uses `material_paths` only as a mask deciding which parts of the
**original** segments are still exposed. `_surface_sample_visible_to_source()`
computes shadowing against `_extract_full_outer_surface_chains()`, which is again
`self.state.regions`.

Surfaces created *by* a process (etched trench walls, deposited shells) have no
segment representation at all, so they are invisible to every directional operation.

Measured — 8 × 0.5 s anisotropic etch on `core`, 12 rays, 0°:

```
i=0: exposed-chain len = 1305.1 nm   area = 46755.3
i=1: exposed-chain len = 1305.1 nm   area = 46652.6
i=2: exposed-chain len = 1305.1 nm   area = 46652.6
...
i=7: exposed-chain len = 1305.1 nm   area = 46652.6
```

The exposed-chain length never changes; the area stops changing after step 1.
**Iterations 2..8 remove exactly zero material.** Worse, splitting a dose makes the
process do *less* work: 1 × 4.0 s leaves area 45930.7, while 20 × 0.2 s leaves
46713.5.

### F3 — Vertex count grows without bound, cost grows superlinearly

Each operation builds its band with `QPainterPathStroker` over a polyline and then
`subtracted()` / `united()`. The result is re-polygonised at the stroker's own
resolution and never re-fitted. Nothing in the mutation path calls
`_simplify_closed_points` — that helper is used only in the read-only analysis path
(`_extract_exposed_boundary`, `extract_topology_edges`).

Measured — isotropic etch on `core`, 0.2 s per step:

| step | subpaths | points | area | cumulative wall |
|-----:|---------:|-------:|-----:|----------------:|
|  1 | 2 |   58 | 46611.9 |  0.00 s |
| 10 | 2 |  334 | 45324.9 |  0.17 s |
| 20 | 2 |  768 | 43904.4 |  2.09 s |
| 30 | 2 | 1234 | 42493.7 |  9.39 s |
| 40 | 2 | 1704 | 41092.9 | 22.77 s |
| 50 | **8** | 2171 | 39702.1 | 48.32 s |
| 60 | 2 | 2602 | 38321.1 | 85.29 s |

≈ +43 vertices per step for a shape that is not becoming more complex. Per-step cost
rises from ~0.02 s to ~3.7 s (≈200×). Conformal deposition is worse still:
20 × 0.2 s → 3273 points and **54.16 s**, versus 275 points and **0.01 s** for the
equivalent single shot.

### F4 — Transient spurious topology — these are the actual artifacts

At step 50 the core splits into **8 subpaths** and is back to 2 at step 60: six
sliver fragments appear and vanish. Conformal deposition at n=10 yields 2 metal
subpaths where n=1, n=5 and n=20 yield 1. These slivers are far below any physical
feature size; they come from stroker/boolean round-off and nothing filters them.

Area also depends on how the dose is split — conformal: 9674.4 (1 shot) vs 9635.4
(20 steps), −0.4 %.

### F5 — The offset band is symmetric, so etching and deposition are the same operation

`_band_from_marked_surface()` and `_offset_band_from_chain_span()` both stroke the
*surface curve*, which produces a band on **both** sides.
`_offset_band_from_chain_span` even does `del outward` — the parameter is accepted
and discarded. Correctness is then rescued after the fact by intersecting or
subtracting against the material path.

Two consequences: `RoundJoin`/`RoundCap` rounds every convex corner by exactly
`delta_nm`, and the inner half of the band reaches into material that should not
move. Over N iterations the corner rounding **compounds** — a sharp corner keeps
getting rounder even under purely vertical etching.

The one function that builds a correct **one-sided** offset and honours `outward`
(`_offset_band_from_segment_piece`) has **zero call sites**.

### F6 — Removal depth is averaged over a whole exposed span

```python
# _offset_band_from_chain_span
stroker.setWidth(max(0.2, total_delta_nm * avg_incidence * 2.0))
```

`avg_incidence` is the mean cosine factor over the entire connected span. A trench
bottom (incidence ≈ 1) and its sidewall (incidence ≈ 0) inside one span therefore
receive the same removal depth. Because span segmentation changes as the geometry
evolves, the averaging window changes from iteration to iteration — the same nominal
dose gives different results depending on how it is split.

### F7 — `steps_per_s` is a phantom parameter

`_iter_time_steps()` and `_directional_band_from_spans()` have **no call sites**.
Every operation computes `_total_delta_nm = rate × time` in one shot;
`deposit_conformal` and `etch_isotropic` literally `del steps_per_s`. The slider is
threaded through the whole API and printed in the info line
(`time/steps: 4.00s @ 2.00Hz`) and then dropped.

The prototype currently has **no sub-stepping at all**. The "iterative growth
overlays" from commit `9b5ab14` were superseded and the machinery left behind.

### F8 — `top_only` uses a hard-coded magic cut plane

```python
top_limit = self.state.extent[1] + 0.42 * (self.state.extent[3] - self.state.extent[1])
# = -33.20 nm for the default extent
```

An absolute y-plane unrelated to the sample. Any surface that recedes past it
silently changes behaviour mid-run — directly hostile to iteration.

### F9 — Dead model fields and dead solver code

- `Region2D.tags`, `Region2D.props` — never read or written.
- `CrossSectionState.operation_log` — written once in `build_base_state`, never appended.
- The previous ray-hit-span solver is unreachable: `_directional_spans_from_surface_rays`,
  `_local_hit_span_on_chain`, `_surface_chain_path_between_hits`, `_path_strip_score`,
  `_directional_incidence_weight`, plus `_iter_time_steps` and
  `_directional_band_from_spans` — roughly 250–300 lines.
- `scan_surface_rays()` is still called by both directional operations, but its
  `traces` are used **for display only**; the physics comes from
  `_directional_band_from_surface_chains`, which runs its own occlusion test. The
  rays are cosmetic and are paid for on every frame.

### F10 — The modular engine's data model cannot hold any of this

`nanofab_modular/domain.py` models the sample as `list[Layer]` with a scalar
`thickness: Quantity` plus `coverage: str`. There is no lateral coordinate, so
undercut, sidewall angle, trench profile and shadowing are unrepresentable, and there
is **no etch step at all** in `nanofab_modular/steps/`.

`ProcessEngine`, on the other hand, already has exactly the right skeleton for
iteration: an append-only `revisions: list[SampleState]` and a `run_step()` that
clones → mutates → appends. That pattern should be reused, not reinvented.

## Decision

### D1 — Make the evolving geometry the state, not a re-derived render

Split `build_scene()` into `apply_step(state, operation, params) -> state'` and
`render(state) -> SceneSnapshot`. Keep an append-only list of geometry revisions with
provenance (which operation, which parameters, which dose), mirroring
`ProcessEngine.revisions`. The UI gets *Apply* / *Undo* / *Reset*; sliders configure
the *next* step instead of silently replaying from virgin substrate.

### D2 — One geometry representation, closed under process operations

Collapse the `state.regions` / `material_paths` split into a single `Boundary` type
per material: a list of closed loops, each an ordered vertex list with per-vertex
provenance (source segment id where known, `None` for process-created surfaces).
**Every** operation must both consume and produce it.

Options considered:

- **(a) Exact segment kernel** — keep line/arc loops authoritative and implement
  segment-level booleans and offsets. Most accurate, largest effort.
- **(b) Polyline authoritative + canonicalisation contract** — accept flattening,
  bound the damage explicitly.
- **(c) Hybrid** — polyline authoritative, provenance retained, arcs re-fitted where
  curvature is consistent.

**Decision: (b) now, (c) as the target.** The blocking defect (F2) is not arc
precision — it is that process-created surfaces have *no representation at all*. Arc
exactness is currently only ever used for the base geometry anyway, since
`loop_to_path()` flattens before the first boolean.

### D3 — Canonicalise after every operation (this is what bounds the artifacts)

Mandatory post-step pass, in this order:

1. drop subpaths with |area| < `min_feature_nm²` (sliver filter — fixes F4),
2. weld vertices closer than `eps_weld`,
3. decimate with `eps_geom` ≪ min feature,
4. re-assert CCW orientation and loop closure,
5. snap to the domain extent within tolerance.

Measured effect — isotropic etch, 40 × 0.2 s, naive Ramer–Douglas–Peucker decimation:

| canonicalisation | points @ i=40 | area @ i=40 | cumulative wall |
|---|---:|---:|---:|
| off | 1704 | 41092.9 | 22.32 s |
| RDP ε = 0.25 nm | **50** | 41530.5 | **0.15 s** |
| RDP ε = 0.50 nm | 32 | 41455.9 | 0.12 s |

Vertex count goes flat, runtime drops ~150×. **But note the accuracy cost:** naive
RDP leaves ≈ +1.07 % more material after 40 steps, because a perpendicular-distance
criterion systematically shaves concave corners. Therefore use an **area-preserving**
criterion (Visvalingam–Whyatt effective area, or a decimation that redistributes the
removed area) rather than plain RDP, and add the area balance to D8.

All tolerances live in one `GeometryTolerances` dataclass derived from a single
`min_feature_nm`. The current magic numbers (`probe_nm=0.8`, sample steps `2.0`/`4.0`/`8.0`,
`1e-4`, `0.42`, `640`) get replaced by derived values.

### D4 — One-sided offsets with per-sample dose

Replace stroker bands with a true one-sided offset of the surface polyline.
`_offset_band_from_segment_piece` already does this correctly for a single segment —
generalise it to a chain and actually call it. Evaluate incidence and rate **per
sample point** and build a *variable-width* offset, instead of `avg_incidence` per
span (fixes F6). Handle corners explicitly: miter for convex corners under
directional etch, arc join only for isotropic, where round corners are physically
correct.

This is what finally makes isotropic and anisotropic *different in the model*,
rather than "same symmetric band, different masking".

### D5 — Always recompute exposure and shadowing from the current state

Remove the `self.state.regions` dependency from `_extract_directional_surface_chains`
and `_extract_full_outer_surface_chains`. Occluders and exposed chains must be
derived from the current boundary. **This is the single change that unblocks
iteration (F2).**

### D6 — Make sub-stepping real and adaptive

Either implement `_iter_time_steps` or delete `steps_per_s`. Decision: implement, but
drive it from a stability criterion rather than a UI slider — choose `dt` such that
`rate · dt ≤ α · min_feature_nm` (α ≈ 0.25) and such that no front advances more than
one canonicalisation tolerance per sub-step.

This decouples the *user-visible* iteration ("etch 5 s, inspect, continue") from the
*numerical* sub-step, and it is what makes N × (t/N) converge to 1 × t.

### D7 — Move the rate model into the operation signature

Operations currently take loose `rate_nm_s` floats while `ProcessInteractionModel` is
only half-used. Let operations take a `ProcessInteractionModel` (rate per material,
selectivity, angular distribution, isotropic/directional fraction) so that
isotropic, anisotropic and selective etching become **one** `etch(state, model, dose)`
with different angular distributions. `etch_selective` — today just a loop over
`etch_isotropic` — collapses into it.

### D8 — Validate after every step (the "inspect" half of the loop)

`validate_loops()` exists but only ever runs on the base state. Promote it to a
post-step gate: closure, self-intersection, orientation, no inter-material overlap,
no sliver below min feature, and an **area balance** check
(removed area ≈ ∫ rate · dt · exposed length, within tolerance) — that last one is
what catches the D3 decimation bias. Store the result on the revision so a suspicious
step is visible instead of silent.

### D9 — Reconcile with `nanofab_modular`

Add the cross-section boundary as an optional field on `SampleState` next to
`layers`, so existing 1D-stack steps keep working while geometry-aware steps operate
on the cross-section. Then add the missing `EtchStep` module. Keep
`ProcessEngine.revisions` as the single revision chain — do not build a second one in
the prototype.

## Consequences

Suggested order, cheapest-and-most-unblocking first:

1. **F7 / F9 cleanup + `GeometryTolerances`** — low risk, makes the rest readable.
2. **D1 persistent revisions + Apply/Undo** — makes the problem testable at all.
3. **D3 canonicalisation contract** — bounds artifacts and runtime immediately (~150×).
4. **D5 current-state exposure** — fixes the anisotropic stall; biggest single win.
5. **D4 one-sided variable-width offsets** — fixes corner-rounding compounding.
6. **D6 adaptive sub-stepping + D8 invariants** — makes dose splitting consistent.
7. **D7 process model, D9 modular integration.**

Accepted costs:

- Under D2(b) arcs remain polylines; analytic curvature is not recovered until D2(c).
  `CONTEXT.md` already flags `Facet` as unsettled — this ADR resolves the surrounding
  geometry question but not the `Facet` naming.
- Canonicalisation introduces a bounded, *measurable* volume error instead of an
  unbounded, unmeasured one. D8's area balance is the guard.
- Steps 1–2 change public signatures inside the prototype; per `AGENTS.md` §7 a
  `ui_backups/` snapshot should be taken before starting step 2.
