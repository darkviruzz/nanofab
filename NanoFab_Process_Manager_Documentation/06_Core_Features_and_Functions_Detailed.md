# 6. Core Features and Functions (Detailed)

## 6.1 Process Chain Management

### 6.1.1 Status Model (Minimum)
- `pending`: not yet reachable (future usage)
- `blocked`: prerequisites not met
- `ready`: runnable
- `running`: executing
- `done`: completed

Future:
- `warning`: completed with warnings
- `failed`: step failed
- `aborted`: canceled by user
- `skipped`: intentionally bypassed

### 6.1.2 Prerequisite Gating
Each step declares prerequisite step IDs.
A step becomes `ready` only if all prerequisites are `done` (or `warning` by policy).

Blocked state must show “why” in UI.

---

## 6.2 Parameter System

### 6.2.1 Parameter Types
- `number` (with unit, min/max, step)
- `select` (predefined options)
- `boolean`
- `text`

Future:
- compound structures (spin programs, multi-row tables)
- file references (mask files)
- calibration model selection

### 6.2.2 Validation Layers
1) **Schema validation** (required fields, bounds, types)
2) **Physics-aware validation** (mismatch vs SampleState)
3) **Policy validation** (cleanroom constraints, safety, machine availability — future)

### 6.2.3 Mismatch Diagnostics (Examples)
- Predicted thickness vs target thickness deviation
- Adhesion risk based on surface energy (facet-derived)
- Exposure step blocked if resist not present

### 6.2.4 Auto-Tune / Helper Tools (Optional)
Example:
- “Auto-tune spin to target thickness” adjusts RPM based on a model curve.
These are “tools” attached to a step; they are not mandatory for v0, but must be architecturally supported.

---

## 6.3 Execution Engine (Non-Blocking)

### 6.3.1 Execution Lifecycle
1) User clicks **Run Process**
2) Engine checks:
   - step is `ready`
   - prerequisites satisfied
   - parameters valid (schema + mismatch threshold policy)
3) Engine creates a **job**:
   - associates process id, parameter set, input revision
4) Job enters:
   - queued → running → finished | failed | aborted
5) During running:
   - progress updates stream to UI
   - log lines stream to UI
   - artifacts may be produced incrementally
6) On completion:
   - create new `SampleState` revision
   - attach artifacts
   - update step status → `done` (or `warning`)
   - unlock downstream steps

### 6.3.2 Job Queue (Target)
- multiple jobs (future)
- concurrency control (one sample at a time by default)
- cancellation
- retries (policy-based)

**Current mock:** simulates execution time using `estimated_duration_sec` and produces canned log lines.

### 6.3.3 Persistence (Target)
- Each run has a run directory:
  - `run.json` metadata
  - parameter set snapshots
  - logs
  - artifacts
- Revisions are stored as separate JSON files.

---

## 6.4 Artifact System

### 6.4.1 Artifact Types
- images (microscopy, SEM, plots)
- tables (CSV)
- reports (PDF/Markdown)
- logs (text)
- meshes (STL/OBJ)
- heightmaps (TIFF/NPY)
- derived metrics (JSON)

### 6.4.2 Indexing and Retrieval
Artifacts are:
- referenced by `ArtifactRef` in the state
- tagged for search and filtering
- optionally summarized by derived metrics for quick view

### 6.4.3 Comparison (Target)
- pick two runs or two revisions
- compare key metrics (mean thickness, uniformity, Ra/Rq)
- side-by-side images/maps
- diff reports (future)

---

## 6.5 Visualization

### 6.5.1 Cross-Section Visualization (2D)
Purpose:
- show substrate + layer stack at a glance
- show thickness and roles
- show basic patterning as segmented bands (abstraction)

**Current mock UI:** SVG/DOM stacked rectangles with tooltips and a visual scaling function to make thin layers visible.

### 6.5.2 3D Visualization (Target)
Purpose:
- view large surfaces/meshes
- compute roughness and metrics
- interactively measure and slice
- overlay features

Implementation options depend on framework:
- web: three.js/Plotly
- Qt: Qt Quick 3D / embedded renderer
- hybrid: web view embedded in desktop app

---
