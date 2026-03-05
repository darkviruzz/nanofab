# 1. Principle of the Application

## 1.1 Digital Twin and “State Evolution” (Core Principle)

The application is **not** a task tracker. It is a **state evolution engine** for a physical sample:

- The sample has a **state snapshot** `SampleState` at every moment.
- A process step consumes an input state, applies a transformation, and emits a **new revision** of state.
- Each revision is **traceable**: what step and what parameter set produced it, and which artifacts were generated.
- Heavy data (maps, meshes, spectra) is **not embedded** in state; it is stored as artifacts and referenced.

This makes the app suitable for:
- Education and training (“for education purposes”)
- R&D process planning, what-if analysis, and simulation-driven iteration
- Run documentation and inspection traceability

## 1.2 Two Roles: “Recipe” vs “Run”

The app separates:

- **Recipe**: the definition of process steps and their parameter schemas (types, units, bounds, defaults, prerequisite rules).
- **Run**: an execution instance for a concrete sample (a sequence of revisions, artifacts, logs, and outcomes).

A run can follow a recipe step-by-step, and can also insert inspection steps or branch (future extension).

## 1.3 Minimal Now, Extensible Later

The system is explicitly designed to start minimal (few fields, simple layers, mocked simulation) while staying robust to later additions:

- Add new process types without breaking old state files.
- Add new metrology types (thickness maps, bow, roughness maps).
- Add new simulation outputs (RCWA fields, FEM results).
- Add more complex geometry representations (pattern references now; full geometry later).

---
