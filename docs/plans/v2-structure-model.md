# Plan: Structure Model v2

- Status: Agreed (design interview 2026-08-24/25), implementation not started
- Inputs: ADR-0001 (v1 autopsy, measured), design interview rounds 1–3, ADR-0002…0004
- Scope: a new package (working name `nanofab_v3`, successor of `nanofab_modular`) that
  puts the sample's geometry and state on solid ground. No compatibility with v1
  required. The `ProcessEngine` ideas worth keeping (append-only revisions, artifacts,
  history, gating) are carried over as concepts, not as code.

All numbers in this plan were measured in this repo's environment (numpy 2.4.6 /
scipy 1.17.1, 540×1200 grid unless stated); the probe scripts are described in
`memory.md` entries of 2026-08-24/25.

## 1. Goal and fidelity contract

v2 is a didactic digital twin: it must get **topology and causality** right, not
nanometers. Any cleanroom process must be expressible against the same structure
model, and complexity must live in the **process**, never in the structure model —
the same model holds an idealised binary grating and a partially developed resist
with a 2D dose profile, distinguished only by which materials and processes were
assigned (interview Q1).

Four canonical scenarios define "works":

- **S1 Naive lift-off (ideal)** — substrate → resist → ideal exposure → ideal
  development → evaporation (directional, sidewalls stay bare) → resist dissolution
  (solvent reaches resist through the coverage gaps) → clean metal pattern.
- **S2 Undercut** — isotropic (wet/chemical) etch undercuts a mask; RIE with the same
  nominal depth does not. Undercut ratio is measurable.
- **S3 Lift-off broken by ALD** — same stack as S1, but conformal ALD seals the
  resist sidewalls; the solvent never reaches the resist; nothing lifts. The failure
  must **emerge** from the model (reachability), not be special-cased.
- **S4 Sputter fences** — partial sidewall coverage (broad lobe + surface mobility);
  after dissolution the sidewall metal attached to the substrate film remains
  standing as fences.

Fidelity tiers: (a) didactic-qualitative is the implementation target; (b)
semi-quantitative later means swapping rate models, not rewriting; (c) predictive is
reachable only by delegating to external simulation packages through the process
interface (§5, §11). The structure model must never block (b) or (c).

## 2. Decisions inherited from the interview

| # | Decision | Where detailed |
|---|---|---|
| I1 | Complexity lives in processes; structure model stays uniform across fidelity tiers | §1, §5 |
| I2 | 2D core; data structures must not exclude 3D; wafer position with default "center" | §3.1, §8, ADR-0004 |
| I3 | Material state = discrete material identity + named volumetric fields | §3.3 |
| I4 | numpy + scipy allowed; heavier solvers loadable; plugin registry from day 1, ship as one exe | §11 |
| I5 | No v1 compatibility; keep revisions/artifacts/history/gating as concepts; UI shell reusable | §6, §10 |
| I6 | Geometry is the truth; diagnoses are predicates evaluated on it; UI decides didactics | §7 |
| I7 | Every process is a standalone function `Structure → Structure (+ outputs)`; processes share kernel primitives; several processes may model the same technique at different fidelity | §5 |
| Q1 | Representation: implicit signed-distance fields on a shared grid are the single truth; analytic primitives exist only as constructors | ADR-0002, §3.2 |
| Q2 | Modular registry in source, monolith in delivery, subprocess reserve for big solvers | §11 |
| Q3 | Capability contracts `requires`/`provides`; downgrade adapters allowed and explicit, upgrade impossible | §5.3 |
| Q4 | Two stored tiers (MaterialType, material fields); Occurrence is a derived view; lineage by overlap matching | ADR-0003, §3.5 |
| Q5 | Wafer position is a property of materialization; lazy replay with cache; determinism invariant | ADR-0004, §8 |
| Q6 | User-visible steps are the chain steps themselves ("10 s etch" is one step; inspect is a step); CFL sub-stepping is solver-internal and invisible; grid resolution balances realism vs. speed, a few seconds per heavy step is acceptable | §4.2, §13 |
| Q7 | Dense arrays; N-D-generic core; flux solver and rendering explicitly 2D behind named interfaces; a `Grid` object is the sole spatial authority | §3.1, §4.3 |

## 3. The structure model

### 3.1 Grid

```python
@dataclass(frozen=True)
class Grid:
    origin: tuple[float, ...]   # nm per axis
    spacing: float              # nm, isotropic cells
    shape: tuple[int, ...]      # e.g. (ny, nx); 3D adds an axis, nothing else changes
    axes: tuple[str, ...]       # ("y", "x") — names, never positional assumptions
```

- The Grid is the **sole authority** on positions. No other object stores
  coordinates, extents or spacings.
- Kernel code must be N-D-generic: no hard-coded axis pairs, no Python loops over
  cells. `scipy.ndimage` and `np.gradient` are already N-D; 2D-only code is confined
  to the flux solver and rendering (§4.3, §10) behind named interfaces.
- **Resolution is a visible model parameter** (default 1 nm/cell for ~1200 nm wide
  scenes → 0.65 M cells, 2.6 MB per float32 field). It trades realism against speed
  and is exposed as an advanced setting; a heavy directional step should stay in the
  low seconds (measured budget in §13).
- **Headroom**: the domain is created at substrate selection with configurable empty
  space above the stack. A kernel guard fails a step whose front touches a lateral or
  top boundary (bottom is "solid continues" by boundary condition; → §17.5: lateral
  faces warn rather than fail — a blanket layer reaches them by construction).
  `np.pad` re-embeds
  the arrays if the domain must grow later. This replaces v1's magic
  `0.42 * extent` cut plane and boundary-edge filtering.
- Units: grid and kernel work in plain float nm / s for speed. `Quantity` (docs
  §4.2.1) appears at API boundaries (process parameters, measurements) and is
  validated/converted there.

### 3.2 Geometry: one signed-distance field per material

```python
class Structure:
    grid: Grid
    phi: dict[MaterialId, np.ndarray]   # float32, phi < 0 inside that material
    fields: dict[FieldKey, np.ndarray]  # §3.3; FieldKey = (name, material_id | None)
```

- `phi[m] < 0` means "inside material m". **Derived, never stored as truth**:
  solid union `phi_solid = min_m phi[m]`, empty space `-phi_solid`, the material
  index map `argmin_m phi[m]` (cached per revision for rendering/queries), contours,
  occurrences (§3.5). *(→ §17.1: `min` is sign-correct but is **not** the union's
  distance function where two materials touch.)*
- Set operations are pointwise (`union = min`, `intersection = max`,
  `difference(A,B) = max(phi_A, -phi_B)`): O(cells), local, no boolean cascade, no
  polygonization — the entire v1 fragmentation/sliver failure class (ADR-0001
  F3/F4) is structurally impossible.
- **Only the exposed front ever moves** (§4.2). Etch clips materials against the new
  union (`phi_m ← max(phi_m, phi_solid_new)`); deposition writes the new material
  into `D ∩ empty` (`phi_k ← min(phi_k, max(d_D, -phi_solid_old))`). *(→ §17.2:
  both are correct **set** operations whose values need the gate's repair.)* Buried
  interfaces are never advected, so they keep their sub-cell shape until re-exposed —
  this is why per-material fields were chosen over a single φ + index map
  (ADR-0002): lift-off re-exposes buried interfaces, and a single-φ model would
  return them cell-quantised (staircase). *(→ §18.7: where a directional
  deposition grew nothing, the deposit formula leaves a zero level with no
  interior behind it.)*
- Measured mechanism checks (this environment): a half-plane SDF is exact on the
  grid (linear function, bilinear reconstruction exact); constructed materials are
  overlap-free; conformal growth is one array op (`phi_solid - t`, 20 offsets in
  4.2 ms); on a re-entrant T-profile, ALD t=25 nm over a 40 nm opening seals an
  enclosed void (empty space splits into 2 components), while a straight 40 nm gap
  fills completely with a center seam — both physically correct with zero
  special-casing.
- Field invariants (checked by the commit gate, §4.5): sign correct everywhere;
  `|∇phi| ≈ 1` within a narrow band around each zero level; pairwise-disjoint
  interiors (guaranteed by construction, verified cheaply). *(→ §17.4: the band
  invariant holds at a high quantile, not at the worst cell — a concave crease is
  a point where a correct distance field is not differentiable; → §18.6: so is
  the medial axis of any film thinner than twice the band, which is most of
  them.)*

### 3.3 Fields

Named per-cell quantities on the same grid: `dose` (mJ/cm²), `damage`,
`temperature_history`, `crystal_orientation`, … Two scopes:

- **Global fields** — meaningful everywhere (rare).
- **Material-scoped fields** — keyed `(name, material_id)`, meaningful only where
  that material exists. **Scoping rule (mechanical, enforced by the commit gate):**
  in cells where the owning material was removed or newly created during a step, the
  field is reset to its default. Without this rule, dose from a first lithography
  leaks into resist deposited later.

The ideal/physical split from the interview lives here: ideal exposure writes an
`int8` field `exposed` sampled from a procedural pattern (a constructor — §4.1);
physical exposure writes a `float32` field `dose`. Ideal development consumes
`exposed`; physical development consumes `dose` through the resist's
`develop_rate(dose)` model. Same structure model, different fields (I1, I3).

### 3.4 Materials: type vs. assignment

- **MaterialType** — a library entry: name, display color, optical `n/k`, density,
  per-process-class rate/yield models, crystallographic anisotropy
  (`rate(θ_normal − θ_crystal)`), develop/dissolve models. Pure data + small model
  objects; no geometry.
- A **material in a Structure** is just a MaterialType id owning a `phi` array and
  optionally scoped fields. Nothing else is stored (ADR-0003).

### 3.5 Occurrence: identity by reconstruction

A Materialvorkommen (occurrence) is a connected component of one material,
**derived per revision** (`ndimage.label`, 2.3 ms at 1 nm), never stored. Identity
across revisions is reconstructed by overlap matching against the parent revision
(label + overlap matrix, 5.2 ms measured): the result is a lineage report —
"occurrence #7 split into #7a/#7b", "merged", "vanished". Splits and merges become
findings instead of bookkeeping corner cases; "which metal lifts off" is a
connectivity question (§4.4), not an identity question. See ADR-0003.

### 3.6 Revision and provenance

```python
class Revision:
    index: int
    parent: int | None
    structure: Structure
    capabilities: set[str]            # §5.3
    history: HistoryEntry             # step id, params snapshot, timing — as docs §4.2.6
    artifacts: list[ArtifactRef]      # unchanged concept, docs §4.2.2
    validation: ValidationReport      # §4.5
    lineage: LineageReport            # §3.5
```

Append-only, exactly like `ProcessEngine.revisions` today. A revision chain belongs
to one wafer position (§8). The v1 1D layer list is not stored; where the UI wants a
stack summary, it is **derived** (occurrences ordered by height).

## 4. The kernel

A module of pure functions on `Structure`. No Qt anywhere in it — v1's central
defect (QPainterPath as physics engine) must not reappear. Rendering consumes the
kernel's outputs (§10), never the other way round.

### 4.1 Constructors

Analytic primitives (half-plane, box, rounded box, procedural gratings, imported
polygons, seeded roughness/particle disks) exist **only** as functions that sample an
SDF onto the grid once, at creation time. After that the sampled field is the truth
and the primitive is forgotten (ADR-0002; v1's permanent analytic/`QPainterPath`
dual truth was the root cause of its iteration stall, ADR-0001 F2). A half-plane is
exactly representable; corners are exact to the corner-rounding of ~½ cell.

### 4.2 Motion

- **General path**: advect the union front `phi_solid` with a speed field
  `F(x) = sign · rate(material_at_front(x)) · yield(θ_incidence) · flux(x)`,
  first-order upwind, CFL `dt ≤ 0.5 · spacing / max|F|` (one step: 3.6 ms at 1 nm,
  140 ms at 0.25 nm — measured). Then clip/assign materials per §3.2. The speed field
  is rebuilt from the current front every sub-step, so etching through material A
  into B switches rates to sub-cell/sub-step order automatically; selectivity 0
  simply stalls the front there — **mask behaviour emerges from rates**, it is not a
  special case. *(→ §17.3: `material_at_front` is the owner of the nearest solid
  cell, which is not what the material fields say in an undercut void.)*
- **Isotropic fast path**: when the motion is purely isotropic and the rate is
  uniform over the affected front, offsetting is exact and instant:
  `phi ← phi ∓ rate·t` (ALD, simple wet etch). Dose splitting is exact here
  (measured: 1×20 nm vs 4×5 nm, max |diff| = 0.0).
- **Sub-stepping is internal** (Q6): the user's "etch 10 s" is one chain step; the
  solver divides it by CFL invisibly. Consistency obligation: `N × (t/N) ≡ 1 × t`
  within integration error — a standing regression test (§13), trivially true on the
  fast path, and true up to O(ε) reinitialisation drift on the general path.
- **Reinitialisation policy**: `phi` loses the distance property under advection and
  is re-normalised **in a narrow band only** (full-field EDT costs 34 ms at 1 nm but
  1016 ms at 0.25 nm — measured; the narrow band keeps this bounded), with an
  interface-preserving sub-cell scheme (Russo–Smereka-type). It runs on a
  sub-step-count/distortion trigger — **never tied to user step boundaries**, or
  3×10 s and 1×30 s would diverge. The commit gate (§4.5) normalises once at the end
  of every chain step so fast paths can rely on `|∇phi| ≈ 1`, and reports the area
  the normalisation moved.

### 4.3 Flux and visibility (the 2D-only module)

Interface `FluxModel2D`: given front samples (points + normals from `∇phi`), a
source (direction θ₀, angular distribution g(θ)), and an occupancy grid, return
flux per sample. *(→ §18.3: the samples became front cells with sub-cell foot
points; → §18.5: what the solver consumes is that array extended into a collar.)*

- **Reverse marching**: visibility is computed from each front sample **toward** the
  source over the quadrature angles of g(θ) — exactly the "backwards-ray casting
  from the structure" requested in the interview, and the grid-native successor of
  v1's reverse-visibility solver (memory 2026-03-10). Shadow boundaries emerge at
  visibility transitions; refinement concentrates samples near transitions.
  *(→ §18.4: the whole accuracy of this sits in how a ray is tested against the
  field, not in how finely it is sampled.)*
- Angular distributions parameterise the techniques: δ(θ) evaporation; narrow lobe
  RIE/IBE (plus an isotropic chemical fraction for RIE); cosⁿ sputter (plus a surface
  mobility kernel that smears deposited flux along the front); isotropic ALD/wet
  (which bypasses flux entirely via the fast path).
- **Redeposition**: after computing removal flux, emit one bounce of secondary,
  isotropic sources from sputtered sites scaled by a redeposition yield; deposit that
  flux on visible front samples (sidewall redeposit, trench bottoms).
- Budget: front ≈ 2–5 k samples × 8–32 angles, marching on a coarsened occupancy
  (2–4 nm) — estimated 10–100 ms per rebuild; rebuilt every K sub-steps
  (K ≈ 5–10, exposed as a solver constant). To be verified in M2; the fallback knob
  is K and the visibility-grid coarseness, not the model. *(→ §18.1: K = 5 holds,
  measured; → §18.2: the coarseness is free, not a trade; → §18.8: the costs.)*
- 3D later means implementing `FluxModel3D` (two-angle hemisphere integration) —
  algorithmically different, deliberately **not** abstracted over now (Q7): the
  seam is named, the work is honest.

### 4.4 Connectivity and reachability

`ndimage.label` on boolean masks (2.9 ms at 1 nm, 59 ms at 0.25 nm — measured):

- **Reachability**: which empty-space component connects to the top boundary; a wet
  process (develop, dissolve, clean) only acts on material cells adjacent to
  reachable empty space. S3's ALD failure **is** this query returning "resist
  unreachable".
- **Support**: which solid components connect to the substrate. Lift-off = dissolve
  resist (reachability-gated), then remove solid components no longer
  substrate-supported. S4's fences survive because they are attached to the
  supported film.
- Both are predicates (§7) as well as kernel steps — same functions.

### 4.5 The commit gate

Every chain step ends in one mandatory pass (the v2 successor of ADR-0001 D8):

1. narrow-band reinitialisation (§4.2) with reported interface displacement,
2. field-scoping resets on the swept cells (§3.3),
3. invariants: sign sanity, band `|∇phi| ≈ 1` (→ §18.6), disjoint interiors,
   headroom guard,
4. **balance check**: added/removed area vs. `∫ rate · flux · dt` along the front,
   within tolerance — the guard against silent numerical drift (→ §17.6: it warns,
   it does not fail; a topology change breaks the estimate legitimately, and S3 is
   such a step),
5. occurrence lineage (§3.5), capability updates (§5.3).

The `ValidationReport` is stored on the revision and surfaced by the UI — a
suspicious step is visible, never silent.

## 5. The process contract

### 5.1 Signature

```python
class ProcessStep(Protocol):
    step_id: str; display_name: str; fidelity: str   # e.g. "ideal" | "didactic" | "physical"
    def parameter_schema(self) -> list[ParamSpec]: ...      # typed, with units — as v1 step_api
    def requires(self) -> set[str]: ...                      # capabilities, §5.3
    def provides(self) -> set[str]: ...
    def run(self, ctx: StepContext) -> StepResult: ...       # pure; no Qt; no global state
```

`StepContext` carries the input `Structure`, validated params, the **effective local
parameters** already resolved for this wafer position (§8), and a seeded RNG.
`StepResult` carries the output `Structure`, artifacts (docs §4.2.2 unchanged),
measurements (`Quantity`), logs. Inspection steps (SEM, profilometry, ellipsometry)
return the input structure unchanged plus artifacts/measurements — they are ordinary
steps in the chain (Q6), which is what makes "etch, inspect, etch, inspect" four
plain steps.

### 5.2 Determinism (invariant, ADR-0004)

A step's outcome is a pure function of (input structure, recipe params, wafer
position, step index, code version). Anything stochastic (particles, roughness,
defects) draws from the context RNG, which is seeded from (recipe id, position,
step index). This is what makes replay materialization (§8) and caching sound.
Registry registration rejects steps that declare stochastic behaviour without using
the context RNG (best-effort: no direct `np.random` imports in plugin lint).

### 5.3 Capabilities

Generalises v1's step-id `prerequisites` into state contracts: `provides = {"resist.dose"}`
(physical exposure) vs `{"resist.exposed"}` (ideal exposure); development variants
`require` the matching one. The engine gates on capability presence in the current
revision. **Downgrade adapters** are explicit steps (e.g. threshold `dose → exposed`)
that warn about the information they discard; upgrades don't exist — missing
information cannot be invented. Fidelity tiers therefore mix safely: everything a
step needs is either present or the step is not runnable, exactly like today's
gating UI, with better reasons.

### 5.4 Registry and plugins

Processes register through a registry fed by entry points (in-tree builtins use the
same mechanism). Several registered processes may model the same physical technique
at different fidelity ("Evaporation (ideal)", "Evaporation (with divergence)") and
share kernel primitives — duplication lives in thin process wrappers, physics lives
once in the kernel (I7).

## 6. Built-in didactic process set (target of milestone M3)

| Process | Kernel composition |
|---|---|
| Substrate select / stack constructors | constructors (§4.1), sets grid + headroom |
| Spin-coat resist | planarising fill up to a level (one constructor op) |
| Exposure (ideal) | write `exposed` from procedural pattern |
| Exposure (dose) | write `dose` field: pattern ∗ blur, Beer–Lambert depth term |
| Development (ideal) | remove `resist ∧ exposed`, reachability-gated |
| Development (rate) | advect front through resist with `F = develop_rate(dose)`, reachability-gated |
| Wet/chemical etch | isotropic fast path per material rates, reachability-gated |
| RIE | directional lobe + isotropic chemical fraction, material yields |
| IBE | narrow lobe, angle-dependent yield, redeposition bounce |
| Evaporation | δ-flux deposit, shadowing |
| Sputter deposit | cosⁿ lobe + mobility smear |
| ALD | conformal offset per cycle count (fast path) |
| Strip / dissolve | material-selective removal, reachability-gated |
| Lift-off | dissolve resist + remove unsupported components (§4.4) |
| Anneal / property change | update fields/material models; optional isotropic reflow later |
| Particles | seeded disk constructors of a particle material |
| Clean | remove particle material where reachable (micromasking = unreachable survivors) |
| Inspect: SEM/profilometer/ellipsometer | artifact + measurement producers from structure/fields |

## 7. Predicates

First-class, reusable model objects evaluated on a revision — the didactic payload
(I6) and the analysis vocabulary: reachability of a material from the top;
pinch-off/void detection (enclosed empty components); undercut ratio; step coverage
(min/nominal film thickness along the front); minimum feature size; aspect ratio;
substrate support. The UI renders their results; the acceptance tests (§13) assert
them; the commit gate reuses the cheap ones.

## 8. Runs, positions, materialization (ADR-0004)

- A **Run** = one recipe over an extensible set of wafer positions, default
  `{center}`. Each position owns an independent revision chain.
- Recipe parameters may be **parameterised over the wafer** (stored as functions/
  interpolants — a sampled list A, B, C is just data for the interpolant).
  `effective_params(recipe, position, step)` resolves them; the solver only ever
  sees resolved local values and stays position-blind. Wafer bow/tilt appears as a
  per-position incidence-angle offset; rate radial profiles as per-position rates.
- **Materialization by replay**: adding position D later replays the chain from
  substrate selection with D-resolved parameters — deterministic by §5.2, so D is
  exactly what it would have been. Lazy, cached per (recipe hash, position, step,
  code version); a 20-step replay is seconds to ~a minute at defaults (budget §13),
  run as a background job (docs §9.2 already requires job management).
- Determinism boundary stated honestly: bit-identity is guaranteed on one machine +
  code version; cross-machine float drift is accepted and handled by the
  code-version cache key.

## 9. Persistence and exchange

One format serves saving, the replay cache, and external-solver exchange (fidelity
tier c): per revision an `.npz` (the `phi_*` and field arrays, compressed) plus a
JSON manifest (`schema_id: "structure.v2"`, grid, material ids, capabilities,
history, content hashes). Artifacts stay URI-referenced files exactly as in docs
§4.2.2. Forward compatibility via `schema_id` + ignored unknown keys (docs §4.1
invariant 5 carried over).

## 10. Rendering and UI hooks

Rendering is a consumer: filled regions from marching squares over each `phi_m`
(sub-cell smooth; own ~60-line N/A-free implementation, no scikit-image dependency),
QImage from the material index map as fast fallback/debug; inspect overlays (normals
from `∇phi`, front samples, flux/shadow visualisation, predicate highlights) from
kernel outputs. The `nanofab_manager` shell (step list, gating, params, run log)
carries over; the cross-section canvas is rewritten against `SceneSnapshot v2`
(contours + overlays instead of QPainterPaths).

## 11. Packaging

Registry + entry points from day 1; develop as a normal package (`pip install -e`,
pytest); **ship one PyInstaller exe** with the builtin process set and numpy/scipy
frozen (plugins usable in source installs; frozen app extension = rebuild). Heavy
external solvers, when they come, run as subprocesses with their own environment and
talk through §9's exchange format. Explicitly no multi-exe delivery.

## 12. What v2 deliberately does not carry over

QPainterPath/Qt in the physics; the regions↔paths dual truth; `steps_per_s` and all
phantom sub-stepping UI; the `top_only` 0.42 cut plane; per-mode monolithic
`build_scene`; stroker bands and the span/chain solver family; `Facet` as a
geometry concept (per-cell fields + derived occurrences replace it — see updated
`CONTEXT.md`); free-string `operation_log`. Carried over as concepts: `Quantity`,
`ArtifactRef`, `HistoryEntry`, append-only revisions, gating (→ capabilities),
process/material split, reverse-visibility principle.

## 13. Testing and acceptance

pytest from M0 (the repo currently has no tests; AGENTS.md validation extends from
`compileall` to `compileall + pytest`). Layers:

1. **Kernel invariants** — constructor exactness on planes; disjointness; offset
   dose-splitting exact; advection dose-splitting `N×(t/N) ≈ 1×t` within tolerance;
   balance check closes; reinit displacement bounded; symmetric scenes stay
   symmetric.
2. **Mechanism tests** — the measured probes become tests: T-profile ALD seals a
   void at t ≥ half-opening, straight gap fills seamed; shadow wedge position vs.
   analytic for a rectangular mask at angle θ; undercut depth vs. `rate·t`.
3. **Acceptance = S1–S4** asserted through predicates (S1 pattern width == design ±
   tol; S2 undercut ratio; S3 resist-unreachable and film continuous; S4 fence
   components present). These four tests are the definition of done for M3.
4. **Performance floors** — heavy directional step ≤ a few seconds at default grid
   (Q6); per-step cost flat across 60-step chains (the v1 superlinear blow-up,
   ADR-0001 F3, must be provably gone).

## 14. Milestones

- **M0 Skeleton** — package layout (`model/`, `kernel/`, `processes/`, `materials/`,
  `runtime/`, `io/`), Grid/Structure/CSG/constructors, marching squares, pytest
  wiring. DoD: kernel-invariant tests green.
- **M1 Motion** — offset fast path, upwind advection + CFL, narrow-band reinit,
  commit gate with balance check. DoD: dose-splitting and balance tests green;
  60-step chain flat cost.
- **M2 Flux** — `FluxModel2D` reverse marching, evaporation/IBE/RIE/sputter,
  redeposition bounce. DoD: shadow-wedge and mechanism tests green; budget verified.
- **M3 Litho + predicates** — materials/fields/capabilities, resist set, dissolution
  with reachability, lift-off, predicates. DoD: **S1–S4 acceptance tests green.**
- **M4 Runtime** — revisions, runs, persistence, replay + cache; UI integration
  (render from φ, chain UI on capabilities). DoD: save/load/replay round-trip;
  interactive session usable.
- **M5 Delivery** — entry-point plugins, PyInstaller monolith, particles/clean,
  anneal, wafer materialization UI (position fan). DoD: packaged exe runs S1–S4.

v1 (`cross_section_general_prototype.py`) stays untouched next to v2 until M3's
acceptance tests pass, per AGENTS.md §7; then it becomes a `ui_backups/` snapshot.

## 15. Risks

| Risk | Mitigation |
|---|---|
| Reinit drift accumulates over long chains | narrow band + sub-cell fix, displacement reported per commit, balance test in CI |
| Flux rebuild too slow at fine grids | rebuild-every-K knob, coarse visibility grid; measured fallback path, not a redesign (→ §18.8: measured, the flux is not what dominates) |
| Corner rounding at ~½ cell disturbs ideal-case didactics | resolution parameter visible + documented; ideal constructors exact for planes; acceptance tolerances set accordingly |
| Determinism broken by a careless plugin | context-RNG contract + registry lint + cache keyed on code version |
| 3D flux solver underestimated | seam is named and 2D-only by decision (Q7); nothing else in the core is 2D |
| Scope creep from fidelity tier (b)/(c) | tiers live in process wrappers and rate models only; M-plan contains none of them |

## 16. Deliberately open

The 3D `FluxModel3D`; semi-quantitative rate calibration; external-simulator
adapters beyond the exchange format; reflow/anneal geometry motion (curvature-driven
flow is a natural level-set extension when wanted); GDS/CAD pattern import into the
exposure constructors.

## 17. Corrections from implementation (M0/M1)

Added 2026-08-25 after M0 and M1 were built and measured. The sections above are
the agreed design and are left as written; each item here amends one statement
that turned out to be wrong or incomplete, with the measurement that showed it.
Nothing in the *decisions* changed — per-material SDFs, one moving front,
pointwise set operations and derived occurrences all held. What changed is a set
of statements about what those objects give you.

The recurring theme: **a formula can be a correct set operation and a useless
field at the same time.** Signs decide which region is which; values decide every
distance, measure and front integral read off them afterwards. Four of the six
items below are that distinction.

### 17.1 `min_m phi[m]` is not the union's distance function

Where two materials touch — the normal case, since constructors sample exactly on
the grid — `min_m phi[m]` is exactly **zero along their shared interface**,
because each field is correctly zero on its own boundary there. That buried seam
is indistinguishable from a front by value alone. Measured on a substrate + mask
scene: the front integral reported 429 nm of front against a true 330 nm, and an
offset pushed the seam positive, punching a void along perfectly continuous
material.

Three consequences the model has to carry:

- `solid_mask` is `phi_solid <= 0`, not `< 0`. A strict test opens a one-cell
  crack through continuous material, which every connectivity query of §4.4 —
  reachability, support, lift-off — would read as a gap. Material *interiors*
  stay strict (`< 0`) so they remain pairwise disjoint; `material_index` (argmin)
  gives an interface cell to exactly one material, so the partition is exclusive.
- "How much material is there" is summed **per material**, not evaluated once on
  `phi_solid`: at a shared interface each side contributes half a cell, which is
  the whole cell.
- The field a motion advects is `min_m phi[m]` **with its seams renormalised
  away** (`kernel.motion.union_front`), run only when a seam is present. It works
  because a cell exactly at the zero level counts as *inside* for sign-change
  detection, so only the real solid/empty interface is held fixed and the seam
  relaxes to the distance it should have had.

### 17.2 The clip and deposit formulas are set operations, not field operations

`phi_m ← max(phi_m, phi_solid_new)` keeps the sign right everywhere, but where
another material's surface is nearer than m's own it **understates** `phi_m` — it
answers "how far to the nearest solid", not "how far to material m". The gate's
reinitialisation is what repairs those values, so the two must be read as a pair:
the clip decides the region, the gate decides the numbers.

Two additions the plan did not state:

- Both bookkeeping formulas take the fields **at the start of the motion**, never
  the previous sub-step. Accumulated per sub-step, a deposit is a sawtooth whose
  every value lies within one sub-step's thickness of zero (`rate · dt`, a
  fraction of a cell), and a receding front leaves stale values behind it.
- The reinitialisation band cannot be defined by `|phi| <= band`. A field that
  needs renormalising is one whose values cannot be trusted to say how far the
  zero level is, so a value band excludes exactly the cells that are furthest
  off. The band is geometric — cells within *n* cells of the interface — **plus**
  every cell whose value merely claims to be near zero, which is what reaches a
  buried seam and a clip artifact. With a value-only band a 2×-steepened circle
  got *worse* (band gradient error 1.0 → 1.85); with both criteria it converges
  to 0.098.

### 17.3 `material_at_front(x)` is the owner of the nearest solid cell

§4.2 reads as though the material at the front is a lookup in the material
fields. It is not, in the one case that matters: **in an undercut void the
nearest solid is the mask overhanging it**, not the material that used to fill
the void. Reading the clipped fields there ties `phi_mask` against a `phi_si`
that equals the union distance, and the mask's own exposed face is handed the
etch rate of the material below it. Measured: the undercut ran to 27 nm instead
of 20, and the front ate into the mask.

The map is therefore `argmin_m phi[m]` **inside the solid** — constant during an
etch, since cells only ever leave the solid, so the A→B rate switch stays exact
per sub-step — extended into empty space by "the owner of the nearest solid
cell", i.e. a distance transform. That extension is a second solver constant
alongside §4.3's flux rebuild interval: it is refreshed every 5 sub-steps,
because where the surrounding walls are changes far more slowly than the front
moves.

Residual, accepted and resolution-dependent: the A→B switch is a cell wide, so
with a rate ratio of 5 the depth reached in B carries a few nm of error. Halving
the spacing halves it.

### 17.4 The band gradient invariant is a quantile, not a maximum

At a concave crease — the union of two overlapping disks, or any re-entrant
corner — a *correct* distance function is not differentiable, so the worst cell
never converges to `|∇phi| = 1` however well the field is normalised. Measured on
that scene: max 0.43, 99th percentile 0.052. The gate and the distortion trigger
read the 99th percentile; constructor-exactness tests, which run on smooth
fields, keep reading the maximum.

### 17.5 The headroom guard is about the top face

"Fails a step whose front touches a lateral or top boundary" fails every
realistic cross-section: a blanket substrate reaches `x-min` and `x-max` by
construction, and a cross-section continuing sideways is the same "solid
continues" statement as the bottom face. The guard fails on the **max face of the
first axis** (the stacking direction) and is configurable per commit; any face a
step *newly* touches is warned about regardless, which is the honest signal that
the domain is running out.

### 17.6 The balance check warns, it does not fail

A step that changes topology genuinely breaks the front-integral estimate — the
front length is not a smooth function across a pinch-off — and **S3 is such a
step**, so a hard check would fail one of the plan's own acceptance scenarios.
The balance check therefore records `expected`, `measured`, `error` and
`tolerance` on the revision and warns; the lineage report in the same pass is
what explains the discrepancy. Broken invariants, which no legitimate process
produces, still fail.

Measured errors after the gate's reinitialisation, against a 5 % default
tolerance: plane etch 0.0 %, disk shrink 0.5 %, disk grow 0.9 %, masked etch with
undercut 2.3 %, heavy step at the reference grid 0.95 %.

### 17.7 Measured costs, replacing the estimates in §4.2 and §13.4

The 3.6 ms in §4.2 is the upwind stencil alone. A **complete sub-step** —
ownership, upwind, bookkeeping, front integral — measures ~50 ms at the reference
grid (540×1200 at 1 nm), of which the stencil is about half. What follows for M2
is that the flux rebuild is being added to a 50 ms sub-step, not a 3.6 ms one, so
§4.3's estimate of 10–100 ms every 5–10 sub-steps costs 2–20 % on top rather than
dominating.

| Measured (540×1200 at 1 nm) | |
|---|---|
| complete advection sub-step | ~50 ms |
| deliberately heavy step (60 nm etch = 120 sub-steps, 4 reinits) | 6.0 s motion + gate |
| typical step (4 nm = 8 sub-steps) | 0.74 s |
| conformal offset (fast path) | 0.11 s |
| commit gate alone, 2 materials | 0.31 s |
| 20-step chain, per-step cost first 5 vs last 5 | ratio 1.00 |

§13.4's "≤ a few seconds at default grid" holds for a typical step and is
exceeded by the extreme one. The remaining cost is the upwind stencil evaluated
over the whole domain; a true narrow-band solver is the fix if M2 shows it
matters, and is deliberately not built yet.

## 18. Corrections from implementation (M2)

Added 2026-08-25 after M2 was built and measured, in the same form as §17: the
agreed text above stays as written, and each item here amends one statement with
the measurement that showed it. Nothing in the *decisions* changed — reverse
marching against the union front, angular distributions parameterising the
techniques, one redeposition bounce, the 2D-only seam.

The recurring theme this time: **most of the accuracy of a visibility solver is
in how it asks "is this point inside", not in how finely it marches.** Four of
the seven items below are that one question.

### 18.1 `K` is a cost knob only because the hit test is honest

§4.3 estimates the flux rebuild interval at `K ≈ 5..10` and §15 names it as the
first fallback if the budget does not hold. Both stand — but only after the hit
test stopped reading the field at the nearest cell.

The arrival is extended off the front by "the value of the nearest front cell".
At the concave corner where a mask meets the surface being etched through it,
the nearest front cell *is* that corner, whose normal is diagonal and whose
sputter yield is therefore near its peak. Every sub-step of staleness lets that
velocity act on a wedge of material the mask fully shadows. Measured on a 40 nm
mask window, 30 nm of ion-beam etch at 1 nm/cell — worst lateral excursion past
the window edge:

| `K` | 1 | 2 | 3 | 5 | 10 |
|---|---|---|---|---|----|
| nearest-cell hit test | 3 nm | 6 nm | 10 nm | 14 nm | 17 nm |
| bilinear hit test (§18.4) | 0 nm | 0 nm | 0 nm | 1 nm | 2 nm |

With the second row, `K = 5` costs a nanometre — inside the cell the grid owes
anyway — and the M2 handoff's suggestion of sharing one refresh point with the
material-ownership map (`motion._OWNER_REFRESH`) is right. With the first row,
`K` would have had to be 1 and a directional step would have cost three times an
isotropic one.

### 18.2 A coarse visibility grid costs nothing

§4.3 has the march running "on a coarsened occupancy (2–4 nm)", and §15 offers
that coarseness as a fidelity-for-speed trade. Measured, it is not a trade at
all: the coarse grid is used **only to bound how far a ray may jump**, while the
hit test reads the fine union field. Shadow-wedge position for a mask edge at
15/30/45/60 degrees is *identical* at a visibility spacing of 1, 2 and 4 cells;
only the number of marching steps changes. There is a standing test for it,
because it is the fallback §15 reaches for first and it is free.

The bound itself is a Euclidean distance transform of the coarsened occupancy,
which lets a ray sphere-trace: steps grow geometrically in open space, so
crossing 500 nm of headroom costs ~15 iterations instead of 500. Near a surface
the union field is the sharper bound and is trusted for three cells, which is
where the reinitialisation guarantees it is a distance.

### 18.3 Flux is per cell, not per sample

§4.3 defines `FluxModel2D` as returning flux per front *sample*; the solver
consumes a per-cell array. Resolved in favour of per-cell throughout. What the
sample abstraction was wanted for — sub-cell placement, so the shadow boundary
is not cell-quantised — is recovered by starting each ray at the **foot point**
`x - n * phi(x)` instead of at the cell centre. The refinement §4.3 wanted near
transitions was not needed: the measured wedge position is within 0.8 nm of
`h * tan(theta)` at 1 nm/cell out to 60 degrees, where the shadow is 69 nm long,
so the error does not grow with the lever arm.

### 18.4 A ray cannot be blinded by displacement or by travel

A ray leaves a front cell, and a front cell is solid by definition, so it reports
itself blocked. Two repairs were tried and both are wrong in ways worth
recording, because both look obviously right:

- **Displace the ray's origin along the surface normal.** This moves the
  geometry. A mask then casts the shadow of a mask one cell shorter, a bias of
  `spacing * tan(theta)` that grows with the source angle.
- **Blind the ray for one cell of travel.** This fails at glancing incidence,
  where a cell of travel is a fraction of a cell of clearance. Measured at 60
  degrees: every ray still shadowed itself and the entire front came out dark.
  Latching on *clearance* instead ("a ray may hit only once it has been a cell
  clear of every surface") fails differently and worse: at a concave corner a ray
  leaves the substrate straight into the mask, is never clear of anything, and
  emerges above the mask reported as lit.

The fix is to read the union field **bilinearly** rather than at the nearest
cell. It is then a smooth signed distance: half a cell along an outward ray
already reads positive, and the only negative readings are inside real material.
No blind window is needed at any angle, and §18.1's whole first row disappears.

### 18.5 A velocity extension has to be a collar

The arrival is extended off the front so the solver has a speed where the front
is about to be. Extended over the whole window it is a bug rather than a
convenience: a cell ten cells deep under a hard mask keeps being handed the etch
rate of the trench floor that happens to be its nearest front, and `phi` there
climbs by `rate * t` until it crosses zero. Measured: a 30 s ion-beam etch opened
a row of disconnected voids under the mask, growing with depth.

Beyond the collar cells are simply frozen — which is what a narrow-band solver
does, and the direction §17.7 already pointed. For a uniformly signed motion the
Godunov upwind side is the one *away* from the frozen boundary, so the step in
`phi` there is never read and the front does not notice.

### 18.6 The band invariant fails on every thin film, and on every mask corner

§3.2's field invariants and §4.5's gate read `|grad(phi)| ≈ 1` in a band around
the zero level, at a high quantile after §17.4. Two ordinary shapes break that as
written, and neither is a solver problem:

- A film's **medial axis** sits half its thickness in, so any film thinner than
  twice the band has its axis *inside* the band — and there a correct distance
  field has a genuine local extremum, so `|grad(phi)| = 0` however well it is
  normalised. Measured: every deposition below 8 nm failed the gate with a band
  gradient error of exactly 1.0, and **a 2 nm ALD film is the most ordinary
  object in this domain**. Medial axes are now detected (opposite one-sided
  differences, the steeper one a real slope) and removed from the band together
  with their neighbours, since a central difference is contaminated a cell away
  from any non-differentiable point.
- A **right-angled concave crease** — a mask sidewall meeting the surface — reads
  exactly `1 - 1/sqrt(2) = 0.293` by arithmetic, and cannot be told from real
  distortion by the same test (the field is flat on one side rather than
  reversed). The gate's tolerance therefore sits above it, at 0.35. Measured on
  the reference grid, a 60 nm ion-beam etch through six mask windows: p90 0.053,
  p99 0.289, max 0.536.

The check keeps its teeth: a 2×-steepened circle still reads 1.0, a flattened one
0.5, a reinitialised one 0.095 — §17.2's numbers unchanged.

### 18.7 A shadowed deposition leaves phantom material

§3.2's deposition formula `phi_k ← min(phi_k, max(d_D, -phi_solid_old))` is a
correct set operation — §17.2 already says its *values* need the gate. It is
worse than that wherever the front does not move, which is every shadowed stretch
of a directional deposition: there `solid_now == solid_start`, the formula
collapses to `|solid_start|`, and the result is exactly zero all along the old
surface. Nothing is inside that zero level, but every sub-cell measure reads
those cells as half full and every front integral counts them as front. Measured
on a 4 nm sputter deposition through a mask: 1849 cells at exactly zero and
~600 nm² of metal that was never deposited.

Clamping them positive does not help: `|solid_start|` is a V, and a V has a zero
central derivative at its vertex whatever its floor. What is wrong is the
*proxy* — away from the deposit, "distance to where the surface used to be" is
not "distance to the deposited material", and the second is what `phi_k` means.
So where nothing grew, the field is now the distance transform of the region that
did. Cells the deposit reached keep the sub-cell value the moved front gives them.

### 18.8 Measured M2 costs, extending §17.7

At the reference grid (540×1200 at 1 nm), against §4.3's estimate of 10–100 ms
per rebuild:

| One flux rebuild | |
|---|---|
| evaporation, δ source (1 angle) | 25–34 ms |
| RIE / IBE, narrow lobe (9 angles) | 63–66 ms |
| sputter, cos¹ (17 angles) | 104 ms |
| sputter + 20 nm surface mobility | 124 ms |
| IBE + redeposition bounce (12 rays) | 139–152 ms |

| Complete step (motion + commit gate) | |
|---|---|
| isotropic 4 nm etch, no flux (the §17.7 baseline) | 0.53 s |
| directional 4 nm etch, evaporation | 0.57 s |
| directional 4 nm etch, IBE | 0.60 s |
| directional 4 nm deposition, sputter cos¹ | 1.26 s |
| heavy 60 nm directional etch, IBE (121 sub-steps, 25 rebuilds) | 5.73 s |
| commit gate alone, 2–3 materials | 0.19 s |

So §4.3's estimate holds for everything but the widest lobes, and the handoff's
"2–20 % on top of a step rather than dominating it" holds as measured: +8 % for
an evaporation, +13 % for an ion beam. The heavy step is *below* §17.7's 6.0 s
despite the flux, because §18.6's windowing more than paid for itself in the
gate — which is also the honest answer to §15's "flux rebuild too slow at fine
grids": at the reference grid it is not the flux that dominates, it is still the
upwind stencil over the whole domain, exactly as §17.7 said.

Balance-check errors on those steps, against the 5 % default: plane etch 3.4 %,
directional etch 1.2–1.5 %, directional deposition 1.2 %, heavy step 0.03 %.
