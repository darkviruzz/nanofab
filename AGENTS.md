# AGENTS.md - NanoFab Manager Workspace Guide

This file defines how the **Coding Assistant** should operate in this repository at the start of every session.

## 1) Startup Checklist (Always)
1. Read this `AGENTS.md`.
2. Read [`memory.md`](memory.md) before making edits.
3. Check current workspace state:
   - `./ripgrep/rg.exe --files`
   - `git status --short`
4. Detect current build/version dynamically (do not hardcode):
   - `./ripgrep/rg.exe -n "^APP_NAME|^APP_VERSION" nanofab_manager*.py`
5. If multiple candidate app entry files exist, ask the user which one is active before major changes.

## 2) Repository Map (Read in This Order)
- Project memory and decisions:
  - `memory.md`
- Active UI/runtime entry:
  - `nanofab_manager.py` (or user-selected active entry file)
- Modular engine and process logic:
  - `nanofab_modular/domain.py`
  - `nanofab_modular/step_api.py`
  - `nanofab_modular/engine.py`
  - `nanofab_modular/registry.py`
  - `nanofab_modular/steps/*.py`
- Product docs:
  - `NanoFab_Process_Manager_Documentation/*.md`
- Baselines/backups:
  - `ui_backups/`

## 3) Efficient Reading Strategy
1. Read `memory.md` first for latest decisions and known issues.
2. Read only documentation chapters relevant to the task.
3. Use targeted search instead of broad scanning:
   - `./ripgrep/rg.exe -n "pattern" <path>`
4. Open only the specific files needed to complete the current request.

## 4) Tool Use Rules
- Use local ripgrep for file discovery and text search:
  - `./ripgrep/rg.exe --files`
  - `./ripgrep/rg.exe -n "text" path`
- Use local virtualenv Python for all runs/checks:
  - `./.venv/Scripts/python.exe ...`
- Preferred fast validation:
  - `./.venv/Scripts/python.exe -m compileall nanofab_manager.py nanofab_modular`
- Avoid unnecessary GUI process loops; prefer compile/import/smoke checks unless UI behavior must be tested directly.

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
  2. Include:
     - active app file(s),
     - `nanofab_modular/`,
     - relevant spec file(s),
     - `memory.md` snapshot.
- Backups should be runnable/self-contained whenever practical.

## 8) Build/Finish Flow
1. Confirm active version from source constants (`APP_VERSION`) in active entry file.
2. Run compile check:
   - `./.venv/Scripts/python.exe -m compileall <active_app_file> nanofab_modular`
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
