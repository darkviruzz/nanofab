# Plan: Structure Model v2

- Status: Agreed (design interview 2026-08-24/25); implemented through M8.
  §17 onward amend the agreed text with what implementation measured
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
  standing as fences. *(→ §19.7: not on S1's stack — a straight wall is coated
  continuously and seals the resist; fences need the re-entrant profile a real
  lift-off resist has, and the broad lobe rather than the mobility is what makes
  them.)*

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
  objects; no geometry. *(Crystallographic anisotropy is deliberately not built
  in M3: no process in §6 consumes it, and a model nothing reads cannot be
  validated. The library imports nothing from the kernel — `processes.rates` is
  the seam; see §19.1's tier split for where the develop/dissolve models are
  read.)*
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
stack summary, it is **derived** (occurrences ordered by height). *(→ §20.1: this
`structure` field and §8's lazy replay are two designs, and the one taken is that
a revision keeps its structure while the **chain** spills what it is not holding;
→ §20.7: a chain with nowhere to spill to therefore holds everything.)*

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
  unreachable". *(→ §19.1: the gate has two shapes, region and speed field, split
  along the ideal/physical axis; → §19.3: "material cells adjacent to" needs a
  third mask, neither `inside` nor `material_index`; → §19.5: as a speed field it
  needs §18.5's collar.)*
- **Support**: which solid components connect to the substrate. Lift-off = dissolve
  resist (reachability-gated), then remove solid components no longer
  substrate-supported. S4's fences survive because they are attached to the
  supported film.
- Both are predicates (§7) as well as kernel steps — same functions.

### 4.5 The commit gate

Every chain step ends in one mandatory pass (the v2 successor of ADR-0001 D8):

1. narrow-band reinitialisation (§4.2) with reported interface displacement
   (→ §20.2: **per material the step actually moved**; a committed field is not
   a fixed point of the reinitialisation, so running it on an untouched material
   inflates it once per step, invisibly),
2. field-scoping resets on the swept cells (§3.3),
3. invariants: sign sanity, band `|∇phi| ≈ 1` (→ §18.6), disjoint interiors,
   headroom guard,
4. **balance check**: added/removed area vs. `∫ rate · flux · dt` along the front,
   within tolerance — the guard against silent numerical drift (→ §17.6: it warns,
   it does not fail; a topology change breaks the estimate legitimately, and S3 is
   such a step),
5. occurrence lineage (§3.5), capability updates (§5.3). *(→ §19.2/§19.4: the
   scoping resets and the removals they follow read a material's **closed
   region**, which is not `phi_m <= 0`.)*

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
plain steps. *(→ §21.7: "unchanged" is the same object, not an equal one, which is
what makes an inspection cost 25 ms and no memory; and a pure step cannot open a
file, so producing an artifact needs `StepContext.artifacts`, a sink.)*

### 5.2 Determinism (invariant, ADR-0004)

A step's outcome is a pure function of (input structure, recipe params, wafer
position, step index, code version). Anything stochastic (particles, roughness,
defects) draws from the context RNG, which is seeded from (recipe id, position,
step index). This is what makes replay materialization (§8) and caching sound.
Registry registration rejects steps that declare stochastic behaviour without using
the context RNG (best-effort: no direct `np.random` imports in plugin lint).
*(→ §21.1: "code version" turned out to be two axes once a plugin can change the
answer — `__version__` stays coarse and each registered step's implementation
digest goes into the recipe hash; → §21.4: `particle.seed` is the first
registered step to exercise any of this.)*

### 5.3 Capabilities

Generalises v1's step-id `prerequisites` into state contracts: `provides = {"resist.dose"}`
(physical exposure) vs `{"resist.exposed"}` (ideal exposure); development variants
`require` the matching one. *(The dot in that example is load-bearing: it is
reserved for `<material>.<field>`, so a free-form promise must not contain one.
The gate re-derives the structural capabilities from the structure itself.)* The engine gates on capability presence in the current
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
once in the kernel (I7). *(→ §21.6: the registry arrived in M3 and the entry points
in M5; what an entry point may resolve to, why discovery reports instead of
raising, and why `builtin_registry()` must stay a fixed set are settled there.)*

## 6. Built-in didactic process set (target of milestone M3)

| Process | Kernel composition |
|---|---|
| Substrate select / stack constructors | constructors (§4.1), sets grid + headroom |
| Spin-coat resist | planarising fill up to a level (one constructor op) |
| Exposure (ideal) | write `exposed` from procedural pattern |
| Exposure (dose) | write `dose` field: pattern ∗ blur, Beer–Lambert depth term |
| Development (ideal) | remove `resist ∧ exposed`, reachability-gated (→ §19.1: by region, per occurrence) |
| Development (rate) | advect front through resist with `F = develop_rate(dose)`, reachability-gated |
| Wet/chemical etch | isotropic fast path per material rates, reachability-gated (→ §19.1: the general path, since selective rates break the fast path's precondition) |
| RIE | directional lobe + isotropic chemical fraction, material yields |
| IBE | narrow lobe, angle-dependent yield, redeposition bounce |
| Evaporation | δ-flux deposit, shadowing |
| Sputter deposit | cosⁿ lobe + mobility smear |
| ALD | conformal offset per cycle count (fast path) |
| Strip / dissolve | material-selective removal, reachability-gated |
| Lift-off | dissolve resist + remove unsupported components (§4.4) |
| Anneal / property change | update fields/material models; optional isotropic reflow later (→ §21.2: the new rates live in the library as a *second entry* and the geometry is reassigned to it; the library stays immutable) |
| Particles | seeded disk constructors of a particle material (→ §21.4: resting on the surface, never at a random point in the domain) |
| Clean | remove particle material where reachable (micromasking = unreachable survivors) |
| Inspect: SEM/profilometer/ellipsometer | artifact + measurement producers from structure/fields (→ §21.7: and the first steps to need an `ArtifactSink`) |

## 7. Predicates

First-class, reusable model objects evaluated on a revision — the didactic payload
(I6) and the analysis vocabulary *(→ §19.6 for what they cost; → §19.3 for the
mask they all read)*: reachability of a material from the top;
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
  *(→ §21.1: the recipe hash gained a per-step implementation digest, which is
  where a plugin's code enters the key at all; → §21.5: the job runner is
  `ui.wafer.WaferFan`, and its second look at a position is a cache read.)*
- Determinism boundary stated honestly: bit-identity is guaranteed on one machine +
  code version; cross-machine float drift is accepted and handled by the
  code-version cache key.

## 9. Persistence and exchange

One format serves saving, the replay cache, and external-solver exchange (fidelity
tier c): per revision an `.npz` (the `phi_*` and field arrays, compressed) plus a
JSON manifest (`schema_id: "structure.v2"`, grid, material ids, capabilities,
history, content hashes). Artifacts stay URI-referenced files exactly as in docs
§4.2.2. Forward compatibility via `schema_id` + ignored unknown keys (docs §4.1
invariant 5 carried over). *(→ §20.3: how well it compresses is a property of
what is in the arrays — measured, one chain's revisions span 35× to 493×, and a
`Field` with per-cell entropy does not compress at all.)*

## 10. Rendering and UI hooks

Rendering is a consumer: filled regions from marching squares over each `phi_m`
(sub-cell smooth; own ~60-line N/A-free implementation, no scikit-image dependency),
QImage from the material index map as fast fallback/debug; inspect overlays (normals
from `∇phi`, front samples, flux/shadow visualisation, predicate highlights) from
kernel outputs. The `nanofab_manager` shell (step list, gating, params, run log)
carries over; the cross-section canvas is rewritten against `SceneSnapshot v2`
(contours + overlays instead of QPainterPaths). *(→ §20.4: a blanket layer's
contour leaves the domain and is not a polygon, so "filled regions from marching
squares" needs the open pieces stitched to each other along the domain edge; →
§20.5: the fill rule, not the contour, is where §19.2's phantom zero bites; →
§20.6: building a scene is 107 ms and painting one is 12, which is where the
boundary between the two goes.)*

## 11. Packaging

Registry + entry points from day 1; develop as a normal package (`pip install -e`,
pytest); **ship one PyInstaller exe** with the builtin process set and numpy/scipy
frozen (plugins usable in source installs; frozen app extension = rebuild). Heavy
external solvers, when they come, run as subprocesses with their own environment and
talk through §9's exchange format. Explicitly no multi-exe delivery.
*(→ §21.6: "from day 1" was half true — the registry was, the entry points arrived
in M5 — and "frozen app extension = rebuild" is literally true, measured: a plugin
installed for the host Python is invisible to the exe. → §21.5: the exe is 115 MB
and costs 2.4 s of startup over a source install. The DoD's S1–S5 run through a
`--selftest` flag against `nanofab_v3.acceptance`, because a checkable claim needs
an exit code; the reasoning is in that module.)*

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
   *(→ §19.8: S4's fences are not components — they are attached to the film,
   which is why they survive; the assertion is their height above it. Each
   scenario also runs its control.)*
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
  *(The position fan's engine exists as of M4 — `Run` over an extensible position
  set, `runtime.positions_on_radius`, and a cache keyed per position — so M5's
  share of it is the view.)*
  *(→ §21 for what M5 measured and corrected; the milestone record is below.)*

v1 (`cross_section_general_prototype.py`) stays untouched next to v2 until M3's
acceptance tests pass, per AGENTS.md §7; then it becomes a `ui_backups/` snapshot.

**Done, 2026-08-25**, on the milestone this paragraph names: S1–S4 went green and
v1 was snapshotted deliberately, as a step of its own rather than as a side
effect. The prototype is now
`ui_backups/2026-08-25_v1.0.0_cross-section-prototype/`, and the v0.2.0
application it sat next to — the PySide6 shell plus the `nanofab_modular` engine,
which §12 already listed as carried over in *concept* only — is
`ui_backups/2026-08-25_v0.2.0_nanofab-manager/`. Each snapshot carries a `README`
saying how to run it and what replaced it. `nanofab_v3/` is now the only actively
built code base at the repository root, which is the state §10's UI rewrite and
M4's runtime start from.

**M4 done, 2026-08-26.** `runtime/` and `io/` are no longer placeholders and
`ui/` is new: `Revision` and the append-only chain (§3.6), the `.npz` + JSON
exchange format (§9), `Recipe`/`Run` with `effective_params` over wafer positions
(§8, ADR-0004), replay cached on (recipe hash, position, step, code version), and
the application — `SceneSnapshot v2`, an interactive `Session`, and the v0.2.0
shell rewritten with gating on capabilities (§10). **DoD met**: the save / load /
replay round trip is bit-identical and asserted, and `python -m nanofab_v3.ui`
runs S1 end to end interactively. 314 tests green; corrections in §20. What M5
starts from is that plus one deliberate absence — inspection steps, particles,
clean and anneal are still unregistered (§19's note 11), and they are what the
artifact plumbing built here exists for.

**M5 done, 2026-08-26. DoD met**: the packaged exe runs the acceptance
scenarios — `./dist/nanofab_v3 --selftest` reports **7 of 7 passed** in 6.9 s and
exits 0, on a 115 MB single-file build with the builtins and numpy/scipy frozen
in. Everything §14 asks for is there: entry-point discovery through the same
`register()` seam every builtin uses, with an in-tree example plugin in its own
package that a test really builds and installs; particles and clean, with
micromasking as a scenario of its own (**S5**, plus its control); the three
inspection steps, which are what finally closed M4's open artifact wire; anneal
as fields and material models, reflow left to §16; and the wafer view — a
Qt-free job runner over `Run`'s positions showing partial results, and a widget
that paints them and decides nothing.

Two things about the *shape* of the milestone, since it is the last one on this
list. The scenarios moved into the package (`nanofab_v3.acceptance`) because an
exe carries no pytest, and `tests/test_scenarios.py` now builds its chains from
the same recipes and asserts the shipped ones pass — one definition, and the two
cannot drift without the suite going red. And the self-test is a **flag** rather
than a menu entry, because the DoD is a checkable claim: a flag has an exit code,
a menu entry needs a display, a human and their report of what they saw.

**394 tests green** (314 at the end of M4, so 80 are new), `python -m compileall nanofab_v3 tests` clean. Corrections
and the measured delivery budget in §21; what is deliberately left open past this
milestone is §21.8.

## 15. Risks

| Risk | Mitigation |
|---|---|
| Reinit drift accumulates over long chains | narrow band + sub-cell fix, displacement reported per commit, balance test in CI (→ §20.2: the mitigation had a leak — the gate renormalised materials the step never touched, and the balance check charges that drift to whichever step did move something; the pass is now skipped) |
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

## 19. Corrections from implementation (M3)

Added 2026-08-25 after M3 was built and measured, in the same form as §17 and
§18: the agreed text above stays as written, and each item here amends one
statement with the measurement that showed it. Nothing in the *decisions*
changed — capability contracts, predicates as first-class objects, reachability
as the gate for wet processes, the ideal/physical split living in the process
rather than in the structure model. What changed is a set of statements about
what those objects give you.

The recurring theme this time: **a material's own field is not a statement about
that material alone.** Three of the eight items below are the same buried-seam
problem §17.1 found in the union field, reappearing in places the plan describes
as per-material — which is what a per-material representation costs, stated
honestly, and it is still cheaper than the alternatives ADR-0002 rejected.

### 19.1 Where reachability gates a process: both, split by fidelity

The one design decision the M3 handoff (§3) asked to be made first. The plan
says only that a wet process "acts on material cells adjacent to reachable empty
space" (§4.4) and marks development, wet etch, strip and lift-off as gated (§6).

Settled as the handoff recommended, along the fidelity axis §3.3 already draws:

- **The ideal tier gates by region.** `predicates.reachable_occurrences` picks
  the connected pieces a bath can touch and `regions.remove_region` takes them
  out in one `csg` operation — no rate, no time, no sub-stepping. Per
  *occurrence*, not per cell: a solvent that reaches one corner of a connected
  piece of resist dissolves the piece, and a cell-by-cell removal would stall at
  the first constriction and leave a plug no real bath leaves.
- **The rate tier gates by speed field.** `predicates.ReachableFront` is a
  `motion.FrontFlux` — `max_arrival` for the CFL bound, `on_front` for the
  per-cell multiplier — so it goes through the seam the flux model already uses,
  and `motion.gated` multiplies the two together. It has to be rebuilt as the
  front moves, because dissolving resist opens paths that were closed.

The two are two *processes* at different fidelity (`develop.ideal` /
`develop.rate`, `strip.dissolve` / `strip.rate`), exactly as §5.4 wants, and not
a fork in the kernel. Neither is a special case anywhere in `motion`.

### 19.2 A carved field is zero on other materials' buried seams

§17.1 records that `min_m phi[m]` is exactly zero along a buried interface
between two touching materials. A **material's own** field has the same defect,
and the plan gives no hint of it: `constructors.add_material` carves the new
region against the union of the others (`max(phi_new, -phi_union)`), and
`-phi_union` is exactly zero along every interface between two of *those* —
interfaces the new material may be nowhere near.

Measured on the S2 stack (silicon, 60 nm of thermal oxide on it, resist spun on
top): `phi_resist` reads exactly 0.0 along the buried silicon/oxide interface,
60 nm below the resist's own underside and in **every column of the domain**. A
`phi_m <= 0` test therefore reported the resist as covering the full width, and
the undercut predicate — which measures against the mask's footprint — returned
zero for every etch, wet and directional alike.

The repair is topological rather than numerical, and is the third disguise of
§18.7's phantom: take the closure of the *interior*
(`kernel.regions.closed_region`). A zero-valued cell counts only when it touches
a cell that is strictly inside, which is exactly what tells a material's own
boundary from a zero level with nothing behind it.

Note that the defect only appears for an **unbounded** constructor — a
planarising spin coat, which is negative all the way down. A slab bounded at the
layer below it hides the problem, which is how it survived M0 to M2.

### 19.3 "The cells of material m" is a third mask, not one of the two that existed

§17.1 established two masks and their division of labour: `inside` is strict
(`phi_m < 0`) so material interiors stay disjoint, and `material_index` is the
exclusive partition. Every connectivity query in §4.4 needs a third, and neither
of those is it.

`inside` is one cell too small in the one place that decides the answer. A
constructor samples exactly on the grid, so a material's own boundary cells read
`phi_m == 0`; a solvent standing in a cavity touches that cell first, and
`inside` leaves it out. Measured on the T-profile fixture: with `inside`, the
bath is two cells from the nearest resist cell it is allowed to see, and
`is_reachable(resist)` comes back `False` for a profile that is wide open.

So `predicates.cells_of` is the **closed region** — the interior plus its own
boundary, per §19.2. The closed regions of two touching materials share their
interface cell, so it is not a partition; that is right for the question, because
both materials really are present in that cell and both really are wet.

### 19.4 A material-selective removal has to name what it attacks

The consequence of §19.3 on the other side. A mask covering the resist's closed
region also covers the substrate's top row, because `phi` is exactly zero there
for both. Measured: dissolving the resist through a mask built that way took
**half a nanometre of silicon** with it, along every cell the two shared, and the
substrate's field stopped being bit-identical across a step that should not have
touched it.

`regions.remove_region` therefore takes a `materials` argument, and it is not a
convenience. A removal that is about *chemistry* — a solvent, a developer — names
what it attacks; a removal that is about *connectivity* — lift-off's unsupported
components — does not have to, because there the removed region is a union of
complete solid components and a component is separated from what stays by empty
space, so no shared interface cell is in play.

### 19.5 The reachability gate needs §18.5's collar, and §18.5's window

Both findings from the flux solver apply unchanged to a gate that is not a flux.

The collar first: extended over the whole domain, the gate hands a cell ten cells
deep in a wall the value of whatever front happens to be nearest, and the upwind
stencil starts moving it. `ReachableFront.collar_cells` is 12, the same number as
`flux._EXTENSION_CELLS`, deliberately — the two collars answer the same question
about the same front.

The window second, and this one is a cost rather than a correctness matter: the
front is a curve and the domain is an area, so the collar's distance transform
has no business running over the headroom and the bulk of the wafer. Restricting
it to a box around the front took one gate rebuild from **48 ms to 20 ms** at the
reference grid.

### 19.6 The gate is not a fidelity knob, and barely a cost one

§4.4 is silent on what reachability costs. Measured at the reference grid
(540×1200 at 1 nm), against §18.8's flux numbers:

| | |
|---|---|
| `label_region` on the empty space | 2.7 ms |
| `reachable_empty` / `supported` | 4.9 / 3.6 ms |
| `enclosed_voids` | 11.5 ms |
| `undercut` / `step_coverage` | 8.7 / 8.9 ms |
| one `ReachableFront` rebuild (windowed) | 20 ms |

Gating a directional process is therefore free within the noise, because
`motion._FLUX_REFRESH` rebuilds every factor of a `ProductFlux` on the same
sub-steps and the flux is the expensive one: a 4 nm RIE at the reference grid
costs **1.28 s gated and 1.28 s ungated**, and a heavy 60 s ion-beam etch 9.9 s
against 9.0 s — **+10 %** on the worst case in the book.

The ideal tier is cheaper still, which is the point of it being a different kind
of operation rather than a flag: the complete spin-coat + ideal exposure + ideal
development sequence is **0.30 s** and an ideal lift-off **0.19 s**, against
0.74 s for a single 4 nm directional deposition. What the *gated* tier costs is
the fast path: a reachability-gated 4 nm ALD is 0.69 s where the ungated
conformal offset is 0.38 s, because gating turns one array operation into an
advection. That is the price of the topology, and S3 is what it buys.

§17.7's conclusion stands unchanged: what dominates a heavy step is still the
upwind stencil over the whole domain, not the flux and not the gate.

### 19.7 S4 as written does not produce fences

§1 describes S4 as "partial sidewall coverage (broad lobe + surface mobility);
after dissolution the sidewall metal attached to the substrate film remains
standing as fences", on the same stack as S1. Measured, that stack does not
produce fences — it produces **S3's failure**.

The reason is geometric and not a solver artifact. On a straight resist wall the
arrival grows monotonically with height: a point on the wall sees the sky through
the opening, and the higher it sits the wider that window is. So the film is
**thinnest at the bottom**, which is precisely where a fence would have to be
attached. Measured on a 120 nm wall over a 60 nm window with a cos¹ source, wall
thickness bottom to top: 2, 2, 2, 3, 3, 4, 4, 5, 6, 7, 9, 8, 10 nm — continuous
from floor to cap, in every combination of window width (50-80 nm), resist
thickness (100-140 nm), film thickness (12-40 nm) and mobility length (0-25 nm)
that was tried. A continuous film seals the resist, the solvent never reaches it,
and nothing lifts.

Fences need the **re-entrant profile a real lift-off resist has**, and the model
gets there the way a cleanroom does: a bilayer, with a non-imaging underlayer
that the developer clears further back than the imaging layer's own window. Then
the overhang's underside faces down, receives an arrival of exactly zero, and
separates the cap from everything inside the cavity — while the broad lobe still
reaches the cavity's vertical walls and leaves metal there, attached to the film
on the floor. Measured over cavity widths 110-130 nm, film 20-30 nm and mobility
0-10 nm: fences 15-26 nm above the flat film, one connected occurrence, lift-off
clean in every case. An evaporation on the identical stack leaves a flat pattern
of the mouth's width and no fences at all.

The other half of §1's sentence is also not what the measurement says. **Surface
mobility is not what creates the fences** — the broad lobe alone does, and the
mobility mostly thickens the cap's edge. On the straight-wall stack a mobility
length of 15 nm or more closes the mouth outright and breaks the lift-off that
worked without it. `didactic_library` gains an `underlayer` entry for this, and
the scenario keeps a modest 10 nm mobility because it is harmless there and
because §1 names it.

### 19.8 The plan's own S4 acceptance wording, adjusted

§13.3 asks for "S4 fence components present". They are not components: §1's own
sentence is the accurate one — the sidewall metal is *attached to the substrate
film*, which is exactly why it survives support filtering. The surviving metal is
**one** occurrence whose profile carries raised rims at both pattern edges, and
that is what the acceptance test asserts (rims ≥ 10 nm above the flat film, at
both edges), together with the control that shows an evaporation on the same
stack leaves none.

## 20. Corrections from implementation (M4)

Added 2026-08-26 after M4 was built and measured, in the same form as §17, §18
and §19: the agreed text above stays as written, and each item here amends one
statement with the measurement that showed it. Nothing in the *decisions*
changed — append-only revisions, lazy cached replay, one exchange format,
capability gating in the UI and a renderer that is a consumer all held. What
changed is a set of statements about what those objects cost and about what the
naive version of each one does.

The recurring theme this time: **a number measured on one scene is a statement
about that scene.** Three of the eight items below are a figure from the M4
handoff that turned out to be the best case rather than the typical one, and the
reason is always the same — the object being measured had less variety in it
than a real revision does. That is the fourth milestone in a row where the
correction is about *values* rather than about structure, which is the shape
§17's own summary predicted.

### 20.1 A `Revision` stores its `Structure`; the *chain* is the lazy element

The design decision the M4 handoff (§3) asked to be made first, and the one
§3.6 and §8 disagree about: §3.6 lists `structure: Structure` as a field, §8
specifies lazy replay with a cache, and they are not the same design.

Settled as the handoff recommended, and the recommendation survives its own
numbers being wrong (→ §20.3). A `Revision` holds its `Structure`, exactly as
§3.6 writes it. `RevisionChain` keeps the recently touched revisions resident,
spills the rest through a `RevisionStore` and faults them back on demand. The
expensive thing was never the format — it was holding twenty structures at once,
and that is a property of the *chain*, so the chain is where the laziness went.

What is always resident is a `RevisionSummary`: index, parent, step id,
capabilities, whether the gate was happy. A step list, a gating decision and a
run log read that and never touch a structure, which is what keeps scrubbing a
long chain cheap. Measured on a six-step chain at the reference grid with
`resident=1`: building the whole run log and step list faults **zero**
revisions.

Replay from the substrate stays the fallback for a cache miss and the mechanism
for a new wafer position, which is what ADR-0004 needs it for.

### 20.2 A committed field is not a fixed point of the reinitialisation

The commit gate reinitialised **every** material on every commit, including the
ones the step never touched, and handed back a fresh array either way. The
handoff (§3, second decision) records this as a footprint matter — revisions
shared no arrays at all. It is also a correctness one, and that half was not
predicted.

Reinitialising S1's developed resist again and again, at 1 nm: the enclosed
measure grows by **+0.16, +0.46, +0.79, +1.44, +2.74, +4.49 and +8.00 nm²** over
1, 2, 3, 5, 10, 20 and 60 passes — monotone, never converging, with the *cell*
count unchanged throughout and the band gradient error getting worse (0.065 →
0.245 at 60). A clean half-plane is a bit-exact fixed point and stays one after
twenty passes; a developed resist is not.

So a chain in which each step moves a different material was quietly inflating
the ones it did not touch, once per step, and §4.5's balance check could not see
it: the check compares the solid's measure against the *swept* estimate of the
step that did move something, so the drift is charged to that step. §15's risk
row ("reinit drift accumulates over long chains") had a leak its mitigation did
not cover, because the displacement it reports per commit is attributed to the
wrong step.

The repair is to skip the pass: `gate.commit` keeps the parent's array for a
material the step handed back unchanged — identity first, bit-equality second at
0.011 ms against 3.8 ms for the reinitialisation it replaces — and reports which
materials on `ValidationReport.shared_with_parent`. `reinit.reinitialise` also
returns its input array when the sweep was a fixed point, the way the
no-zero-level path always has.

Measured on S1 at 241×301: consecutive material/revision pairs sharing an object
**0 → 7 of 9**, distinct `phi` arrays **12 → 5**, `phi` footprint **3.48 →
1.45 MB**. At the reference grid, **31.19 → 12.99 MB** over six steps, the same
58 %.

**Sharing is a property of the step, not a promise the gate can make**, and the
asymmetry is §17.2's clip read in both directions. A deposition grows the union,
so `max(phi_m, phi_solid_new)` is the identity and every existing material comes
through untouched. A removal grows the union's *distance*, so the clip raises
`phi_m` wherever the opened region is now further from any solid than the
understated value that material carried: measured, a 4 s etch that gives a mask
a rate of **zero** still changes **1589 of its cells by up to 2.41 nm**. That is
why the shared set is reported rather than assumed.

### 20.3 The compression ratio belongs to the field's content, not to the format

§9 does not promise a number, but the M4 handoff (§3) does — 5.83 MB raw to
**0.04 MB** compressed, 137×, on "one revision, 2 materials + 1 field" — and
uses it to conclude that persistence is a non-issue. The conclusion holds. The
number is the best case.

`savez_compressed` compresses well because a signed-distance field on a grid is
piecewise linear and therefore takes very few distinct values. That is a
property of *signed-distance fields*, and a `Field` is not one. Measured across
one six-step chain at the reference grid (541×1201 = 649 741 cells):

| revision | raw | on disk | ratio | distinct values |
|---|---|---|---|---|
| `substrate.select` | 2.60 MB | **0.005 MB** | 493× | silicon: 541 |
| `resist.spin_coat` | 5.20 MB | 0.010 MB | 541× | + resist: 321 |
| `litho.expose_dose` | 7.80 MB | 0.126 MB | 62× | + dose: 9 895 |
| `develop.ideal` | 8.45 MB | 0.100 MB | 84× | resist: 1 583, dose: 5 113 |
| `deposit.evaporate` | 11.05 MB | **0.319 MB** | 35× | + metal: 21 162 |

Two things follow. The ratio varies **14×** within one chain, and it tracks the
number of distinct values rather than the number of arrays: a `dose` field
written by a real exposure has ~10 000 of them and a `phi` freshly grown by a
directional deposition has ~21 000, where a clean half-plane has 541. A field
with per-cell entropy does not compress at all — a synthetic `linspace` dose over
648 000 cells took the whole revision down to **6×**, which is the honest
worst case for a format that stores arrays.

The conclusion the handoff drew from its number survives its correction, which is
why the design above was not revisited: the heaviest *real* revision measured is
**0.319 MB and 71 ms to save**, against 1.3 s for the cheapest step that produces
one. Persistence is still a non-issue. What is not safe is quoting 0.04 MB as
the size of a revision.

### 20.4 A blanket layer's outline is not a polygon

§10 says "filled regions from marching squares over each `phi_m`". Every layer
that spans the domain — every substrate, every spin coat, every blanket film —
reaches the lateral faces **by construction**, which is the same sentence §17.5
uses about the headroom guard. `kernel.contours` says plainly what it does with
those ("open polylines … do not [repeat their first point]"), and §10 does not
say what a filler should then do with an open polyline.

Filling each on its own closes it with a straight chord between its own two
ends. Measured on a silicon/resist stack at 300×240 nm: silicon comes back as
**one open polyline from (40, 300) to (40, 0)** and the resist as **two**, at 40
and 130 nm; for a horizontal line the chord makes a polygon of zero area, and
the substrate and the resist did not appear in the picture at all. Only the
metal pattern, whose contour is a genuine closed loop, was drawn.

The repair is to stitch the open pieces **to each other** around the domain
boundary rather than each to itself. Walking counter-clockwise in the drawn frame
keeps the region on the left, which is the orientation `marching_squares` already
guarantees, so the boundary run from where one piece leaves the domain to where
the next comes back is exactly the part of the domain edge that belongs to the
region; corners passed on the way are inserted. After it, the enclosed areas are
**12 000 and 27 000 nm²** against cell counts of 12 040 and 26 789 — the contour
being the sub-cell number and the cell count the quantised one, as §17.1 requires
for a per-material measure.

`ui.scene.fillable_outlines` is that operation, and it is a **rendering** concern
rather than a kernel one: it decides how to fill, not where anything is.

### 20.5 The phantom zero reaches a fill rule, not a contour

The M4 handoff's first trap (§4.1) predicts that "`marching_squares` over
`phi_m` will happily draw a contour along a phantom zero level". Measured, it
does not, and the reason is worth writing down because it is the one place
§19.2's defect is harmless: marching squares tests `field < level` **strictly**,
and a phantom zero is a zero-valued cell with no strictly-inside cell on either
side, so it produces no sign change and no contour. On the silicon / 60 nm oxide
/ resist stack — §19.2's own fixture, where `phi_resist` reads exactly 0.0 along
the buried silicon/oxide interface in **all 301 columns** — the resist still
contours as 2 loops of 600.0 nm, which is right.

What the trap really is, is a **fill rule** of `phi_m <= 0`: on that same stack
it claims 301 extra cells for the resist, one full row across the domain, 60 nm
below its own underside. So regions come from `material_index` — `argmin_m
phi[m]` masked by the *union's* `solid_mask`, an exclusive partition that cannot
contain a phantom — and outlines come from the field.

Going the other way, contouring `regions.closed_region`, is correct and
**cell-quantised by construction** (`regions.signed_distance_of` says so itself),
and it shows: on S1 after evaporation the metal's outline comes out **687.2 nm**
against the field's **681.4 nm**. The region path is therefore the fallback, not
the default.

Both rules are checked rather than trusted, the way the handoff asks: every
`MaterialShape` carries the occurrence count `kernel.occurrences` derived for the
same revision, and the test suite asserts that the loop count matches it at every
revision of S1 — where the resist splits in two, the metal lands in three pieces
and one survives.

### 20.6 A scene is not a frame; a repaint is

§10 is silent on where the boundary between "build a picture" and "paint it"
should sit, and the M4 handoff's §5 budget suggests it does not matter much
(`marching_squares` 21 ms, `material_contours` 28 ms). It does matter, because
`label_occurrences` is in the same picture and is the expensive half. Measured at
the reference grid, three materials:

| | |
|---|---|
| `SceneSnapshot.build`, no overlays | **107.5 ms** |
| of which `label_occurrences` | 69.3 ms |
| of which `marching_squares`, all materials | 41.7 ms |
| `SceneSnapshot.build`, every overlay | 260.5 ms |
| canvas repaint from a built scene, 900×600 | **11.9 ms** |
| the same, index-map path | 12.1 ms |

A scene is built when the revision changes; a repaint happens on every resize,
every hover and every expose. The 9× separation is what makes that split
worth having, and it is the reason `CrossSectionCanvas` holds a snapshot rather
than a `Structure`. Overlays are computed only for the kinds actually asked for,
which is handoff §4.3's finding applied: a predicate is 3–12 ms, cheap once and
not cheap per frame.

### 20.7 Eviction without a store is deletion

Found while building, and recorded because the error it produced named the wrong
thing. `RevisionChain` applied its residency LRU whether or not it had a
`RevisionStore`, so a four-step run at the default residency of three silently
dropped revision 0, and asked for it said "this chain has no store to fault it
from" — which reads as a missing store rather than as a chain that threw a
revision away.

A residency window is a *memory* policy. A memory policy that loses data is a
different feature, so a chain without a store now holds everything and ignores
`resident` entirely.

### 20.8 Measured M4 costs, extending §17.7, §18.8 and §19.6

Reference grid, 540×1200 at 1 nm (the recipe runs at 541×1201).

| | |
|---|---|
| save one real revision | 14–71 ms |
| load one back, content hashes verified | 7.5–34 ms |
| the same, `verify=False` | 3.0–15 ms |
| one revision on disk | 0.005–0.319 MB |
| a six-step chain on disk, whole | **0.50 MB** |
| a six-step chain's `phi` in RAM, shared | 12.99 MB |
| the same if nothing were shared | 31.19 MB |
| S1 solved, six steps | **7.6 s** |
| the same, replayed from a warm cache | **0.11 s** (68×) |
| faulting one revision back into a chain | 43 ms |
| save a six-step session | 200 ms |
| load it back | 102 ms |
| `SceneSnapshot.build` / canvas repaint | 107.5 / 11.9 ms |

Verifying content hashes on load costs **2.3–2.5×**, and it is on by default
anyway: the cache faults structures into a *running* chain, so an unchecked
corruption becomes a wrong answer rather than an error, and 34 ms against the
7.6 s solve it replaces is not a trade worth making. §8's "a 20-step replay is
seconds to ~a minute" holds — six steps solve in 7.6 s, so twenty are ~25 s, and
a warm replay of the same is under half a second.

**§17.7's conclusion is unchanged through four milestones**: what dominates is
the upwind stencil over the whole domain, not the flux, not the reachability
gate, and not persistence. A true narrow-band solver remains the structural fix
that is deliberately not built.

## 21. Corrections from implementation (M5)

M5 built no model. Every line of it is packaging, a view, or one of the four §6
rows M3 and M4 deliberately left out — so the failure modes changed again, and
the handoff predicted where: *"M5 in ways that only appear in the frozen exe on
somebody else's machine"*. That prediction was half right. The exe did produce
two findings (§21.1's fallback confirmed, §21.6's plugin boundary), and both were
already *written down* as expectations rather than discovered; what actually went
wrong was ordinary Python (§21.3) and a layering assumption in the handoff itself
(§21.7).

§20's findings were about values and costs. §21's are about **boundaries** — what
a cache key covers, what a step may reach, what a frozen build is.

### 21.1 The cache key has two axes, and the per-step one belongs in the recipe hash

The decision the M5 handoff (§3) asked to be taken first, taken as recommended.

ADR-0004 keys a cached revision on `(recipe hash, position, step index, code
version)` and M4 implemented `code_version()` as `nanofab_v3.__version__`,
writing down that bumping it is "the intended and only mechanism" for retiring a
cache. That is honest while this package is the only code that can change. It
stops being honest the moment a plugin ships a step: a third-party
`deposit.mocvd` can change its rate model without `__version__` moving, and every
revision cached under the old one is then served as if it were current. Nothing
errors — the numbers are quietly from the previous version. The same hole is
already open without plugins, because editing a builtin's own wrapper during
development does not move `__version__` either.

So: **two axes.**

- `code_version()` stays `__version__` and stays coarse. It covers what a recipe
  cannot name — the kernel, numpy/scipy, the interpreter — and it is the axis
  ADR-0004's cross-machine-drift paragraph is about. Bumping it retires
  everything, everywhere.
- `processes.registry.implementation_digest(step)` digests the step's `step_id`,
  `fidelity`, parameter schema, capability contract and the source of its own
  wrapper. It goes into the **recipe** hash (`RecipeStep.fingerprint(digest)`,
  `Recipe.fingerprint(digests)`, `io.store.recipe_hash(recipe, registry=...)`),
  so editing a step retires exactly the recipes that use it and editing an unused
  plugin retires nothing.

Measured over the 18 builtins as they stood: **3.6 ms per step cold** (64–69 ms
for all of them; the first `inspect.getsource` on a module pays for reading it
into `linecache`) against **0.00015 ms** memoised on the registry. A six-step
recipe therefore pays ~21 ms the first time it is hashed and nothing after —
which is what makes it affordable for a wafer fan, where the hash is taken once
per position.

**The limit, stated because it is not obvious: the digest covers the step's
wrapper, not the kernel it calls.** `deposit.evaporate`'s `run_function` is 16
lines of parameter unpacking around `kernel.flux`; a change inside
`kernel/flux.py` does not move it. That is the division of labour — the wrapper
is what a plugin owns, the kernel is what `__version__` owns — and it only works
if both are actually maintained.

The digest is an **argument** at every level rather than a lookup, because a
`RecipeStep` names a step by id and which registry resolves that id is the
caller's fact. `io.replay_cache_for(directory, recipe, registry=...)` is the one
call a cache site makes, so "which hash does this cache go under" is answered in
one place.

A source-less step falls back to the contract alone and **says so**: the digest
is `nosrc:…` instead of `src:…`. Confirmed on the frozen build, which reports
`step digests: contract only (no source)` — so an exe and a source install never
trade cache entries under a key claiming they are the same code. For an exe whose
plugin set is fixed at build time (§21.6) that fallback is the whole story
anyway, since nothing can change between two runs of it.

### 21.2 An annealed material's new rates live in the library, as a second entry

The handoff (§6, item 4) asked where they go, given that `StepContext.library` is
passed in rather than stored. The answer is that they were already there.

Plan §3.4's rule is load-bearing: a `Structure` that carried its own rate table
would be a `Structure` whose meaning changed when the library was corrected, and
every cached revision would have to be replayed to find out. So an anneal cannot
hand back a modified library — there is nowhere to put it, and a cached revision
would not know which one it ran under.

It does not need to. **An anneal that changes how a material behaves has turned
it into a different material**, and the library holds both: `resist` and
`resist_hardbaked` are two `MaterialType`s, and `anneal.thermal` moves the
geometry from one to the other. The same `phi` array is handed to the new
material — exact, one dict operation, no reinitialisation — and every rate
downstream follows without a step being told about temperature.

The capability machinery comes along free, which is the sign the decision fits:
`material:resist` retires because the resist is gone, `material:resist_hardbaked`
appears because it is there, and `resist.exposed` goes with the old material,
which is right — a latent image in a hard-baked resist is not a latent image.

The mechanism lands at the **rate tier**, and that is worth recording because it
is a limit of the ideal one. `strip.rate` consults `dissolve_rates`, which gives
a rate of zero to a material the bath does not attack, so acetone takes an
unbaked 60 nm resist to zero measure in 3 s and leaves a hard-baked one whole.
The *ideal* tier (`strip.dissolve`, `strip.lift_off`) does not consult chemistry
at all — it removes the reachable occurrences of whatever material the recipe
names, which is §19.4's rule and is coherent: at the ideal tier, naming the
material *is* the statement that the bath attacks it. A recipe that keeps saying
`strip.lift_off(material="resist")` after a bake finds no `resist` and is a
silent no-op, which is the honest failure and the realistic mistake.

Reflow geometry stays open (§16). An anneal sweeps no front, so it is outside the
balance check.

### 21.3 An empty registry is falsy, and `or` silently replaced it

Ordinary Python, found by a test that meant to pass an empty registry and got the
builtins back.

`ProcessRegistry` and `MaterialLibrary` both define `__len__`, so an empty one is
**falsy**. Every `registry or builtin_registry()` and `library or
didactic_library()` therefore swapped a caller's deliberate choice for the
defaults without a word. In `runtime.replay.Run`, `run_recipe`, `materialize`,
`ui.Session` and `acceptance.run_all`, a run built against a registry that turned
out to be empty would have run the builtins and reported success.

`processes.engine.run_step` had it right (`didactic_library() if library is None
else library`) since M3, which is why nothing had caught it: the one place a test
passes a deliberate library is the one place the idiom was correct. Every site
now tests `is None`, and `tests/test_runtime.py` asserts that a `Run` with an
empty registry raises `KeyError` rather than quietly running something else.

Worth stating as a rule rather than a fix: **a container with `__len__` may not
be used as a truth value for "was one supplied".** The same shape would bite
`Recipe` (which has `__len__`) and any future collection.

### 21.4 Two of the handoff's traps did not fire, and where the particle decision went

Handoff §4 named six traps. Two were aimed at particles and neither fired, for
reasons worth recording so the next milestone does not re-aim them.

**Trap 2 ("a correct set operation can be a useless field") was avoided by
construction rather than survived.** The trap is that a disk placed at a
uniformly random point in the domain lands inside the substrate about as often as
not, `add_material` carves it away, and the step reports a particle count the
geometry does not match. So `particle.seed` draws only the *lateral* coordinate
and reads the height off the sample — the topmost solid cell in that column, with
the disk sunk one cell so it shares a cell with what it landed on before the
carve. A particle is then always in empty space, always touching what it landed
on, and always visible. A column with no solid in it gets **no** particle: the
model has no floor below the domain to invent, and the step says how many draws
it skipped.

**Trap 5 ("ordinary geometry breaks tolerances tuned on smooth scenes", §18.6)
did not fire at all.** Measured on a disk of 8 nm at 1 nm/cell: the commit gate's
reinitialisation moves a particle's interface by **0.0002 nm** (0.045 nm² of
measure), and a 10 nm conformal film over four of them balances **2.50% off
against a 5% tolerance**. Nothing was loosened for S5, which is the only way
those numbers stay worth anything.

What the two traps did produce is S5's shape. Five particles at the seed give
**four occurrences** — two of them overlap and are one connected piece, which is
ADR-0003 answering rather than a fixture to fix. Buried under 10 nm of conformal
alumina the clean removes **0 of 4**, leaves 868 nm² micromasked, and the film
that is flat to the cell over bare silicon bulges **14 nm** over the particles.
The control — the identical draw, cleaned before anything covers it — loses all
four and retires `material:particle`. No step is told the particles are buried;
`reachable_occurrences` answers, exactly as it does for S3's sealed resist.

### 21.5 Measured M5 costs, extending §17.7, §18.8, §19.6 and §20.8

The new numbers are about **delivery**, and handoff §4's first trap applies to
every one of them: a number measured on one machine is a statement about that
machine. These were taken on the build machine, cold, once each.

| | |
|---|---|
| the frozen exe | **115 MB** |
| `pyinstaller nanofab_v3.spec`, cold | 1 min 37 s |
| exe cold start to argument parsing | **2.6–3.4 s** |
| the same from a source install | **0.53 s** |
| exe `--selftest`, all seven scenarios | 6.9 s of solver, **10.7 s wall** |
| per-step implementation digest, cold / memoised | 3.6 ms / 0.00015 ms |
| an inspection step through the commit gate | **25 ms**, every array shared |
| build + install the example plugin | 3.4 s |
| a five-position fan of a two-step recipe, cold | 0.15 s |
| the same over a warm cache | **0.01 s** |

Two things follow.

**Freezing costs ~2.4 s of startup, five and a half times a source install.** That
is the bootloader unpacking 115 MB of numpy, scipy and Qt before a single line of
this package runs. It is invisible to `--selftest`, where 4 s of overhead sits
next to 7 s of solver, and it is the first thing a person double-clicking the exe
notices. Recorded rather than fixed: a one-directory build (`--onedir`) trades it
for a folder instead of a file, which is a delivery decision and not a model one.

**The scenarios cost the same frozen as unfrozen.** 6.9 s of solver in the exe
against 6.5–7.0 s from source — the same arithmetic on the same numpy, which is
what ADR-0004's "determinism per machine + code version" needs to be true of a
build as well as of a checkout.

**§17.7's conclusion is unchanged through five milestones**: the upwind stencil
over the whole domain is what dominates, and a true narrow-band solver remains
the structural fix that is deliberately not built. M5 was the wrong place to
start it — it would have invalidated every cached revision on the day the exe
shipped.

### 21.6 "Entry points from day 1" was half true, and a frozen build is a closed set

§11 says *"registry + entry points from day 1"*. Half of it was: the registry
existed from M3 and every builtin went through `register()`, which already
refuses a duplicate `step_id` and lints for a process-global RNG. Nothing read
`importlib.metadata`; `builtin_registry()` was a hard-coded list. That was
deliberate — a seam exercised by every test beats a discovery mechanism designed
against nothing — and M5 closed it through the same door rather than a second
one.

Three things the implementation settled that §5.4 left open.

**An entry point may be a `ProcessStep` or a callable taking the registry.** One
step per entry point with no boilerplate, or a package that registers several.
`isinstance(obj, ProcessStep)` tells them apart unambiguously, because the
protocol is `runtime_checkable` and a plain function has no `step_id`.

**Discovery reports; it never raises.** A plugin whose import fails, whose object
is the wrong shape, or whose `step_id` collides with a builtin is recorded in a
`DiscoveryReport` and skipped, and everything else still loads. The failure this
avoids is the one that matters for a delivered application: one stale
third-party package, and the process list is empty with a traceback where the
step list should be.

**`builtin_registry()` stays a fixed set and does no discovery.** The recipe
hashes and implementation digests the cache is keyed on (§21.1) are computed
against a registry; a *test* whose registry depended on what happened to be
installed would answer differently on every machine. So the tests take the
builtins and the application takes `plugins.application_registry()`. The
self-test does too: a third-party plugin that failed to load must not be able to
turn S1 red.

**And a frozen build is a closed set, measured.** §11's "plugins usable in source
installs; frozen app extension = rebuild" is literally true: the exe reads the
entry-point metadata frozen into it, and a plugin installed for the *host*
Python — even on `PYTHONPATH` — is not found. The exe reports `plugins: none
found` where the same command from source reports the two the example plugin
brings. That is the intended boundary; it is recorded here because "I installed
the plugin and the exe cannot see it" is otherwise a bug report.

`examples/nanofab-plugin-example/` is the second implementer this needed: its own
package, its own material the didactic library has never heard of, one entry
point of each shape, and a test that really builds and installs it into a temp
directory (3.4 s) and runs discovery in a subprocess — so a pass proves the
loader found it through `importlib.metadata` and not through `sys.path` happening
to contain the source.

### 21.7 The artifact wire was not a one-line change, and a pure step needs a sink

The M5 handoff (§2) called wiring `StepResult.artifacts` through to
`Revision.artifacts` "a one-line change". Two things were in the way, and both
are boundaries rather than plumbing.

**`ArtifactRef` was on the wrong side of the layering.** It lived in
`runtime.revision`, and `processes` may not import `runtime` — the dependency
runs the other way. It moved to `model/artifact.py`, which is where docs §4.2.2
puts the concept anyway, and `runtime.revision` re-exports it so nothing else
changed. `StepResult.artifacts` was `tuple[str, ...]` and is now
`tuple[ArtifactRef, ...]`, which is what `Revision.artifacts` always was.

**A pure step cannot open a file.** §5.2 makes a step a pure function of (input
structure, params, position, step index, code version), and an artifact is a
*file*. So a step that produces one is handed somewhere to put it:
`StepContext.artifacts`, an `ArtifactSink` (`MemoryArtifactSink` for tests and
sessions, `io.DirectoryArtifactSink` for files, and a `Run` hands one to every
position).

The invariant survives, and the reason is worth stating once: what §5.2 makes
pure is the step's **outcome** — the structure it commits, the capabilities it
provides, the numbers it measured. An artifact is none of those. It is a record
of a run, in the same category as `HistoryEntry.started_at`, which replay has
never reproduced either. Two replays write the same bytes to the same relative
name, so a re-materialized position points at a file with the same content.

**A step with no sink emits no artifact and still measures everything.** That is
the honest default rather than a degraded one: `inspect.profilometer` with
nowhere to write a trace has still measured the step height, and a reference to a
file nobody wrote would be worse than no reference.

One measured consequence, and it is the one that makes inspection cheap: because
an inspection returns `ctx.structure` **itself** rather than an equal structure,
§20.2's sharing rule hands the whole revision its parent's arrays. Measured on a
developed stack: **25 ms** for the commit, every material's `phi` shared by
identity, `swept=None` so it is outside the balance check.

### 21.8 What the plan does not carry past M5

Written here rather than left implicit, because §14's milestone list ends and
§16's "deliberately open" was written before any of it was built.

Still open exactly as §16 has it: the 3D `FluxModel3D`; semi-quantitative rate
calibration; external-simulator adapters beyond §9's exchange format;
reflow/anneal *geometry* (§21.2 built the field and material-model half only);
GDS/CAD pattern import.

Added to that list by M5, each with the reason it was not done rather than
overlooked:

1. **A narrow-band solver.** §17.7's dominant cost, unchanged through five
   milestones. Deliberately not built in M5 because it would invalidate every
   cached revision on the day the exe shipped (§21.5).
2. **`--onedir` packaging.** 2.4 s of the exe's startup is the bootloader
   unpacking a 115 MB archive (§21.5). A folder instead of a file trades that
   away, and it is a delivery decision.
3. **A recipe encoding open to a plugin's own `WaferParameter`.** M4's note 6:
   the encoding knows `RadialProfile` and `LinearTilt` and raises on anything
   else rather than writing a resolved value at some arbitrary position. A
   plugin's interpolant therefore cannot be *saved* yet, though it runs. Opening
   it up means a registry of parameter kinds, which is the same shape as §5.4's
   step registry and should probably reuse it.
4. **Artifact payloads in the exchange format.** §9 saves a revision's
   `ArtifactRef`s and not what they point at, which is correct (docs §4.2.2) and
   means moving a saved session moves the manifest and not the SEM images.
   Bundling is a packaging question for the format, not a model one.

## 22. Corrections from implementation (M6)

M6 is roadmap `docs/plans/m6-m9-roadmap.md`'s first milestone rather than one of
§14's, so this section continues §17–§21 for a plan whose own milestone list ends
at M5 (§21.8). What it corrects is mostly §3.4 — the sentence "a **MaterialType**
— a library entry" turns out to have been a statement about a *file*.

### 22.1 One rate key cannot hold two rate sets

The roadmap's §3 maps the student table's row 1, "sputter etching", onto the
existing `ION_BEAM` process class, marked *(existiert)*. It cannot be taken
literally, and the reason is arithmetic rather than taste.

`ion_beam` already carried the didactic ratios S1–S5 are tuned to — silicon 1.0,
oxide 0.8, resist 1.2 nm/s. The table's row 1 gives the same three materials
0.2333, 0.2000 and 0.2500. Writing the table's numbers into that key would have
changed what every existing ion-beam recipe *means*, four-fold and silently, and
E14's own completion criterion is bit-identity of the migrated models — so the
same milestone would have asserted that nothing changed and changed something.

The resolution is the roadmap's own rule (`§3`: *additiv erweitern, nichts
umbenennen*) applied one step further than its table anticipated: row 1 became a
seventh new class, `sputter_etch`, and `ion_beam` was left alone. Recorded here
as **E18**, because a later reader comparing the table to `PROCESS_CLASSES` will
count thirteen where §3 implies twelve.

It is not a workaround. Plan §5.4 already says several registered processes may
model the same technique at different fidelity; this is the same statement one
layer down, in the rate table instead of in the step. `etch.ibe` and
`etch.sputter` are one technique, one wrapper (`ion_beam_etch` gained a
`process_class` argument) and two columns of the library — and the honest reading
of "didactic numbers" versus "a measured table" is that they are two sets of
numbers, not one set with a disagreement in it.

The general form, and the part worth keeping: **a rate key is a claim about
provenance as much as about physics.** Two numbers from different sources under
one name make the library's own provenance unreadable, which is what `rate_notes`
(§22.4) exists to prevent one level further down.

### 22.2 "Bit-identical" is a claim about a commit, so the test carries both halves

E14 asks the migrated library to be bit-identical to `didactic_library()`. The
obvious test — compare the loaded library against the function — becomes vacuous
the moment the function *is* the loader, which is the same commit. And the
non-obvious problem is the next one: M6 then *deliberately* added the table's
rates to `oxide`, `silicon` and `resist`, so a test that forbade every difference
would have had to be relaxed on the day it was written.

`tests/test_material_files.py` holds the eight pre-migration entries as literals,
copied out of the commit before the migration, **and** a dict of every change M6
made to one of them. The assertion is `pre + declared additions == what loaded`.
Both halves earn their keep: the first says the migration lost nothing, the
second says every later difference between the code that was and the files that
are is deliberate and listed in one place. A rate edited by hand in a JSON file
fails a test naming the material, instead of quietly changing what a scenario
means.

The prose fields (`notes`, `rate_notes`) are excluded from that comparison and
checked separately — that every table-derived rate has a stated provenance, and
that every borrowed one says it is assumed. Pinning prose would have made the
test a transcription exercise; pinning *that prose exists* is the actual rule.

### 22.3 A library that loads from the source tree is a library the exe does not have

The roadmap says `data/materials/`. Taken as a repo-root directory it is in git
and in **no** install: `pip install nanofab-v3` installs `nanofab_v3/` and leaves
it behind, and §11's one-file exe would collect a path that only exists in a
checkout. So it is `nanofab_v3/data/materials/`, inside the package, with
`pyproject.toml`'s `package-data` for a wheel and `collect_data_files` in
`nanofab_v3.spec` for the exe.

Measured rather than argued, because §21.6's lesson was that the delivery
boundary is where assumptions die:

- a wheel built from this tree carries all eleven files plus the README, and a
  **non-editable** install of it loads them (`builtin_materials_dir()` resolving
  to `…/site-packages/nanofab_v3/data/materials`);
- the frozen exe reports `materials: 11 from 2 root(s)` with its shipped root at
  `/tmp/_MEI…/nanofab_v3/data/materials`, and passes 7 of 7 scenarios.

`builtin_materials_dir()` tries `importlib.resources` and falls back to the
package directory, and both paths are needed: the fallback is what answers under
PyInstaller's one-file unpacking. And `--version` now prints how many materials
loaded and from where, because the failure mode of getting this wrong is an
application that starts normally and dies at the first rate lookup — on somebody
else's machine.

**Two roots, and the split is `builtin_registry()` versus `application_registry()`
one layer down** (§21.6). `didactic_library()` reads the shipped root only and is
what the tests, the scenarios and `--selftest` use; `application_library()` reads
that plus a writable directory outside the package and is what the shell uses. A
check whose numbers depended on what happened to be in somebody's home directory
would answer differently on every machine, and the material library is the one
input the acceptance scenarios are least able to notice a change in.

### 22.4 A spin curve is not a rate, and the power law does not carry the points

`rates` is keyed by process class and answers nm/s. The student table's process
11 answers nm at an rpm, which is neither — hence roadmap E17's fourth submodel
on `MaterialType`, beside `develop`, `dissolve` and `sputter_response`, and on
the *resist* for the reason E13 puts tone there: the thickness a resist spins to
belongs to the resist, not to the coating step.

The arithmetic that decided interpolation over a fit is worth keeping because it
is the sort of thing a later reader will want to "simplify". Anchored on the
1000 rpm point, `d = k·rpm^-1/2` is **+6.3 %** at 2000 rpm and **−6.8 %** at
5000 — the error changes sign, so no single power law passes through the five
measured points, and the effective exponent drifts from 0.588 to 0.456 because
the curve flattens. The interpolation is linear in **log-log**: it passes exactly
through every measured point and gives each segment its own local exponent, which
is the quantity that drift was computed from in the first place. Measured points
are returned before any arithmetic runs, so 3000 rpm answers `82.0` and not
`82.00000000000001` — a quoted measurement with a float tail invites a reader to
wonder what else was computed.

Two things the data does not contain and the model therefore does not either.
Outside 1000–5000 rpm the curve **clamps and the run log says so**; and there is
**no time axis**, so `spin_time` is a documented parameter whose help text states
it does not enter the thickness. Both are the same rule: the alternative to
saying "nobody measured this" is a plausible number, and a plausible number is
the only kind that cannot be noticed.

### 22.5 An unknown *material* has to warn; a missing *rate* must not

E15's failure came from a real project: a chromium particle the library had never
heard of, silently at rate 0 through every process, behaving exactly like a
perfect hard mask. Every lookup in `processes.rates` filters on `material in
library`, so nothing raised and nothing printed.

The fix is one check, and its **placement is the whole of it**. It lives in
`processes.engine.run_step`, which is the only place every step passes through —
per-wrapper there would be thirty places to forget it and no coverage for a
plugin's step at all — and it runs **after** the commit, on the committed
structure's materials, because a material can arrive without any step naming it.
The particle it is named after arrived exactly that way.

What took the most care was the boundary, and it is a boundary of meaning rather
than of implementation. `MaterialType.rate_for` answering 0.0 for a class a
material has no entry for is a **documented statement** — "this does not move" —
and it is how a hard mask behaves without being modelled as one (§4.2). Warning
about that would fire on nearly every step and teach everybody to ignore
warnings, which would cost the feature its only mechanism. So: the library not
being *askable* about a material warns; the library being asked and answering
zero does not.

Free text stays legal, and that is not a concession — plan §5.4 already lets a
plugin bring a material the didactic library has never seen (§21.6's example
plugin does), and trying something uncalibrated is the didactic point. What ends
is the silence.

### 22.6 Measured M6 costs, extending §17.7, §18.8, §19.6, §20.8 and §21.5

M6 touches no kernel, so §17.7's conclusion — the upwind stencil over the whole
domain dominates, and a narrow-band solver is still the structural fix that is
deliberately not built — is unchanged for a sixth milestone. What is measured
here is the *data* layer, and the question it answers is whether reading a
library from disk costs anything worth noticing. It does not.

| | |
|---|---|
| `load_library`, 11 files, cold | **4.1 ms** |
| the same, warm OS cache | 0.8 ms |
| `didactic_library()`, memoised | **0.022 ms** |
| one material through `to_json`/`from_json` | 0.11 ms |
| `unknown_materials` over a structure's materials | **0.002 ms** |
| `SpinCurve.thickness` | 0.0014 ms |
| the whole shipped library on disk | 11 kB in 11 files |
| 31 implementation digests, cold | 116 ms (was 64–69 ms for 18) |
| the frozen exe, this machine, no PySide6 installed | 60 MB, `--selftest` **4.0 s** solver / 5.8 s wall |

Three things follow.

**The memoisation is what makes the migration free, and it is load-bearing.**
`engine.run_step` falls back to `didactic_library()` when no library is passed —
once per step — so an unmemoised loader would put eleven file reads inside every
step and turn §21.5's warm five-position fan (0.01 s) into a disk-bound one. At
0.022 ms it is below the noise of anything else a step does. The cache is keyed
on the root paths and cleared by `save_material`, so E15's dialog is visible
immediately rather than after a restart.

**E15's check is free at the scale it runs at**, which is what let it go in the
common path rather than behind a flag: 0.002 ms against the 25 ms an *inspection*
step costs through the commit gate (§21.7), i.e. four orders of magnitude down.

**The exe numbers are not comparable to §21.5's and should not be read as an
improvement.** 60 MB against 115 MB and 4.0 s against 6.9 s are a different
machine, a different OS and — decisively — a build with no PySide6 present to
freeze. §21.5's own first sentence applies: a number measured on one machine is a
statement about that machine. What the build *does* establish is the packaging
claim of §22.3, which is a yes/no and travels.

## 23. Corrections from implementation (M7)

M7 is roadmap §4's second milestone. What it corrects is §3.1's "the Grid is the
sole authority on positions" — still true — and the assumption that sat quietly
beside it, that a `Structure`'s grid is *fixed*. It is not, from M7 on, and most
of the section below is about what that touched and what it did not.

### 23.1 The trap that was named first did not exist

The M7 handoff names four traps and calls the second the place "M7 first meets
resistance": the grid is stored per revision (`io/manifest.py:143`) *and* at the
recipe (`:404`), and `manifest.py:18` speaks of "the reference grid, checked on
load", so allowing revisions of different sizes would mean reworking that
consistency path.

There is no such path. `manifest.py:18` says *"4.4 ms per `phi` at the reference
grid"* — it is the sentence quoting a **benchmark** grid for a measurement, not a
stored grid checked against anything. `Grid.check_same_grid` exists and is called
nowhere in the package (only in `tests/test_grid.py`, on itself);
`structure_from_json` reads each revision's grid from that revision's own
manifest; and `Recipe.grid` is the *initial* domain, which is exactly what
`Recipe.initial()` uses it for.

So a chain whose revisions have different grids saved and loaded on the first
try, and the test that proves it (`test_a_resized_revision_survives_the_exchange
_format`) was written expecting to have to fix something first. Recorded because
the handoff's prediction was reasonable and wrong, and the next person reading it
should not spend the afternoon that was budgeted for it.

What the resize *did* touch was smaller and less obvious, and it is §23.4.

### 23.2 The two ends of the domain are two different questions

The obvious implementation of "how much room is left" is symmetric: count the
rows at each end that look like the edge row, since those are where the sample is
doing nothing. It is wrong at the top, and wrong in the direction that matters.

A resist coat that fills the domain to the ceiling makes **every** upper row
identical to the top row. A symmetric rule reads that as plenty of room, and it
is precisely the case the growth exists for — measured, not reasoned: the first
implementation grew nothing and let the headroom FAIL stand.

So each end is asked what that end of the domain is *for*:

- `headroom` counts consecutive **entirely empty** rows at the top. Headroom is
  empty space by definition; a solid row is not headroom however uniform.
- `underroom` counts consecutive **laterally uniform** rows at the bottom that
  match the bottom row. Below, the domain is a window onto a homogeneous
  substrate that continues out of sight (roadmap §1), so a quiet row there is a
  vertical extrusion of the face — and a trench that reaches the floor makes the
  bottom row non-uniform, which is the signal to grow.

The general form is worth keeping because it is not about domains: **a predicate
that is symmetric in the code is not automatically symmetric in the physics.**
The top of a cross-section is where things arrive and the bottom is what they
arrive on, and no single "is this region interesting" test can serve both.

### 23.3 A margin is a trigger, not a target — and a trigger is not enough

Two decisions that look like one knob.

**The margin is small.** A policy that grew every domain until it had a
comfortable margin would silently replace the domain somebody chose: 40 nm of
substrate under 200 nm of headroom — the shape most of this repository's tests
are written against — would come back 190 nm deep before a single step ran, and
every measurement taken against it would be taken against a different picture
than the one asked for. So the trigger is a few cells and the *growth* is
generous (`chunk`), which also keeps it from re-triggering on the next nanometre.
Shrinking waits for `slack`, a whole micron, which is what E5's "auch schrumpfen,
wenn groß und leer" means by empty.

**A margin cannot deliver E5's promise on its own.** "Grows automatically instead
of failing" is about one step that moves the front further than any margin — a
150 nm coat into 100 nm of headroom. Nothing checked before the step can know how
far it will go, and the front that hit the domain face was clipped by it and
cannot be asked how much further it wanted. So `engine.run_step` runs the step,
sees the sample used the domain up, grows the **input** and runs it again, up to
twice with the growth doubling.

That costs an extra solve on the step that needed it and nothing on any other,
and it stays deterministic — which ADR-0004 requires: the resize is a pure
function of the input and the policy, the retry is a pure function of the
outcome, and the RNG is re-seeded identically from (recipe, position, index) on
every attempt.

### 23.4 The fit goes *before* the step, because the gate's parent shares its grid

The natural place for "fit the domain around the sample" is after the commit,
where the sample is. It is the wrong place, and the reason is one line in
`kernel.gate`: `commit(structure, parent=...)` compares the two — `_untouched`
for array sharing (§20.1) and `occurrences.match_lineage` for occurrence identity
(§3.5). Both assume one grid. A structure fitted after its commit would be the
*parent* of the next step at a different shape, and lineage matching between two
differently shaped label arrays is not a degraded answer, it is an exception.

So the fit runs first, and the fitted input is both what the step runs on and
what the gate takes as its parent. Grids then differ only *between* revisions,
never within a commit — which is the one place anything compares two.

The general rule this is an instance of: **a value object shared by two
consumers can only change shape where neither is mid-comparison.** The revision
chain tolerates differing grids because it never compares across revisions; the
gate does not, because comparing is its job.

### 23.5 The substrate's thickness is metadata, and the alternatives each fail differently

Roadmap E7 asks for the thickness to be "a real field from the start" so backlog
B2 (back-side processes, vias) is a behaviour change rather than a schema change.
Three places it could have gone, and each is wrong in its own way:

- **A `Field`** is one value per cell. Four bytes times the whole grid to say
  "1 mm", and a value that a step could accidentally make vary over the sample.
- **A capability** is set membership. `substrate.thickness` is a number, and the
  vocabulary of §5.3 has no room for one.
- **The `Revision`** is where provenance lives, and it is out of reach: §5.1 hands
  a step a `Structure` and nothing else, and the step that must refuse to etch
  through the wafer is exactly the one that needs the number.

So `Structure.metadata`: a small mapping of JSON scalars, carried by every
derivation and by the exchange format, deliberately open rather than a typed
`SubstrateSpec` field so that the next thing needing it — a chuck temperature, a
tool id, B2's back-side flag — is not a schema change. Scalars only, so §9's
format needs no encoder for it and a manifest stays readable by any JSON parser
(§9's third job).

The through-etch check that reads it lives in `processes`, not in the kernel
gate: `substrate.thickness` is a convention of the process layer, and a gate that
knew what that key meant would be a kernel that knows what a wafer is. It is
added to the gate's report in `engine.run_step` — the same "one place, every
step, plugins included" argument §22.5 makes for unknown materials.

And it measures the **deepest column**, not the average. A wafer is not breached
on average.

### 23.6 "Substrate first" cost no step contract, because the domain is derivable

E4 asks that a step other than the first be blocked with a hint rather than a
runtime physics warning. The obvious implementation — give every other step
`requires={"domain"}` — would have edited thirty contracts, moved thirty
implementation digests (§21.1) and retired every cached recipe in existence, to
express something none of those steps has an opinion about.

Instead `domain` is a **structural** capability like `material:<id>`:
`capability.derived` adds it whenever the structure has any geometry, so it
appears and retires by the same mechanism, and the rule lives once in
`ProcessRegistry` — a step that does not *provide* `domain` is blocked while none
is available. `substrate.select` is the only step that provides it.

The pay-off beyond the saved churn is that hand-built structures keep working:
every test that constructs a `Structure` directly has materials in it, so it has
a domain, and nothing had to be told about the new rule. What changed was three
tests whose *synthetic* capability sets described samples that did not exist.

### 23.7 Measured M7 costs, extending §17.7, §18.8, §19.6, §20.8, §21.5 and §22.6

The handoff asks for the resize at 1 µm and 5 µm depth, because §17.7's standing
finding — the upwind stencil over the whole domain dominates — means a growing
domain gets directly more expensive. Reference cross-section 1200 nm wide at
1 nm, one material, this machine:

| domain depth | 0.5 µm | 1 µm | 5 µm |
|---|---|---|---|
| rows × columns | 501 × 1201 | 1001 × 1201 | 5001 × 1201 |
| RAM per revision, 5 arrays | 11.5 MB | **22.9 MB** | **114.6 MB** |
| `resize` by +256 rows | 1.6 ms | 1.8 ms | 12.3 ms |
| `window` (the fit's own cost, per step) | 0.32 ms | 0.84 ms | 4.4 ms |
| `label_occurrences`, isolated | — | 95 ms | **642 ms** |
| `reinitialise` one `phi`, isolated | — | 52 ms | 148 ms |

Three things follow, and the third is a warning rather than a result.

**The fit is free at the scale it runs at.** 4.4 ms per step against the hundreds
of milliseconds the commit gate spends on the same domain — under 1 %, which is
what let it go in the common path rather than behind a flag, exactly as §22.6's
unknown-material check did.

**§17.7's conclusion needs refining rather than repeating.** On a *deeper* domain
the dominant cost is not the solver at all: it is the **commit gate**, and inside
it `occurrences.label_occurrences`, which scales worse than linearly (5× the
cells, 6.8× the time) where reinitialisation scales better than linearly (2.8×).
The solver's own advection is windowed around the front (§18.5) and barely
notices. So the thing that would make a 5 µm domain painful is occurrence
lineage, not the upwind stencil — which is a different optimisation target than
five milestones of measurement had suggested, and is recorded here rather than
acted on because M7 is not the place to start it.

**End-to-end step timings on this machine were non-monotonic and are not
trustworthy.** The same spin-coat took 169 ms at 0.5 µm, 283 ms at 1 µm and
129 ms at 5 µm, reproducibly, while every component of it measured in isolation
scaled upward. It could not be reproduced outside `run_step` and no structural
difference explains it — same occurrence counts, same geometry, same sub-steps.
§21.5's rule applies at full strength: **a number measured on one machine is a
statement about that machine**, and this one is a statement about a shared
virtual one. The per-component numbers above are the ones to trust; the
end-to-end ones are recorded so that nobody later reads a speed-up into them.

## 24. Corrections from implementation (M8)

M8 is roadmap §4's third milestone and the first that is almost entirely about
the application rather than the model. What it corrects is mostly §10 — "the UI
decides didactics" — by finding the places where the UI was not deciding
anything because the thing it would decide about was invisible.

### 24.1 A UI milestone whose UI tests skip is a UI milestone with no tests

`tests/test_ui.py` and `tests/test_wafer.py` had nine Qt tests behind
`pytest.importorskip("PySide6")`, and PySide6 was not installed in this
repository's container. They had been skipping for three milestones. Nobody was
being told anything by them.

Installing Qt and setting `QT_QPA_PLATFORM=offscreen` in `tests/conftest.py` —
before anything imports Qt, `setdefault` so a developer can still watch the
widgets — turned the nine skips into runs, and **one failed immediately**:
`StepListPanel.refresh(frozenset())` answered M7's E4 sentence where the test
expected the step's own requirement. The new behaviour was right; the test had
been asserting the old one for a day without anyone finding out.

Worth recording as a rule rather than a fix: **a skipped test is not a passing
test, and a suite that reports its skips as a number rather than a list makes
them invisible.** The skip count had been "9" in every commit message since M5.

### 24.2 E10 has to come before E11, and it is one feature rather than two

The roadmap lists process descriptions and the step filter as separate items.
They are not: the filter searches *name and description*, so a list you can
search for "undercut" or "hard mask" is only possible once the steps say what
they do. Written the other way round, E11 would have been a filter over 31 short
names, which is a filter nobody needs.

Two decisions inside E10 that are not obvious:

**`description` is deliberately not on the `ProcessStep` protocol.** That
protocol is `runtime_checkable`, and `registry.register` gates on
`isinstance(step, ProcessStep)` — so a member added there would make every plugin
written before M8 fail the check and be refused registration. It lives on
`FunctionStep`, `registry.describe` reads it with `getattr`, and a step with
nothing to say gets its display name back: a poor description, never a missing
one.

**The key is structural, not the English text.** `nanofab_v3.text` is the
indirection E10 asks for and *not* the catalog B10 says to defer, which together
mean one thing: a key beside each string now (`step.<id>.description`) costs
nothing and is the entire difference on the day a second language arrives, where
31 bare strings would be 31 call sites to edit. Keying on the English text would
have been the tempting shortcut and would break every translation the first time
somebody fixed a typo.

### 24.3 Two pictures of one exposure, and why they are two objects

E9 asks for a light preview and an exposure overlay and says the didactic content
is the difference between them. That difference only survives if they cannot be
confused, so they are different kinds of thing in the code as well:

- an **`Overlay`** is derived from a `Structure`. It is what the simulation
  produced — blur, depth falloff, the lot;
- a **`LightPreview`** is derived from a *recipe parameter the sample has never
  seen*. It exists before the step runs and knows nothing about the resist.

Merging them into one "exposure view" would have been the natural refactor and
would delete the lesson: a student who expects the second to look like the first
has just learned what an aerial image is.

The preview is offered only while an exposure step is selected, because asking
any other step for mask parameters would be inventing a mask; and it uses
`lithography.pattern_from_params`, the step's own, because two readings of the
parameters would drift the first time one was added — and the drift would look
like an optical effect.

### 24.4 A latent image stored over the whole grid is not a latent image over the whole grid

`expose_ideal` writes `exposed` over the entire domain on purpose (§3.3's scoping
rule is what keeps it meaningful — resist spun *after* an exposure arrives
unexposed whatever the pattern said about those cells). Drawing that field
directly puts a latent image in the empty space above the resist, which is a
picture of nothing, and the first implementation did exactly that: 24 341 cells
"struck" where the answer is 8 000.

The overlay clips each field to the material it is scoped to. The general form:
**a field's storage extent and its meaningful extent are different, and a
renderer must use the second.** The commit gate already knows this — it is why
the scoping rule exists — and the renderer had to learn it separately.

### 24.5 A picture that is silently compressed is worse than one that is awkward

E8's own sentence, and it survives contact with the implementation unchanged. The
rule is: draw a domain within about 4:1 of square true to scale, compress the
*long* axis of a more extreme one until the picture is 4:1, and never do either
without saying so.

What implementation added is the shape of the saying. The distortion factor is
painted into every picture including when it is **1** ("1:1 true to scale"),
because a label that appears only when something is wrong is a label whose
absence has to be interpreted — and the interpretation "no label means nothing to
report" is indistinguishable from "no label means nobody drew one". The pixel-to-
nm hit test follows both scales, or the status bar would name a different cell
than the cursor is over.

### 24.6 B12, decided rather than guessed — which is what B12 asked for

M8's etch-stop demo needs a number the student process table does not contain:
neither TiO₂ nor Al₂O₃ has a row. B11's rule (an invented spin curve is worse
than none) would say leave it out; B12's own text says the opposite for this
case — *"dann ist zu entscheiden — nicht zu raten — ob die Zahl aus einer Messung
kommt oder als didaktisch markiert wird"*.

So the *ratio* is didactic and the *direction* is physics: a fluorine plasma
makes AlF₃, which is not volatile, so alumina stops a fluorine etch where titania
does not. `rate_notes` on both files says that in those words, and
`tests/test_material_files.py` gained a second additions dict so that which
milestone changed which number stays legible rather than merging into one pile.

The distinction worth carrying: **an invented number is dishonest when it is
indistinguishable from a measured one, not when it is invented.** The library has
carried didactic rates since M0 and says so per entry; what B11 forbids is a
curve labelled "AZ10XT" that nobody measured.

### 24.7 Measured M8 costs, extending §17.7, §18.8, §19.6, §20.8, §21.5, §22.6 and §23.7

| | |
|---|---|
| `registry.matching` over 31 steps, warm | **0.006 ms** |
| the same, cold (builds the search text) | 0.17 ms |
| `scene.build`, no overlays, 1200×640 @ 1 nm | 78 ms |
| … `+ exposed` | **+81 ms** |
| … `+ dose` (four iso-contours) | +63 ms |
| … `+ reachable` (a predicate, for comparison) | +73 ms |
| `light_preview` | 1.3 ms |
| `display_scale` | 0.0008 ms |
| the four demos, end to end | 0.5 / 10.6 / 23.8 / 2.9 s |
| the frozen exe, with Qt this time | 116 MB, `--selftest` 4.0 s solver / 6.8 s wall |

Two of these corrected something that had been written down as a reason.

**"Free — they read a field" was wrong, and it was in a docstring.** The `exposed`
overlay's *data* is free; **drawing** it is not — an outline costs a distance
transform and a marching-squares pass, which is 81 ms at this grid, the same
order as the predicate it was being contrasted against. The wording is corrected
in place. They stay on by default anyway, and now for the reason that actually
holds: a scene is rebuilt when the revision changes and not per frame (§20.6), so
80 ms sits next to a step that takes seconds.

**The search is genuinely free, which is what made a live filter reasonable.**
0.006 ms per keystroke over 31 steps, because the searchable text is memoised per
registry and invalidated on `register`. Had it been milliseconds the filter would
have needed a timer, and a filter with a timer is a filter that feels broken.

The exe is 116 MB against M5's measured 115 MB, with Qt frozen in both times, and
its self-test is unchanged at 4.0 s of solver — which is the point of measuring
it: three milestones of new steps, a new library format, a resize and a rewritten
shell, and the seven scenarios cost what they cost in M5.

## 25. Corrections from implementation (M9)

M9 is a bug fix and nothing else: roadmap §4's last milestone, deliberately last
because it blocks none of the others. What it corrects is §4.2 — specifically the
one sentence that said the union front needed a *repair*.

### 25.1 The bug, and why it took a real project to find

`docs/plans/m6-m9-roadmap.md` §M9 diagnosed it on `structure.v2`: 241×301 at
1 nm, 40 nm of silicon, 80 nm of resist, a speck of contamination against the
left wall, and a `develop_at_rate` that ran 200 sub-steps and 19 mid-motion
reinitialisations. After half a minute of development the resist was in pieces,
the speck had holes in it, and the commit gate reported

    band |grad(phi)| - 1 is 0.353, above 0.35

`tests/test_domain_edge.py` reproduces it exactly: the same geometry fails at
30 s (0.353) and 60 s (0.355) and **passes at 4 s and 16 s**. The bug was
cumulative, which is why no unit test had it. Every test in this repository ran a
handful of sub-steps; the failure needed a hundred.

### 25.2 `min_m phi[m]` is not a distance function, and the seam was the small half

§17.1 already recorded that the union field reads exactly zero along a buried
material seam, and `union_front` already repaired that with a narrow-band
reinitialisation. M9's finding is that the seam is the *visible* symptom of a
defect that is not local at all:

> `min_m phi[m]` is not a distance function anywhere **below** such a seam
> either. It reproduces the lower material's own depth, so a cell 30 nm inside a
> stack reads −5 because a buried interface passes 5 nm away.

Measured on the reproduction case before the fix, the union along the row through
the speck's centre read a flat **−4.0 across six columns** — the particle's own
field, verbatim, because the seam with the resist above it reads zero and the
particle is 8 nm thick there.

A narrow-band reinitialisation is a five-cell tool pointed at a domain-wide
defect. It cannot reach, so the kink survives the pass; and the relaxation
`v − dτ·sign·(|grad| − 1)` pushes the correction a few cells further into the
volume each time it runs. Nineteen passes make a 45° wedge. **That is the whole
bug**, and links 2–4 of the roadmap's chain are its consequences:

| roadmap link | what it really was |
| --- | --- |
| 2. reinit marches the kink deeper | the repair mechanism, doing what it does |
| 3. at the wall it tips positive | the kink reaching a column with no front in x |
| 4. `_clipped` punches it into everything | `max(phi_m, solid)`, faithfully |

### 25.3 The defect is strictly inside the solid, and that bounds the fix

This is the sentence the first attempt was missing, and it cost a full test run
to learn. **Outside the solid, `min_m phi[m]` is already the exact union
distance.** Every point of a material's boundary is either on the union's surface
or strictly inside the solid; the straight segment from an outside cell to a
strictly-inside point must cross the union surface, so there is always a nearer
union point, and the minimum over materials picks it. Inside the solid the same
argument runs the other way — `∂(A∪B) ⊆ ∂A ∪ ∂B`, so `|min_m phi|` **understates**
the depth, which is exactly the observed −4.0.

Rebuilding the outside anyway is not neutral, it is a loss. Measured, when the
first version of the fix rebuilt the whole domain:

| | `min_m phi` | rebuilt everywhere | rebuilt inside only |
| --- | --- | --- | --- |
| band `\|grad(phi)\| − 1`, 99th pct | 0.024 | 0.339 | **0.162** |
| ALD sealing a T-profile void | sealed | **10 spurious pockets** | sealed |
| the etch-stop demo's 350 s etch | passed | **FAIL at 0.436** | passed |

Three tests caught it — `test_conformal_growth_seals_the_cavity_at_half_the_opening`,
`test_a_sealed_void_stops_shrinking_once_the_precursor_cannot_reach_it`, and
`test_the_alumina_stops_a_deliberately_long_etch` — and they caught it because a
cavity is where two facing walls seed opposite offsets into the same cell.

### 25.4 Build the field, do not repair it

`union_front` no longer reinitialises. Inside the solid it **constructs** a
distance function in one pass (`motion.seeded_distance`):

1. the cells straddling the true solid/empty interface keep `min_m phi[m]`,
   which is the sub-cell-exact distance exactly there and nowhere else;
2. every other solid cell takes the Euclidean distance to the nearest such cell,
   **plus that cell's own sub-cell offset**, signed negative.

`ndimage.distance_transform_edt(..., return_indices=True)` returns both in one
call, so step 2's correction costs nothing beyond the transform. The result is
**bit-identical to `min_m phi[m]` on the interface**, so none of the sub-cell
accuracy this package's measurements depend on (§17.2, §20.4) is spent to buy the
volume; `tests/test_domain_edge.py` asserts that bit-identity directly.

The wall is handled here rather than in the stencil, and in one line:
`interface_cells` erodes with `border_value=1`, which says *outside this face the
array continues as it is here*. Solid cut by a wall is not flagged as an
interface, and neither is empty space running off the edge — the same statement
`predicates.open_faces` makes about reachability, made once more where the front
field is built. §M9's intent (a) is satisfied; its proposed mechanism is not what
satisfies it.

**The approximation, stated as one.** Adding the seed's offset as a scalar along
a straight ray is exact where the surface is locally planar and wrong by up to a
cell where it is not. Measured at the one concave corner in the reproduction case
— where the speck's dome emerges through the resist plane — the field reads
−1.7 nm one cell in against a true −0.9, so `|grad(phi)|` reads 1.97 across that
step. It is bounded by a cell, local to concave corners, and it does not move the
interface. Clamping the result to within half a cell of the plain mask EDT was
tried: it costs a second full transform (7.9 ms, i.e. double) and takes the corner
from 0.97 to 0.59. Not bought.

### 25.5 Two fixes the roadmap proposed that the measurements refuted

Both are recorded in code — in `_clipped`'s docstring and in
`tests/test_domain_edge.py`'s — because the next person to read §M9 will
otherwise try them again.

**Ghost cells / Neumann conditions in `kernel.stencil`.** Zeroing the one-sided
differences at a domain face breaks `test_an_exact_field_is_a_fixed_point` and
`test_advection_reproduces_the_fast_path_on_a_plane`: the stencil's linear
continuation is load-bearing, and its module docstring already said so. The
measurement that settled it was a synthetic wall-cut disk driven through 286
reinitialisation passes. The wall column is **stable on its own** — worst
`||grad| − 1|` 0.05, solid cell count constant at 853, no sign flip, `phi[40,:9]`
unchanged — while the band error grows 0.03 → 0.65 with its worst cells at
`phi ≈ 0` in the domain **interior**. The wall never needed a boundary condition.
It needed a union field that was already a distance function when the front got
there.

**Narrowing `motion._clipped` to the cells the union emptied.** This looks
obviously right — "no material may stick out of the new union" is a statement
about a boundary — and it is wrong, measurably. `max(phi_m, solid)` is also what
keeps a material's field *continuous* as the front approaches; clipping only the
emptied cells leaves the cell behind the front at its old value and the cell in
front at the union's, and the jump between them is a gradient of five. Every
duration failed. What made the understatement harmful was never this line.

### 25.6 What it measures

Reproduction case, `develop_at_rate`, gate report:

| | before | after |
| --- | --- | --- |
| 30 s: band `\|grad(phi)\| − 1` (tol. 0.35) | **0.353 FAIL** | **0.117 PASS** |
| 60 s | **0.355 FAIL** | **0.094 PASS** |
| 16 s / 4 s | 0.181 / 0.207 | 0.110 / 0.209 |
| mid-motion reinit passes at 30 s | 96 | 119 |
| union at the wall, row 120, columns 0–7 | flat `−4.0` | `−9.75 −8.76 −7.77 −6.78 …` |
| `\|front − min_m phi\|` on the 612 interface cells | — | **0.0** |
| particle cells / connected components | 100 / 1 | 100 / 1 |
| `union_front`, 241×301 | 14.2 ms | **6.4 ms** |
| the 30 s develop, end to end | 6.30 s | 6.27 s |

Three of those deserve a sentence.

**The error stops growing.** Before the fix it tracked the number of
reinitialisation passes — 0.207 at 15 passes, 0.353 at 96. After it, 119 passes
(0.117) are no worse than 15 (0.209), and 239 passes give the best reading in the
table. That is the difference between a defect that accumulates and one that is
not there.

**The reinit count went up, not down** (96 → 119), and that is not a regression.
The distortion trigger fires on the band gradient error; with a union that is a
distance function, the sub-step field is measured honestly rather than against a
kink that made some cells look fine. More passes, each doing less.

**One transform beats a relaxation**: `union_front` is 2.2× faster, because a
narrow-band reinitialisation iterates and an EDT does not. End to end the develop
costs the same, because the extra passes spend the saving — which is the right
trade to have made, and worth knowing it was free.

### 25.7 What M9 did not fix

Nothing in the reproduction case, now: the speck keeps all 100 of its cells as
one component through 60 s of a development it is not subject to. The §18.5
velocity-extension collar is still there — it is what made the earlier, broken
runs erode a thin body from both sides — but with a valid union field it no
longer bites at this geometry. Backlog, not M9.

## 26. Corrections from implementation (M10)

Written 2026-08-27, at the end of `docs/plans/m10-m12-roadmap.md`'s first
milestone. M10 was the one that "fasst keine einzige gemessene Zahl an" — no rate,
no geometry, no scenario — and it held: the seven scenarios are unchanged and the
suite went 589 → 672 with nothing red in between. Two numbers did move and
neither is physics: **31 → 30 registered steps**, because E35 removes the
ellipsometer, and the delivered build's size, below.

### 26.1 `contents_directory` is an `EXE` option, and onedir is not free

Roadmap E19 asks for `--onedir` with the collected files pushed into `bin/`, so
that a delivered folder holds the executable and the four things somebody opens.
Two things the build taught:

**`contents_directory` belongs on `EXE`, not on `COLLECT`.** It describes the
*collected* layout, so `COLLECT` is where it reads as if it belongs — and
PyInstaller takes it off the executable's own options table. Set on `COLLECT` it
is silently ignored and the folder comes out as `_internal`, which is the same
class of failure as the whole packaging strand: correct-looking, and only visible
in the artifact.

**The size is the price of the decision, measured rather than assumed.** The
one-file build was 115 MiB, because its archive is compressed; the same content
as a directory is **304 MB**. That is 2.6x, it buys the one thing E19 is about —
a library an operator can open, in exactly one copy — and it is worth writing
down because "onedir is basically the same, just unpacked" is what somebody would
otherwise assume. Startup is unchanged in the direction that matters: 7/7 in
4.5 s, the same as the one-file build's, because the bootloader no longer unpacks
an archive into a temp directory.

The delivered folder is `nanofab_v3 · bin/ · data/materials/ · data/demos/ ·
settings.ini`, and `data/materials/.original/` inside the first of those (E37's
reset copy, a dot directory so `read_root`'s `*.json` glob never sees it).

### 26.2 The `adjust` bug was two writes, and the second was an ordering

Roadmap §0.1 measured the first half exactly right: `_on_revision_chosen` wrote
`revision.history.params` into whatever form was on screen, **by parameter name**,
and after `rewind(1)` the selection lands on revision #0 — `substrate.select`,
`material=silicon`, `thickness=0.0` — whose two parameter names collide with the
spin coat's. Stored `resist`/90.0, displayed `silicon`/0.0.

Fixing that was not enough, and the second half is the more interesting one.
`_on_adjust` filled the form and *then* called `_refresh_all`. Rewinding changes
the capabilities, so the refresh rebuilds the step list, which changes its
selection, which emits `step_chosen`, which rebuilds the form from the schema —
throwing away the values that had just been written into it. Refresh first, fill
second.

Both halves look identical from the outside ("adjust does not load what ran") and
both look like the material filter, which is what the roadmap warned about. The
general form is worth keeping: **a form belongs to one step, and a parameter set
only means anything inside the step that declared it.** `ParameterForm.step_id`
exists so that rule is checkable rather than remembered.

### 26.3 E28 softens §10 by exactly one number, and here is the fence

Plan §10 says rendering is a consumer: it decides pictures, never physics. E28
breaks that on purpose. The dose overlay's bands are multiples of the resist's
**clearing dose**, which is `DevelopModel.clearing_dose` — physics, read by the
renderer.

The alternative was what M8 shipped: bands as fractions of the *peak dose
present*. That is a picture whose meaning changes between two revisions of the
same recipe, because the peak moves — and a scale that moves is not a scale. It
is also unreadable in the way that matters: "twice over-dosed" is a sentence a
relative scale cannot produce.

The softening is bounded and the bound is written into `ui.scene.DOSE_BANDS`'s
docstring, which is the point of recording it here as well: `scene.build` already
receives the library (it needs the display colours), so nothing new crosses the
boundary; what crosses is one number, read by name, for one overlay. No rate, no
model evaluation, no decision about geometry. **If a second physical quantity
ever wants in, that is the moment to move this to a "presentation scale" the
session computes and hands over, rather than to soften §10 a third time.**

The `exposed` overlay changed for a different reason and it is not a softening: a
binary field has one value and nothing to grade, so a contour of it read as a
*shape*, which is exactly what a latent image is not. It is a flat translucent
area now.

### 26.4 Roughness is a number, and the instrument reads it — deterministically

E30's substance is that 0.5 nm at 1 nm per cell is below what the level set can
carry, and the reinitialisation would pull it flat within a few sub-steps; an
unpolished back side at Ra ~ 1 µm would be taller than the whole domain. So
`substrate.roughness_nm` is metadata and the profilometer reads it.

The decision the implementation had to make: E30 says the profilometer "adds it
as noise", and a *drawn* random component would put `ctx.rng` into a measurement.
That is backlog **B5** — it makes a measurement depend on replay order, which is
a decision with its own consequences rather than a detail of this one. So the two
contributions are added **in quadrature and deterministically**: two independent
contributions to one Ra add that way, a polished wafer measures 0.50 nm on a
cross-section that is perfectly flat, and the log says which part came from
where. Nothing replay-dependent, and B5 stays open for the case it is about.

The same decision surfaced `SEMI_INFINITE`, which had been a form factor with no
preset: reachable only by typing it. It has an entry now, and it is the reason
`presets_by_section()` grew a third section.

### 26.5 The R1 exercise found one, and it was E31

Handoff R1's process finding was that **a decision recorded in a roadmap's §2 but
never written into a §4 task list gets built only by luck**, and its
recommendation was a pass over the remaining §2 decisions before the next
milestone list was written. That pass was done for E19–E40 at the start of M10
and it found exactly one:

**E31** — *"a step that introduces a material asks first"* — has two halves. Its
bake trilogy is assigned to M12 explicitly. Its first clause, the pre-flight
check, is in **no** §4 list at all, in any milestone. It is built here, because
the case it names is live: `anneal.thermal` swaps a resist for
`resist_hardbaked` and nothing checked the target existed, so a typo in `becomes`
produced a sample made of a material the library cannot answer for — silently,
one step before the strip that then did nothing.

The check reads the *schema* rather than guessing from parameter names, which E22
made possible: a material parameter says it is one. `becomes` is the single
exception and is named as such, because it holds a material without being chosen
from a list.

This also settles the ordering question the two decisions raise together. E15
asks **after** a step, because a material can arrive without any step naming it —
a scattered particle, a plugin's own film — and nothing can be asked in advance
about a material nobody typed. E31 asks **before**, because a material the form
names is knowable now. Both are right for their own case, and cancelling E31's
question means the step does not run.

### 26.6 A constructor that opens a modal dialog hangs a headless suite silently

E38's restore prompt was called from `MainWindow.__init__`. Every `MainWindow()`
in the test suite then opened a modal `QMessageBox` and waited for an answer
nobody could give — a hang with no output, no traceback and no failing test,
which took two aborted twenty-minute runs and a `faulthandler` dump to see.

It is the sharpest instance of a rule this repository already half-had: **a
widget's constructor builds, and asking is something a caller decides to do.**
`run()` calls `offer_the_last_session()` after `show()`, and the method returns a
bool so a test can drive it.

The same run turned up its sibling: the suite was autosaving into the developer's
own `~/.cache`, so a test run leaked into the machine it ran on *and* into the
next run, through exactly the file the restore prompt reads. `tests/conftest.py`
points `$NANOFAB_CACHE` at a temp directory for the whole session — the same
shape as the `QT_QPA_PLATFORM` line above it, and for the same reason.

### 26.7 Measured M10 costs, extending §17.7, §18.8, §19.6, §20.8, §21.5, §22.6, §23.7 and §24.7

Same container as M6–M9; §23.7's warning applies (a number measured on one
machine is a statement about that machine).

| | end of M9 | end of M10 |
| --- | --- | --- |
| tests | 589, 0 skipped | **672**, 0 skipped |
| registered steps | 31 | **30** (E35 removes the ellipsometer) |
| materials | 11, untagged | 11, **tagged** (E21) |
| delivery | one file, 115 MiB | **one folder, 304 MB** (§26.1) |
| `--selftest` | 7/7 in 4.5 s | 7/7 in **4.5 s** |
| library roots, frozen | 2 (one of them sealed) | **1** (E19) |
| library fingerprint | — | `82f5c67a11d3` (E36) |

Two costs worth naming because they are per-step rather than per-build:

- **The autosave is free at this scale.** A six-step lift-off recipe is 893 bytes
  and the write is one `write_text` plus one `os.replace`; measured against the
  step it follows (0.1–2.3 s), it does not appear. That is the whole argument of
  E38 in one line — the *build* it deliberately does not write is 23 MB per
  revision.
- **The derived hints are recomputed on every keystroke** and are a library
  lookup plus, for the spin coat, one interpolation. `ui.derived` never raises,
  because a half-typed value in a spin box is a normal state for a form to be in
  and a hint is not worth an exception.

## 27. Corrections from implementation (M11)

Written 2026-08-28 at the end of the directed-process milestone in
`docs/plans/m10-m12-roadmap.md`. M11 deliberately changes rates and the flux
kernel, so unlike M10 its green result is a statement about the new physics
contracts, not bit-identical behaviour.

### 27.1 One ion beam means one process and one rate key

`etch.ibe`, `etch.sputter` and the `sputter_etch` process class are gone. The one
registered step is `etch.ion_beam`, and the five materials named by the process
table carry its converted rates under `ion_beam`. The six unnamed materials keep
their old didactic ratios scaled by 0.23, with the provenance in `rate_notes`.
S2c is the only shipped recipe affected: 120 s at scale 1.25 still produces the
same nominal 30 nm oxide depth. Old recipes naming a removed step fail loudly;
they are not reinterpreted.

ICP fluorine is now fixed at normal incidence and 3 degrees divergence. Neither
value is a recipe parameter: the table describes a vertical process, not a
tiltable beam.

### 27.2 Reflection is one ion bounce, and never deposition

`SputterYield.reflected_fraction` turns only the grazing loss
`clip(1 - Y(theta)/Y(0), 0, 1)` into a specular ray. The receiver sees the same
projected-area and yield response as the first surface, and the contribution is
added to `FluxOutcome.arrival` before the existing extension and CFL-bound seams.
There is no recursion: one incident ray can create at most one reflected ray.
The reflected ion carries no material; redeposition remains the separate product
flux. `UnitYield`, used by deposition, reflects zero by construction.

### 27.3 Redeposition identity is a field split, inheritance is a file feature

`processes.rates.release_maps` returns one masked release field per source
material. The static redeposition pass runs once per field and deposits that same
material id. Thus chromium remains chromium and an etched resist cannot relabel
it. No runtime process mutates the library.

Schema-1 files may declare `inherits`. Resolution happens before the immutable
`MaterialLibrary` is built, mapping fields merge, roots already read may provide
parents, and missing parents or cycles are errors. `chrome_redeposit.json` is the
first example, but the normal IBE identity rule still redeposits `chrome` unless
a recipe explicitly starts with the derived material.

One report detail only became visible after inheritance existed: overriding a
parent changes the resolved child value even when the child's file is byte-for-
byte identical. `LibraryReport.overridden` therefore compares raw definitions,
not resolved `MaterialType`s; otherwise editing `chrome.json` falsely reports a
second edit to `chrome_redeposit.json`.

### 27.4 `StepPreview` is presentation data, not a cheap solver

The preview is Qt-free data attached to `SceneSnapshot`. It uses surface normals
and simple ray hits, never `FluxModel2D` or `advect_front`. Its physical length is
the naive `rate * duration * scale`, or the requested deposition thickness, and
the independent `view.preview_scale_px_per_nm` converts that length to pixels.
That absolute scale is intentional: arrows may leave the sample picture, because
their length is a setting aid rather than a fitted legend. Below 5 px the arrow
is replaced by a numeric note instead of becoming invisible.

`ParameterForm.valueChanged` rebuilds the preview from the values currently in
the form, including half-edited safe defaults. Directed steps show ray fans,
isotropic and conformal steps show normal vectors, sputter mobility is dashed,
redeposition points back from the impact, and particle seeding shows a bounded
deterministic raster.

### 27.5 Measured M11 state

| | after M10 + E31 correction | end of M11 |
| --- | --- | --- |
| tests | 673, 0 skipped | **681**, 0 skipped |
| registered steps | 30 | **29** |
| materials | 11 | **12** (`chrome_redeposit`) |
| ion-beam rate keys | 2 | **1** |
| version | `0.3.0.dev0` | **`0.4.0.dev0`** |
