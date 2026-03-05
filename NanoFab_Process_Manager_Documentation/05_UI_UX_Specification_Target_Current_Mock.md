# 5. UI/UX Specification (Target + Current Mock)

## 5.1 Layout Model (Desktop and Mobile)

### Desktop (3-column workspace)
1) **Process List (left)**  
   - shows recipe name/run id
   - step table
   - status badges
   - click-to-select

2) **Process Details (center)**  
   - parameter editor (units, constraints, types)
   - validation/mismatch panel
   - execution controls
   - live execution monitor (progress + logs)

3) **Visualization & Artifacts (right)**
   - top: wafer cross-section preview
   - bottom: artifact gallery

### Mobile / Small Screen
Principle: **focused view** with overlays.
- Default: process list.
- Selecting a step opens details as an overlay or navigates to a focused details screen.
- If the viz panel cannot fit, show a **toggle button** in the top bar to open visualization/artifacts in an overlay.

## 5.2 Primary Views (Conceptual)

### View A — Process Chain (Home)
Purpose: chain overview, gating, quick parameters, next runnable.
Key interactions:
- click a row → open View B (details) without losing context
- status indicates gating: blocked + reason
- “Step” runs next runnable step (future)

### View B — Process Parameters (“Recipe Card”)
Purpose: edit safely, validate, detect mismatch.
Must include:
- typed inputs with units
- bounds/constraints
- schema-driven required fields
- mismatch diagnostics vs SampleState
- optional helper tools (auto-tune)
- save/versioning of parameter sets (future)

### View C — Execution Monitor (Queue + Progress)
Purpose: non-blocking execution + logs.
Must include:
- job state (queued/running/finished/failed)
- progress
- live logs
- cancellation
- artifact list that refreshes during execution

### View D — Inspection Results Browser
Purpose: browse persisted outputs and compare runs.
Must include:
- sort/filter by time and tags
- previews for images/maps
- comparison workflow (select two runs → compare)

### View E — 3D Viewer
Purpose: interactive mesh/height map visualization.
Must include:
- rotate/pan/zoom
- measurement tools
- cross-sections
- derived roughness metrics
- export/annotate

---
