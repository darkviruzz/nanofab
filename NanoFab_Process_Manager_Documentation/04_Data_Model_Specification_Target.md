# 4. Data Model Specification (Target)

This section merges the intended `SampleState` schema (extensible, artifact-referenced) with the simplified structure used in the current mock app.

## 4.1 Design Rules (Invariants)

1. **Revisions are append-only**: each step creates a new `SampleState` revision.
2. **No heavy data inline**: maps/meshes/spectra are artifacts referenced by URI.
3. **Quantities have units**: no raw floats for physical values.
4. **Layers are ordered** bottom → top.
5. **Unknown extensions are ignored**: forward compatibility via facets.

## 4.2 Entities

### 4.2.1 `Quantity` (scalar)
Used for thickness, temperature, time, dose, roughness, etc.

- `value: number`
- `unit: string` (e.g., `nm`, `um`, `mm`, `C`, `s`, `mJ/cm^2`)
- `source?: nominal | measured | simulated | estimated`
- `uncertainty?: { sigma: number, unit: string }` (future)
- `provenance?: { method: string, artifact_ref?: ArtifactRef, timestamp?: ISO8601 }` (future)

### 4.2.2 `ArtifactRef`
Artifacts are persisted files, referenced from state.

- `id: string`
- `kind: image | table | plot | report | mesh | heightmap | log | other`
- `uri: string` (e.g., `file:runs/2026-01-14_2014/thickness_map.png`)
- `created_at: ISO8601`
- `mime_type?: string`
- `summary?: string`
- `tags?: string[]`
- `metrics?: Record<string, Quantity>` (quick numbers for UI)

### 4.2.3 `Substrate`
- `material: string` (e.g., Fused Silica, Si)
- `form_factor: wafer | chip | coupon | other`
- `geometry`:
  - wafer: `diameter_mm`, `thickness_um`
  - chip/coupon: `size_mm: [x,y]`, `thickness_um`
- optional: `surface_finish (SSP/DSP/unknown)`, `orientation`, `vendor/lot/serial`, `notes`

### 4.2.4 `Layer`
Represents a film or remaining/removed portion.

Required:
- `layer_id: string`
- `name: string`
- `role: resist | metal | dielectric | hardmask | adhesion | etched_feature | unknown`
- `material: string`
- `status: present | partially_removed | removed`
- `thickness: Quantity`

Optional:
- `coverage: blanket | patterned | edge_only | unknown`
- `pattern: PatternRef` (reference to GDS/bitmap/etc.)
- `properties: Record<string, Quantity>` (n, stress, density, etch model params)
- `uniformity` (scalar stats + optional map_ref)

**Current mock UI note:** the Angular mock uses a simplified layer object with an optional `color` field for visualization and (in the written recipe) a segmentation concept. The target model supports segmentation as a future extension:
- Option A: represent segmentation as `facets.geometry.segments` and draw it in viz
- Option B: upgrade `Layer` to include `segments[]` with material/state flags  
(Currently described in the doc to match the demonstrated UI behavior.)

### 4.2.5 `PatternRef`
- `type: mask | cad | raster | procedural | unknown`
- `ref: ArtifactRef`
- `description?: string`

### 4.2.6 `History`
Tracks provenance for the latest revision.
- `last_step: { process_id, process_name, started_at, finished_at, status, parameter_set_ref, produced_artifacts }`
- `parents?: revision refs` (future branching)
- `notes?: string`

### 4.2.7 `Facets` (Extensibility)
A dictionary of namespaced payloads, e.g.:
- `metrology.scalar`
- `metrology.maps`
- `simulation.rcwa`
- `wafer.geometry`
- `inspection.sem`
- `process.resist_coating`

Rules:
- Keys are dotted namespaces.
- Unknown facets must be ignored by older code.

---
