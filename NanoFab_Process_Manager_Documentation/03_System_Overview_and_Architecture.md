# 3. System Overview and Architecture

> Current UI implementation is an Angular dashboard; backend “physics” is currently mocked. The long-term requirement is **Python backend** with an appropriate UI framework for visualization and responsiveness.

## 3.1 Core Components

### A) Process Chain Model (`ProcessStep[]`)
Defines:
- step identity (`id`, `name`, `description`)
- status (`pending`, `blocked`, `ready`, `running`, `done`, plus future: `failed`, `warning`, `skipped`)
- prerequisites (dependency graph)
- parameter schema (`ProcessParam[]`)
- estimated duration (for UX, scheduling, and timeouts)

### B) Sample State (`SampleState`)
Defines the physical representation of the sample:
- substrate metadata and geometry
- layer stack model
- artifact references
- history / provenance
- extensibility blocks (“facets”) for future growth

### C) Execution Engine
Responsible for:
- validating inputs and prerequisites
- scheduling/running jobs non-blockingly
- progress and log streaming
- updating state revisions
- artifact creation and indexing
- failure handling (future)

### D) Artifact Store + Index
Responsible for:
- persistent storage on disk (or remote)
- structured metadata (tags, metrics)
- thumbnails/previews where applicable
- efficient browsing and comparison

### E) Visualization Layer
Responsible for:
- cross-section/stack visualization (2D)
- artifact previews (images, plots)
- 3D viewer integration (mesh/height map)
- measurement overlays and derived metrics

---
