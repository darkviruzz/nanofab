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

### Attachments & annotations

**Attachment**:
Named, structured (measurement) data hung off a `SampleState` or a `Layer` for anything that doesn't have a dedicated field yet (metrology results, simulation output, ...). Every attachment carries an optional `note` field for freetext commentary. A pure comment with no real payload is just an attachment with only `note` set — there is no separate "comment" type.
_Avoid_: "Facet" (the code currently names this field `facets` — known drift, glossary wins per this file's own rule; renaming the field is a follow-up, not a glossary concern), "metadata".

**Facet** (unsettled — do not treat as final):
A geometric segment or face that a `Layer` or sample is composed of (e.g. which regions are exposed, etched, coated). Unrelated to `Attachment` above despite the naming collision in code. The shape isn't decided — this is the open problem the `cross_section_general_prototype.py` prototype branch is working through. Current thinking leans toward per-layer **properties** (e.g. `exposed`) set by process steps and read via runtime queries, rather than modelling it as an `Attachment`.
_Avoid_: "Attachment" for this concept (different thing, see above).
