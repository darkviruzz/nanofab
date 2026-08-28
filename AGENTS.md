# AGENTS.md - NanoFab Manager Workspace Guide

This file defines how the **Coding Assistant** should operate in this repository at the start of every session.

## 1) Startup Checklist (Always)
1. Read this `AGENTS.md`.
2. Read [`memory.md`](memory.md) before making edits.
3. Check current workspace state:
   - `rg --files`
   - `git status --short`
4. Detect current build/version dynamically (do not hardcode):
   - structure model v2: `rg -n "^__version__" nanofab_v3/__init__.py`
   - a snapshotted application: `rg -n "^APP_NAME|^APP_VERSION" ui_backups/*/nanofab_manager.py`
5. There is one actively built code base (`nanofab_v3/`). The PySide6 applications live in `ui_backups/` and are read-only history — never edit a snapshot in place.

## 2) Repository Map (Read in This Order)
- Project memory and decisions:
  - `memory.md`
- Structure model v2 — the only actively built code base:
  - `docs/plans/v2-structure-model.md` (the specification; its §17 onward amend the agreed text with what implementation measured — read those before trusting an earlier section), `docs/adr/*.md`
  - `docs/plans/m6-m9-roadmap.md` continues the plan's milestone list past where it ends, with the decisions (E1…) the later handoffs cite; `docs/plans/backlog-later.md` is what was deliberately deferred, each entry with what would trigger it
  - `nanofab_v3/model/` — `Grid`, `Structure`, fields, capabilities, reports, `ArtifactRef`/`ArtifactSink`
  - `nanofab_v3/kernel/` — set ops, constructors, motion, reinit, flux, predicates, regions, commit gate
  - `nanofab_v3/materials/` — the `MaterialType` library: the models, the JSON
    format, the roots it is read from, and what an unknown material does
  - `nanofab_v3/data/materials/` — **the library itself**, one JSON file per
    material (roadmap E14). Since M6 the code holds no `MaterialType`; a shipped
    root inside the package plus a writable one outside it, and
    `data/materials/README.md` says which numbers came from where
  - `nanofab_v3/processes/` — the process contract, registry (+ entry-point plugin discovery) and didactic step set
  - `nanofab_v3/runtime/` — revisions, runs, wafer positions, replay + cache
  - `nanofab_v3/io/` — the `.npz` + JSON exchange format, revision stores, replay cache
  - `nanofab_v3/ui/` — `SceneSnapshot` v2, the interactive `Session`, the wafer fan + its view, the Qt shell
    (`python -m nanofab_v3.ui`; PySide6 is the `[ui]` extra)
  - `nanofab_v3/acceptance.py` — S1-S5 as shipped code (the packaged exe's DoD path)
  - `nanofab_v3/cli.py`, `nanofab_v3/__main__.py` — `python -m nanofab_v3`, `--selftest`, `--version`
  - `nanofab_v3.spec` — the PyInstaller recipe (`pyinstaller nanofab_v3.spec`; `console=True`, see plan §21.5)
  - `examples/nanofab-plugin-example/` — an out-of-tree process plugin; not part of the distribution, exists so plugin discovery has a second implementer
  - `tests/`
- Product docs:
  - `NanoFab_Process_Manager_Documentation/*.md`
- Baselines/backups (read-only history; each has its own `README.md`):
  - `ui_backups/2026-08-25_v0.2.0_nanofab-manager/` — the v0.2.0 PySide6 app and the `nanofab_modular` engine
  - `ui_backups/2026-08-25_v1.0.0_cross-section-prototype/` — the prototype ADR-0001 was written against
  - `ui_backups/2026-03-05_v0.1.0_baseline/`

## 3) Efficient Reading Strategy
1. Read `memory.md` first for latest decisions and known issues.
2. Read only documentation chapters relevant to the task.
3. Use targeted search instead of broad scanning:
   - `rg -n "pattern" <path>`
4. Open only the specific files needed to complete the current request.

## 4) Tool Use Rules
- Use local ripgrep for file discovery and text search 
- if `rg ` is NOT working, try:
  - `./ripgrep/rg.exe --files`
  - `./ripgrep/rg.exe -n "text" path`
- Use local virtualenv Python for all runs/checks:
  - `./.venv/Scripts/python.exe ...`
- Preferred fast validation (both steps, in this order):
  1. `./.venv/Scripts/python.exe -m compileall nanofab_v3 tests`
  2. `./.venv/Scripts/python.exe -m pytest`
- The test suite covers `nanofab_v3` (structure model v2); its layers and the acceptance
  criteria are defined in `docs/plans/v2-structure-model.md` §13. A change to `nanofab_v3`
  is not validated by `compileall` alone.
- Avoid unnecessary GUI process loops; prefer compile/import/smoke checks unless UI behavior must be tested directly.
- Before a release, also run the packaged exe's own DoD path (plan §14, §21.5):
  `pyinstaller nanofab_v3.spec && ./dist/nanofab_v3 --selftest`. `tests/test_scenarios.py`
  and `nanofab_v3/acceptance.py` share one definition of S1-S5, so this checks the build
  rather than re-checking the model.

## 5) memory.md Policy (Keep Updated)
After meaningful work, append an entry with these mandatory fields:
1. Date and short title.
2. What changed.
3. Why it changed.

optional:
How did you validate, next steps, known risks, reverted changes and why, what was tried and did not work, etc.

Keep entries append-only and concrete.

## 6) AGENTS.md Self-Update Rule
The **Coding Assistant** may propose improvements to `AGENTS.md`, but must **always ask the user before editing this file**.

## 7) Versioning and Backup Rules
- Use semantic versioning for milestones (`MAJOR.MINOR.PATCH`).
- Keep `AGENTS.md` version-agnostic: never lock instructions to a fixed version number.
- Before potentially breaking changes:
  1. Create a snapshot folder in `ui_backups/`:
     - `ui_backups/YYYY-MM-DD_vX.Y.Z_<label>/`
  2. Include whatever makes the snapshot stand on its own:
     - the code being snapshotted and everything it imports locally,
     - relevant spec file(s), with their paths repointed at the snapshot's own filenames,
     - a `README.md` saying what it is, how to run it, and what replaced it.
- Backups should be runnable/self-contained whenever practical. Verify it: `compileall` the folder and import its local packages from inside it.
- Never edit a snapshot after taking it — it is a record, not a branch.

## 8) Build/Finish Flow
1. Confirm active version from `nanofab_v3.__version__`.
2. Run validations:
   - `./.venv/Scripts/python.exe -m compileall nanofab_v3 tests`
   - `./.venv/Scripts/python.exe -m pytest`
3. Run minimal smoke test for key flows when feasible.
4. Update `memory.md` with outcome and any release notes.
5. Prepare Git tag only after user approval.

## 9) Git Workflow
- Branch model:
  - `main` for stable history.
  - `feature/<topic>` for normal work.
  - `hotfix/<topic>` for urgent fixes.
- Commit style:
  - focused commits with clear messages (`feat:`, `fix:`, `docs:`, `chore:`).
- Before commit:
  1. `git status --short`
  2. run validations
  3. stage only intended files
- Do not commit local/runtime artifacts:
  - `.venv/`, `.idea/`, `__pycache__/`, `build/`, `dist/`, local tool binaries.

## 10) Safety Rules
- Do not delete files/folders without explicit user approval of exact targets.
- If unexpected file changes appear, stop and ask the user how to proceed.
- For major refactors, summarize plan before editing.

## Agent skills

### Issue tracker

Issues live as GitHub issues in this repo (darkviruzz/nanofab), via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Standard label vocabulary (needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
