# NanoFab Process Manager

A digital twin for nanofabrication process runs: each process step (lithography, thin-film deposition, etch, lift-off, …) consumes a sample state and produces a new, traceable revision. Built for education and R&D process planning.

The repository is mid-rewrite. **`nanofab_v3/` is the only actively built code base**; the PySide6 application it will be wired into is preserved in `ui_backups/` (see [Where the application went](#where-the-application-went)).

## Structure model v2 (`nanofab_v3/`)

Geometry is one signed-distance field per material on one shared `Grid` — the single stored truth (ADR-0002). Set operations are pointwise min/max; solid union, material index map, contours and occurrences are all derived per revision. Complexity lives in the **process**, never in the structure model.

```bash
pip install -e ".[dev]"   # numpy + scipy, pytest as dev extra
pytest
```

The four acceptance scenarios of [`docs/plans/v2-structure-model.md`](docs/plans/v2-structure-model.md) §1 are green: naive lift-off, undercut, lift-off broken by ALD, and sputter fences. They are the definition of done for the model, and they are asserted through predicates rather than by poking at arrays.

## Project layout

- `nanofab_v3/` — the structure model: `model/` (Grid, Structure, fields, capabilities), `kernel/` (set ops, motion, flux, predicates, commit gate), `materials/`, `processes/`; `runtime/` and `io/` are milestone M4
- `tests/` — pytest suite for `nanofab_v3`
- `docs/plans/` — the v2 plan and its per-milestone handoffs
- `docs/adr/` — architecture decision records
- `NanoFab_Process_Manager_Documentation/` — product documentation chapters
- `ui_backups/` — versioned snapshots taken before breaking changes

## Where the application went

`AGENTS.md` §7 and plan §14 both say v1 becomes a `ui_backups/` snapshot once the v2 acceptance tests pass. They did, so it has:

- `ui_backups/2026-08-25_v0.2.0_nanofab-manager/` — the v0.2.0 app and the `nanofab_modular` process engine. `pip install PySide6 && python nanofab_manager.py` inside that folder.
- `ui_backups/2026-08-25_v1.0.0_cross-section-prototype/` — the cross-section prototype ADR-0001 was written against. PySide6 only.
- `ui_backups/2026-03-05_v0.1.0_baseline/` — the v0.1.0 app.

Each snapshot has a `README.md` saying what it is, how to run it, and what replaced it. The UI shell is expected to carry over in milestone M4 (plan §10); the cross-section canvas is rewritten against the kernel's outputs rather than QPainterPaths, which was v1's central defect (ADR-0001).

## Working with this repo

- [`AGENTS.md`](AGENTS.md) — workflow guide for coding assistants (startup checklist, versioning, git workflow)
- [`CONTEXT.md`](CONTEXT.md) — domain glossary
- [`memory.md`](memory.md) — append-only project decision log
- `.claude/skills/` — [mattpocock/skills](https://github.com/mattpocock/skills) engineering/productivity skills for Claude Code
