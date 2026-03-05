# 2. Target Use Cases (User Needs)

## 2.1 Primary Use Case: Manage a Complex Cleanroom Chain

Users want a clear, responsive UI that shows:
- the full chain of process steps (often long and complex),
- their status and prerequisite gating,
- the most important “headline parameters” per step,
- and the next runnable step.

## 2.2 Parameter Editing With Physics-Aware Validation

Users must be able to:
- edit process parameters with units and constraints,
- see mismatches between parameter sets and current sample state,
- get actionable warnings (not just “invalid input”),
- and (optionally) use helper tools (e.g., auto-tune).

## 2.3 Execute Steps and Keep UI Responsive

Execution may:
- take time (simulations, remote calls, computation),
- require operator confirmation,
- generate incremental logs and artifacts.

The app must stay responsive and show progress.

## 2.4 Inspection, Persistence, and Comparison

Inspection outputs must:
- be saved to disk as artifacts,
- be easily browsed by run/time/tags,
- be comparable across runs (e.g., thickness uniformity before/after).

## 2.5 Scientific Visualization (Including 3D)

Some steps and inspections produce:
- 2D plots and images,
- thickness maps,
- and potentially large 3D surfaces/meshes.

The UI must present those natively and interactively.

---
