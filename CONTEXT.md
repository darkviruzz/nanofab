# NanoFab Process Manager

A digital-twin state evolution engine for simulating nanofabrication process runs (lithography, thin-film deposition, lift-off, etc.) on a sample, separating process **Recipes** from concrete **Runs**.

## Language

This glossary describes the system **as currently implemented**, not the aspirational target model in `NanoFab_Process_Manager_Documentation/`. Where the two disagree, the docs are the ones expected to catch up — this file grows term by term as design decisions actually crystallise.

### Sample & state

**SampleState**:
A snapshot of the physical sample (substrate, layers, artifacts, history) at one point in time. Every process step consumes one and produces a new revision of it.
_Avoid_: "state" alone, "sample" alone (that's `Substrate` — the base material, not the whole snapshot).

**Revision**:
One version of a `SampleState`, identified by an incrementing `revision` number. Revisions are append-only: a step never mutates its input state, it produces a new one.
_Avoid_: "version", "update".

**Substrate**:
The physical base material a sample is built on (material, form factor, geometry) — the foundation `SampleState.layers` are stacked on top of.
_Avoid_: "sample" (too broad — see `SampleState`).

**Layer**:
One physical layer of material stacked on the `Substrate` (resist, metal, dielectric, etc.), tracked with a status (present / partially removed / removed) and a thickness `Quantity`.
_Avoid_: "film" (unless directly quoting deposition-process terminology).

**Artifact**:
A persisted output (image, table, mesh, log) referenced from a `SampleState` via an `ArtifactRef`, rather than embedded inline. Keeps heavy data out of the state itself.
_Avoid_: "file", "output" alone.

### Process & execution

**Recipe**:
The ordered sequence of process steps (and their parameter schemas) a run is meant to follow. Currently informal — not a dedicated object, just however the step registry orders the installed `ProcessStepModule`s.
_Avoid_: "process" alone (too broad), "workflow".

**Run**:
One execution of a `Recipe` against a concrete sample: the resulting sequence of revisions, artifacts, logs, and outcomes. Currently lives inside `ProcessEngine`, not a standalone `Run` object.
_Avoid_: "session", "job".

**Step** (Process Step):
One stage of a recipe/run — consumes an input `SampleState`, applies one transformation (e.g. thin-film deposition), and emits an output `SampleState` as a new revision. Implemented as a `ProcessStepModule`.
_Avoid_: "stage", "operation", "task".

**Gating**:
The rule that a step stays blocked until its declared prerequisite steps have completed. Implemented via each step's `prerequisites` list plus its status (`Blocked` / `Ready` / ...).
_Avoid_: "locking", "dependency" alone.

**History**:
The append-only log of `HistoryEntry` records on a `SampleState` — which step, when, with what parameters, produced each revision. Carries the full trail, not just the latest step.
_Avoid_: "log" alone (too generic).

### Process character

These describe *how* a process acts on the sample, not which machine runs it. They are
the axis the step registry is organised on (`etch_isotropic` / `etch_anisotropic`,
`deposit_conformal` / `deposit_directional`), so getting them backwards inverts the
model.

**Isotropic**:
Direction-independent: the process acts at the same rate on a surface regardless of
that surface's orientation. Isotropic removal undercuts a mask; isotropic arrival
coats vertical sidewalls as thickly as horizontal faces. Wet chemical etching and ALD
are the reference cases.
_Avoid_: "uniform" (that's about *place*, not direction), "non-directional".

**Anisotropic**:
Direction-dependent: the rate varies with direction. Two distinct causes, and the
model must keep them apart because they respond to different inputs:
- **Flux anisotropy** — the flux arrives from, or removes along, a limited solid
  angle, so what a surface receives depends on its orientation and on what stands in
  the way. Evaporation, RIE and ion beam etching. This is the one that produces
  shadowing.
- **Crystallographic anisotropy** — the *material* responds differently along
  different lattice directions, independent of where the flux comes from. KOH on
  silicon. Governed by the material's properties, not by the process geometry.

_Avoid_: "directional" as a synonym (see below — that's the flux case only),
"selective" (that's material contrast, an unrelated axis).

**Conformal**:
A property of the *result*, not of the process: equal layer thickness on every
reachable surface, sidewalls and undercuts included. It is what isotropic arrival
produces, so a conformal process is an isotropic one — never an anisotropic one.
_Avoid_: "even", "uniform coverage".

**Directional**:
Shorthand for a flux-anisotropic process whose incoming or outgoing solid angle is
narrow enough that surface orientation and occlusion dominate the outcome.
_Avoid_: "anisotropic" alone (crystallographic anisotropy is anisotropic but not
directional).

**Shadowing**:
The reduction or absence of flux on a surface because another part of the sample
occludes the line to the source. Only meaningful for a directional process — an
isotropic one has no line to block.
_Avoid_: "masking" (that's a deliberate patterning layer), "occlusion" alone.

**Undercut**:
Material removed laterally beneath a masking layer, so the mask overhangs the feature
it defined. The signature of an isotropic removal component; a purely directional etch
produces none.
_Avoid_: "underetch", "lateral etch" (describes the mechanism, not the resulting shape).

**Redeposition**:
Material sputtered off one surface that lands on another instead of leaving the
sample — the reason an ion-milled trench lines its own sidewalls with what came
off its floor. Modelled as a single isotropic bounce scaled by a redeposition
yield; only meaningful for a removal process energetic enough to eject material,
so a wet etch has none.
_Avoid_: "backscatter" (that is the source side), "contamination".

### Structure model v2

Decided in ADR-0002…0004 and `docs/plans/v2-structure-model.md`, and implemented
in `nanofab_v3` from milestone M0 on (grid and geometry, motion, flux,
capabilities and predicates). The v1 code does not use these terms; where a term
below is still ahead of the code — `Materialization` is, until M4 — it says so.

**Grid**:
The sole spatial authority of a v2 structure: origin, cell spacing, shape and axis names. Resolution is a visible model parameter, not an implementation detail.
_Avoid_: "extent"/"canvas" as data carriers, hard-coded axis pairs.

**Structure**:
The material geometry and per-cell state of the sample at one revision: one signed-distance field per material plus named `Field`s, all on one `Grid`. The single stored truth — analytic primitives exist only as constructors.
_Avoid_: "scene", "geometry" alone, "material paths".

**Field**:
A named per-cell quantity on the `Grid` (dose, damage, temperature history), either global or scoped to one material; material-scoped fields are reset wherever their material changes.
_Avoid_: "facet", "map" alone, "property" (that's on `MaterialType`).

**Occurrence** (Materialvorkommen):
A connected region of one material, derived per revision by connected-component labelling; identity across revisions is reconstructed by overlap matching, never stored.
_Avoid_: "layer" for this, "segment", "island".

**Arrival** (per unit front):
How much of a directional source a piece of front can see, per unit of front, as
a dimensionless multiplier on that material's blanket rate: visibility times the
projected area times the angle-dependent yield, integrated over the source's
angular distribution. Normalised so an unobstructed flat surface receives exactly
1, which is what lets a rate keep meaning "nm/s on an open surface".
_Avoid_: "flux" alone for the normalised quantity (that is the source's, before a
surface has seen it), "coverage" (that is the deposited result).

**Capability**:
A named promise about sample state that a process requires or provides (e.g. `resist.dose`). Gating runs on capabilities; downgrade adapters may discard information explicitly, upgrades cannot exist. Two name forms are **structural** — `material:<id>` and `<material>.<field>` — and the commit gate re-derives them from the structure itself, so a capability retires when the material or field backing it is gone. The dot is reserved for that second form; a free-form promise must not contain one.
_Avoid_: "prerequisite" (v1's step-id gating), "dependency".

**Materialization** (ahead of the code until M4):
Evaluating a Run at one wafer position by deterministic replay with position-resolved parameters; the solver itself stays position-blind.
_Avoid_: "sampling" (collides with grid sampling), "instantiation".

**Predicate**:
A named question asked of one revision's geometry, answered without changing it — reachability, support, enclosed voids, undercut ratio, step coverage. The analysis vocabulary and the didactic payload: the UI renders their results and the acceptance tests assert them. Reachability and support are predicates *and* kernel steps, which is why they are the same functions.
_Avoid_: "check" (that is the commit gate's invariants, which fail a step), "metric" (a predicate may answer a shape, not only a number).

**Reachability**:
Whether a material can be touched from outside the sample, i.e. whether the empty space adjacent to it connects to the domain's open face. What makes a wet process (develop, dissolve, strip, clean) act on some material and not on other, chemically identical material — and what makes a sealed cavity stop being fed. A cross-section's lateral faces are not open: the section continues sideways, so treating them as a bath would make a cavity reachable because of where the window was cropped.
_Avoid_: "accessible" (unqualified), "exposed" (that is the resist field, an unrelated thing).

**Support**:
Whether a piece of solid connects to the wafer. Lift-off is dissolution followed by removing what support no longer finds, so "which metal lifts off" is a connectivity question and never an identity one. Topological: one shared cell is enough, which is why a sidewall film touching a pattern at its foot stays.
_Avoid_: "attached" (too vague), "anchored" (that is the optional seed material, a parameter of the query).

**Fence**:
Metal deposited on a resist sidewall that stays standing after the resist is gone, because it is attached to the film on the substrate. The signature of a broad-lobe deposition into a re-entrant profile; an evaporation on the same stack leaves none. Appears in the model as a raised rim on the surviving pattern's profile, not as a separate occurrence.
_Avoid_: "ear", "wing" (cleanroom slang, and neither says why it is there), "burr".

### Attachments & annotations

**Attachment**:
Named, structured (measurement) data hung off a `SampleState` or a `Layer` for anything that doesn't have a dedicated field yet (metrology results, simulation output, ...). Every attachment carries an optional `note` field for freetext commentary. A pure comment with no real payload is just an attachment with only `note` set — there is no separate "comment" type.
_Avoid_: "Facet" (the code currently names this field `facets` — known drift, glossary wins per this file's own rule; renaming the field is a follow-up, not a glossary concern), "metadata".

**Facet** (retired for v2 — settled by ADR-0002):
Was: a geometric segment or face a `Layer` is composed of (which regions are exposed, etched, coated). The v2 structure model resolves this question without the concept: "which regions" is answered by `Field`s on the `Grid` and by derived `Occurrence`s — geometric segmentation does not exist as an entity. The term survives only in v1 code (where `facets` also collides with `Attachment`, see above); do not build new things on it.
_Avoid_: "Attachment" for this concept (different thing, see above); introducing "Facet" into v2 code.
