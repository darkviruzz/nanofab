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
