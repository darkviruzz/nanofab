# NanoFab Modularization Memory

Last updated: 2026-03-05

## Goal
- Create a new modular implementation based on `app_pyside.py` UI flow.
- Keep all existing files unchanged.
- Split process logic so each process step lives in its own importable module with explicit inputs/outputs.

## Comparison: Documentation vs `app_pyside.py`
- UI structure alignment:
  - Present in `app_pyside.py`: View A (process chain) and View B (recipe card) are implemented.
  - Missing from target docs: dedicated Execution Monitor (View C), Inspection Browser (View D), and 3D Viewer (View E).
- Process-chain alignment:
  - Docs emphasize an 8-step lithography + lift-off template.
  - `app_pyside.py` uses a mixed 12-step mock chain and monolithic in-file process behavior.
- Architecture alignment:
  - Docs require recipe/run separation, explicit state evolution, append-only revisions, artifact references, and extensibility.
  - `app_pyside.py` keeps mostly UI + mock logic together and does not isolate step logic into interchangeable modules.
- Validation/runtime alignment:
  - Current app has local mismatch warnings and mock actions.
  - Missing from docs target: clear step-module interface with prerequisite gating, module-swappable execution logic, and module-level I/O contracts.

## Decisions
- Build a new package: `nanofab_modular/`.
- Keep PySide UI structure close to `app_pyside.py`:
  - View A: Process chain table + context.
  - View B: Parameter card/editor.
- Implement a module contract (`ProcessStepModule`) with:
  - parameter schema
  - default values
  - validation
  - helper tools (optional)
  - execution returning output state + artifacts + logs
- Implement 8 step modules from documentation section 7.

## Current Task Backlog
1. [Done] Create core domain and step API files.
2. [Done] Add 8 step modules with I/O and state mutations.
3. [Done] Add process engine and registry.
4. [Done] Create `app_pyside_modular.py` using modular engine as backend.
5. [Done] Run syntax validation with `.venv/Scripts/python.exe`.
6. [Active] Continue iterative feature work (Execution Monitor view, artifact browser view, persistence).

## New Files Created
- `app_pyside_modular.py`
- `nanofab_modular/__init__.py`
- `nanofab_modular/domain.py`
- `nanofab_modular/step_api.py`
- `nanofab_modular/engine.py`
- `nanofab_modular/registry.py`
- `nanofab_modular/steps/__init__.py`
- `nanofab_modular/steps/_helpers.py`
- `nanofab_modular/steps/substrate_selection_step.py`
- `nanofab_modular/steps/cleaning_step.py`
- `nanofab_modular/steps/resist_coating_step.py`
- `nanofab_modular/steps/soft_bake_step.py`
- `nanofab_modular/steps/projection_exposure_step.py`
- `nanofab_modular/steps/development_step.py`
- `nanofab_modular/steps/thin_film_deposition_step.py`
- `nanofab_modular/steps/lift_off_step.py`

## Progress Log
- 2026-03-03: Reviewed `NanoFab_Process_Manager_Documentation` and `app_pyside.py`.
- 2026-03-03: Drafted modular architecture and initial implementation plan.
- 2026-03-03: Implemented modular domain model, step API, and process engine.
- 2026-03-03: Added 8 independent step modules for the documented lithography + lift-off chain.
- 2026-03-03: Added new PySide entrypoint `app_pyside_modular.py` with View A/View B layout based on `app_pyside.py`.
- 2026-03-03: Validation run:
  - `.\.venv\Scripts\python.exe -m compileall app_pyside_modular.py nanofab_modular`
  - engine smoke test executed first 3 steps successfully.
- 2026-03-03: Stability hardening after runtime crash report (`0xC0000005`):
  - Replaced unsafe table `layoutChanged` refresh with `dataChanged` range emission.
  - Added defensive selection/index validity checks in process list context updates.
  - Deferred chain view refresh/context restore with `QTimer.singleShot(0, ...)` to avoid re-entrant model/view updates.
- 2026-03-03: UI replacement request executed:
  - Backed up previous modular UI file to `ui_backups/2026-03-03_pre_new_ui/app_pyside_modular.py`.
  - Replaced `app_pyside_modular.py` with the new responsive UI implementation.
  - Removed `Angular` naming from class/window/app labels in the replaced UI.
- 2026-03-03: Restored original modular app and reworked UI while preserving core features:
  - Restored `app_pyside_modular.py` from backup and kept engine-backed architecture (`ProcessEngine`, module validation, helper tools).
  - Added modern visual styling pass (cards/controls/table/toolbar) without removing validation/save/revert/run-next/run-all workflows.
  - Added row drag-grabber column (`⋮⋮`) and row-reorder support for unfinished steps.
  - Enforced rule: `Done`/`Warning`/`Running` rows are fixed and cannot be moved.
  - Added per-row action badge column:
    - first not-done row: `Run Now`
    - all later not-done rows: `Pending`
    - done rows: `Done`
  - Added engine-level order mutation helper (`ProcessEngine.move_step`) with done-step locking.

## Next Steps
1. Add View C (execution monitor with progress and logs) in the new modular app.
2. Add View D artifact browser wired to `SampleState.artifacts`.
3. Add basic file-backed persistence (`runs/<run_id>/run.json`, revisions, logs).
4. Add inspection-step insertion workflow (from documentation section 8.1).

## Update 2026-03-03 (Current Session)
- Rewired `app_pyside_modular.py` `MainWindow` to a modern active 3-column runtime UI:
  - left column: process cards from module runtime metadata (name, description, key params, status),
  - center column: schema-driven parameter editor (`RecipeCardView`) with validate/save/revert/helper tools,
  - right column: cross-section + artifacts derived from `engine.current_state`.
- Replaced active table usage with list cards and soft drag-reorder UX:
  - drag grabber shown as `::`,
  - done/warning/running steps fixed,
  - reorder enabled only when filters are clear.
- Enforced active row-action labels in list:
  - first unfinished row => `Run Now`,
  - later unfinished rows => `Pending`,
  - done/warning => `Done`, running => `Running`.
- Added responsive behavior:
  - `wide` (>=1320): three columns,
  - `medium` (>=980): hide right column,
  - `compact` (<980): list/detail navigation with back action,
  - compact/medium open cross-section via toolbar action + overlay dialog.
- Added cross-section renderer that adapts horizontal resolution using `geometry.segments` facets and layer stack data.
- Validation executed:
  - `./.venv/Scripts/python.exe -m compileall app_pyside_modular.py nanofab_modular`
  - `MainWindow` create/show/close smoke test
  - run-next + reorder method smoke test

## Immediate Next Iteration
1. Tune spacing/typography for closer visual parity to angular mock.
2. Add explicit execution monitor pane (global run logs/progress).
3. Implement actual `Add Step` workflow from module catalog.
4. Add file-backed run persistence (`runs/<run_id>/run.json`, revisions, logs).

## Update 2026-03-03 (Display/UX Fix Pass)
- Replaced toolbar row with modern `TopBar` in active app runtime:
  - left: `N` badge + `NanoFab Manager` branding,
  - right: `Cross Section` button, `System Online`, `ID:` placeholder.
- `Cross Section` behavior updated:
  - wide layout: toggles right column visibility,
  - medium/compact: opens/closes floating non-modal cross-section/artifacts window.
- Removed hardcoded bright-theme colors from active UI stylesheet and switched to palette-based roles (`palette(window/base/text/mid/highlight)`), so controls follow system light/dark mode consistently.
- Left process list compactness and structure updated:
  - drag-grabber + step number stacked vertically,
  - removed per-item description line,
  - kept name + wrapped parameter summary,
  - right-aligned status/action controls,
  - dynamic minimum width computed from longest process title + action buttons.
- Interaction stability updates for list:
  - selection no longer rebuilds the full list,
  - active marker updates in-place,
  - scroll position preserved across refresh,
  - removed splitter-size resets on simple row clicks,
  - added explicit row drag-start handling to improve reorder behavior.
- Center parameter view layout changed from side-column to row stacking:
  - form section on top,
  - validation/helper section below.
- Process description moved into parameter header subtitle to avoid duplication in list rows.
- Verification:
  - `./.venv/Scripts/python.exe -m compileall app_pyside_modular.py`
  - smoke checks for wide/medium/compact transitions, non-modal overlay behavior, and run/back flow.

## Update 2026-03-03 (Bugfix Pass: Reorder/Theme/Lift-off)
- Execution ordering semantics changed in `nanofab_modular/engine.py`:
  - `Ready/Blocked` are now implicit from process order:
    - first unfinished step -> `Ready`,
    - all later unfinished steps -> `Blocked`.
  - Reordering now immediately re-evaluates readiness.
  - Hard prerequisite blocking in `validate_step(...)` removed (module-level validation still applies).
- Left process list action model simplified in active UI:
  - right side now uses one state/action button per row (`Run Now`, `Pending`, `Done`, `Running`),
  - removed extra status badge button from list rows.
- List drag UX fixes:
  - vertical gap removed to avoid ambiguous drop indicator positions,
  - drag attempt in filtered (non-draggable) mode no longer triggers selection changes,
  - click is emitted on release (if pointer did not move), reducing accidental selection/reset behavior.
- Runtime theme adaptation improvements:
  - added `MainWindow.changeEvent(PaletteChange)` hook to reapply stylesheet and refresh visible UI blocks,
  - increased text readability by reducing low-contrast muted text usage in active list/top-bar styles.
- Top bar typography tweak:
  - larger `NanoFab Manager` brand text; `Manager` remains lighter in the rich-text label.
- Lift-off logic corrected in `nanofab_modular/steps/lift_off_step.py`:
  - metal above resist is removed logically by segment mapping,
  - metal is retained only in developed openings,
  - metal layer receives `geometry.segments` pattern instead of remaining blanket.
- Verification (non-GUI-loop checks):
  - `./.venv/Scripts/python.exe -m compileall app_pyside_modular.py nanofab_modular`
  - engine reorder readiness check
  - full chain run check with final patterned metal segment verification.

## Update 2026-03-03 (Recursion Fix)
- Fixed `PaletteChange` recursion in `MainWindow.changeEvent`:
  - replaced direct heavy refresh calls with guarded deferred refresh (`QTimer.singleShot`),
  - added `_palette_refresh_guard` and `_palette_refresh_scheduled` flags,
  - avoided rebuilding list rows in `changeEvent` path (no `left_col.refresh(...)` there).
- Added non-UI simulation check for repeated palette change events to validate non-recursive behavior.

## Update 2026-03-03 (UI Polish Fixes)
- Contrast/readability:
  - `_muted_text_style()` switched to `palette(text)` for better dark-mode readability of IO/helper/description text.
- Parameter setup spacing:
  - added `3px` margin around parameter labels and input widgets in `RecipeCardView._build_form(...)`.
- Process list item interaction/visual updates:
  - step handle now shows step number by default,
  - grabber is hidden until hover over the step handle,
  - action button is vertically centered and right-aligned.
- Drag behavior in filtered (non-draggable) mode:
  - pointer move no longer cascades into unwanted selection changes.
- Cross-section toggle layout recalculation:
  - when right column is shown/hidden in wide mode, splitter sizes are recalculated immediately using current window width and left-column minimum width.

## Update 2026-03-03 (Padding + List Geometry Polish)
- Parameter form spacing adjusted from margin-heavy to padding-first:
  - labels now use small margin (`1px`) + padding (`3px`),
  - parameter widgets now use `margin: 1px; padding: 3px;`.
- Center header description stabilized:
  - added padded description box styling,
  - shortened long descriptions with ellipsis,
  - moved technical metadata to separate single-line meta label,
  - added stretch below form to absorb extra vertical space cleanly.
- Process list geometry and hover handle behavior:
  - list item outer spacing added (`QListWidget` spacing),
  - left inset reduced and right inset increased to avoid right-edge clipping,
  - added viewport right margin (`2px`) to prevent cropped right border,
  - step number/grabber now share a stack: number by default, grabber on hover.
- Wide-layout cross-section toggle:
  - on enable/disable of right column, left-column width/min-size is recalculated and list is refreshed once.
- Corner radii refined for more consistent concentric look:
  - top bar > cards > items/buttons hierarchy adjusted to harmonized rounded radii.

## Update 2026-03-03 (Edit Mode + Chain Editing)
- Left-column top controls reworked:
  - removed `Add Step` top button,
  - added `Edit` toggle button (enables/disables chain editing actions),
  - added `Restart Chain` button.
- Edit mode behavior in process list:
  - reordering only when Edit is ON and filters are clear,
  - per-step red delete button (bin icon) appears in top-right for removable (unfinished) steps,
  - per-step `+` insertion control appears on hover (insert-after position), only for editable unfinished region.
- Added process insertion flow:
  - selecting `+` opens a process selection list (`QInputDialog`) built from all available module types,
  - inserted modules receive unique runtime step IDs via engine allocator.
- Added/extended engine APIs in `nanofab_modular/engine.py`:
  - `insert_step(module, index)`
  - `remove_step(step_id)` (blocks done/warning/running)
  - `restart_chain()` (resets runtime state/status while preserving chain + params).
- Added MainWindow handlers for:
  - edit-mode state changes,
  - add/remove step actions,
  - restart chain confirmation and reset.
- Verification:
  - `./.venv/Scripts/python.exe -m compileall app_pyside_modular.py nanofab_modular`
  - engine-level insert/remove/restart checks
  - MainWindow initialization check (without GUI show loop).

## Update 2026-03-03 (Floating Insert Controls)
- Moved add-step `+` controls out of list item cards into floating overlay buttons on the list viewport.
- Floating `+` buttons are now positioned:
  - above each unfinished step (i.e., between list elements),
  - plus one at the very end of the list.
- Insert controls are suppressed before done items by using `first_unfinished_row` as insertion start.
- Insert controls remain tied to Edit mode + unfiltered list state (same safety policy as reorder).
- Per-item inline insert button was removed so list cards are no longer shifted by insertion controls.

## Update 2026-03-03 (Flicker/Speed + Insert Position)
- Edit toggle performance improved:
  - removed duplicate list refresh on edit-mode change from `MainWindow`.
- List rebuild flicker reduced:
  - disabled updates while rebuilding filtered list and floating insert controls,
  - overlay `+` controls now created hidden and shown only after final positioning,
  - cleared overlay buttons with hide+detach before delete.
- Floating insert button vertical offsets adjusted:
  - each between-step `+` moved up by half list spacing,
  - end-of-list `+` moved down by half list spacing.
- Right-side bin/delete control alignment updated:
  - delete button vertically centered.

## Update 2026-03-03 (Material-Aware Cross Section + Generic Step Names)
- Cross-section renderer now derives layer color from `layer.material` (with a material palette map), with role-based fallback for unknown materials.
- Material color mapping added for common metals/resists (`Cr`, `Au`, `Al`, `Ti`, `Cu`, `Ni`, `AZ10XT`, `S1813`, `SU-8`, `PMMA`).
- Process display names made material-agnostic:
  - `Resist Coating` (removed hardcoded AZ10XT)
  - `Thin Film Deposition` (removed hardcoded Cr)
- Parameter summaries updated to still reflect selected material/resist values:
  - resist summary includes selected resist type
  - thin-film summary includes selected deposition material
- Validation:
  - `./.venv/Scripts/python.exe -m compileall app_pyside_modular.py nanofab_modular`
  - module name/summary smoke check via `build_default_modules()`.

## Update 2026-03-04 (Unsaved-Changes Guard + Tiny-Window Flicker Cause)
- Added setup-change guard in `app_pyside_modular.py`:
  - leaving a modified setup now opens a 3-choice dialog: `Apply`, `Revert`, `Cancel`.
  - `Cancel` keeps the user on the current step/view.
  - guard is enforced when switching selected steps and when backing out of setup in compact mode.
- Added explicit form-state APIs in `RecipeCardView`:
  - `has_unsaved_changes()`
  - `apply_changes(...)`
  - `revert_changes(...)`
  - existing Save/Revert buttons now use these shared methods.
- Fixed likely tiny-window flicker trigger in process list overlays:
  - removed `setParent(None)` from floating insert-button cleanup to avoid creating transient top-level widgets during frequent list rebuilds.
- Verification:
  - `./.venv/Scripts/python.exe -m compileall app_pyside_modular.py nanofab_modular`

## Update 2026-03-04 (App Rename + Center Scroll + Button Hover)
- Renamed the active main app module:
  - moved implementation from `app_pyside_modular.py` to `nanofab_manager.py`.
  - left `app_pyside_modular.py` as a small compatibility launcher importing `main` from `nanofab_manager`.
- Updated app naming:
  - window title now `NanoFab Manager`.
  - Qt application name now `NanoFab Manager`.
- Center setup view layout improved for small window heights / many parameters:
  - introduced a dedicated vertical `QScrollArea` for form + validation/helper sections.
  - keeps top action bar fixed while allowing scroll to validation area.
- Long text handling improved in center validation section:
  - switched validation and input/output blocks to read-only text editors (`QTextEdit`).
  - added dynamic auto-height with upper bounds; content fits when short and uses internal scrollbars when long.
- Button discoverability improved:
  - added consistent hover styling for main button classes (`Top`, `RowAction`, `Primary`, `Secondary`, `Back`, `Insert`).
  - row status buttons (`Run Now`, `Pending`, `Done`) now show hover feedback while preserving click behavior (`Run Now` only executes).
- Packaging spec alignment:
  - `app_pyside_modular.spec` now points to `nanofab_manager.py` and names the executable `nanofab_manager`.
- Verification:
  - `./.venv/Scripts/python.exe -m compileall nanofab_manager.py app_pyside_modular.py nanofab_modular`
  - startup smoke test: create/show/close `MainWindow` from `nanofab_manager`.

## Update 2026-03-04 (Encoding/Mojibake Repair)
- Fixed broken symbol rendering introduced by encoding mismatch:
  - delete button no longer uses fragile Unicode glyph text; it now uses Qt standard trash icon (`QStyle.SP_TrashIcon`).
  - `System Online` indicator no longer relies on Unicode bullet text; replaced with separate styled dot widget (`SystemDot`) + ASCII text label.
- Removed UTF-8 BOM markers from:
  - `nanofab_manager.py`
  - `app_pyside_modular.py`
- Confirmed both files are ASCII-only source text (no non-ASCII lines).
- Verification:
  - `./.venv/Scripts/python.exe -m compileall nanofab_manager.py app_pyside_modular.py`
  - startup smoke test (`MainWindow` create/show/close).

## Update 2026-03-04 (Edit-Toggle Flicker Root Cause + Fix)
- Investigated tiny foreground windows during `Edit` toggle with runtime `QEvent.Show` probe.
- Root cause identified:
  - per-row `run`/`delete` buttons were created parentless and visibility was set before layout parenting.
  - when visibility became `True` during row rebuilds, Qt briefly treated these as top-level windows.
  - this happened differently on enable/disable:
    - enable `Edit`: delete/bin buttons became visible first,
    - disable `Edit`: run/pending buttons became visible first.
- Fix applied in `nanofab_manager.py`:
  - `ProcessListItemWidget` now accepts explicit `parent`.
  - row widget is created with `parent=self.list`.
  - `delete_button` and `run_button` are now constructed with parent `self` immediately.
- Verification:
  - instrumented toggle probe now shows only `MainWindow` as visible top-level during edit toggles (no transient button windows).

## Update 2026-03-04 (Post-Flicker Layout Regression Fix)
- Fixed button-placement regression introduced after anti-flicker parenting change:
  - Cause: row action button insertion into right-column layout was gated by `isVisible()`, which is `False` before parent widgets are shown.
  - Effect: run/pending buttons could stay at default `(0,0)` inside list rows instead of right-aligned.
- Fix in `nanofab_manager.py`:
  - compute intended visibility via explicit booleans (`show_run_button`, `show_delete`),
  - always add both buttons to the right-column layout,
  - toggle visibility without using `isVisible()` as layout condition.
- Verification:
  - runtime geometry check confirms right alignment for run/delete controls in both edit OFF/ON states.

## Update 2026-03-04 (Row Height Normalization + Button Style Pass)
- Root cause for uneven row heights identified and fixed:
  - previous item heights were set from early widget `sizeHint()` before final viewport width, leaving stale wrapped-height hints on some rows.
  - added width-aware relayout pass (`ProcessListItemWidget.relayout_for_width(...)`) and `ProcessListColumn._relayout_list_rows()` after rebuild and on resize.
  - rows now recompute text wrapping against actual available width, then update item size hints consistently.
- Process list action controls updated per request:
  - `Delete` button now text-based (`Delete`), width-aligned to action buttons.
  - `Edit` checked state now fully filled highlight (not border-only).
  - floating `+` button restyled:
    - default: transparent, bold `+` text only (no border/background),
    - hover: expands to `26x26`, circular, highlight-filled.
  - implemented via dedicated `InsertStepButton` class with hover-size state.
- Verification:
  - runtime check confirms uniform row heights in default state (`42 px` each for current chain width/content).
  - `InsertStepButton` size transitions verified (`18x18` default -> `26x26` hover).
  - `./.venv/Scripts/python.exe -m compileall nanofab_manager.py`.

## Update 2026-03-04 (Setup Run-State Sync + Unsaved Run Prompt)
- Setup-view run button now mirrors list-step action state exactly:
  - label and `action_state` are synced from `ProcessTableModel.action_label_for_row(...)`.
  - states shown in setup: `Run Now`, `Pending`, `Done` (and `Running` if present).
- Setup run execution is now readiness-gated:
  - center run button emits run request only when current state is `Run Now`.
  - main run handler also enforces readiness (`Only the next ready step can be run...`) as a safety guard.
- Added unsaved-changes run-context prompt:
  - when running from setup and current step has unsaved edits, dialog now asks `Apply / Revert / Cancel` before execution.
  - wording in run-context dialog clarifies apply/revert behavior for the immediate run.
- Wiring changes:
  - center run signal now routes to dedicated `_run_row_from_setup(...)` flow instead of direct `_run_row(...)`.
- Verification:
  - checked center button labels against model action labels for multiple rows.
  - verified non-ready setup run does not execute.
  - verified run-context unsaved prompt path is invoked before running ready step.
  - `./.venv/Scripts/python.exe -m compileall nanofab_manager.py app_pyside_modular.py`.

## Update 2026-03-04 (List-Run Unsaved Guard + TextBox Scrollbar Fit Fix)
- List run actions now also honor unsaved setup changes:
  - `left_col.run_requested` is routed through `_run_row_from_list(...)` instead of direct `_run_row(...)`.
  - before executing list-run, app now triggers unsaved dialog (`Apply / Revert / Cancel`) using run-context semantics.
  - if running a different step than currently selected dirty setup, dialog text clarifies that current setup changes are pending.
- Data-loss edge case addressed:
  - running another step from list while selected step is dirty now requires explicit Apply/Revert/Cancel first; changes are no longer silently dropped.
- Validation/Input-output textbox scrollbar false-positive fix:
  - improved `QTextEdit` autosize math by including document margins + frame width + safety slack.
  - vertical scrollbar is forced off when content fits and only enabled when true overflow exceeds configured max height.
  - line-wrap mode explicitly set to widget width for stable text layout.
- Verification:
  - runtime test confirms unsaved prompt is invoked for list-run on both same-step and other-step targets.
  - runtime check confirms short content does not show vertical scrollbar in validation and IO boxes.
  - `./.venv/Scripts/python.exe -m compileall nanofab_manager.py app_pyside_modular.py`.

## Update 2026-03-04 (Done-Step Lock + Robust Dirty-State Baseline)
- Done-step editing disabled in setup view:
  - when selected runtime status is `Done`/`Warning`, parameter widgets are disabled and Save/Revert/Helper actions are disabled.
  - applying parameter changes on locked steps now returns false and (when requested) shows a read-only info message.
- Dirty-state logic hardened to avoid stale false positives across direction-dependent step switches:
  - `has_unsaved_changes()` now compares current form values to engine-saved params for the current step (not only local cached `_original_params`).
  - both sides are canonicalized by parameter schema type (`select/bool/int/number/text`) before comparison.
  - after `load_process(...)`, baseline `_original_params` is refreshed from current widget values to match widget-representable precision.
  - `revert_changes(...)` now reloads from engine-saved params and refreshes local baseline.
- Outcome:
  - reproduced both switch orders (`2->3->2->3` and `3->2->3->2`) with modified numeric field and no residual false-dirty popup.
  - done-step widgets are read-only and save/revert are disabled.
- Verification:
  - sequence automation checks for both direction orders with auto-apply prompt path.
  - done-step lock check after running step 1.
  - `./.venv/Scripts/python.exe -m compileall nanofab_manager.py app_pyside_modular.py`.

## Update 2026-03-05 (Versioning Baseline + Polygon Work Prep)
- Introduced explicit semantic version constants in active main file:
  - `APP_NAME = "NanoFab Manager"`
  - `APP_VERSION = "0.1.0"`
  - window/app titles now include version string.
- Created backup snapshot folder for current baseline:
  - `ui_backups/2026-03-05_v0.1.0_baseline/`
  - includes: `nanofab_manager.py`, `app_pyside_modular.py`, `app_pyside_modular.spec`, `memory.md`, `nanofab_modular/`.
- Created next-version code copy (no functional changes beyond version number):
  - `nanofab_manager_v0_2_0.py` with `APP_VERSION = "0.2.0"`.
- Normalized source encoding to UTF-8 without BOM after file-copy operations.
- Validation:
  - `./.venv/Scripts/python.exe -m compileall nanofab_manager.py nanofab_manager_v0_2_0.py app_pyside_modular.py nanofab_modular`.

## Polygon Renderer Preparation Plan (v0.2.0)
1. Geometry core abstraction
 - Add `CrossSectionGeometry` backend interface independent of Qt renderer.
 - Keep operations API 2D-first but dimension-agnostic (reserve z/depth axis for 3D extension).
2. State model extension
 - Add optional polygon region store to `SampleState.facets` first (non-breaking), then migrate to typed domain object if stable.
 - Preserve current layer list as compatibility summary/projection.
3. Process operation primitives
 - Define canonical ops: `deposit_blanket`, `deposit_conformal`, `etch_isotropic`, `etch_anisotropic`, `etch_selective(material_rules)`, `lift_off(mask_ref)`.
 - Each step module maps to these ops instead of directly mutating ad-hoc segment facets.
4. Material/stack semantics
 - Introduce material IDs + etch/deposition behavior tables (selectivity, directional bias, rate model hooks).
 - Keep simple nominal-rate models initially; allow pluggable physics later.
5. Renderer migration strategy
 - Add polygon renderer alongside current segment renderer behind feature flag.
 - Keep fallback rendering from existing `geometry.segments` during transition.
6. Performance constraints
 - Start with rectangle-heavy polygon generation (low polygon count by default).
 - Add optional refinement/splitting only where topology changes (corners/undercuts/sidewalls).
7. Validation and replay
 - Add deterministic operation log per step so geometry can be replayed/rebuilt after reorder or parameter edits.
 - Build snapshot tests for critical patterns (conformal coat, isotropic undercut, anisotropic trench, selective wet etch).

## Update 2026-03-05 (Repository Cleanup: Delete 1-8)
- User-approved deletion set (`1-8`) was executed with exact path targets.
- Safety note applied for `nanofab-process-manager`:
  - deleted only the root folder `./nanofab-process-manager`,
  - no wildcard/pattern deletion was used, so other occurrences of the string in files/paths were not touched.
- Removed obsolete/duplicate launchers and build outputs:
  - `app.py`, `main.py`, `app_flet.py`, `app_flet.spec`, `app_pyside.py`, `app_pyside.spec`, `app_pyside_modular.py`, `app_pyside_modular.spec`,
  - `new-ux-mockup/`, `build/`, `dist/`,
  - legacy backup `ui_backups/2026-03-03_pre_new_ui/`.
- Retained active and useful structure:
  - active app: `nanofab_manager.py`, `nanofab_manager_v0_2_0.py`,
  - modular core: `nanofab_modular/`,
  - baseline backup: `ui_backups/2026-03-05_v0.1.0_baseline/` (self-contained with its own `nanofab_modular/`),
  - docs/tools/history: `NanoFab_Process_Manager_Documentation/`, `ripgrep/`, `memory.md`.
- Post-cleanup validation:
  - `./.venv/Scripts/python.exe -m compileall nanofab_manager.py nanofab_manager_v0_2_0.py nanofab_modular` succeeded.

## Update 2026-03-05 (Git Bootstrap)
- Initialized Git repository at project root with `main` as default branch.
- Added root `.gitignore` to exclude local/runtime artifacts from commits:
  - Python caches (`__pycache__`, `*.pyc`),
  - local virtual environments (`.venv/`, `venv/`),
  - IDE metadata (`.idea/`, `.vscode/`),
  - build outputs (`build/`, `dist/`, `*.egg-info/`),
  - local bundled tool folder (`ripgrep/`).
- Resulting first-commit candidate set now focuses on source code, docs, and baseline backup only.

## Update 2026-03-05 (Workspace AGENTS Guide Added)
- Added root `AGENTS.md` to define session startup behavior for the Coding Assistant.
- Guide content is version-agnostic and requires dynamic detection of current build version from source constants (`APP_NAME`, `APP_VERSION`).
- Included explicit policies for:
  - use of local tools (`./ripgrep/rg.exe`, `./.venv/Scripts/python.exe`),
  - required `memory.md` updates,
  - backup/version workflow,
  - Git branching/commit practices,
  - safety rules for deletion and major changes.
- Added strict rule: ask user before any future edit to `AGENTS.md`.

## Update 2026-03-05 (General Cross-Section Prototype: Region/Interface Model)
- Created new branch `feature/general-cross-section-prototype`.
- Added standalone prototype file `cross_section_general_prototype.py` (no changes to existing app entrypoints):
  - Introduces a minimal general cross-section state model:
    - `CrossSectionState` (schema version, extent, materials, regions, scalar fields, operation log)
    - `Region2D` polygon regions with material IDs/tags
    - `InterfaceSegment` extraction from exposed boundaries
    - `ScalarField2D` placeholder for future gradients
  - Geometry scene built as requested:
    - substrate with slight overetch profile,
    - two-period patterned T-grating,
    - conformal thin metal generated from orthonormal interface offset.
  - Added conformal-thickness experiment control:
    - slider changes thickness (nm),
    - metal is rebuilt from exposed interfaces by normal-offset extrusion.
  - Added vertical ray-cast utility (`vertical_ray_first_hit`) to demonstrate structural compatibility with top-down beam checks.
  - UI is a single card-style window focused only on cross-section display.

Why it changed:
- Provide a minimal, testable implementation of a more general geometry representation (region/interface based) replacing column-placeholder ideas for experimentation before larger integration.

Validation run:
- `./.venv/Scripts/python.exe -m compileall cross_section_general_prototype.py`
- Offscreen smoke test:
  - state build with conformal metal,
  - ray-cast hit query,
  - `CrossSectionCardWindow` create/show/close.

Next steps / known risks:
1. Conformal deposition is represented as interface-strip extrusion and can overlap at corners (no boolean merge yet).
2. Interface extraction uses polygon exposure sampling and is robust for this prototype, but should be replaced by explicit topology adjacency for production.
3. Ray-cast utility currently returns first-hit only; full ion-beam simulation needs multi-hit traversal + per-material removal update loop.

## Update 2026-03-05 (Prototype Revision: Process/Material Separation + Iterative Growth Overlays)
- Updated `cross_section_general_prototype.py` based on feedback:
  - Removed process-specific etch rates from `MaterialDef`.
  - Material DB now holds only material descriptors/properties:
    - `material_id`, `name`, category/composition/crystallinity/morphology, optical constants, display colors.
  - Added process-side interaction model `ProcessInteractionModel`:
    - explicit mapping `etch_rate_by_material_nm_min`,
    - optional fallback derived from material category.
  - `CrossSectionState` now includes `process_models` and `active_process_id`.
- Reworked conformal deposition model to avoid overlapping rectangle strips:
  - implemented iterative shell-growth from base interface path with bounded passes,
  - each pass builds the next shell and accumulates into one metal geometry,
  - uses rounded joins to yield natural corner rounding behavior.
- Added UI visualization controls (as requested):
  - toggle button `Exposed Interfaces` (highlights exposed segments + normals),
  - toggle button `Ray Casting` (top-down rays with hit/open visualization).
- Added analysis/status output in card UI:
  - exposed segment count,
  - open-ray ratio,
  - active process/material etch-rate summary from process model.

Validation run:
- `./.venv/Scripts/python.exe -m compileall cross_section_general_prototype.py`
- smoke script (offscreen) verified:
  - no process rates in material model,
  - process-material rate lookup active,
  - conformal metal regions generated with non-rectangular contour detail,
  - exposed-interface extraction and ray-cast scanning,
  - window + overlay controls create/show/update/close successfully.

Next steps / known risks:
1. Iterative shell-growth uses path-level geometric approximation (bounded passes) rather than full per-nm physical simulation.
2. Ray-casting currently reports first-hit only; full ion-beam removal requires iterative material-removal updates with per-material etch rate integration.
3. Exposure/dose scalar fields remain placeholders and are not yet coupled into geometry evolution.

## Update 2026-03-05 (Prototype Refresh: Curve-Segment Topology Testbed)
- Replaced `cross_section_general_prototype.py` with a new prototype centered on explicit interface-loop topology:
  - Segment primitives now include `LineSegment` and `ArcSegment` with analytic start/end/normal-tangent sampling.
  - Geometry is represented by closed `InterfaceLoop` boundaries in `Region2D`, then converted to render/boolean paths through configurable arc sampling (`arc_chord_nm`).
  - Added loop diagnostics (`LoopDiagnostic`) for closure and tangential continuity checks at segment joints.
- Added a lightweight geometry/topology operation engine API in the prototype file:
  - `deposit_blanket(...)`
  - `deposit_conformal(...)` (iterative, capped-pass shell growth with rounded joins)
  - `etch_isotropic(...)`
  - `etch_anisotropic(...)` (ray-driven directional preview)
  - `etch_selective(...)`
  - `lift_off(...)`
- Rebuilt the test scene from the new structure:
  - substrate loop with rounded overetch trench,
  - two-period T-shaped grating loops,
  - conformal metal deposition as a process-layer preview.
- Reworked UI into a single card-style prototype stress harness:
  - mode selector (`Conformal`, `Isotropic`, `Directional`, `Combined`, `Diagnostics`),
  - extended slider set for geometry/process/ray/sampling stress tests,
  - overlay toggles for `Interfaces`, `Normals`, `Rays`, and `Shadow`,
  - info panel reporting loop counts/warnings, exposed-edge counts, ray hit/open stats, and active process etch-rate table.
- Added responsiveness guardrails:
  - slider tracking disabled (apply on release),
  - iterative conformal growth pass cap + boundary edge decimation to avoid runaway boolean complexity.

Why it changed:
- The previous polygon-only prototype was not enough to stress curved-interface topology and tangent continuity behavior. This refresh makes curved + linear interfaces first-class and keeps process interactions visible while still avoiding heavy physics.

Validation run:
- `./.venv/Scripts/python.exe -m compileall cross_section_general_prototype.py`
- offscreen smoke:
  - `QT_QPA_PLATFORM=offscreen` window init/create/close for `CrossSectionCardWindow`
  - directional scene build check (`rays 36 / hits 33`) to verify ray + hit-normal pipeline.

Next steps / known risks:
1. Boolean geometry still relies on `QPainterPath` approximation; topology ownership at triple-junctions is heuristic (`contains` probe based).
2. Directional etch currently uses first-hit ray cuts with fixed slit width; it is suitable for structure testing, not for physical rate accuracy yet.
3. If this data model is accepted, split primitives/engine into a dedicated `nanofab_modular` geometry package and add deterministic geometry replay tests per operation.

## Update 2026-03-05 (Prototype Fix Pass: Uniform Conformal Growth + Mode-Aware Controls)
- Addressed clumpy conformal growth for small arc chords:
  - replaced edge-fragment stroking with continuous closed-boundary offset shell generation in `deposit_conformal(...)`,
  - uses one uniform dilation shell (`2 * thickness`) to avoid droplet artifacts and unequal growth spacing,
  - remains smooth for curved and linear interfaces and is now fast for fine boundary sampling.
- Added directional ray-mask smoothing control:
  - `etch_anisotropic(...)` now accepts `ray_overlap_ratio`,
  - switched to round-cap/round-join slit generation and simplified merged etch mask.
- Updated UI controls to reduce ambiguity:
  - added `Ray Overlap (%)` slider,
  - renamed `Growth Step` to `Etch Step`,
  - controls are now mode-aware (only parameters used by the current mode are shown),
  - ray overlay toggles are auto-hidden outside ray-relevant modes.

Why it changed:
- User feedback showed non-uniform/clumpy layer growth and confusing parameter visibility. This pass makes growth mathematically uniform and improves test UX by showing only active controls.

Validation run:
- `./.venv/Scripts/python.exe -m compileall cross_section_general_prototype.py`
- offscreen checks:
  - conformal growth at fine sampling (`arc_chord=2`, `thickness=20`, `step=1`) completed quickly (`~0.018 s`) and produced non-empty merged shells,
  - thin-shell case (`thickness=1`, `step=8`) produced non-empty conformal region,
  - directional mode scene + window init smoke passed (`prototype smoke ok`).

Next steps / known risks:
1. Conformal growth now ignores pass-step in geometry generation (uniform final shell); this is intentional for robustness but no longer represents explicit per-pass evolution.
2. Ray-based etch remains a geometric preview (first-hit + overlap mask), not a physical transport model.

## Update 2026-03-05 (Directional Etch Rework: Surface-Marked Normal Removal)
- Reworked directional etch in `cross_section_general_prototype.py` to remove the per-ray ripple artifact pattern:
  - old approach: each hit ray generated an individual slit/circle-like subtraction stroke,
  - new approach:
    1. cast rays and collect first-hit points on target material,
    2. map each hit to the nearest exposed surface edge,
    3. mark a local interval around the hit on that edge (footprint set by ray spacing and overlap),
    4. merge overlapping intervals per edge,
    5. etch by offset-stroking the merged marked-surface path (normal-removal style, matching deposition-style interface offset behavior).
- Added geometry helpers for robust interval marking:
  - point-to-segment projection
  - interval merge
  - segment interpolation (`lerp`)
- Kept `Ray Overlap (%)` as the smoothness/coverage control for directional mode:
  - higher overlap increases marked interval width and reduces unetched gaps.

Why it changed:
- User feedback: directional mode should not etch isolated circles per ray; rays should mark impacted surface regions and removal should follow the interface normal continuously.

Validation run:
- `./.venv/Scripts/python.exe -m compileall cross_section_general_prototype.py`
- offscreen directional checks:
  - engine-level anisotropic etch with `ray_count=64` produced non-empty merged mask and valid hit counts,
  - prototype mode build + window init smoke passed (`directional smoke ok`).

Next steps / known risks:
1. Hit-to-nearest-edge mapping is geometric (distance-based), so very tight corner cases may still need explicit topology adjacency for perfect material-boundary ownership.
2. Directional etch remains a geometric response model; no physics transport/depth-rate coupling yet.

## Update 2026-03-05 (Directional Etch Iteration: Adjacent-Ray Band Marking + Recast Loop)
- Replaced the previous directional marking strategy with an iterative adjacent-ray band approach:
  - per pass:
    1. cast rays on current geometry,
    2. find adjacent ray pairs that both hit the target material and are not blocked in between (pair adjacency),
    3. mark the full surface segment between those two hits (instead of tiny point circles),
    4. remove material via normal-offset stroke of the marked segment (etch opposite of deposition offset),
    5. recast rays on updated surface and repeat until target depth is reached.
- Added guardrails for efficiency:
  - explicit step control via `step_nm` in `etch_anisotropic(...)`,
  - adaptive pass cap (`max_passes=24`) to avoid runaway loops when very small step values are chosen.
- Updated mode wiring:
  - directional mode now uses `Etch Step` slider (`growth_step_nm`) in addition to depth/ray controls.

Why it changed:
- User requested marking of the whole region between adjacent open rays and iterative surface-following etch, not isolated per-ray imprint artifacts.

Validation run:
- `./.venv/Scripts/python.exe -m compileall cross_section_general_prototype.py`
- offscreen checks:
  - engine anisotropic etch (`depth=80nm`, `ray_count=64`, `step=4nm`) finished in ~2.0 s and produced non-empty etched geometry,
  - small-step run (`step=1nm`) remained efficient (~2.3 s) due pass capping,
  - full directional mode scene + window init smoke passed (`directional iterative smoke ok`).

Next steps / known risks:
1. Adjacent-pair marking still depends on ray density; very coarse ray counts can under-resolve steep local geometry.
2. The model is geometric-topological, not a transport solver; rate/selectivity physics are still placeholders.

## Update 2026-03-06 (Prototype Upgrade: Zoom/Inspect, Material Routing, Exact Ray-Interface Selection)
- Implemented interactive view controls in `cross_section_general_prototype.py`:
  - mouse-wheel zoom,
  - right-drag panning,
  - right-double-click or `Reset View` to return to fit view.
- Added grid visibility toggle:
  - new `Grid` button controls grid rendering on/off.
- Added interface inspection mode (special mode):
  - new `Inspect` button switches canvas to interface-only rendering,
  - clicking an interface segment highlights it and shows detailed info (loop id, edge index, owner material, length, midpoint, normal) in the info panel.
- Lowered default stress values for responsiveness:
  - reduced default directional depth/ray count and coarsened default arc chord.
- Reworked ray-hit model to fix normal mismatch / below-surface start:
  - replaced inside-sampling hit detection with exact ray-segment intersection on extracted exposed interfaces,
  - each ray hit now carries `loop_id`, `edge_index`, `edge_t`, and position along loop.
- Reworked directional selection logic for etch/deposition:
  - each ray marks a local interface segment at hit,
  - adjacent rays on the same interface mark the complete boundary segment between hits,
  - removal/growth is then applied only on these selected interface paths.
- Added directional growth process mode:
  - new mode `Directional Growth` with iterative recast loop and directional shell deposition.
- Expanded process/material controls in UI:
  - lists all used materials with checkboxes and per-material etch rates,
  - `Isotropic Undercut`: selected materials + per-material rate scaling,
  - `Conformal Growth`: selectable deposited material,
  - `Directional Growth`: selectable deposited material + selectable affected surface materials,
  - `Directional Etch`: selected materials + per-material rate scaling.
- Updated topology diagnostics clarity:
  - diagnostics mode now explicitly reports that it performs topology checks/boundary extraction/ray diagnostics without process mutation.

Why it changed:
- User requested robust interface-driven directional behavior, interactive detail inspection, and process-material configurability while keeping runtime efficient.

Validation run:
- `./.venv/Scripts/python.exe -m compileall cross_section_general_prototype.py`
- offscreen smokes:
  - all mode scene builds (`all modes build ok`),
  - window initialization/update (`window smoke ok`),
  - interface picking path (`inspect pick smoke ok`),
  - directional etch + directional growth performance probe (default-like settings) remained fast (~0.07 s / ~0.05 s in engine-only checks).

Next steps / known risks:
1. Same-interface linking uses extracted polygon loops from current geometry booleans; at very complex topology junctions, explicit topological adjacency graphs would be more reliable.
2. Per-material rate scaling currently uses relative depth scaling for prototype responsiveness; future integration should separate process time and physical rate units explicitly.

## Update 2026-03-06 (Prototype Fix: Pan Direction + Etch Time Semantics)
- Updated `cross_section_general_prototype.py`:
  - fixed vertical panning sign in `CrossSectionCanvas.mouseMoveEvent(...)` so mouse drag up/down now moves the view in the same up/down direction as left/right drag behavior.
  - completed/verified time-based etch/deposition control wiring in the UI + scene builder:
    - sliders use `Isotropic Time (min)` and `Directional Time (min)`,
    - per-material removal/deposition amount is computed as `rate_nm_min * time_min`.

Why it changed:
- User reported reversed vertical pan and requested process-time-driven etch control so different material etch rates are actually usable.

Validation run:
- `./.venv/Scripts/python.exe -m compileall cross_section_general_prototype.py`
- `./.venv/Scripts/python.exe -m compileall nanofab_manager.py nanofab_modular`
- model-level smoke (offscreen-independent) across all prototype modes with reduced load:
  - `Conformal Growth`, `Isotropic Undercut`, `Directional Growth`, `Directional Etch`, `Combined Stress Test`, `Topology Diagnostics` all built successfully.

Next steps / known risks:
1. Full offscreen `CrossSectionCardWindow` smoke can be slow/hang depending on mode defaults and Qt/path complexity; model-level scene-build smoke is currently the reliable fast validation path.
2. `Shadow` overlay remains a diagnostic process mask visualization (not a physical transport/shadowing solver field).

## Update 2026-03-06 (Input Model Backlog: Physical Process Controls)
- Captured additional process-input settings requested for later implementation (beyond the new unified base inputs `time_s`, `rate_nm_s_by_material`, `steps_per_s`):
  - angular distribution / beam divergence,
  - angle-dependent yield `f(theta)` for etch/deposition,
  - selectivity model (process- and material-pair dependent),
  - mask erosion rate,
  - redeposition probability,
  - temperature scaling factor,
  - stop-condition mode (`time`, `target_thickness`, endpoint),
  - sticking coefficient (deposition).

Why it changed:
- User requested these to be explicitly remembered for future solver/data-model restructuring.

Validation run:
- documentation update only (no code-path changes).

Next steps / known risks:
1. Integrate these as optional, mode-scoped parameters to avoid overloading the initial prototype UI.
2. Move from depth-per-pass style internals to a consistent time-integration solver so these controls have a clear physical insertion point.

## Update 2026-03-06 (Shared-Edge Inspect Topology)
- Updated `cross_section_general_prototype.py` inspect/topology model to expose shared edges between regions/materials:
  - added `TopologyEdge` representation (edge id, geometry, normal, primary/secondary material, shared flag, supporting materials),
  - added `extract_topology_edges(...)` in `GeometryTopologyEngine` to build inspectable edges from per-material boundaries and deduplicate opposite-side/shared edges,
  - `SceneSnapshot` now includes `topology_edges`.
- Reworked inspect mode rendering/selection:
  - inspect mode now shows topology edges (shared + exposed), not only exposed outer edges,
  - clicking an edge highlights that segment and highlights the full supporting material region(s),
  - selected-edge info text now reports material relationship and shared status:
    - `materials=...`,
    - `shared=yes/no`,
    - `relation=<mat_a><-><mat_b|void>`,
    - source loop/segment id, length, midpoint, and normal.
- Kept process/raycast behavior stable:
  - directional/isotropic process operations still use exposed-edge extraction for process evolution,
  - shared-edge topology is added primarily for inspect/debug visualization.

Why it changed:
- User requested transition from “connected/open interface feeling” to explicit shared-edge interpretation and inspect tooling that can show which regions a segment belongs to.

Validation run:
- `./.venv/Scripts/python.exe -m compileall cross_section_general_prototype.py`
- model smoke across all modes (reduced-load params):
  - verified non-empty `topology_edges` and shared-edge counts per mode.
- offscreen inspect smoke:
  - `CrossSectionCardWindow` create/refresh/select-edge/close path.

Next steps / known risks:
1. Shared-edge dedup currently uses geometric quantization; near-colinear mismatched segmentation can still produce split/duplicate inspect edges.
2. Full topological half-edge ownership (exact adjacency graph) is not yet implemented; current approach is robust for prototype inspection but still geometry-derived.

## Update 2026-03-06 (Time-Integrated Solver Refactor + Directional Corner Fix)
- Refactored prototype process inputs and internals to unified time-based controls:
  - `PrototypeParams` now uses:
    - `process_time_s`,
    - `steps_per_s`,
    - `rate_nm_s_by_material`.
  - Removed old mixed control path (`nm/pass`, separate minute-based etch/depo time sliders).
- Updated process interaction model to `nm/s`:
  - `ProcessInteractionModel.rate_nm_s_by_material`,
  - base placeholder rates converted from prior minute-scale values.
- Reworked operation engine to use a shared time-step integrator:
  - added `_iter_time_steps(time_s, steps_per_s)` using full steps + remainder,
  - `deposit_conformal(...)`, `etch_isotropic(...)`, `etch_anisotropic(...)`, and `deposit_directional(...)` now advance by `delta_nm = rate_nm_s * dt`.
- Fixed directional marking artifact around single-ray hits and corners:
  - local hit marking now stays on the hit edge (`_local_hit_span_on_edge`) instead of wrapping across loop corners,
  - directional etch/deposition masks now use round-cap/round-join stroking via `_band_from_marked_surface(...)` to avoid open-end wedges,
  - tightened adjacent-ray connection distance gating to reduce incorrect long-span bridging.
- Updated UI controls to match unified solver:
  - added `Process Time (s)` and `Steps Per Second`,
  - material rate spinboxes now use `nm/s`,
  - lowered default time/sampling values for faster initial responsiveness,
  - mode visibility updated to show only relevant controls under new model.
- Updated scene info text to display:
  - current time/sampling (`s @ Hz`),
  - per-material rates in `nm/s`.

Why it changed:
- User reported growth/etch artifacts at corners with single-ray local marking and requested the previously discussed full time-integrated solver architecture (`time_s`, `rate_nm_s`, `steps_per_s`) for all modes.

Validation run:
- `./.venv/Scripts/python.exe -m compileall cross_section_general_prototype.py`
- `./.venv/Scripts/python.exe -m compileall nanofab_manager.py nanofab_modular`
- model smoke across all modes (new params):
  - `Conformal Growth`, `Isotropic Undercut`, `Directional Growth`, `Directional Etch`, `Combined Stress Test`, `Topology Diagnostics` scene builds succeeded.
- targeted single-step directional scenario smoke (`1s`, `1 step/s`, low sampling chord/ray count) succeeded without runtime errors.

Next steps / known risks:
1. The solver is now time-integrated, but geometry updates still rely on `QPainterPath` booleans; pathological tiny-feature cases can still create sliver artifacts.
2. Full half-edge topology ownership and physically richer process factors (angular spread, yield models, redeposition, mask erosion, temperature coupling) remain future extensions.

## Update 2026-03-06 (One-Shot Span Solver for Conformal + Directional)
- Addressed severe runtime blow-up seen in conformal mode for larger `time_s * steps_per_s`:
  - root cause: repeated per-step boolean updates causing geometry fragmentation and superlinear cost growth.
- Reworked conformal and directional operations to one-shot span/band application while preserving unified inputs:
  - conformal deposition now computes total thickness once (`rate_nm_s * time_s`) and applies a single boundary band operation.
  - directional deposition/etch now:
    1. builds ray-selected boundary spans (`start/end` via local hit spans + adjacent-ray spans on same loop),
    2. assigns per-span incidence weight from ray direction vs interface normal,
    3. applies one-shot band generation with coarse weight binning (piecewise one-shot),
    4. performs collision-safe boolean composition (`band - occupied` for deposition, `target ∩ band` then subtract for etch).
- Added helper primitives for the new kernel:
  - `_total_delta_nm(...)`
  - `_directional_incidence_weight(...)`
  - `_directional_spans_from_adjacent_rays(...)`
  - `_directional_band_from_spans(...)`
- Kept unified user inputs unchanged:
  - `process_time_s`, `steps_per_s`, `rate_nm_s_by_material`.

Why it changed:
- User reported that conformal growth became much slower than earlier and requested a one-shot approach for selected interface parts, including shading/edge behavior handling.

Validation run:
- `./.venv/Scripts/python.exe -m compileall cross_section_general_prototype.py`
- performance probe:
  - conformal `time=4s`, `2Hz` reduced from multi-minute behavior to ~0.01 s scene-build level in current smoke.
- model smoke:
  - all modes scene build passed,
  - targeted directional single-step coarse-sampling scenarios executed without runtime errors and without tiny-sliver polygon artifacts in quick checks.

Next steps / known risks:
1. Span weighting currently uses a simple incidence term; angular spread and material-dependent yield are still placeholders for future physics fidelity.
2. Boundary-span extraction still depends on polygonized paths; exact half-edge topology ownership remains a future upgrade for maximal robustness.

## Update 2026-03-06 (Inspect Geometry Cleanup: Segment Merge, Shared Edge Handling, Selection Cycling)
- Improved boundary extraction quality to avoid unnecessary segment splitting:
  - added closed-loop collinear simplification in boundary point processing,
  - applied this simplification to exposed-boundary and topology-edge extraction.
- Updated normal direction handling for topology edges:
  - normal orientation is now determined by explicit material-side probes (`inside/outside`) per edge rather than relying only on polygon winding,
  - this stabilizes “outward” normals for selected material edges.
- Reworked shared-edge representation for inspect mode:
  - removed artificial global dedup that collapsed opposite shared sides into one edge,
  - topology extraction now keeps per-material edge ownership and marks `secondary_material_id`/`is_shared` from side probes.
- Added inspect click cycling for overlapping/shared edges:
  - repeated clicks at the same location now cycle through candidate edges under the cursor (e.g., both sides of a shared interface).
- Adjusted conformal one-shot growth surface selection to avoid domain-cut artifacts:
  - conformal deposition now uses exposed interface edges excluding domain clip boundaries (left/right/bottom extent edges),
  - this prevents spurious lower/side conformal loops from finite-domain clipping and reduced observed multi-loop artifacts in tested conformal case.

Why it changed:
- User reported excessive segment splitting in inspect view, incorrect shared-status labeling on straight segments, confusing normal direction display on selected edges, hard selection of overlapping shared segments, and undesired multi-loop conformal artifacts linked to finite substrate clipping.

Validation run:
- `./.venv/Scripts/python.exe -m compileall cross_section_general_prototype.py`
- all-mode model smoke passed.
- conformal performance smoke remained fast after cleanup (`4s @ 2Hz` stayed in millisecond-scale scene build in current tests).
- targeted check confirmed conformal metal path produced a single subpath in the tested scenario.

Next steps / known risks:
1. Segment simplification currently merges collinear polyline fragments; true arc reconstruction (line+arc primitive preservation through booleans) is still future work.
2. Finite simulation extent remains a numerical domain boundary; semi-infinite substrate behavior is approximated by boundary-edge filtering in conformal growth, not by an unbounded geometry kernel.

## Update 2026-03-06 (Directional Span Selection Fix + Adaptive Ray Refinement)
- Updated directional deposition/etch span construction to better follow loop edge sequences between ray hits:
  - adjacent-hit span path selection now uses a constrained loop traversal (`_loop_path_between_hits_constrained`) rather than relying only on shortest-path selection,
  - added strip-based path scoring so the chosen boundary path remains between the two ray origins instead of wrapping across unrelated loop parts.
- Added occlusion guard for adjacent-hit linking:
  - if the direct chord midpoint between adjacent hits lies inside solid union, span-connection is rejected (prevents wrong bridges across blocked corners/steps).
- Added adaptive ray refinement (2 passes in directional modes):
  - starts with user ray count,
  - inserts midpoint rays where adjacent rays indicate likely under-resolution (hit/no-hit transitions, material/loop/edge changes, strong normal changes, excessive hit separation),
  - all refined rays are used for process computation and returned for plotting.
- Kept conformal one-shot fast path and unified input model unchanged (`process_time_s`, `steps_per_s`, `rate_nm_s_by_material`).

Why it changed:
- User reported directional modes still selecting wrong between-hit regions and requested that actual segment lists be respected plus intelligent ray densification near difficult geometry transitions.

Validation run:
- `./.venv/Scripts/python.exe -m compileall cross_section_general_prototype.py`
- directional mode smokes with adaptive rays:
  - user ray count `12` refined to `24` rays in tested cases,
  - directional growth and etch scene builds completed with non-empty hit sets.
- all-mode build smoke passed with current defaults.

Next steps / known risks:
1. Boundary geometry is still polygonized after booleans; constrained span traversal is robust but cannot recover exact analytic arcs once flattened.
2. Adaptive refinement currently uses geometric heuristics; future work can include explicit error estimators tied to hit-angle and curvature fields.

## Update 2026-03-06 (Directional Segment-Gap Fix at Loop Vertices)
- Fixed directional span path traversal at exact loop vertices in `cross_section_general_prototype.py`:
  - updated `_loop_edge_index_at_position(...)` to use half-open edge intervals (`[start, end)`) instead of closed intervals.
  - this prevents selecting the previous edge when `s` lands exactly on a vertex, which had caused diagonal shortcut segments in `_loop_path_forward(...)`.
- Resulting behavior:
  - adjacent-ray span paths now stay on the true boundary sequence across corners/fillets,
  - directional deposition selection no longer drops corner segments due vertex-index ambiguity.

Why it changed:
- User reported that not all segments were selected and there were visible gaps between rays in directional growth.
- Root cause was geometric traversal ambiguity at cumulative-distance edge boundaries (vertex hits).

Validation run:
- `./.venv/Scripts/python.exe -m compileall cross_section_general_prototype.py`
- directional growth smoke (user test settings):
  - mode: `Directional Growth`
  - `ray_count=8`, `process_time_s=4`, defaults otherwise
  - result: `metal_loops 5` (expected), `rays 17`, `hits 17`, refinement passes `[0, 1, 2]`.
- targeted span trace check confirmed trench-corner spans now include intermediate corner points (no diagonal shortcuts).

Next steps / known risks:
1. Core geometry still relies on boolean operations over polygonized paths; tiny-feature robustness can still be affected by path simplification tolerance.
2. If needed, add a debug toggle to disable adaptive refinement at runtime for direct A/B inspection against base-ray behavior.

## Update 2026-03-09 (Directional Chain Selection Fix + Pass-Color Rays)
- Reworked directional growth/etch span selection in `cross_section_general_prototype.py`:
  - directional ray hits are now resolved against exposed surface chains extracted from the original region segment lists instead of the polygonized union loop,
  - exposed chains are split at hidden intervals so spans only follow truly continuous exposed surfaces,
  - between-hit selection now walks the actual ordered chain segments, including arcs/corners, instead of shortcutting across the union outline,
  - uncovered hits still fall back to local per-hit spans without any ray-overlap widening control.
- Updated directional ray rendering:
  - refinement passes now use a linear bright-red to dark-red ramp, so added rays are visually grouped by pass depth.

Why it changed:
- User reported that directional growth and etch still selected the wrong between-hit surfaces, left visible gaps, and should not rely on any overlap-style smoothing control to hide those errors.

Validation run:
- `./.venv/Scripts/python.exe -m compileall nanofab_manager.py nanofab_modular cross_section_general_prototype.py`
- directional growth smoke with requested settings:
  - mode: `Directional Growth`
  - `ray_count=8`, `process_time_s=4`, `ray_angle_deg=-19`, defaults otherwise
  - result: `metal_loops 5` (expected), `rays 21`, `hits 19`, refinement passes `[0, 1, 2]`
- offscreen render smoke for the same growth case confirmed continuous shell coverage across the exposed cap/trench surfaces.
- directional etch smoke with the same ray settings completed with non-empty etch mask output.

Next steps / known risks:
1. The directional solver now follows source-region segment chains for the pre-process geometry; if a future workflow needs repeated directional re-casts after arbitrary boolean-mutated geometry, those regenerated surfaces will still need a segment-aware reconstruction path.
2. Final deposited/etched solids still use `QPainterPath` boolean operations, so extremely tiny features can still be limited by polygonization tolerance.

## Update 2026-03-10 (Directional Outer-Surface Visibility Solver)
- Reworked directional growth/etch in `cross_section_general_prototype.py` around exact outer-surface segments:
  - directional visibility now evaluates the real line/arc outer loops from the prototype regions, not polygonized arc approximations,
  - deposition/etch selection is derived from front-facing segment incidence against the ray direction,
  - reverse visibility now traces back to the top source boundary and rejects segments whose source line exits through the side walls or is blocked by another outer segment,
  - diagnostic rays now stop only on front-facing exact segments and no longer use folded-away/back-facing hits.
- Adjusted directional band construction:
  - visible chain intervals are built from the exact segment chains,
  - chain continuity around corners is preserved by stroking the exact interval path with square caps instead of creating isolated local patches.

Why it changed:
- User identified two remaining major bugs:
  - rays could appear to penetrate the surface,
  - folded/shadowed segments were still sometimes selected.
- The goal was to make directional growth/etch depend on exact outer-surface geometry and segment normals, then verify stable metal-loop counts across multiple angle/ray-count cases.

Validation run:
- `./.venv/Scripts/python.exe -m compileall nanofab_manager.py nanofab_modular cross_section_general_prototype.py`
- directional growth checks:
  - `angle=-18`, `ray_count=8` -> `metal_loops 5`
  - `angle=-12`, `ray_count=12` -> `metal_loops 5`
  - `angle=-8`, `ray_count=24` -> `metal_loops 5`
- requested baseline still holds:
  - `angle=-19`, `ray_count=8`, `process_time_s=4` -> `metal_loops 5`
- directional etch smoke:
  - `angle=-12`, `ray_count=12` completed with non-empty shadow/etch output and no runtime errors.

Next steps / known risks:
1. The current directional visibility uses the prototype’s source-region outer loops as occluders; if later workflows depend on repeated re-casts after arbitrary boolean-mutated geometry, those occluders will also need a regenerated exact-segment representation.
2. The geometry mutation step still finishes through `QPainterPath` booleans, so sub-nanometer slivers can still be limited by Qt path simplification behavior.

## Update 2026-08-24 (Data-Model Review for Iterative Etch/Deposition — ADR-0001)
- Reviewed the cross-section prototype's data model against the requirement "isotropic/anisotropic etch + deposition, applied iteratively (remove a little, inspect, remove more) without artifact build-up".
- Wrote `docs/adr/0001-cross-section-model-for-iterative-process-steps.md` (first ADR in the repo) with 10 findings (F1-F10) and 9 decisions (D1-D9).
- Measurements were taken headless (PySide6 6.11.2, `QT_QPA_PLATFORM=offscreen`) against the prototype's own default scene (`cap_corner_radius_nm=18`, `trench_depth_nm=60`, `trench_radius_nm=40`, `arc_chord_nm=4.0`).

Key measured facts:
- Anisotropic etch **stalls after the first iteration**: `_extract_directional_surface_chains()` and `_extract_full_outer_surface_chains()` read `self.state.regions` (the frozen base loops), so process-created surfaces are invisible. Over 8 x 0.5 s the exposed-chain length stays at exactly 1305.1 nm and the core area stops changing after step 1 (46652.6 from i=1 to i=7). 1 x 4.0 s removes *more* material than 20 x 0.2 s (area 45930.7 vs 46713.5).
- Isotropic etch iterated 60 x 0.2 s: vertex count 58 -> 2602 (~+43/step), cumulative wall 0.00 s -> 85.29 s, per-step cost ~0.02 s -> ~3.7 s. At i=50 the core transiently splits into 8 subpaths (sliver artifacts) and is back to 2 at i=60.
- Conformal deposition 20 x 0.2 s: 3273 points / 54.16 s versus 275 points / 0.01 s for the equivalent single shot; area drifts -0.4 %.
- Post-boolean canonicalisation is the effective mitigation: with RDP eps=0.25 nm after each step, 40 iterations give 50 points and 0.15 s instead of 1704 points and 22.32 s (~150x faster, vertex count flat) — but naive RDP leaves ~+1.07 % more material, so an area-preserving decimation criterion is required, not plain RDP.
- Dead code confirmed: `_iter_time_steps`, `_directional_band_from_spans`, `_offset_band_from_segment_piece`, `_directional_spans_from_surface_rays`, `_local_hit_span_on_chain`, `_surface_chain_path_between_hits`, `_path_strip_score`, `_directional_incidence_weight` have no call sites (~250-300 lines). `steps_per_s` is threaded through the whole API and then discarded (`del steps_per_s`) — the prototype has no sub-stepping at all. `Region2D.tags`, `Region2D.props` and `CrossSectionState.operation_log` are never used. `scan_surface_rays()` traces are display-only; the physics runs on `_directional_band_from_surface_chains`.
- `_offset_band_from_chain_span` does `del outward` and strokes the surface curve symmetrically, so etch and deposition are the same geometric operation with different masking; `RoundJoin` rounds every convex corner by `delta_nm` per step, which compounds over iterations. Removal depth uses `avg_incidence` over a whole span, so trench bottom and sidewall get the same depth.
- `etch_isotropic(top_only=True)` uses a hard-coded cut plane `extent[1] + 0.42*(extent[3]-extent[1])` = -33.20 nm for the default extent.

Why it changed:
- User asked what has to be improved in the prototype's data model so etching/coating work well, and what has to be restructured so an iterative process is possible without large artifacts.

Validation run:
- `python -m compileall cross_section_general_prototype.py nanofab_modular` (PySide6 installed into the session container; `apt-get install libegl1 libgl1 libxkbcommon0 libdbus-1-3 libfontconfig1` was needed for offscreen QtGui).
- Three measurement scripts were run headless (iteration-count sweep, anisotropic stall trace, canonicalisation A/B). They live in the session scratchpad and were intentionally not committed.

Next steps / known risks:
1. Recommended implementation order is in the ADR's Consequences section; D5 (exposure from current state) is the single change that unblocks iteration, D3 (canonicalisation) is what bounds the artifacts.
2. ADR decision D2 accepts polyline-only geometry for now; analytic arcs stay lost through booleans until the hybrid provenance model (D2c) is built.
3. Take a `ui_backups/` snapshot per AGENTS.md §7 before starting the persistent-revision refactor (D1) — it changes public signatures inside the prototype.

## Update 2026-08-25 (Glossary: Process Character Terms — Isotropic/Anisotropic Corrected)
- Added a `### Process character` section to `CONTEXT.md` defining `Isotropic`, `Anisotropic`, `Conformal`, `Directional`, `Shadowing` and `Undercut`.
- The definitions correct an inversion: conformal deposition on all exposed surfaces (ALD) is **isotropic**, not anisotropic; a process that only reaches surfaces "open" towards a source and therefore casts shadows (evaporation, sputtering, RIE, IBE) is **anisotropic/directional**. `Conformal` is recorded as a property of the result, and as a consequence of isotropic arrival — so a conformal process is never an anisotropic one.
- `Anisotropic` is split into two causes that the model must keep apart because they respond to different inputs:
  - **flux anisotropy** — limited solid angle of arrival/removal, orientation- and occlusion-dependent, produces shadowing;
  - **crystallographic anisotropy** — the material responds differently along lattice directions independent of flux geometry (KOH on Si), governed by material properties rather than process geometry.
- Terms were grounded in the v1 code that already exists (`etch_isotropic` / `etch_anisotropic`, `deposit_conformal` / `deposit_directional`, `build_shadow_mask`, `MODE_ISOTROPIC = "Isotropic Undercut"`), so the glossary still describes the system as implemented, per `CONTEXT.md`'s own rule.

Why it changed:
- During the v2 data-model design interview the terms were used inverted for ALD and sputtering. Since the whole process model is organised on this axis, the glossary had to be settled before the representation decision.

Validation run:
- Documentation only; no code paths touched.

Next steps / known risks:
1. v2-only vocabulary (flux, angular distribution, redeposition, pinch-off, reachability) is deliberately **not** in the glossary yet — it gets added when the v2 decisions actually settle, per the file's "as currently implemented" rule.
2. The design interview for the v2 structure model is still open (representation, multi-material, time integration, 3D upgrade path); no plan has been written yet.

## Update 2026-08-25 (v2 Structure Model: Plan Written, ADR-0002..0004, Glossary v2 Terms)
- Concluded the three-round design interview for the v2 structure model and wrote the plan: `docs/plans/v2-structure-model.md` (goal/fidelity contract with four acceptance scenarios S1-S4, structure model, kernel, process contract, didactic process set, predicates, wafer materialization, persistence, packaging, testing, milestones M0-M5, risks).
- Recorded the hard-to-reverse decisions as short ADRs:
  - `docs/adr/0002-per-material-signed-distance-fields.md` — geometry = one signed-distance field per material on one shared Grid as the single stored truth; analytic primitives are constructors only; only the exposed union front advects, buried materials are maintained by pointwise min/max clipping. Rejected: B-Rep (v1 path), VOF (poor normals; directional yield f(theta) and crystallographic anisotropy need grad-phi), single phi + material index (re-exposed buried interfaces would return staircase-quantised — the lift-off case).
  - `docs/adr/0003-occurrence-identity-by-reconstruction.md` — Materialvorkommen is a derived view (connected components), lineage reconstructed by overlap matching, no stored occurrence IDs.
  - `docs/adr/0004-wafer-materialization-by-deterministic-replay.md` — wafer position is a property of materialization; lazy replay with cache keyed (recipe hash, position, step, code version); determinism invariant with (recipe, position, step)-seeded RNG.
- `CONTEXT.md`: retired the unsettled `Facet` entry (settled by ADR-0002: fields + derived occurrences, no geometric segmentation entity) and added a `### Structure model v2` section (Grid, Structure, Field, Occurrence, Capability, Materialization), explicitly marked implementation-pending.
- Consistency check before writing found one real gap and three mechanical rules, all resolved in the plan:
  1. the multi-material question had been announced for round 3 but never asked — resolved in ADR-0002 (per-material SDFs, single moving front, clipping) and validated numerically;
  2. material-scoped fields must be reset where their material changes, or dose from a first litho leaks into later resist (commit-gate rule);
  3. reinitialisation must be triggered by sub-step count/distortion, never by user step boundaries, or 3x10s and 1x30s diverge (commit normalises once per chain step, displacement reported);
  4. domain headroom + boundary guard replaces v1's magic 0.42 cut plane and boundary-edge filtering.
- Numerical mechanism probes (540x1200 grid, numpy 2.4.6/scipy 1.17.1): half-plane SDF exact on the grid; constructed materials overlap-free; conformal growth as one array op (20 offsets in 4.2 ms); offset dose-splitting exact (1x20 vs 4x5: max diff 0.0); deposit-region clip formula disjoint from old solid; ALD t=25 nm over a 40 nm re-entrant T-profile opening seals an enclosed void (empty space -> 2 components) while t=15 stays open, and a straight 40 nm gap fills completely with a seam instead of a void — physically correct emergent behavior, no special-casing.
- Interview decisions captured in the plan's inheritance table: complexity lives in processes not the structure model; 2D core with 3D-open data structures; hybrid material identity + fields; numpy/scipy accepted; no v1 compatibility (successor package, working name nanofab_v3) but revisions/artifacts/history/gating kept as concepts; geometry is truth + predicates for diagnosis; each process a standalone Structure->Structure function sharing kernel primitives; capability contracts with downgrade-only adapters; registry+entry points with monolith exe delivery and subprocess reserve; user-visible steps are chain steps, CFL sub-stepping internal.

Why it changed:
- User confirmed the remaining interview answers (Q4 derived occurrence view, Q5' lazy replay with cache, Q6 chain-steps-as-user-steps, Q7 N-D core with 2D flux/render seams) and asked for a final consistency check and the plan.

Validation run:
- Probe scripts executed headless in the session scratchpad (probe4/probe5); documentation-only changes to the repo, no code paths touched; `python -m compileall` not applicable.

Next steps / known risks:
1. Implementation starts at M0 (package skeleton + kernel invariant tests) per the plan's milestone order; v1 prototype stays untouched until M3's S1-S4 acceptance tests pass, then becomes a ui_backups snapshot per AGENTS.md §7.
2. Flux-solver budget (10-100 ms per rebuild, rebuild-every-K) is estimated, to be verified in M2 — fallback is the K knob and visibility-grid coarseness, not a redesign.
3. `NanoFab_Process_Manager_Documentation/04_Data_Model_Specification_Target.md` now lags the agreed v2 model (per CONTEXT.md's rule the docs catch up later); Layer becomes a derived stack summary, facets become Fields.

## Update 2026-08-25 (v2 Structure Model M0: `nanofab_v3` Skeleton, Kernel, pytest)
- Implemented milestone M0 of `docs/plans/v2-structure-model.md` §14: the new package `nanofab_v3` (working title, successor of `nanofab_modular`, no v1 compatibility) with the layout the plan asks for — `model/`, `kernel/`, `materials/`, `processes/`, `runtime/`, `io/`. `processes/`, `runtime/` and `io/` are docstring-only placeholders naming their milestone (M3/M4/M4); nothing speculative was built into them.
- `model/`:
  - `grid.py` — `Grid(origin, spacing, shape, axes)`, frozen, validated; the sole spatial authority. Cell `(i0,i1,...)` sits at `origin[a] + i_a*spacing`; axes are addressed by name (`axis_index`), never positionally. Helpers: `ndim/size/cell_measure`, `coordinates`, `mesh` (open mesh, what every constructor samples on), `position`, `extent`, `zeros/full/as_field`, `check_same_grid`.
  - `structure.py` — `Structure(grid, phi, fields)`: one float32 SDF per material plus named `Field`s, the single stored geometry truth. Frozen value object, mappings wrapped in `MappingProxyType`, every mutator (`with_material`, `without_material`, `with_field`, ...) returns a new revision. Derived views are `cached_property` and explicitly *not* truth: `solid_phi = min_m phi[m]`, `empty_phi = -solid_phi`, `solid_mask`, `material_index = argmin_m phi[m]` (`EMPTY = -1`).
  - `field.py` — `FieldKey(name, material|None)` (None = global field) and `FieldSpec(name, dtype, default, material_scoped, unit)`.
- `kernel/` (pure functions, no Qt anywhere):
  - `csg.py` — `union=min`, `intersection=max`, `difference(A,B)=max(phi_A,-phi_B)`, `complement`, `offset(phi,d)=phi-d`; N-D generic, float32, shape-checked.
  - `constructors.py` — `half_space`, `box`, `rounded_box`, `ball`, plus `add_material(structure, material, phi, carve=True)`. Analytic primitives are sampled onto the grid once and then forgotten (ADR-0002); nothing in the kernel consults them afterwards.
  - `contours.py` — own marching squares (~90 lines, no scikit-image) for rendering/debug per plan §10.
  - `invariants.py` — `pairwise_overlap`, `max_overlap_depth`, `gradient_magnitude`, `band_gradient_error`, `boundary_contact`.
- `tests/` — 59 pytest tests: the plan §13 layer-1 invariants (constructor exactness on planes, pairwise disjointness of constructed materials, symmetric scenes stay symmetric) plus unit coverage for `Grid`, `Structure`/fields, set operations, constructors and marching squares.

Why it changed:
- User asked to start implementing the agreed v2 plan at milestone M0. v1 (`cross_section_general_prototype.py`) was left completely untouched next to v2, per plan §14 / AGENTS.md §7.

Decisions taken where the plan left the detail open (recorded here rather than blocking):
1. **`pyproject.toml`, not `requirements.txt`.** Plan §11 wants development as a normal package (`pip install -e`, pytest), so one file carries both the dependency declaration (`numpy>=2.0`, `scipy>=1.13`; `dev` extra `pytest>=8`) and the pytest config. `pythonpath = ["."]` + `testpaths = ["tests"]` means `pytest` runs from a clean checkout without installing anything. `[tool.setuptools.packages.find] include = ["nanofab_v3*"]` keeps the v1 entry scripts out of the distribution. Package version `0.3.0.dev0` (successor of the v0.2.0 app line); the v1 `APP_VERSION` constants were not touched.
2. **`half_space` instead of the plan's 2D word "half-plane"** — the function is N-D generic (half-plane in 2D, half-space in 3D) and the plan's own rule is that no kernel code assumes a fixed dimensionality. `box` accepts `None` per side for unbounded, which is how slabs and stack constructors are expressed without a second primitive. `ball` (disk in 2D) was added beyond the task list: it is the particle/roughness primitive of plan §4.1 and it is what makes the symmetry and corner-rounding checks honest.
3. **Disjointness is produced by `add_material`**, which carves the new region against the union of the *other* materials (`max(phi_new, -union(others))`) — the construction-time analogue of the deposition clip in plan §3.2. Re-adding an existing material unions the primitives, which is how one material is built from several. `carve=False` exists for callers that established disjointness themselves, and a test asserts the overlap is real without it, so the invariant is demonstrated, not assumed.
4. **`FieldSpec` carries `default` and `material_scoped`** although M0 resets nothing: the mechanical scoping rule of plan §3.3 (reset where the owning material changed) is a commit-gate job in M1 and needs exactly these two facts. `Structure` already refuses a field scoped to a material it does not have, and `without_material` drops that material's scoped fields.
5. **Marching squares without a 16-case table**: the case analysis is generated from the four corner signs (segments run from an inside->outside to an outside->inside crossing along the counter-clockwise cell boundary), ambiguous saddles are resolved by the cell centre. That orientation puts `field < level` on the left, so an enclosed void runs opposite to the outer surface and a renderer can fill a ring correctly. Points are `(axis0, axis1)` in nm — the renderer decides what is drawn where — closed loops repeat their first point, contours leaving the domain stay open. The module is declared 2D-only (plan §4.3/Q7) and raises on a 3D grid instead of pretending to be generic.
6. **`invariants.py` lives in the kernel, not in the tests**, so M1's commit gate (plan §4.5) reuses the same functions the M0 tests assert on. They measure and report rather than assert: `boundary_contact` returns which domain faces the solid touches and states no policy, because "bottom is solid-continues, top/lateral is a failed step" is M1's decision.
7. Branch mechanics: this session's branch was fast-forwarded onto `8cb90db` (plan + ADR-0002..0004) before starting, since the specification lived on `claude/datenmodell-iteratives-aetzen-14976q`.

Validation run:
- `python -m pytest tests/` -> **59 passed** (0.3 s).
- `python -m compileall nanofab_v3 tests` -> clean.
- Manual check on the plan's reference grid (540x1200 at 1 nm = 0.65 M cells, numpy 2.4.6 / scipy 1.17.1), half-plane substrate at y = 120 nm:
  - max |phi| on the surface row = **0** and 0 nonzero cells on that row;
  - max |phi - analytic| over the whole field = **0** (not "small") — reproduces the ADR-0002 exactness claim;
  - band `| |grad phi| - 1 |` = **0.0**;
  - 2.59 MB per float32 field, matching the plan's 2.6 MB estimate;
  - marching squares over the solid union: 2 polylines / 2517 points in 21.5 ms.
- Corner rounding measured, since plan §15 lists it as an accepted cost: the contour of a 40x100 nm box is 277.657 nm against 280.0 nm analytic, a deficit of 2.343 nm = exactly `4*(2-sqrt(2))*spacing`, i.e. ~0.29 cell per corner at 1 nm/cell.
- The session container had no numpy/scipy/pytest; they were pip-installed there. No `.venv` was added to the repo.

Next steps / known risks:
1. M1 (motion) is next per plan §14: isotropic offset fast path, upwind advection with CFL sub-stepping, narrow-band reinitialisation, commit gate with the balance check. `kernel/invariants.py` is the seed of that gate; `csg.offset` is already the fast path and its dose-splitting exactness (`1x20` vs `4x5`, max diff 0.0) is a standing test.
2. AGENTS.md §4/§8 still name `compileall` as the validation command, while plan §13 asks for `compileall + pytest` now that tests exist. AGENTS.md §6 forbids editing that file without asking, so this is a **proposal awaiting the user's approval**, not a change.
3. `nanofab_v3/io/` shadows the stdlib `io` in name only — Python 3 absolute imports keep `import io` inside the package resolving to the stdlib. Deliberate (the plan names the directory), noted so it does not get "fixed" later.
4. Nothing in M0 moves a front yet, so the reinit-drift and balance-check risks of plan §15 are untested by construction; they arrive with M1.

## Update 2026-08-25 (v2 M1: Motion, Reinitialisation, Commit Gate, Occurrence Lineage)
- Implemented milestone M1 of `docs/plans/v2-structure-model.md` §14 in `nanofab_v3` (offset fast path, upwind advection + CFL, narrow-band reinit, commit gate with balance check) and extended `AGENTS.md` §4/§8 to `compileall + pytest` after the user approved the M0 proposal.
- New kernel modules:
  - `kernel/stencil.py` — one-sided differences and the Godunov upwind norm shared by motion and reinit, N-D generic.
  - `kernel/measures.py` — `enclosed_measure`, `solid_measure`, `front_integral`, `surface_normals` via smoothed Heaviside/Dirac.
  - `kernel/motion.py` — `offset_solid` (isotropic fast path), `advect_front` (CFL-sub-stepped upwind), `SurfaceRates`, `union_front`, `MotionOutcome`.
  - `kernel/reinit.py` — Russo-Smereka narrow-band reinitialisation with `ReinitPolicy` / `ReinitOutcome`.
  - `kernel/occurrences.py` — connected components per material and lineage by overlap matching (ADR-0003).
  - `kernel/gate.py` — `commit()`, `GateTolerances`, `CommitOutcome`.
- New model types: `model/occurrence.py` (`Occurrence`, `OccurrenceMap`, `LineageEntry`, `LineageReport`), `model/reports.py` (`ValidationReport`, `BalanceCheck`). `Structure` gained `nearest_material_index`.

Why it changed:
- User asked to continue after M0 and implement M1 fully per the plan.

Four representation problems the plan's formulas do not cover, found by measurement and fixed structurally (this is the substance of M1, more than the advection itself):
1. **Buried seams in the union field.** Where two materials touch exactly — the normal case, since constructors sample exactly on the grid — `phi_solid = min_m phi[m]` is exactly 0 *along their shared interface*, because each field is correctly zero on its own boundary there. Consequences measured: `front_integral` reported 429 nm instead of 330 nm of front on a substrate+mask scene (the seam counted as front), and an offset pushed the seam positive, punching a void along continuous material. Fixed three ways: `Structure.solid_mask` now uses `phi <= 0` (a strict `< 0` opens a one-cell crack that every connectivity query would read as a gap; `material_index` keeps the partition exclusive); `measures.solid_measure` sums per material instead of evaluating the union once; `motion.union_front` reinitialises the union when a seam is actually present, which works because `stencil.has_opposite_sign_neighbour` counts a cell at the zero level as inside, so only the real solid/empty interface is held fixed and the seam relaxes away.
2. **Reinit band defined by field value.** A field that needs renormalising is one whose values cannot be trusted to say how far the zero level is, so a `|phi| <= band` criterion excludes exactly the cells that are furthest off. The band is now geometric (dilation of the interface by `band/spacing` cells) **plus** every cell whose value merely claims to be near zero — the second criterion is what reaches a buried seam and a clip artifact, the first is what reaches a badly scaled field. With a value-only band a 2x-steepened circle got *worse* (band gradient error 1.0 -> 1.85); it now converges to 0.098.
3. **Anisotropic Russo-Smereka denominator.** The sub-cell distance was `h*phi0 / max(one-sided differences)`, which reports 0.707 for a 45-degree front and therefore mis-scales every diagonal interface by sqrt(2). Replaced by `phi0 / |grad(phi0)|` with the per-axis magnitudes combined as a Euclidean norm (`stencil.one_sided_gradient_magnitude`). Also: the domain faces now continue the field **linearly** rather than with zero gradient — a zero-gradient edge reports `|grad(phi)| < 1` for any front not parallel to it and made the reinitialisation invent a correction there (an exact tilted plane picked up an error of 0.10 at the boundary; it is now a fixed point to 0.0000).
4. **"Material at the front" cannot be read off the clipped fields.** In an undercut void the nearest solid is the *mask overhanging it*, but the clipped `phi_si` there equals the union distance and ties with `phi_mask`, so the mask's own exposed face was given silicon's etch rate: the undercut ran to 27 nm instead of 20 and the front ate into the mask. Now the owner of each cell is the owner of the nearest solid cell — `argmin_m phi[m]` inside the solid (constant during an etch, since cells only leave the solid) extended into empty space by a distance transform, refreshed every `_OWNER_REFRESH = 5` sub-steps. The mask now stays intact to the cell and the undercut lands at 18 nm.

Other decisions taken where the plan left detail open:
5. **The balance check warns, it does not fail.** A step that changes topology (pinch-off, a film splitting) genuinely breaks the front-integral estimate; the lineage report in the same pass is what explains it. Broken invariants, which no legitimate process produces, fail. Measured balance errors after the gate's reinit: plane etch 0.0 %, disk shrink 0.5 %, disk grow 0.9 %, masked etch 2.3 %, heavy step at the reference grid 0.95 % — the default tolerance is 5 %.
6. **Headroom guard defaults to the top face only.** Plan §3.1 says "lateral or top", but a cross-section continues sideways: every blanket layer touches `x-min`/`x-max` by construction, so failing on that would fail every realistic scene. Default is now every face except the max face of the first axis, configurable per commit, and any face a step *newly* touches is warned about regardless.
7. **The band gradient invariant is read at the 99th percentile, not the maximum.** At a concave crease — the union of two overlapping disks — a *correct* distance field is not differentiable, so the worst cell there never converges. Measured on that scene: max 0.43, p99 0.052. Constructor exactness tests still use the maximum.
8. **`FieldSpec` is passed to the gate, not stored in the `Structure`.** A spec is type information, like `MaterialType`, and the plan deliberately keeps `MaterialType` in a library rather than in the geometry. A field with no spec is reset to 0.0 and the report names it.
9. Occurrence lineage is implemented now rather than in M3 because plan §4.5 lists it as step 5 of the gate and ADR-0003 specifies it completely. Capability updates, the other half of that step, need the process contract of §5.3 and stay in M3.

Validation run:
- `python -m pytest tests/` -> **113 passed** (~8 s), of which 54 are new: `test_motion`, `test_reinit`, `test_gate`, `test_occurrences`, `test_performance`.
- `python -m compileall nanofab_v3 tests` -> clean.
- Dose splitting: offset `1x20` vs `4x5` max diff **0.0** (bit-exact, as the plan's probe measured); advection `1x12 s` vs `4x3 s` max diff below 0.05 cell; advection on a plane reproduces the offset **exactly** (max diff 0.0).
- **ADR-0001 F3 answered.** 60-step chain, 120x200 grid: first-ten median 17.9 ms, last-ten median 18.3 ms, **ratio 1.02**, total 1.10 s — against v1's ~0.02 s -> ~3.7 s (~200x) over the same 60 steps. State size is constant (same float32 array, same cells at step 60 as at step 1). At the reference grid (540x1200) a 20-step chain runs 0.74 s/step with ratio 1.00.
- Budget at the reference grid: a deliberately heavy step (60 nm etch = 120 CFL sub-steps, 4 mid-motion reinits) costs 6.0 s motion+gate, a typical 4 nm step 0.74 s, a conformal offset 0.11 s. Optimised down from 10.05 s by three changes: the ownership map is constant during an etch, the front integral and enclosed measure evaluate only the band instead of the domain, and the Godunov norm computes one upwind side when the front moves the same way everywhere.
- Reinit drift measured: 20 consecutive passes on a disk of radius 40 move the enclosed measure by 0.55 % in total, under 0.01 cell of normal displacement each; a planar front is an exact fixed point. The residual is curvature (the sub-cell distance is first order), not accumulation — reported per commit as `ValidationReport.reinit_displacement`.

Next steps / known risks:
1. M2 (flux) is next per plan §14: `FluxModel2D` reverse marching, evaporation/IBE/RIE/sputter, redeposition bounce. `advect_front` already takes a `flux` array as the per-cell multiplier the solver will produce, so the seam is wired.
2. Known sub-cell artifact, resolution-dependent by design: when the front crosses from material A into B, the switch happens within about one cell, so with a rate ratio of 5 the depth in B carries a few nm of error. Halving the spacing halves it; documented in `test_the_front_switches_rate_when_it_reaches_the_next_material`.
3. The heavy-step budget (6 s for 120 sub-steps at 1 nm) is above plan Q6's "low seconds" for the extreme case. The remaining cost is the upwind stencil over the whole domain; a true narrow-band solver would fix it and is not needed until M2 shows the flux rebuild dominates anyway.
4. `_OWNER_REFRESH = 5` and the reinit policy defaults are solver constants chosen by measurement, not derived; they are the knobs to check first if a later scenario behaves oddly near an overhang.

## Update 2026-08-25 (Plan Corrections from M0/M1 + M2 Handoff)
- Added `docs/plans/v2-structure-model.md` §17 "Corrections from implementation (M0/M1)" and pointed at it inline from the six affected statements (§3.1 headroom, §3.2 union/clip/field-invariants, §4.2 speed field, §4.5 balance check). The agreed design text is left as written; §17 amends it with the measurement that showed each problem.
- The seven corrections: (1) `min_m phi[m]` is not the union's distance function where materials touch, with the three consequences (`solid_mask <= 0`, measure summed per material, union repaired before advection); (2) the clip/deposit formulas are set operations whose values need the gate's repair, always taken from the start of the motion, and the reinit band cannot be value-defined; (3) `material_at_front` is the owner of the nearest solid cell, not a lookup in the material fields; (4) the band gradient invariant is a quantile, not a maximum; (5) the headroom guard is about the top face — lateral faces warn; (6) the balance check warns rather than fails, because S3 is itself a topology-changing step; (7) measured costs replacing the estimates in §4.2/§13.4 (a complete sub-step is ~50 ms, not the 3.6 ms of the stencil alone).
- No *decision* changed: per-material SDFs, one moving front, pointwise set operations and derived occurrences all held. What changed is a set of statements about what those objects give you — four of the seven are the same distinction, that a formula can be a correct set operation and a useless field at once.
- Wrote `docs/plans/m2-flux-handoff.md`: what M2 builds on, the exact shape of the seams already wired (`advect_front(flux=...)` as a per-cell multiplier that also enters the CFL bound and the balance check; `surface_normals`; `union_front` as the occupancy input), the one design decision M2 must make first (per-cell flux throughout vs. samples-then-scatter, with a recommendation), the five traps M1 hit that recur, the measured budget the flux rebuild is added to, and a suggested order.

Why it changed:
- User asked whether implementation had produced changes to the plan, and for an M2 handoff.

Validation run:
- Documentation only; `python -m pytest tests/` -> 113 passed and `python -m compileall nanofab_v3 tests` clean, unchanged from the M1 entry.
- One measurement taken while writing the handoff: plan §13.2's T-profile ALD mechanism runs today with `offset_solid` + `occurrences.label_region`. Over a 20 nm opening under an overhang, t=5 nm leaves the cavity open (1 empty-space component), t=15 nm seals an enclosed void (2 components), and t=25 nm closes the void *completely* — geometric deposition keeps growing inside a sealed cavity. Correct for M1, and precisely the gap M3's reachability gate fills; recorded in the handoff so it is not rediscovered as a bug.

Next steps / known risks:
1. §17 is an amendment written by the assistant from measurements, not an interview outcome — worth the user's read, particularly §17.6 (balance check warns) since it relaxes a check the plan called "the guard against silent numerical drift".
2. The M2 handoff recommends folding the angular yield into the flux array rather than into `SurfaceRates`, so `F = sign * rate(material) * flux` keeps two factors; if M2 decides otherwise the solver signature changes with it.

## Update 2026-08-25 (v2 M2: FluxModel2D, Reverse-Marching Visibility, Redeposition)
- Implemented milestone M2 of `docs/plans/v2-structure-model.md` §14 in `nanofab_v3`: `FluxModel2D` with reverse-marching visibility, the four angular distributions, angle-dependent yield, the surface-mobility kernel and the redeposition bounce, plus the T-profile ALD and shadow-wedge mechanism tests of plan §13.2 and the budget verification.
- New kernel module `kernel/flux.py` (~1000 lines, the **second** deliberately 2D-only seam next to `contours`, plan Q7 — it says so and raises on a 3D grid):
  - `AngularDistribution` — `Delta` (evaporation), `Lobe` (RIE/IBE), `CosinePower` (sputter), `Isotropic`, `Scaled`, `Mixture`. Every one is normalised so that `sum_k w_k cos(theta_k) = 1`, i.e. an unobstructed flat surface receives exactly 1. That single convention is what lets `SurfaceRates` keep meaning "nm/s on an open surface" while everything angular lives in the flux model.
  - `AngularYield` — `UnitYield` and a Yamamura-form `SputterYield` (`sec^f * exp(-sigma*(sec-1))`, peak at 60 degrees / 1.47x with the defaults). Folded into the arrival rather than into `SurfaceRates`, per the M2 handoff's recommendation, so plan §4.2's speed field keeps its two factors `F = sign * rate(material) * arrival(x)`.
  - Reverse marching by **sphere tracing**: a coarsened occupancy distance transform bounds each step, the fine union field decides the hit. Steps grow geometrically in open space (~15 iterations to cross 500 nm of headroom instead of 500).
  - `_smear_along_front` (surface mobility as a normalised convolution restricted to the front band) and `_bounce` (one isotropic redeposition bounce marched from the *receiver*, so occlusion is correct for free, with an optional per-cell `release` weight).
  - Technique factories: `evaporation`, `ion_beam_etch`, `reactive_ion_etch` (chemical fraction as a flux floor), `sputter_deposition`.
- `motion.advect_front` now accepts either a static flux array (M1 behaviour unchanged) or a `FrontFlux` model it re-evaluates every `_FLUX_REFRESH` sub-steps; `MotionOutcome` reports `flux_rebuilds`. Zero-speed cells are classified with the majority so a directional deposition keeps `godunov_norm`'s uniform-sign fast path in the cells its own shadow creates.
- Wrote `docs/plans/v2-structure-model.md` §18 (eight corrections from M2, in §17's form) with inline pointers from §3.2, §4.3, §4.5 and §15, and `docs/plans/m3-litho-handoff.md`.

Why it changed:
- User asked to continue the v2 plan at milestone M2 after M0/M1.

The design decision the handoff asked to be made first (§3), and how it was settled:
1. **Per-cell flux throughout, not samples-then-scatter.** The handoff recommended starting at (a) and adding sample refinement if the wedge was not accurate enough. It was accurate enough and the refinement was never needed: front cells are `|phi_solid| < spacing`, but each ray starts at the **sub-cell foot point** `x - n*phi(x)` rather than at the cell centre, which recovers exactly what the sample abstraction was wanted for. Measured wedge position within 0.8 nm of `h*tan(theta)` at 1 nm/cell for 15/30/45/60 degrees — and the 60-degree case casts a 69 nm shadow, so the error does not grow with the lever arm.
2. **The yield is folded into the arrival**, as recommended, so the solver signature is unchanged and `flux` means "arrival per unit front" rather than raw flux.

Five things the plan and the handoff got wrong, found by measurement (full write-up in plan §18):
1. **The hit test is where a visibility solver's accuracy lives, not the marching.** Reading the union field at the *nearest cell* makes a ray report itself blocked (a front cell is solid by definition). Displacing the ray origin along the normal biases the geometry by `spacing*tan(theta)`; blinding it for a cell of *travel* fails at glancing incidence (at 60 degrees the entire front came out dark); latching on *clearance* tunnels through a concave corner — a ray leaves the substrate straight into the mask, is never clear of anything, and emerges above it reported as lit. Reading the field **bilinearly** removes the problem instead of patching it. This one finding moved the ion-beam etch's spurious undercut under a 40 nm mask from 14 nm to 1 nm at `K = 5`.
2. **The visibility grid's coarseness is free.** Plan §4.3/§15 treat it as the first fidelity-for-speed fallback. It is not a trade at all, because the coarse grid only bounds how far a ray may *jump* while the hit test reads the fine field: the wedge position is identical at 1, 2 and 4 cells. There is a standing test for it.
3. **A velocity extension must be a collar.** Extended over the whole window, a cell ten cells under a hard mask keeps being handed the trench floor's etch rate and `phi` there climbs until it crosses zero — a 30 s ion-beam etch opened a row of disconnected voids under the mask. Beyond 12 cells the arrival is now zero and cells are frozen, which is what a narrow-band solver does.
4. **The band gradient invariant failed on every film thinner than 8 nm** — an M1 bug that had simply never been committed, and a 2 nm ALD film is the most ordinary object in this domain. A film's medial axis sits half its thickness in, so below twice the band it lies *inside* the band, and there a *correct* distance field has a local extremum: `|grad(phi)| = 0` however well it is normalised. `invariants.turning_points` now detects those cells and removes them and their neighbours (a central difference is contaminated a cell away from any non-differentiable point). Separately, a right-angled concave crease — every mask corner — reads exactly `1 - 1/sqrt(2) = 0.293` by arithmetic, so the gate's tolerance moved from 0.25 to 0.35. The check keeps its teeth: 2x-steepened circle 1.0, flattened 0.5, reinitialised 0.095, i.e. M1's numbers unchanged.
5. **A directional deposition left phantom material.** Where the front does not move, `max(solid_now, -solid_start)` collapses to `|solid_start|`: a zero level with no interior all along the shadowed surface. Measured, 1849 cells at exactly zero and ~600 nm^2 of metal never deposited. Clamping does not help (a V has a zero central derivative at its vertex whatever its floor); the *proxy* was wrong, so where nothing grew the field is now the distance transform of the region that did.

Other decisions taken where the plan left detail open:
6. **RIE's chemical fraction is a flux floor**, not a mixture component with its own visibility. A radical flux is scattering-dominated and effectively orientation-blind, and a floor keeps the arrival strictly positive, which keeps the solver's uniform-sign fast path. What it deliberately does not model is depletion deep in a feature; `Isotropic` exists as the honest (and much more expensive) alternative, and M3's reachability gate is what stops a sealed void being fed.
7. **The redeposition bounce is marched from the receiver**, so occlusion is correct for free — the first surface a ray reaches is by definition the one that can see it — and it reuses the same tracer instead of a pairwise form factor. Weighted by the didactic two-cosine factor, so the deposit can never exceed `redeposition_yield` times the strongest removal in sight.
8. **`release` is the seam where material knowledge enters the flux model.** The module knows only geometry, so without it a hard mask standing in an ion beam sprays material it is not losing. `None` means every site releases in proportion to what it receives, which is right for a single-material scene.
9. `_FLUX_REFRESH` shares `_OWNER_REFRESH = 5`, as the M2 handoff suggested — but only after (1). With the nearest-cell hit test it would have had to be 1 and a directional step would have cost three times an isotropic one.

Validation run:
- `python -m pytest tests/` -> **160 passed** (~5 s), of which 47 are new: `test_flux` (30) and `test_mechanisms` (11), plus 6 gate/invariant regressions.
- `python -m compileall nanofab_v3 tests` -> clean.
- **T-profile ALD (plan §13.2, the handoff's warm-up)**: over a 20 nm mouth widening into a 60 nm cavity, conformal growth seals an enclosed void at exactly `t = 10 nm = half the opening`, the sealed void keeps shrinking, and at `t = 20 nm` it has closed completely — correct for the M1/M2 kernel and precisely the gap M3's reachability gate fills. Asserted, with that behaviour written into the test's docstring.
- **Shadow wedge (plan §13.2)**: within 0.8 nm of `edge - h*tan(theta)` at 15/30/45/60 degrees, unresolved rays 0, and identical at a visibility spacing of 1, 2 and 4 cells.
- **End to end**: an ion beam through a 40 nm mask window leaves walls vertical to the cell with the mask intact; the same etch with a 30 % chemical fraction undercuts it — scenario S2's contrast in miniature.
- **Budget at the reference grid** (540x1200 at 1 nm), against plan §4.3's 10-100 ms estimate per rebuild: evaporation 25-34 ms, RIE/IBE 63-66 ms, sputter cos^1 104 ms, sputter+mobility 124 ms, IBE+redeposition 139-152 ms. Complete steps: isotropic 4 nm 0.53 s (the M1 baseline), directional 4 nm 0.57-0.60 s (**+8 to +13 %**, against the handoff's predicted 2-20 %), directional deposition 1.26 s, heavy 60 nm directional etch 5.73 s, commit gate 0.19 s. The heavy step is *below* M1's 6.0 s despite the flux, because windowing `band_gradient_error` took the gate from 0.31 s to 0.19 s. Balance errors 0.03-3.4 % against a 5 % tolerance, no gate failures.

Next steps / known risks:
1. M3 (litho + capabilities + predicates, DoD = S1-S4 acceptance tests) is next per plan §14; `docs/plans/m3-litho-handoff.md` has the seams, the one design decision to make first (where reachability gates a process), the traps, the budget and a suggested order.
2. `test_the_sealed_void_keeps_shrinking_and_finally_disappears` asserts behaviour that M3 must **change** — once ALD is reachability-gated the sealed void has to stop shrinking. Rewrite it, do not delete it: it is the smallest possible S3.
3. Rays that exhaust the 256-step march budget count as blocked, never as lit, and are reported as `FluxOutcome.unresolved`. A cos^1 sputter source at the reference grid reports ~1000 of 27000 — all near-grazing, whose `cos(theta_incidence)` is ~0, so their weight in the sum is ~0. Worth a look if a scene ever reports a large fraction.
4. Solver constants chosen by measurement, not derived, and the first knobs to check if a later scenario behaves oddly: `flux._EXTENSION_CELLS = 12`, `flux._TRUSTED_CELLS = 3`, `flux._MAX_MARCH_STEPS = 256`, `invariants._TURNING_SLOPE = 0.5`, `motion._FLUX_REFRESH = 5`.
5. A film **one cell** thick still fails the band gradient invariant (0.5). That is the resolution limit rather than a defect — a single-cell film cannot carry a distance field — but a process that deposits sub-nanometre layers at 1 nm/cell will hit it.

## Update 2026-08-25 (v2 M3: Capabilities, Predicates, the Resist Set, S1-S4 Green)
- Implemented milestone M3 of `docs/plans/v2-structure-model.md` §14 in `nanofab_v3`: `MaterialType` built out, capabilities + the `ProcessStep` contract + the registry, predicates, the resist set, and the four acceptance scenarios. **S1-S4 are green**, which plan §14 makes the definition of done for the whole v2 structure model, not just for M3.
- `materials/` — `MaterialType` with a rate table keyed on process class (`wet_etch`/`dry_etch`/`ion_beam`/`deposit`/`develop`/`dissolve`), `SputterResponse`, `DevelopModel.rate(dose)`, `DissolveModel`, optical/density data; `MaterialLibrary` and `didactic_library()` with six materials (silicon, oxide, resist, underlayer, metal, alumina).
- `kernel/predicates.py` (new) — `reachable_empty`/`reachable_surface`/`is_reachable`/`reachable_occurrences`, `ReachableFront` (the gate as a `motion.FrontFlux`), `supported`/`unsupported`, `enclosed_voids`, `undercut`, `step_coverage`, `film_thickness`, `cells_of`. N-D generic: **not** a third 2D seam next to `contours` and `flux`.
- `kernel/regions.py` (new) — `closed_region`, `signed_distance_of`, `remove_region`: the ideal tier's one-shot set operations.
- `kernel/motion.py` — `ProductFlux` / `gated()`, so a process can multiply a flux model by the reachability gate through the seam that already existed.
- `model/capability.py` + `model/quantity.py` (new); `kernel/gate.py` gained plan §4.5's **sixth** step, which closes the commit gate completely.
- `processes/` (new, was an empty placeholder) — `contract` (`ParamSpec`/`StepContext`/`StepResult`/`ProcessStep`/`FunctionStep`), `rates` (the materials-to-kernel seam), `substrate`, `lithography`, `deposition`, `etching`, `removal`, `registry` (with §5.2's determinism lint), `engine` (validate -> gate -> run -> commit). 18 registered steps.

Why it changed:
- User asked to continue the v2 plan at milestone M3 after M0/M1/M2, with S1-S4 as the definition of done.

The design decision the handoff asked to be made first (§3), and how it was settled:
1. **Reachability gates a process in both places, split along the ideal/physical fidelity axis** — as the handoff recommended. The ideal tier gates by **region**: `reachable_occurrences` picks the connected pieces a bath can touch and `remove_region` takes them out in one `csg` operation, per *occurrence* rather than per cell (a solvent that reaches one corner of a connected piece of resist dissolves the piece; cell-by-cell removal would stall at the first constriction and leave a plug no real bath leaves). The rate tier gates by **speed field**: `ReachableFront` is a `motion.FrontFlux` with `max_arrival` and `on_front`, so it goes through the seam the flux model already uses, and it must be rebuilt as the front moves because dissolving resist opens paths that were closed. The two are two *processes* at different fidelity (`develop.ideal`/`develop.rate`, `strip.dissolve`/`strip.rate`), exactly as plan §5.4 wants, and not a fork in the kernel.

Four things the plan and the handoff got wrong, found by measurement (full write-up in plan §19):
2. **A carved field is exactly zero on *other* materials' buried seams.** §17.1's union-field problem, reappearing in a per-material field. `add_material` carves against the union of the others (`max(phi_new, -phi_union)`), and `-phi_union` is zero along every interface between two of those. Measured on the S2 stack (silicon / 60 nm oxide / resist): `phi_resist` reads 0.0 along the buried silicon/oxide interface 60 nm below its own underside, **in every column**, so a `phi_m <= 0` test called the resist full-width and `undercut` returned zero for every etch, wet and directional alike. Fixed topologically (`regions.closed_region`: a zero counts only where it touches a strictly-inside cell) — the third disguise of §18.7's phantom. It only shows for an *unbounded* constructor, i.e. a planarising spin coat, which is why M0-M2 never hit it.
3. **Connectivity needs a third mask.** `inside` is strict, so the bath is two cells from the nearest resist cell it may see and an open T-profile reads unreachable; `material_index` is the exclusive partition and gives an interface cell to only one side. `predicates.cells_of` is the closed region, and two touching materials sharing their interface cell is *correct* here — both are present in it and both are wet.
4. **A material-selective removal has to name what it attacks.** Same interface cell, other side: dissolving the resist through a closed-region mask took **half a nanometre of silicon** with it along every shared cell. `remove_region(..., materials=(...))`; a connectivity-driven removal (lift-off's unsupported components) does not need it, because components are separated by empty space.
5. **S4 as written does not produce fences — it produces S3's failure.** On a straight resist wall the arrival grows monotonically with height (a point sees the sky through the opening, and higher means a wider window), so the film is thinnest at the *bottom*, exactly where a fence would attach. Measured on a 120 nm wall over a 60 nm window with a cos^1 source: 2,2,2,3,3,4,4,5,6,7,9,8,10 nm bottom to top — continuous in every combination of window width 50-80, resist 100-140, film 12-40 and mobility 0-25 that was tried. A continuous film seals the resist and nothing lifts. Fences need the **re-entrant profile a real lift-off resist has**, reached the way a cleanroom does it: a bilayer whose non-imaging underlayer clears wider than the imaging window. The overhang's underside faces down, receives exactly zero, and separates the cap from the cavity; the broad lobe still reaches the cavity walls. Measured over cavity 110-130 nm, film 20-30 nm, mobility 0-10 nm: fences 15-26 nm above the flat film, one occurrence, clean lift-off every time. Also: **the surface mobility is not what makes the fences** — the broad lobe is; on the straight-wall stack a mobility of 15 nm or more closes the mouth and breaks a lift-off that worked without it.

Other decisions taken where the plan left detail open:
6. **`materials/` imports nothing from `kernel/`.** `kernel.motion` takes `MaterialId` from there, so the reverse is a cycle. `SputterResponse` holds the two numbers `flux.SputterYield` needs rather than the object, and `processes/rates.py` is the seam that converts — which is also where `SurfaceRates` and the redeposition `release` map are built. Plan §5.4's "duplication lives in thin process wrappers, physics lives once in the kernel", applied to the import graph.
7. **The gate re-derives structural capabilities rather than trusting `provides`.** `material:<id>` and `<material>.<field>` are statements about the structure, so the gate reads them off it: dissolving the resist retracts `material:resist` and `resist.exposed` with no step remembering to. A step that *declares* a structural capability it did not deliver **fails** the gate, which catches a class of process bug that would otherwise surface three steps later as an unrunnable chain. Free-form promises pass through untouched. **The dot is reserved** for the field form (plan §5.3's own example is `resist.dose`), so a free-form name must not contain one.
8. **A deposition's rate belongs to the source, not to the surface.** Every deposition step uses `SurfaceRates(default=rate)` — one number, uniform over the front — because at this fidelity an arriving atom does not care what it lands on. Selectivity in deposition (nucleation delay, area-selective ALD) is a tier-(b) rate model and would be expressed by filling the rate table, not by changing the solver.
9. **ALD ships at two fidelities and the gated one is the default** (plan §5.4). `deposit.conformal_offset` is the exact geometric answer — one array operation, bit-exact dose splitting — and it keeps growing inside a cavity it has sealed; `deposit.ald` runs the same growth behind `ReachableFront` and stops. S3 is that difference.
10. **Crystallographic anisotropy is deliberately not built**, although plan §3.4 names it: no process in the didactic set of §6 consumes it, and a model nothing reads cannot be validated. It arrives with the first crystallographic process (KOH).
11. **Inspection steps, particles/clean and anneal are not registered.** Plan §14 puts them in M4/M5 (they need the artifact plumbing and the particle constructors); every row of §6 that S1-S4 need is there. `processes/engine.py` is a thin runner, not the append-only `Revision` chain of §3.6 — that stays M4.
12. **The reachability gate's collar is windowed.** §18.5's finding applies unchanged (extended over the whole domain, a cell ten cells deep in a wall gets the nearest front's value and starts moving), and so does the windowing: restricting the collar's distance transform to a box around the front took one rebuild from 48 ms to 20 ms at the reference grid. `collar_cells` is 12, the same number as `flux._EXTENSION_CELLS`, deliberately.

Validation run:
- `python -m pytest tests/` -> **249 passed** (~16 s), of which 89 are new: `test_materials` (14), `test_predicates` (20), `test_processes` (33), `test_scenarios` (18), plus 3 budget tests and the rewritten mechanism pair.
- `python -m compileall nanofab_v3 tests` -> clean.
- **S1 (naive lift-off)**: pattern width **101 nm** from a 100 nm design, one occurrence, centred to 1 nm, film thickness 19.0 nm from a 20 nm deposit; three metal pieces before dissolution and the resist still reachable; `material:resist` and `resist.exposed` retracted by the gate. Control (no lithography): the blanket resist under blanket metal is unreachable and nothing lifts.
- **S2 (undercut)**: at equal depth (30 nm), wet ratio **0.90**, ion beam **0.03**, RIE with a 0.25 chemical fraction **0.13**. `undercut.vertical` lands within 1 nm of the nominal depth in all three.
- **S3 (lift-off broken by ALD)**: 15 nm of gated ALD over S1's stack makes the resist unreachable, the solid one continuous piece, and the lift-off a no-op that says so in its log. At mechanism scale the sealed void is **frozen at 586 cells from t = 13 nm to t = 40 nm** (four times the dose that closes it geometrically), where `conformal_offset` runs 741 -> 525 -> 261 -> 0.
- **S4 (sputter fences)**: bilayer stack, cos^1 sputter, 25 nm: metal spans the full 120 nm cavity with rims **26 nm** above the flat film at both edges, one occurrence, underlayer reachable, lift-off clean. An evaporation on the identical stack leaves a flat 80 nm pattern, rims 0.
- **Budget at the reference grid** (540x1200 at 1 nm), against handoff §5: `label_region` 2.7 ms, `reachable_empty` 4.9 ms, `supported` 3.6 ms, `enclosed_voids` 11.5 ms, `undercut` 8.7 ms, `step_coverage` 8.9 ms, one gate rebuild 20 ms. Gating a directional process is free within the noise — a 4 nm RIE is **1.28 s gated and 1.28 s ungated**, because `_FLUX_REFRESH` rebuilds every factor of a `ProductFlux` on the same sub-steps — and a heavy 60 s ion-beam etch is 9.9 s against 9.0 s, **+10 %**. The ideal tier is cheaper than one advection: spin-coat + expose + develop **0.30 s**, lift-off **0.19 s**. A gated 4 nm ALD is 0.69 s where the ungated offset is 0.38 s: gating turns one array operation into an advection, and that is what buys S3.
- §17.7's conclusion is unchanged — the upwind stencil over the whole domain still dominates a heavy step, not the flux and not the gate.

Next steps / known risks:
1. **v1 (`cross_section_general_prototype.py`) is still untouched.** Plan §14 and AGENTS.md §7 say it becomes a `ui_backups/` snapshot once S1-S4 pass, which they now do. That is a deliberate, explicit step and is **waiting on the user's go-ahead**, not done as a side effect of the tests going green.
2. M4 (runtime) is next per plan §14: revisions, runs, persistence, replay + cache, UI integration. `processes/engine.py` already threads structure and capabilities from step to step and seeds the RNG from (recipe id, position, step index), so the determinism contract M4's replay depends on is wired and tested.
3. `dominant_yield` gives a whole scene **one** angular yield curve — the fastest-etched material's — because the arrival is computed per front cell before anything knows which material that cell belongs to. A scene etching two materials with very different yield curves side by side gets one curve. Per-material arrival would mean one visibility solve per material, which is the cost plan §4.3 is built to avoid; tier (b) is where that trade is worth revisiting.
4. `DissolveModel.swells` is recorded and deliberately not modelled. It is the physical reason a real lift-off works through cracks far too small for a reachability query, and it is why S4 needed a geometric mechanism rather than a mechanical one. Plan §16 keeps it open.
5. New solver constants chosen by measurement: `predicates._COLLAR_CELLS = 12` (shared with `flux._EXTENSION_CELLS` by intent). The gate's rebuild interval is `motion._FLUX_REFRESH`, which is why the sealed void loses a few cells between sealing and freezing — inside the cell the grid owes anyway, per §18.1's argument.
6. Ideal development and ideal exposure are cell-quantised by construction (plan §3.3 stores `exposed` as `int8`), so S1's pattern width carries one cell of error at 1 nm/cell. The dose tier does not have that limit; it is what tier (b) would use.

## Update 2026-08-25 (v1 and v0.2.0 Snapshotted to ui_backups/, Root Cleared to nanofab_v3)
- Took the step `docs/plans/v2-structure-model.md` §14 and `AGENTS.md` §7 both call for once M3's acceptance tests pass: v1 became a `ui_backups/` snapshot. Done deliberately and on the user's explicit go-ahead, not as a side effect of S1-S4 going green.
- `ui_backups/2026-08-25_v1.0.0_cross-section-prototype/` — `cross_section_general_prototype.py`, the prototype ADR-0001 was written against. One file; its only dependency is PySide6.
- `ui_backups/2026-08-25_v0.2.0_nanofab-manager/` — `nanofab_manager_v0_2_0.py` (renamed `nanofab_manager.py` per the v0.1.0 baseline pattern), `nanofab_modular/`, and the spec (renamed `nanofab_manager.spec`).
- Root deletions, both already preserved and md5-verified identical to the copies in `ui_backups/2026-03-05_v0.1.0_baseline/`: `nanofab_manager.py` (`APP_VERSION = "0.1.0"`, `328d49e7...` on both sides) and `nanofab_manager.spec` (byte-identical to that baseline's `app_pyside_modular.spec`).
- The root now holds `nanofab_v3/`, `tests/`, `docs/`, the markdown files and `ui_backups/` — one actively built code base.
- Docs pulled straight: plan §14 marked done with the snapshot paths; `README.md` rewritten around `nanofab_v3` with a "Where the application went" section; `nanofab_v3/__init__.py`'s docstring no longer claims v1 sits next to it.

Why it changed:
- Plan §14 and AGENTS.md §7 make the snapshot conditional on M3's acceptance tests, which passed the same day (249 tests, S1-S4 green). The user confirmed the step and specified the layout.

Which file was actually 0.2.0 — verified before moving anything:
1. `nanofab_manager.py` at root carried `APP_VERSION = "0.1.0"`, not 0.2.0, and was **byte-identical** to `ui_backups/2026-03-05_v0.1.0_baseline/nanofab_manager.py` (same md5). It was a duplicate of an already-archived baseline, so deleting it loses nothing and there is no remaining reason for it at the root.
2. `nanofab_manager_v0_2_0.py` carried `APP_VERSION = "0.2.0"` and is the version that went into the new snapshot.
3. Root `nanofab_modular/` was likewise byte-identical to the baseline's copy — the engine did not change between 0.1.0 and 0.2.0, all of 0.2.0's changes are in the UI file. It is duplicated into the v0.2.0 snapshot anyway so that snapshot stands on its own.

Decisions taken while doing it:
4. **The snapshot's `.spec` was repointed, not copied verbatim.** `nanofab_manager_v0_2_0.spec` names `Analysis(['nanofab_manager_v0_2_0.py'])`, which after the rename would be a build recipe naming a file that is not in the folder — AGENTS.md §7 asks for backups that are runnable and self-contained, and the v0.1.0 baseline solved the same problem the same way (its `app_pyside_modular.spec` already points at `nanofab_manager.py`). The `Analysis` entry now reads `nanofab_manager.py`; the exe name it produces is left as v0.2.0 built it (`nanofab_manager_v0_2_0`), because that is a real output identity and not an artifact of the rename.
5. **Each new snapshot got a short `README.md`** — what it is, how to run it, what replaced it, and which renames were made and why. Cheap, and it is what makes a folder self-describing years later.
6. **No `memory.md` snapshot inside the new folders**, deviating from AGENTS.md §7's list. The user asked for the v1 prototype "ohne weiteres Beiwerk", `memory.md` is now 110 KB and would be duplicated twice, and git history already carries its state at this commit. Recorded here as a decision rather than an omission.
7. **ADRs and the M2/M3 handoffs were left alone** although they say v1 "stays untouched": they are historical records of what was true when written, and the repo's own convention (plan §17/§18/§19) is that agreed text stays and corrections are added elsewhere. The forward-looking statements were updated instead — plan §14, README, package docstring.

Validation run:
- `python -m compileall nanofab_v3 tests` -> clean; `python -m pytest tests/` -> **249 passed**, unchanged by the move (nothing in `nanofab_v3` or `tests` referenced the moved files).
- `python -m compileall ui_backups/2026-08-25_v1.0.0_cross-section-prototype ui_backups/2026-08-25_v0.2.0_nanofab-manager` -> clean.
- **Snapshot self-containment checked, not assumed**: from inside `ui_backups/2026-08-25_v0.2.0_nanofab-manager/`, `from nanofab_modular import ProcessEngine, build_default_modules` imports and builds **8 step modules**; the entry file's only local import is `nanofab_modular`, which resolves there; its `APP_VERSION` parses as `0.2.0`. The prototype's imports are PySide6 plus stdlib only (`math`, `sys`, `dataclasses`, `typing`). PySide6 is not installed in this container, so the two UI files were checked by compile and import-graph rather than by launching a window.

Next steps / known risks:
1. **`AGENTS.md` is not yet updated** — §6 forbids editing it without asking. §1 (the version probe reads `nanofab_manager*.py`), §2 (the repository map lists the root app and `nanofab_modular`), §4 and §8 (the `compileall` invocation names both) and §7 (the snapshot content list) all still describe the old root. A proposed diff has been shown to the user and is **awaiting approval**; until then those five sections point at files that no longer exist at the root.
2. `NanoFab_Process_Manager_Documentation/` still describes the v1 application, and plan §12/§16 already record that the docs catch up later. Unchanged by this move.
3. Plan §10 still expects the `nanofab_manager` shell to carry over in M4. That is now a statement about reading it out of `ui_backups/2026-08-25_v0.2.0_nanofab-manager/` rather than off the root; the snapshot's README says so.

## Update 2026-08-25 (AGENTS.md Realigned to the Cleared Root + M4 Handoff)
- `AGENTS.md` updated after the user approved the proposed diff (§6 requires asking first; the diff was shown and approved in full, including the one line that goes beyond path corrections).
  - §1.4/§1.5 — the version probe read `nanofab_manager*.py` at the root, which no longer exists there. Now `nanofab_v3/__init__.py` for the structure model and `ui_backups/*/nanofab_manager.py` for a snapshotted application. The "ask which entry file is active" rule became gestureless with one code base and is replaced by "snapshots are read-only".
  - §2 — repository map rebuilt around `nanofab_v3`'s subpackages and the three snapshot folders.
  - §4/§8 — `compileall nanofab_manager.py nanofab_modular nanofab_v3 tests` -> `compileall nanofab_v3 tests`; §8's version check reads `nanofab_v3.__version__`.
  - §7 — the snapshot content list was written for the old root (`nanofab_modular/` by name). Generalised, plus two things this session learned: repoint a spec's paths at the snapshot's own filenames, and *verify* self-containment rather than assume it. The one addition beyond path correction, explicitly approved: **"Never edit a snapshot after taking it — it is a record, not a branch."**
- Wrote `docs/plans/m4-runtime-handoff.md` in the shape of the M2 and M3 handoffs: what M4 builds on, the seams already wired (`run_step`/`run_chain`/`StepOutcome`, `step_seed`, the completed commit gate, the rendering inputs), the one design decision to make first, the traps that recur, the measured budget, and a suggested order.

Why it changed:
- The root cleanup left five sections of AGENTS.md pointing at files that had moved; the user approved the correction. The M4 handoff was requested to close out the session.

The design decision the M4 handoff asks to be made first:
1. **Is a `Revision` a stored `Structure`, or a position in a replayable recipe?** Plan §3.6 lists `structure: Structure` as a field; plan §8 specifies lazy replay with a cache. Both are agreed text and they are not the same design, and the persistence granularity, the cache key, the cost of scrubbing a chain and whether a 60-step run fits in memory all hang off it. The handoff recommends "a Revision stores its Structure, and the *chain* is what is lazy" on the measured basis below.

Measurements taken while writing the handoff (reference grid 540x1200 at 1 nm):
2. **Persistence is a non-issue, by a factor nobody would have guessed.** One revision (2 materials + 1 field) is 5.83 MB raw and **0.04 MB compressed** — 137x, lossless, round-trip bit-identical. The reason is structural rather than lucky: a signed-distance field on a grid is piecewise linear, so a scene freshly ion-beam-etched for 30 s holds only **2964 distinct float32 values in 648 000 cells**. `savez_compressed` costs 22-28 ms, `np.load` 10 ms. A 20-step chain is ~116 MB in RAM and **~0.8 MB on disk**, which is what makes "keep a few resident, spill the rest, fault them back" the obvious shape.
3. **Revisions share no arrays at all.** Zero shared by identity between consecutive revisions of the S1 chain, *including* silicon between `substrate.select` and `resist.spin_coat`, where the content is bit-identical. The commit gate reinitialises every material on every commit and returns a fresh array. Making `reinit.reinitialise` return its input when the field did not move would collapse a chain's footprint by the fraction of materials a step does not touch — most of them, in a lithography chain — and would make `Structure`'s "arrays are shared cheaply between revisions" docstring true, which it currently is not. Recorded as M4's second, nearly free decision.
4. Rendering inputs measured for the same reason: `marching_squares` on the union 21 ms, `material_contours` 28 ms, `material_index` 15 ms, `label_occurrences` 54 ms. A full re-contour is one frame, so the thing to avoid is re-contouring on every mouse move, not contouring at all.
5. S1 end to end (6 steps at 241x301) is **0.53 s**, so a 20-step replay at the reference grid is roughly 10-20 s of solver plus 0.6 s of I/O — inside plan §8's "seconds to ~a minute" and background-job territory as docs §9.2 already requires.

Validation run:
- `python -m compileall nanofab_v3 tests` -> clean; `python -m pytest tests/` -> **249 passed**, unchanged (documentation and AGENTS.md only).
- `AGENTS.md` re-grepped after the edit: the only remaining `nanofab_manager`/`nanofab_modular` mentions are the two that deliberately point into `ui_backups/`.
- The persistence round-trip was verified rather than assumed: `np.array_equal` on every field after `savez_compressed` -> `np.load`.

Next steps / known risks:
1. M4 is next per plan §14. `docs/plans/m4-runtime-handoff.md` has the seams, the decision to make first, the traps, the budget and the order.
2. The array-sharing finding (3) is a change to `kernel/reinit.py` or `kernel/gate.py` — i.e. to code M0-M3's tests cover heavily. It is worth doing early in M4 while the chain footprint is still the thing being designed, and it needs the dose-splitting and balance tests to stay green.
3. `NanoFab_Process_Manager_Documentation/` still describes the v1 application. Plan §12/§16 already record that the docs catch up later; M4's UI work is the natural moment.

## Update 2026-08-26 (v2 M4: Revisions, Runs, Persistence, Replay+Cache, the UI)
- Implemented milestone M4 of `docs/plans/v2-structure-model.md` §14 in `nanofab_v3`, in the order `docs/plans/m4-runtime-handoff.md` §6 suggests: the array-sharing decision first, then `Revision` + chain, `io/`, `Run` + positions, replay + cache, and the UI last. **DoD met**: the save/load/replay round trip is bit-identical and asserted, and `python -m nanofab_v3.ui` runs S1 end to end interactively.
- `runtime/` (was an empty placeholder) — `revision` (`Revision` wrapping `StepOutcome`, `HistoryEntry`, `ArtifactRef`, `RevisionSummary`, the append-only `RevisionChain` with `rewind`, `MemoryRevisionStore`), `run` (`Recipe`/`RecipeStep`, `RadialProfile`/`LinearTilt`, `effective_params`, `positions_on_radius`), `replay` (`apply_step`, `run_recipe`, `materialize`, `Run`).
- `io/` (likewise) — `manifest` (dataclasses to JSON and back, blake2b content hash per array, recipe encoding including wafer-parameterised values), `exchange` (`save_structure`/`save_revision`/`save_chain` and their readers), `store` (`FileRevisionStore`, `ReplayCache` keyed per ADR-0004, whose per-position view is itself a `RevisionStore`).
- `ui/` (new) — `scene` (`SceneSnapshot` v2), `session` (`Session`: an interactive run, save/load, replay elsewhere), `canvas`, `panels`, `window`, `__main__`.
- `kernel/gate.py` + `kernel/reinit.py` changed: revisions now share the fields a step did not touch. `model/reports.py` gained `ValidationReport.shared_with_parent`.

Why it changed:
- User asked to continue the v2 plan at milestone M4 after M0-M3, following the M4 handoff.

The design decision the handoff asked to be made first (§3), and how it was settled:
1. **A `Revision` stores its `Structure`; the *chain* is the lazy element** — as the handoff recommended, and the recommendation survives its own numbers being wrong (see 4 below). Plan §3.6 lists `structure: Structure` and plan §8 specifies lazy replay; both are agreed text and they are not the same design. `RevisionChain` keeps the recently touched revisions resident, spills the rest through a `RevisionStore` and faults them back. What is *always* resident is a `RevisionSummary` — index, parent, step id, capabilities, ok — so a step list, a gating decision and a run log fault **zero** revisions, measured on a six-step chain at `resident=1`. Replay from the substrate stays the cache-miss fallback and the mechanism for a new position, which is what ADR-0004 needs it for.

Five things the plan or the handoff got wrong, found by measurement (full write-up in plan §20):
2. **The second, "nearly free" decision was not only a footprint matter — the redundant reinitialisation was moving material.** The gate renormalised every material on every commit, including untouched ones. A committed field is **not** a fixed point in general: reinitialising S1's developed resist again and again grows its enclosed measure by +0.16, +0.46, +0.79, +1.44, +2.74, +4.49 and +8.00 nm² over 1, 2, 3, 5, 10, 20 and 60 passes — monotone, never converging, cell count unchanged, band gradient error worsening 0.065 -> 0.245. A clean half-plane *is* a bit-exact fixed point, which is why it survived M0-M3. §4.5's balance check cannot see it: it charges the drift to whichever step did move something, so plan §15's risk row had a leak its own mitigation did not cover. `gate.commit` now keeps the parent's array for a material the step handed back unchanged (identity first, `np.array_equal` second at 0.011 ms against 3.8 ms for the reinit it replaces) and reports which on the revision. Measured: consecutive material/revision pairs sharing an object **0 -> 7 of 9** on S1, distinct `phi` arrays 12 -> 5, footprint 3.48 -> 1.45 MB; at the reference grid **31.19 -> 12.99 MB**.
3. **Sharing is a property of the step, and §17.2's clip is why.** A deposition grows the union, so `max(phi_m, phi_solid_new)` is the identity and every existing material comes through bit-identical. A removal grows the union's *distance*, so the clip raises `phi_m` where the opened region is now further from any solid than the understated value it carried: a 4 s etch that gives a mask a rate of **zero** still changes **1589 of its cells by up to 2.41 nm**. Hence `shared_with_parent` is reported rather than assumed.
4. **The handoff's 137x / 0.04 MB per revision is the best case, not the typical one.** `savez_compressed` compresses a signed-distance field because it is piecewise linear and takes few distinct values — a property of *SDFs*, and a `Field` is not one. Across one six-step chain at the reference grid: `substrate.select` 493x (0.005 MB), `spin_coat` 541x, `expose_dose` **62x** (dose has 9895 distinct values), `develop.ideal` 84x, `deposit.evaporate` **35x** (0.319 MB; the fresh metal `phi` has 21162). A synthetic `linspace` field takes the whole revision to **6x**. The *conclusion* holds and the design was not revisited — the heaviest real revision is 0.319 MB and 71 ms against 1.3 s for the cheapest step that makes one — but quoting 0.04 MB as "the size of a revision" is wrong by 8x.
5. **A blanket layer's outline is not a polygon.** Every substrate, spin coat and blanket film reaches the lateral faces by construction (§17.5's sentence again), so marching squares returns *open* polylines: measured at 300x240 nm, silicon is **one** open line from (40, 300) to (40, 0) and the resist **two**, at 40 and 130 nm. Closing each against its own ends gives a horizontal chord of zero area — the substrate and the resist did not appear in the picture at all, and only the metal, whose contour is genuinely closed, was drawn. `ui.scene.fillable_outlines` stitches the open pieces to **each other** counter-clockwise around the domain edge (the orientation marching squares already guarantees), inserting corners. After it the enclosed areas are 12 000 and 27 000 nm² against cell counts of 12 040 and 26 789.
6. **The handoff's first trap does not fire where it says, and does fire one step later.** `marching_squares` over `phi_m` does *not* draw a contour along a phantom zero level: it tests `field < level` strictly, and a phantom zero has no strictly-inside cell either side. On §19.2's own stack (silicon / 60 nm oxide / resist), where `phi_resist` reads exactly 0.0 in **all 301 columns** of the buried interface, the resist still contours as 2 loops of 600.0 nm. What *is* wrong is a **fill rule** of `phi_m <= 0`, which claims those 301 cells. So regions come from `material_index` (the exclusive partition) and outlines from the field. Contouring `regions.closed_region` instead is correct and cell-quantised — the metal's outline measures 687.2 nm against the field's 681.4 — so it is the fallback, not the default.

Other decisions taken where the plan left detail open:
7. **`runtime` declares the store protocols and `io` implements them**, so the dependency runs one way and the runtime knows nothing about files. `ReplayCache.for_position` returns something shaped as a `RevisionStore`, so a chain spills straight into the replay cache: what it drops for memory is exactly what a later replay of that position wants back, and it is one directory rather than two.
8. **`HistoryEntry.params` is the *resolved, validated* parameter set**, not what the recipe said: defaults filled, every `Quantity` unwrapped, every wafer-parameterised value already resolved for this position. That is what actually ran, so it is what a saved file and a replay have to reproduce — and a function over the wafer cannot be written into a per-revision manifest while its value can. The recipe file next to a saved session carries the *unresolved* one, so reopening and adding a position still works.
9. **npz members are named `a0`, `a1`, ...** and the manifest says which material or field each is. Encoding a material id into an archive member name would make the set of legal material ids a function of what a zip entry may be called.
10. **Content hashes are verified on load by default**, costing **2.3-2.5x** (7.5-34 ms against 3.0-15 ms). The cache faults structures into a *running* chain, so an unchecked corruption becomes a wrong answer rather than an error, and 34 ms against the 7.6 s solve it replaces is not a trade worth making.
11. **The cached prefix is walked forward and stops at the first miss.** A chain is sequential — step k needs the structure after k-1 — so a hit past a miss is a gap, not a shortcut. One cold `materialize` therefore costs exactly one cache read, not one per step.
12. **`ui.scene` and `ui.session` import no Qt at all**, asserted by a subprocess test that checks `PySide6` never reaches `sys.modules`. That is ADR-0001's finding made structural rather than conventional: anything that decides geometry, and everything that drives a run, is on the Qt-free side. `canvas` builds throwaway `QPainterPath`s and reads none of them back, and the hit test goes through `SceneSnapshot.material_at` (the index map) because two filled paths both claim their shared point and the answer would depend on paint order.
13. **`ui.scene` is the third deliberately 2D module and it says so**, raising on a grid that is not 2-D. Rendering is 2D by decision (plan Q7, §10); the handoff asks that the *kernel* not gain a third 2D seam by accident, so the 2D-ness went here. `kernel.predicates` stays N-D.
14. **A scene is built per revision change, not per frame**: 107.5 ms to build (69.3 of it `label_occurrences`, 41.7 marching squares) against **11.9 ms** to repaint from one at 900x600. Overlays are computed only for the kinds ticked.
15. **An interactive session grows a recipe and a chain together**, which is what lets a run built by hand at the wafer centre be replayed at the edge without anyone writing the recipe down (`Session.at_position`). `strict=False` there, so a step whose invariants broke still becomes a revision, marked, with the report on it — plan §4.5's "visible, never silent".
16. **Eviction without a store is deletion.** `RevisionChain` applied its residency LRU unconditionally, so a four-step run at the default residency of three silently dropped revision 0 and then reported a missing store. A chain without a store now holds everything and ignores `resident`.
17. **PySide6 is an optional extra** (`pip install -e .[ui]`), which is what keeps 12's structural rule checkable on a headless runner.

Validation run:
- `python -m pytest` -> **314 passed** (~90 s), of which 65 are new: `test_io` (11), `test_runtime` (25), `test_ui` (24), 3 in `test_gate`, 1 in `test_processes`, plus the tightened `test_reinit` fixed-point assertion.
- `python -m compileall nanofab_v3 tests` -> clean. Dose-splitting, balance and S1-S4 all still green after the gate change, which was the condition the handoff put on it.
- The handoff's explicit ask, **"replay at a new position == a fresh run at that position"**, is asserted twice: at the engine seam in `test_processes.py` next to the determinism test it extends, and at the runtime level in `test_runtime.py` with a recipe whose resist thickness is a `RadialProfile` (60 nm centre, 40 nm at 60 mm out) and a cache **warm with the centre's revisions** — the state that would make a position-blind key serve the wrong sample. The edge takes 0 hits from it, equals a fresh uncached run at the edge, and differs from the centre.
- Interactive session checked headless (`QT_QPA_PLATFORM=offscreen`, PySide6 6.11.2): the window builds, the demo runs S1's six steps, the revision list marks #3 and #5 with warnings, the run log carries the gate verbatim ("resist #1 split into #1, #2", "balance: expected 6073.68, measured 6026.43 (0.78% off)", "capability 'material:resist' is no longer backed by the structure"), and the canvas renders both of plan §10's paths. The picture shows S1's mechanism: metal on the resist and metal in the window, **sidewalls bare**, and after lift-off one pattern.
- **Budget at the reference grid** (540x1200 at 1 nm; the recipe runs at 541x1201), against handoff §5: save one real revision 14-71 ms, load it back 7.5-34 ms verified, one revision on disk 0.005-0.319 MB, a six-step chain on disk **0.50 MB**, S1 solved **7.6 s** against **0.11 s** replayed from a warm cache (**68x**), faulting one revision into a chain 43 ms, save/load a six-step session 200/102 ms. §17.7's conclusion is unchanged through four milestones: the upwind stencil over the whole domain still dominates.

Next steps / known risks:
1. M5 per plan §14: entry-point plugins, PyInstaller monolith, particles/clean, anneal, the wafer materialization UI. The position fan's **engine** exists now (`Run` over an extensible position set, `positions_on_radius`, a cache keyed per position), so M5's share of it is the view.
2. **Inspection steps, particles/clean and anneal are still unregistered** (M3's note 11 carried forward). The artifact plumbing they were waiting on now exists — `ArtifactRef` on the revision, `StepResult.artifacts` — but nothing produces one yet, so `Revision.artifacts` is exercised only by a round-trip test.
3. **`StepResult.artifacts` is not carried onto the revision.** `apply_step` takes `artifacts` as an argument and no step supplies any, so the wiring from a step's own output to `Revision.artifacts` is a one-line change waiting for the first step that produces one; doing it before then would be untested plumbing.
4. `RevisionChain.rewind` truncates but does not delete what was spilled: a store keeps the files for indices past the new head, and re-running to the same index overwrites them. Correct as long as indices are reused in order, which is the only way a chain grows; a store shared between two chains of the same recipe and position would not be, and nothing does that yet.
5. `Session.save` writes every revision including the spilled ones (faulting each back at ~43 ms). At six steps that is the 200 ms measured; at sixty it is ~2 s, which is a progress bar rather than a redesign.
6. The recipe encoding knows `RadialProfile` and `LinearTilt` and **raises** on any other `WaferParameter` rather than writing its resolved value at some arbitrary position — the failure that would look like it worked. A plugin's own interpolant therefore cannot be saved until the encoding is opened up, which is an M5 plugin-boundary question.
7. `didactic_library()`'s resist (#e8b84b) and metal (#d9a441) are close enough that the two are hard to tell apart in the cross-section; the outline pen carries the distinction. Left alone deliberately — display colour is `MaterialType` data, not a rendering decision (plan §10), so changing it is a library change.

## Update 2026-08-26 (AGENTS.md Realigned to M4 + M5 Handoff + Start Prompt)
- `AGENTS.md` §2 updated after the user approved the proposed diff (§6 requires asking first; the diff was shown and approved). The repository map still said "`nanofab_v3/runtime/`, `nanofab_v3/io/` — placeholders, milestone M4", which they have not been since this morning. Now three lines: `runtime/` (revisions, runs, wafer positions, replay + cache), `io/` (the `.npz` + JSON exchange format, revision stores, replay cache) and `ui/` (SceneSnapshot v2, the interactive Session, the Qt shell, with `python -m nanofab_v3.ui` and the `[ui]` extra named). The same line's "§17-§19 amend the agreed text" became "§17-§20", which is a factual correction inside the section being edited.
- Wrote `docs/plans/m5-delivery-handoff.md` in the shape of the M2, M3 and M4 handoffs: what M5 builds on, the seams already wired, the one design decision to make first, the traps that recur, the measured budget, and a suggested order.
- Wrote `docs/plans/m5-start-prompt.md` — the prompt to paste into the next session, plus the container setup that is otherwise rediscovered by hand.

Why it changed:
- M4 left one section of AGENTS.md describing files that had changed status; the user approved the correction. The handoff and the start prompt were requested to close out the session.

The design decision the M5 handoff asks to be made first:
1. **What is the "code version" in the cache key, once a plugin can change the answer?** ADR-0004 keys every cached revision on (recipe hash, position, step index, code version) and M4 implemented `code_version()` as `nanofab_v3.__version__`, writing down that bumping it is "the intended and only mechanism". That is honest while the only code that can change is this package's, and stops being honest the moment a plugin ships a step: a third-party `deposit.mocvd` can change its rate model without `__version__` moving, and every revision cached with the old one is then served as current. Nothing errors — the numbers are quietly from the previous version. The same hole is already open without plugins: editing a builtin's wrapper during development does not move `__version__` either.
2. **Recommendation, two axes**: `code_version()` stays `__version__` and stays coarse (kernel, numpy/scipy, interpreter — the axis ADR-0004's cross-machine-drift paragraph is about); `RecipeStep.fingerprint()` gains the registered step's *implementation digest* (step id, fidelity, parameter schema, capability contract, `inspect.getsource` of its own wrapper), so editing a step invalidates exactly the recipes that use it and editing an unused plugin invalidates nothing. **Measured: 3.0 ms per step, 53 ms for all 18**, memoisable per step object.
3. The limit is stated in the handoff rather than left to be discovered: the digest covers the step's **wrapper**, not the kernel it calls. `deposit.evaporate`'s `run_function` is 16 lines, so a change in `kernel/flux.py` does not move it. Wrapper is what a plugin owns, kernel is what `__version__` owns — a division that only works if both are maintained. A frozen build has no source for `inspect.getsource` at all, the same caveat `registry._uses_global_rng` already carries.

Two things the handoff records about the state M5 starts from, because neither is obvious from the code:
4. **Plan §11's "registry + entry points from day 1" is half true.** The registry exists and every builtin goes through `register()` — which already refuses a duplicate `step_id` and lints for a process-global RNG — but nothing reads `importlib.metadata.entry_points`; `builtin_registry()` is a hard-coded list. Deliberate (a seam exercised by every test beats a discovery mechanism designed against nothing) and it is M5's.
5. **The wafer materialization engine is done and only the view is missing.** `Run` covers an extensible position set, materializes on first access and caches per position; `positions_on_radius` and `Run.structures()` are there. Nine positions of a 20-step recipe is ~4 minutes of solver against 1 second of I/O, so the fan is a background-job problem rather than a rendering one, and its second look at a position must hit the cache (68x) — which means the fan and the cache share a directory.

Validation run:
- `python -m pytest` -> **314 passed**, `python -m compileall nanofab_v3 tests` -> clean. Documentation-only change to the code base; the measurement in 2 above was taken against `builtin_registry()` as it stands.

## Update 2026-08-26 (v2 M5: Plugins, Packaging, the Last Processes, the Wafer View)
- Implemented milestone M5 of `docs/plans/v2-structure-model.md` §14 in `nanofab_v3`, in the order `docs/plans/m5-delivery-handoff.md` §6 suggests: the cache-key decision first, then particles/clean, inspection, anneal, entry-point plugins, the wafer view, and PyInstaller last. **DoD met**: `./dist/nanofab_v3 --selftest` reports **7 of 7 scenarios passed** in 6.9 s and exits 0, on a 115 MB single-file build with the builtins and numpy/scipy frozen in.
- `processes/` gained six registered steps and two modules — `contamination` (`particle.seed`, `clean.particles`), `inspection` (`inspect.sem`, `inspect.profilometer`, `inspect.ellipsometer`), `anneal` (`anneal.thermal`) — plus `plugins` (entry-point discovery, `DiscoveryReport`, `application_registry`) and `registry.implementation_digest`. 18 steps -> 24.
- `model/artifact.py` is new: `ArtifactRef` moved down from `runtime.revision` (a `processes` module may not import `runtime`), joined by the `ArtifactSink` protocol and `MemoryArtifactSink`. `io.DirectoryArtifactSink` writes them.
- `ui/` gained `wafer` (Qt-free job runner over `Run`'s positions) and `wafer_view` (the Qt map). `nanofab_v3/acceptance.py` and `nanofab_v3/cli.py` are new at the package root, with `nanofab_v3/__main__.py` and `nanofab_v3.spec`. `examples/nanofab-plugin-example/` is a separate package, not part of the distribution.
- `materials/library.py` gained `particle` and `resist_hardbaked`. 6 materials -> 8.

Why it changed:
- User asked to continue the v2 plan at milestone M5 after M0-M4, following the M5 handoff.

The design decision the handoff asked to be made first (§3), and how it was settled:
1. **The cache key has two axes, and the per-step one goes in the *recipe* hash** — as recommended. `code_version()` stays `nanofab_v3.__version__` and stays coarse: it covers what a recipe cannot name (kernel, numpy/scipy, interpreter) and is the axis ADR-0004's cross-machine-drift paragraph is about. `registry.implementation_digest(step)` digests the step's id, fidelity, parameter schema, capability contract and the source of its own wrapper, and enters through `RecipeStep.fingerprint(digest)` / `Recipe.fingerprint(digests)` / `recipe_hash(recipe, registry=...)`. So editing a step retires exactly the recipes that use it, and editing an unused plugin retires nothing. **Measured: 3.6 ms per step cold (64-69 ms for all 18; the first `inspect.getsource` on a module pays for `linecache`), 0.00015 ms memoised** — a six-step recipe pays ~21 ms once, which is what makes it affordable for a wafer fan that hashes once per position. `io.replay_cache_for(dir, recipe, registry=...)` is the one call a cache site makes, so "which hash does this cache go under" is answered in one place.
2. **The limit is in the docstring because it is not obvious: the digest covers the step's *wrapper*, not the kernel it calls.** `deposit.evaporate`'s `run_function` is 16 lines around `kernel.flux`; a change in `kernel/flux.py` does not move it. Wrapper is what a plugin owns, kernel is what `__version__` owns.
3. **A source-less build falls back to the contract alone and says so** (`nosrc:` instead of `src:`). Confirmed on the exe, which reports `step digests: contract only (no source)` — so a frozen build and a source install never trade cache entries under a key claiming they are the same code.

Findings, all with the measurement that showed them (full write-up in plan §21):
4. **The artifact wire was not the "one-line change" the handoff called it, and both obstacles were boundaries.** `ArtifactRef` lived in `runtime.revision` and `processes` may not import `runtime`, so it moved to `model/artifact.py` (where docs §4.2.2 puts the concept) with a re-export. And **a pure step cannot open a file**: §5.2 makes a step a pure function, and an artifact is a *file*. So `StepContext.artifacts` is an `ArtifactSink`. The invariant survives because what §5.2 makes pure is the step's *outcome* — structure, capabilities, measurements — and an artifact is a record of a run, the same category as `HistoryEntry.started_at`, which replay has never reproduced either. A step with no sink emits no ref and still measures everything: a ref to a file nobody wrote is worse than none.
5. **An empty registry is falsy, and `or` silently replaced it.** `ProcessRegistry` and `MaterialLibrary` both define `__len__`, so `registry or builtin_registry()` swapped a caller's deliberate choice for the defaults without a word — in `Run`, `run_recipe`, `materialize`, `ui.Session` and `acceptance.run_all`. `processes.engine.run_step` had it right since M3 (`is None`), which is why nothing caught it: the one place a test passes a deliberate library is the one place the idiom was correct. Every site now tests `is None`; a `Run` with an empty registry raises `KeyError` and is asserted to. **Rule, not just a fix: a container with `__len__` may not be used as a truth value for "was one supplied".**
6. **Two of the handoff's six traps did not fire.** Trap 2 (a correct set operation that is a useless field) was **avoided by construction**: `particle.seed` draws only the lateral coordinate and reads the height off the sample, so a particle always rests on the surface and never lands inside solid. Trap 5 (tolerances tuned on smooth scenes) **did not fire at all** — measured on an 8 nm disk at 1 nm/cell, the gate's reinitialisation moves the interface **0.0002 nm** (0.045 nm^2 of measure) and a 10 nm conformal film over four particles balances **2.50% off against a 5% tolerance**. Nothing was loosened for S5.
7. **The handoff predicted M5's findings would come from the exe. Half right.** The exe produced two (§21.1's `nosrc:` fallback, §21.6's plugin boundary) and both were already written down as *expectations* rather than discovered. What actually went wrong was ordinary Python (5 above) and a layering assumption in the handoff itself (4 above).

Other decisions taken where the plan left detail open:
8. **An annealed material's new rates live in the library as a second entry.** `StepContext.library` is passed in and never stored (§3.4), so an anneal cannot hand back a modified one — and does not need to: an anneal that changes how a material behaves has turned it into a *different* material. `resist` becomes `resist_hardbaked`, same `phi` array, new `MaterialType`, and every rate downstream follows. The capabilities swap mechanically (`material:resist` retires, `material:resist_hardbaked` appears, `resist.exposed` goes with the old material — right, because a latent image in a hard-baked resist is not a latent image). The mechanism lands at the **rate** tier: acetone takes an unbaked 60 nm resist to zero measure in 3 s and leaves a hard-baked one whole, because `dissolve_rates` gives zero to a material with no `DissolveModel`. The *ideal* tier consults no chemistry — it removes whatever material the recipe names, which is §19.4's rule and is coherent, and a recipe that keeps saying `lift_off(material="resist")` after a bake is a silent no-op, which is the realistic mistake.
9. **A column with no solid gets no particle.** The model has no floor below the domain and inventing one would be inventing geometry. The step reports how many draws it skipped. Does not arise on a `substrate.select` cross-section (every column carries solid, §17.5), but a through-etched trench would.
10. **An entry point may be a `ProcessStep` or a callable taking the registry** — one step with no boilerplate, or a package registering several. `isinstance(obj, ProcessStep)` tells them apart unambiguously because the protocol is `runtime_checkable` and a plain function has no `step_id`.
11. **Discovery reports and never raises.** A plugin that fails to import, is the wrong shape, or collides with a builtin is recorded in a `DiscoveryReport` and skipped, and everything else still loads. The failure avoided is one stale third-party package leaving a delivered application with an empty step list and a traceback where the process list should be.
12. **`builtin_registry()` stays a fixed set and does no discovery; `application_registry()` is what the app takes.** Recipe hashes and digests are computed against a registry, so a *test* whose registry depended on what happened to be installed would answer differently on every machine. The self-test uses the builtins for the same reason: a plugin that failed to load must not be able to turn S1 red.
13. **A frozen build is a closed plugin set, measured.** §11's "frozen app extension = rebuild" is literally true: the exe reads the entry-point metadata frozen into it, and a plugin installed for the *host* Python — even on `PYTHONPATH` — is invisible. The exe reports `plugins: none found` where the same command from source reports the example plugin's two. Recorded because "I installed the plugin and the exe cannot see it" is otherwise a bug report.
14. **The wafer fan polls rather than emits.** The runner works on a worker thread and the widget reads `snapshot()` on a 200 ms timer — one lock-guarded dict rather than a signal per event. That buys the thing the view needs: **partial results are the normal state, not an error path**, so pending/running/done/failed are four values of one field and there is no "loading" mode to get out of. It also keeps Qt out of `ui.wafer`, which now joins `ui.scene` and `ui.session` in the subprocess assertion — a wafer fan *drives runs*.
15. **Cancel stops between positions, never between steps.** A chain abandoned mid-step would still have written its earlier revisions to the cache and would come back as complete on the next look.
16. **`default_cache_dir()` lives in the Qt-free module**, so the fan, the session and a headless self-test share one directory rather than one each — a warm replay is 68x and paying for the same position twice is what squanders it. `$NANOFAB_CACHE` overrides, then `$XDG_CACHE_HOME`, then a temp dir when neither is writable.
17. **The scenarios moved into the package** (`nanofab_v3/acceptance.py`) because an exe carries no pytest, and `tests/test_scenarios.py` now builds its chains from the *same* recipes and asserts every shipped scenario passes. One definition of what S1 is; the two cannot drift without the suite going red. The honest limit is in the module: `--selftest` checks that each mechanism holds, not the thirty-odd assertions about how it comes about.
18. **The self-test is a `--selftest` flag, not a menu entry** (the handoff asked to decide and write it down). The DoD is a *checkable claim*, so it needs an exit code; a menu entry needs a display, a human, and their report of what they saw. Each scenario is seconds of solver, which on a command line is a progress line and in a menu entry is a frozen UI or a second threading story. The cost is recorded rather than hidden: the spec builds with `console=True` so the flag has somewhere to print, which on Windows means a terminal behind the window; `--report PATH` is there for a build that would rather read a file.
19. **Four things in `nanofab_v3.spec` differ from the v0.2.0 recipe in `ui_backups/`,** each written down in it: `console=True` (18 above); `hiddenimports` naming the process modules, because `builtin_registry()` imports them *inside the function* so a plugin host need not pull in every process — and PyInstaller's static analysis does not follow that, so without them the exe starts with an empty step list and passes nothing; `collect_submodules("scipy")` for the same reason one level down (`ndimage`'s compiled backends); and `upx=False`, because UPX and numpy's extensions break in build-machine-specific ways and this delivers a model whose answers have to hold elsewhere.
20. **No `ui_backups/` snapshot was taken for `nanofab_v3`,** though handoff §7 suggests one. `nanofab_v3` is the actively built code base rather than something being replaced, git is its record, and a 17k-line second copy that AGENTS.md §7 forbids editing would diverge in meaning from the one under development the same day. The right mechanism is a git tag, which AGENTS.md §8 says needs user approval. **Open for the user to decide.**

Validation run:
- `QT_QPA_PLATFORM=offscreen python -m pytest` -> **394 passed** (67 s), of which **80 are new**: `test_wafer` (16), `test_cli` (11), `test_plugins` (9), 22 in `test_processes`, 13 in `test_runtime`, 9 in `test_scenarios`.
- `python -m compileall nanofab_v3 tests` -> clean.
- **The DoD, run against the built exe**: `./dist/nanofab_v3 --selftest` -> `7 of 7 scenarios passed in 6.9 s`, exit 0. `./dist/nanofab_v3 --version` -> 24 processes, `step digests: contract only (no source)`, `frozen build (PyInstaller)`. The frozen GUI starts and runs its event loop headless (`QT_QPA_PLATFORM=offscreen`, killed by timeout rather than exiting).
- **S5 asserted with its control**: buried under 10 nm of conformal alumina, the clean removes **0 of 4** occurrences, leaves 868 nm^2 micromasked, `material:particle` survives, and the film that is flat to the cell over bare silicon bulges **14 nm** over every surviving particle. The identical draw cleaned before anything covers it loses all four and retires the capability. No step is told the particles are buried.
- **The plugin really installs**: `tests/test_plugins.py` builds a wheel of `examples/nanofab-plugin-example` into a temp directory (3.4 s) and runs discovery in a subprocess, so a pass proves the loader found it through `importlib.metadata` and not through `sys.path` holding the source. Its `sog.spin` runs, provides `material:sog` for a material the didactic library has never heard of, and its digest reaches the recipe hash.
- **Interactive check headless** (PySide6 6.11.2, offscreen): the window builds with the four new step families in the list, `Wafer -> Fan this recipe over the wafer` materializes five positions of S1 in the background, the map paints them going pending -> running -> done, and clicking the edge position rebuilds one scene captioned `(60, 0) mm: 6 steps, 0.9 s`.
- **Budget at the reference grid, and on the exe** (plan §21.5): exe **115 MB**, build 1 min 37 s, cold start to argument parsing **2.6-3.4 s against 0.53 s from source** (5.5x, the bootloader unpacking 115 MB before a line of this package runs), `--selftest` 6.9 s of solver in **10.7 s wall**. An inspection step through the commit gate is **25 ms with every array shared**. A five-position fan of a two-step recipe is 0.15 s cold and **0.01 s** over a warm cache. **§17.7's conclusion is unchanged through five milestones**: the upwind stencil over the whole domain still dominates.

Next steps / known risks (and see plan §21.8):
1. **§14's milestone list ends here.** What stays open is §16 as written (3D flux, rate calibration, external-solver adapters, reflow *geometry*, GDS import) plus four things M5 named with reasons: a narrow-band solver (the dominant cost through five milestones, deliberately not started in M5 because it would invalidate every cached revision on the day the exe shipped); `--onedir` packaging (trades 2.4 s of startup for a folder); a recipe encoding open to a plugin's own `WaferParameter` (M4's note 6 — a plugin's interpolant runs but cannot be *saved*); and artifact payloads in the exchange format (§9 saves refs, not what they point at, which is correct and means moving a session moves the manifest and not the SEM images).
2. **`AGENTS.md` §2's repository map is now out of date** — it lists no `acceptance.py`, `cli.py`, `processes/plugins.py`, `ui/wafer.py` or `examples/`. §6 requires asking the user before editing that file, so the diff is **proposed, not applied**.
3. The wafer fan's `compare()` is measure-per-material, which is the smallest honest comparison and shows nothing when the recipe has no wafer-parameterised value. That is correct and can read as a bug: a fan over an unvaried recipe is five identical samples. The tests use a `RadialProfile` recipe for exactly this reason.
4. `inspect.sem`'s artifact is the material index map as `.npy` rather than an image. `DirectoryArtifactSink` is deliberately lossless and self-describing; rendering one as a picture is a consumer's job (plan §10), and nothing consumes it yet — `Revision.artifacts` is displayed nowhere in the UI.
5. The registry's RNG lint reads the *wrapper's* source, the same scope as the digest. `processes/contamination.py` mentions `np.random.Generator` in a type hint at module scope and registers fine, because the lint never sees it. Consistent with the digest and best-effort by construction (§5.2), but it means a step whose randomness lives in a helper is not linted.
6. `tests/test_plugins.py`'s two slow tests need `pip` and a working build backend. They `pytest.skip` with the build output when either is missing, so a locked-down runner loses the second implementer without failing — which is a weaker guarantee than it looks and is why the fast half of that file exists.

## Update 2026-08-26 (v2 M6: the material library on disk, the process table, SpinCurve, E15)

- Implemented milestone **M6** of `docs/plans/m6-m9-roadmap.md` §4 in the order the start prompt gives (migration first, then everything else). **DoD met, all five clauses**: the library comes entirely from disk with no material left in code; the suite is green and grew 394 → **448**; the table's eleven processes are callable as steps; a spin coat at 3000 rpm produces **82.0 nm** with no thickness typed; an unknown material produces a visible warning instead of a silent zero.
- `nanofab_v3/data/materials/` is new: **11 JSON files** (the 8 migrated + `chrome`, `fused_silica`, `titania`) and a README. `materials/schema.py` (the format, version 1), `materials/store.py` (roots, loading, saving), `materials/unknown.py` (E15) are new; `materials/library.py` kept the `MaterialId` constants and became a loader.
- `PROCESS_CLASSES` 6 → **13**, `builtin_registry()` 24 → **31** steps, `MaterialType` gained `spin_curve`, `notes`, `rate_notes`.
- Validated: `python -m compileall nanofab_v3 tests` and `python -m pytest` (439 passed, 9 skipped — the skips are PySide6, absent here). Plus the packaging leg, because `data/` was new (see 3 below).

Why it changed:
- User asked to continue the v2 plan at milestone M6 following `docs/plans/m6-m9-roadmap.md` and `docs/plans/m6-start-prompt.md`.

The one place the plan could not be followed literally, and what was decided instead (**E18**, now in the roadmap §2 and plan §22.1):
1. **The table's sputter-etch row got its own process class, `sputter_etch`; `ion_beam` was left untouched.** Roadmap §3 maps row 1 onto the existing `ion_beam` *(existiert)*. It cannot hold it: `ion_beam` already carries the didactic numbers S1–S5 are tuned to (silicon 1.0, oxide 0.8, resist 1.2) and row 1 gives the same three materials 0.2333/0.2000/0.2500 — writing the table into that key would have changed what every existing ion-beam recipe means, four-fold and silently, in the same milestone whose completion criterion is bit-identity of the migrated models. So §3's own rule ("additiv erweitern, nichts umbenennen") went one step further than its table anticipated. Seven new classes, not six. This is plan §5.4 one layer down — one technique, one wrapper (`ion_beam_etch` gained a `process_class` argument), two columns of the library — and the general lesson is that **a rate key is a claim about provenance as much as about physics**.

Findings and decisions, each with what settled it (full write-up in plan §22):
2. **"Bit-identical" is a claim about a *commit*, so the test carries both halves.** Comparing the loaded library against `didactic_library()` is vacuous once that function *is* the loader. `tests/test_material_files.py` therefore holds the eight pre-migration entries as literals (copied out of the commit before the migration) **and** a dict of every change M6 then made to one of them; the assertion is `pre + declared additions == what loaded`. The first half says the migration lost nothing, the second says every later difference is deliberate and listed in one place. Prose (`notes`, `rate_notes`) is excluded from that comparison and checked separately — that provenance *exists* for every table rate, and that every borrowed value says it is assumed.
3. **`data/` went *inside* the package, and the packaging leg was actually run.** A repo-root `data/` is in git and in no install; `pip install` would leave it behind and the exe would collect a checkout-only path. So `nanofab_v3/data/materials/`, `package-data` in `pyproject.toml`, `collect_data_files` in `nanofab_v3.spec`. Verified rather than argued, because the start prompt names this trap: a built wheel carries all 11 files, a **non-editable** install of that wheel loads them, and the **frozen exe reports `materials: 11 from 2 root(s)` from `/tmp/_MEI…/nanofab_v3/data/materials` and passes 7 of 7 scenarios**. `builtin_materials_dir()` tries `importlib.resources` and falls back to the package directory; the fallback is the one that answers under PyInstaller's one-file unpacking. `--version` now prints the material count and the roots, because getting this wrong produces an application that starts fine and dies at the first rate lookup on somebody else's machine.
4. **Two library roots, and the split is §21.6's `builtin_registry()`/`application_registry()` one layer down.** `didactic_library()` reads the shipped root only — tests, scenarios, `--selftest` — and `application_library()` reads that plus a writable directory (`$NANOFAB_MATERIALS`, else `$XDG_DATA_HOME/nanofab_v3/materials`). A check whose numbers depended on somebody's home directory would answer differently on every machine, and the library is the input the scenarios are least able to notice a change in. It is also the seam B7 (calibrated rates) arrives through: one set of files per tool, no code change.
5. **The two SiO₂ entries and the assumption marking.** The table names "silicon oxide" for sputter etching and "fused silica" for the plasma chemistries, so both are carried as separate materials. Where it is silent about one, that one takes the other's value and `rate_notes[class]` begins with `"Assumed, not measured."`. `rate_notes` is a **field** rather than a comment in the file, because a comment is invisible to the program — a UI can now say "assumed" next to a number, which is what §3.1 asked for when it said mark it rather than take it silently.
6. **`titania` carries no table-derived rate at all**, only didactic values on the four older classes, and its `notes` say a zero on a chemistry class means "nobody stated one", not "inert". B11's rule about invented spin curves applied to rates: a plausible made-up number is worse than an absent one because only the absent one can be noticed. **New backlog entry B12** for when M8's TiO₂ grating demo needs one.
7. **The spin curve is interpolated in log-log, not fitted.** Anchored on 1000 rpm, `d = k·rpm^-1/2` is +6.3 % at 2000 and **−6.8 %** at 5000 — the error changes sign, so no power law passes through the five points. Log-log linear passes through every measured point exactly and gives each segment its own local exponent (the quantity §3.1's drift was computed from). Measured points are returned *before* any arithmetic, so 3000 rpm answers `82.0` and not `82.00000000000001` — a quoted measurement with a float tail invites doubt about everything else. Outside 1000–5000 rpm it clamps and the run log says so; `spin_time` is a documented parameter whose help text states it does not enter the thickness.
8. **E15's placement is the whole of E15.** The check is in `processes.engine.run_step` — the only place every step passes through, so there are not thirty wrappers to forget it in and a plugin's step is covered — and it runs **after** the commit, on the committed structure's materials, because a material can arrive without any step naming it. The chromium particle the feature is named after arrived exactly that way.
9. **The boundary took more care than the feature: a missing *rate* must not warn.** `rate_for` answering 0.0 for a class a material has no entry for is a documented statement — "this does not move" — and it is how a hard mask behaves without being modelled as one. Warning about it would fire on nearly every step and teach everybody to ignore warnings, costing the feature its only mechanism. So: the library not being *askable* warns; the library being asked and answering zero does not.
10. **Four explicit isotropic runners rather than one closure factory.** `implementation_digest` reads a wrapper with `inspect.getsource`, and four closures from one factory share one source text — the rate key each captured would be invisible to the cache key, so pointing `etch.rie_chlorine` at the oxygen column would not retire a single cached revision. Written out, each one's own class constant is in its own source.
11. **A submodel that is written is written whole, a top-level default is not written at all.** Opposite rules for opposite reasons: a file should say what is *special* about its material, but `"develop": {}` is a useless thing to hand somebody who came to change a clearing dose. A test pins the canonical encoding byte for byte, so a save through E15's dialog cannot rewrite unrelated files and bury the one change that mattered.
12. **`SpinCurve` needed no special case in the serializer** even though its field is a tuple of pairs: JSON has arrays and `__post_init__` normalises them back, so the round-trip is exact like every other. Pairs rather than two parallel lists because a file cannot then drift into pairing a speed with the wrong thickness.

Costs, measured on this machine (plan §22.6 has the table; §17.7's conclusion is unchanged for a sixth milestone — M6 touches no kernel):
- `load_library` 11 files cold **4.1 ms**; `didactic_library()` memoised **0.022 ms**. The memoisation is load-bearing, not a nicety: `run_step` falls back to it once per step, so an unmemoised loader would put 11 file reads inside every step and turn §21.5's warm five-position fan (0.01 s) into a disk-bound one. Cache keyed on the root paths, cleared by `save_material` so E15's answer is visible immediately.
- E15's check **0.002 ms** against the 25 ms an inspection step costs through the commit gate — four orders of magnitude down, which is what let it go in the common path rather than behind a flag.
- 31 implementation digests cold **116 ms** (was 64–69 ms for 18); the whole library is **11 kB**.
- The frozen exe here: 60 MB, `--selftest` 4.0 s solver / 5.8 s wall. **Not comparable to §21.5's 115 MB / 6.9 s** — different machine, different OS, and no PySide6 present to freeze. What the build establishes is the packaging claim, which is a yes/no and does travel.

Known risks and things left for later:
- The exe was built on Linux without PySide6 installed, so the `hiddenimports` entries for `nanofab_v3.ui.window` / `ui.wafer_view` were not exercised. That is unchanged from M5's situation on a machine that had them, but a release build should still be the one that counts.
- `application_library()` reads the operator's directory, so a stray file there changes what the *shell* shows and nothing the tests check. That is the intended split (4 above) and is worth remembering when a bug report says "my chromium etches wrong".
- E13's read-only display of an override in the UI (a typed `thickness` shown as coming from the curve) is **M8**, not here; M6 only made `thickness` an override. Same for E10's long help text — §3.1's "the spin time does not enter the thickness" currently lives in the `ParamSpec` description, which is today's only help text, and should move to the long text when E10 exists.
- **AGENTS.md §2's repository map does not mention `nanofab_v3/data/`.** Per §6 this file is not edited without asking, so it is not edited. Suggested line for the map, when the user agrees: `nanofab_v3/data/materials/` — the material library as JSON, one file per material (roadmap E14); the code holds no `MaterialType`.

## Update 2026-08-26 (v2 M7: substrate vs domain, the resize, presets, E4 and E7)

- Implemented milestone **M7** of `docs/plans/m6-m9-roadmap.md` §4 (roadmap E1-E7). **DoD met, all four clauses**, each as a test in `tests/test_substrate_domain.py`: a 100 mm fused-silica preset produces substrate and domain consistently; an etch that would leave the domain at the bottom grows it instead of failing; a step that will not fit under the cap says what raising it would cost; etching through says "etched through" instead of computing something. Suite 448 -> **485** green, and the frozen exe still passes **7 of 7**.
- New: `nanofab_v3/kernel/domain.py` (the one resize function, `DomainPolicy`, `DomainChange`, `memory_estimate`) and `nanofab_v3/ui/presets.py` (the generic preset-override pattern). `Structure` gained `metadata`; `Revision` and `StepOutcome` gained the `DomainChange`; `capability` gained `DOMAIN`; `substrate.select` went from 2 parameters to 12 with 17 semi-standard presets.
- Also updated `AGENTS.md` §2's repository map after asking (§6): `nanofab_v3/data/materials/` is in it now, the plan's correction sections are referenced as "§17 onward" rather than a fixed range that goes stale every milestone, and the roadmap and backlog are listed.
- Validated: `python -m compileall nanofab_v3 tests`, `python -m pytest` (476 passed / 9 skipped, then 485 after the preset tests; skips are PySide6, absent here), and `pyinstaller nanofab_v3.spec && ./dist/nanofab_v3 --selftest` -> 7/7 in 4.4 s.

Why it changed:
- User asked to continue with M7 after M6, following `docs/plans/m7-start-prompt.md`.

Findings, each with what showed it (full write-up in plan §23):
1. **The handoff's trap 2 did not exist.** It predicted that allowing revisions of different grid sizes would mean reworking a consistency path, citing `manifest.py:18`'s "the reference grid, checked on load". That sentence is about a *benchmark* grid quoted for a timing ("4.4 ms per `phi` at the reference grid"), not a stored grid checked against anything. `Grid.check_same_grid` is called **nowhere** in the package (only in its own test), every revision reads its grid from its own manifest, and a chain with two grid sizes saved and loaded on the first try. Recorded because the prediction was reasonable and wrong, and an afternoon was budgeted for it.
2. **What the resize really touched is the commit gate's parent.** `commit(structure, parent=...)` compares the two — `_untouched` for array sharing (§20.1) and `match_lineage` for occurrence identity — and both assume one grid. Lineage matching between differently shaped label arrays is an exception, not a degraded answer. So the fit runs **before** the step and the fitted input is both the step's input and the gate's parent; grids then differ only *between* revisions, which is the one place nothing compares. General rule: **a value object shared by two consumers can only change shape where neither is mid-comparison.**
3. **The two ends of the domain are two different questions, measured rather than reasoned.** The symmetric implementation ("count rows that look like the edge row") grew nothing on a resist coat that filled the domain to the ceiling — because every upper row *is* identical to the top row then, and that is the exact case the growth exists for. So `headroom` counts entirely empty rows and `underroom` counts laterally uniform ones: each end is asked what that end of the domain is for. **A predicate that is symmetric in the code is not automatically symmetric in the physics.**
4. **A margin is a trigger, not a target — and a trigger alone does not deliver E5.** Small margin, because a policy that grew every domain until it was comfortable would silently replace the domain somebody chose (40 nm substrate + 200 nm headroom, the shape most of this repo's tests use, would come back 190 nm deep before a step ran). And a margin cannot catch one step that moves the front further than any margin, and a front clipped by the domain face cannot be asked how far it wanted to go — so `run_step` runs the step, sees the room used up, grows the *input* and runs again (twice at most, doubling). Extra solve only on the step that needed it; deterministic because the resize is a function of the input and the policy and the RNG re-seeds identically per attempt.
5. **The substrate thickness is `Structure.metadata`, and the three alternatives each fail differently.** A `Field` is four bytes per cell to say "1 mm" and a value a step could accidentally make vary. A capability is set membership and this is a number. The `Revision` is out of reach, because §5.1 hands a step a `Structure` and nothing else — and the step that must refuse to etch through the wafer is exactly the one that needs the number. So: JSON scalars only, carried by every derivation and by the exchange format, open rather than a typed field so B2's back-side flag is not a schema change. A pre-M7 file loads with an empty one (§9's own tolerance rule).
6. **E4 cost no step contract.** Giving thirty steps `requires={"domain"}` would have moved thirty implementation digests and retired every cached recipe, to express something none of them has an opinion about. Instead `domain` is *structural* like `material:<id>` — derived whenever the structure has geometry — and the rule lives once in `ProcessRegistry`. Hand-built structures in tests kept working untouched; what changed was three tests whose **synthetic** capability sets described samples that did not exist.
7. **The through-etch check measures the deepest column, not the average.** A wafer is not breached on average. It lives in `processes` and is added to the gate's report in `run_step`, because `substrate.*` metadata is a process-layer convention and a gate that knew what that key meant would be a kernel that knows what a wafer is.
8. **The preset rule needs `touched`, and "differs from its default" is not the same fact.** A value that happens to equal what somebody typed is not a value they typed, so `ParameterForm` marks a field touched on a *user* edit and writes preset values behind an `_applying` flag. A touched field the preset agrees with is not a conflict — asking there would only teach people to click yes.
9. **A preset suggests; it does not replace the domain silently.** `substrate.select` uses the grid it was handed unless the recipe names a preset (or types domain fields). A step whose output depended on something not in its parameters would be a step no recipe reproduces — and every chain written before M7 keeps its domain.
10. **Empty and zero mean "take the preset's".** A parameter whose default is a real value cannot say "I did not choose", so `material` and `form_factor` default to `""` and every dimension to `0`. Found by a test: `wafer_fs_100` produced silicon, because `material`'s default of `"silicon"` overrode the preset every time.

Decisions taken where the roadmap left detail open:
11. **The substrate presets are a table in code, not JSON beside the material library.** The difference is what the numbers *are*: a wafer diameter is a standard, a rate is a measurement. Nobody needs to correct SEMI D1 without a rebuild, and a substrate the table does not list is already expressible (pick a form factor, type the dimensions). If a lab ever needs its own, the seam is E14's shape and one file away.
12. **A mask blank gets a wider domain at 2 nm/cell**, a wafer 1200 nm at 1 nm. A blank is written with coarser features; `spacing` is plan §3.1's visible model parameter and doubling it buys 4x the speed at half the resolution. A didactic default, overridable, not a rule.
13. **The domain policy is per `Run` and per `Session`, not per step**, because E5 makes the cap raisable and two positions of one wafer must not come out in different sizes.
14. **The cap dialog shows the estimate before the choice.** Growing and shrinking are decisions the model can make (it knows where the sample is); spending another gigabyte is one only the person paying for it can. Disk is quoted as plan §20.3's honest 6x-500x range rather than a single invented number.

Measured (plan §23.7 has the table). Reference cross-section 1200 nm wide at 1 nm, this machine:
- RAM per revision at 5 arrays: **22.9 MB at 1 µm, 114.6 MB at 5 µm**; `resize` by +256 rows: 1.8 ms / 12.3 ms; the fit's own per-step cost (`window`): 0.84 ms / 4.4 ms — under 1 % of what the commit gate spends on the same domain, which is what let it go in the common path.
- **§17.7's standing conclusion needs refining rather than repeating.** On a deeper domain the dominant cost is the **commit gate**, and inside it `occurrences.label_occurrences`, which scales *worse* than linearly (5x the cells, 6.8x the time: 95 -> 642 ms) where reinitialisation scales *better* (2.8x). The advection is windowed around the front (§18.5) and barely notices. So the thing that would make a 5 µm domain painful is occurrence lineage, not the upwind stencil — a different optimisation target than five milestones of measurement had suggested. Recorded, not acted on: M7 is not the place to start it.
- **End-to-end step timings on this machine were non-monotonic and are not trustworthy.** The same spin-coat: 169 ms at 0.5 µm, 283 ms at 1 µm, **129 ms at 5 µm**, reproducibly, while every component measured in isolation scaled upward. Could not be reproduced outside `run_step`; no structural difference explains it (same occurrence counts, same geometry). §21.5's rule at full strength — a number measured on one machine is a statement about that machine, and this one is a shared VM. Trust the per-component numbers; the end-to-end ones are here so nobody reads a speed-up into them.

Known risks and what was deliberately left:
- **The domain policy is not in the cache key.** `DomainPolicy` is an argument like `ReinitPolicy` and `GateTolerances`, none of which are. It is benign as long as a resize only adds quiet rows — the sample inside the window is the same sample, and the lateral extent never changes (E6), so even `particle.seed`'s draws are unaffected. It would stop being benign if a policy ever changed geometry rather than framing. Worth a line in ADR-0004 if that day comes.
- **Two tests that produced a deliberate headroom FAIL now describe a cap instead.** A coat taller than the domain succeeding is the milestone, not a regression, and the replacement failure is the one that still means something.
- **M9's lateral boundary bug was not touched**, per the handoff: `kernel.domain.STACK_AXIS` is a constant and not a parameter, so nothing here grows along x (E6, backlog B9). Nothing new was noticed about the x edge while working on y.
- `substrate.select`'s twelve parameters are a lot for one form. E10's long help text (M8) is where the explanation of which of them a preset drives belongs; the `ParamSpec` descriptions carry it in the meantime.

## Update 2026-08-26 (v2 M8: the UI grows up — descriptions, search, two exposure pictures, truncate, aspect ratio, four demos)

- Implemented milestone **M8** of `docs/plans/m6-m9-roadmap.md` §4 (roadmap E8-E12 plus the demo picker). **DoD met, all five clauses**: every step explains itself, the step list is searchable, you can see where the light falls before exposing and what was exposed after, revisions are removable, and the demos are selectable and run. Suite 485 -> **547** green with **0 skipped** (it was 9), and the frozen exe still passes 7 of 7.
- New: `nanofab_v3/text.py` (the translation indirection), `nanofab_v3/ui/demos.py` (four demos with their explanations), `scene.LightPreview` / `scene.display_scale` / the `exposed` and `dose` overlays, `registry.matching` / `describe` / `display_name`, `Session.repeat` / `parameters_of`, and search, tag, truncate and aspect-ratio controls in the shell. 31 step descriptions written at their registrations.
- Validated: `python -m compileall nanofab_v3 tests`, `python -m pytest` (547 passed, 0 skipped), and `pyinstaller nanofab_v3.spec && ./dist/nanofab_v3 --selftest` -> 7/7 in 4.0 s on a 116 MB build (Qt frozen in this time, so comparable to M5's 115 MB).

Why it changed:
- User asked to continue with the next milestone after M7.

Findings, each with what showed it (full write-up in plan §24):
1. **A UI milestone whose UI tests skip has no tests, and ours had been skipping since M5.** Nine Qt tests sat behind `importorskip("PySide6")` in a container with no PySide6. Installing Qt and putting `QT_QPA_PLATFORM=offscreen` in `conftest.py` — before anything imports Qt, `setdefault` so a developer can still watch the widgets — turned them into runs and **one failed immediately**: an M7 regression in the step list that had been invisible for a day. Rule rather than fix: **a skipped test is not a passing test**, and "9 skipped" in every commit message since M5 is exactly how that stays unnoticed.
2. **E10 and E11 are one feature, in that order.** The filter searches name *and description*, so a list searchable for "undercut" or "hard mask" is only possible once the steps say what they do. Built the other way round, E11 would have been a filter over 31 short names — a filter nobody needs.
3. **`description` is deliberately not on the `ProcessStep` protocol.** It is `runtime_checkable` and `register` gates on `isinstance`, so a member added there would refuse registration to every plugin written before M8. It lives on `FunctionStep`; `registry.describe` reads it with `getattr` and falls back to the display name — a poor description, never a missing one.
4. **The catalog key is structural, never the English text.** `nanofab_v3.text` is E10's indirection and explicitly *not* B10's catalog: a key beside each string costs nothing now and is the whole difference on the day a second language arrives, where 31 bare strings would be 31 call sites. Keying on the English would break every translation the first time somebody fixed a typo.
5. **The two exposure pictures are two *kinds* of object, so they cannot be merged by accident.** An `Overlay` is derived from a `Structure` (what the simulation produced); a `LightPreview` is derived from a recipe parameter the sample has never seen (what the mask would do). Merging them into one "exposure view" is the natural refactor and would delete E9's whole lesson — a student who expects the second to look like the first has just learned what an aerial image is.
6. **A field stored over the whole grid is not meaningful over the whole grid.** `expose_ideal` writes `exposed` everywhere on purpose (§3.3's scoping rule is what keeps it correct), and drawing it directly put a latent image in the empty space above the resist: 24 341 cells "struck" where the answer is 8 000. The overlay clips to the material each field is scoped to. **Storage extent and meaningful extent are different, and a renderer must use the second** — the commit gate already knew this; the renderer had to learn it separately.
7. **The distortion label is painted even when it is 1.** A label that appears only when something is wrong is a label whose absence has to be interpreted, and "no label means nothing to report" is indistinguishable from "no label means nobody drew one". So every picture says either `1:1 true to scale` or `1.25x compressed horizontally — angles are not true`.
8. **"Free — they read a field" was wrong, and it was in a docstring I wrote.** The `exposed` overlay's *data* is free; **drawing** it costs a distance transform and a marching-squares pass — **81 ms** at the reference grid, the same order as the predicate it was being contrasted against. Corrected in place. They stay on by default for the reason that actually holds: a scene is rebuilt on a revision change, not per frame (§20.6), so 80 ms sits beside a step that takes seconds.
9. **The search really is free, which is what made a live filter reasonable.** 0.006 ms per keystroke over 31 steps, memoised per registry and invalidated on `register`. Had it been milliseconds it would have needed a debounce timer, and a filter with a timer is a filter that feels broken.

Decisions taken where the roadmap left detail open:
10. **Backlog B12 was decided rather than guessed, which is what B12 asked for.** The etch-stop demo needs a number the process table does not have. B11's rule (an invented spin curve is worse than none) does not apply here because B12's own text says to *decide*: the ratio (25:1) is didactic, the direction is physics — a fluorine plasma makes AlF3, which is not volatile, so alumina stops a fluorine etch and titania does not — and `rate_notes` says exactly that in both files. **An invented number is dishonest when it is indistinguishable from a measured one, not when it is invented.**
11. **Filtering and gating stay different things.** A filtered-out step is hidden; a blocked one is shown in grey with its reason. Hiding what the sample cannot run would answer "why can I not do this?" by removing the question.
12. **The preset rule from M7 pays off in E12.** "Adjust" writes the old parameters through `apply_values`, so they do not count as the operator's own typing and a preset chosen afterwards still fills silently.
13. **The truncate confirmation only appears when it costs more than the revision being removed.** A dialog on every deletion is a dialog people learn to dismiss, which would spend the one case where it matters.
14. **`demo_recipe()` delegates to `demos.lift_off()`** rather than repeating it — two definitions of one recipe is the drift this repository keeps refusing everywhere else.

Measured (plan §24.7 has the table):
- `registry.matching` warm **0.006 ms** / cold 0.17 ms; `light_preview` 1.3 ms; `display_scale` 0.0008 ms.
- `scene.build` at 1200x640 @ 1 nm: 78 ms bare, **+81 ms** for `exposed`, +63 ms for `dose`, +73 ms for the `reachable` predicate.
- The four demos end to end: lift-off 0.5 s, chromium grating 10.6 s, etch stop 23.8 s, black silicon 2.9 s.
- The exe: **116 MB** with Qt frozen in (M5 measured 115 MB), `--selftest` 4.0 s of solver / 6.8 s wall — three milestones of new steps, a new library format, a domain resize and a rewritten shell, and the seven scenarios cost what they cost in M5.

Known risks and what was deliberately left:
- **The etch-stop demo is ~24 s in the foreground.** The events are pumped between steps and a wait cursor is set, so the chain and log fill in as it goes, but the window is not usable while it runs. Backgrounding it the way the wafer fan does would be the better answer and is deliberately not done: that runner is built around wafer *positions*, and one interactive chain is not that. If demos get longer, this is the thing to build.
- **The grating demos leave a component count that is higher than the picture suggests** (a 200 nm grating comes back as several `fused_silica` occurrences). The profile is correct and steep — the tests assert the profile — but the reinitialisation at sharp corners on a 2 nm grid splits the label field. Not investigated further: it does not affect what is drawn or measured, and §23.7 already flags occurrence labelling as the thing that would need work on a bigger domain.
- **`ParameterForm` shows the description as Markdown** in a `QLabel`, which renders the backticks and bold but has no scroll area. A long description on a small window is clipped rather than scrollable.
- M9 is untouched, as intended: nothing in M8 goes near the lateral boundary.
