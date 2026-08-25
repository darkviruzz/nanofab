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
