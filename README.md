# NanoFab Process Manager

A digital twin for nanofabrication process runs: each process step (lithography, thin-film deposition, etch, lift-off, …) consumes a sample state and produces a new, traceable revision. Built for education and R&D process planning.

**`nanofab_v3/` is the only actively built code base.** It now carries its own application (`python -m nanofab_v3.ui`); the v0.2.0 PySide6 app its shell descends from is preserved in `ui_backups/` (see [Where the application went](#where-the-application-went)).

## Structure model v2 (`nanofab_v3/`)

Geometry is one signed-distance field per material on one shared `Grid` — the single stored truth (ADR-0002). Set operations are pointwise min/max; solid union, material index map, contours and occurrences are all derived per revision. Complexity lives in the **process**, never in the structure model.

```bash
pip install -e ".[dev,ui]"   # numpy + scipy; pytest and PySide6 as extras
pytest
python -m nanofab_v3.ui      # the application
```

The four acceptance scenarios of [`docs/plans/v2-structure-model.md`](docs/plans/v2-structure-model.md) §1 are green: naive lift-off, undercut, lift-off broken by ALD, and sputter fences. They are the definition of done for the model, and they are asserted through predicates rather than by poking at arrays.

### Running a recipe without the UI

A recipe is an ordinary object, and a run of it is a chain of revisions:

```python
from nanofab_v3.materials import RESIST, SILICON
from nanofab_v3.runtime import Recipe, RecipeStep, run_recipe
from nanofab_v3.processes.substrate import cross_section_grid

recipe = Recipe(
    grid=cross_section_grid(width=300.0, thickness=40.0, headroom=200.0),
    recipe_id="coat",
    steps=(
        RecipeStep("substrate.select", {"material": SILICON, "surface": 40.0}),
        RecipeStep("resist.spin_coat_ideal", {"material": RESIST, "thickness": 90.0}),
    ),
)
chain = run_recipe(recipe)
print(chain.logs())                     # what each step did, and what the gate said
print(sorted(chain.capabilities))       # what the sample now promises
```

A recipe parameter may be a function over the wafer (`RadialProfile`, `LinearTilt`), and `Run` materializes it at any position by deterministic replay — cached on (recipe hash, position, step, code version), so adding a position later is the ordinary path rather than a re-run (ADR-0004).

## Project layout

- `nanofab_v3/` — the structure model: `model/` (Grid, Structure, fields, capabilities), `kernel/` (set ops, motion, flux, predicates, commit gate), `materials/`, `processes/`, `runtime/` (revisions, runs, replay), `io/` (the `.npz` + JSON exchange format), `ui/` (SceneSnapshot, the interactive session, the Qt shell)
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

Each snapshot has a `README.md` saying what it is, how to run it, and what replaced it. The v0.2.0 shell carried over in milestone M4 as `nanofab_v3/ui/` — read out of the snapshot and rewritten, since a snapshot is a record and not a branch (`AGENTS.md` §7). Two things changed on the way: gating moved from step ids to **capabilities**, so a blocked step says what is missing about the sample rather than which step has not run; and the cross-section canvas is rewritten against `SceneSnapshot v2`. `nanofab_v3/ui/scene.py` and `session.py` import no Qt at all — anything that decides geometry is on that side of the line, which is v1's central defect (ADR-0001) turned into a rule a test can check.

## Working with this repo

- [`AGENTS.md`](AGENTS.md) — workflow guide for coding assistants (startup checklist, versioning, git workflow)
- [`CONTEXT.md`](CONTEXT.md) — domain glossary
- [`memory.md`](memory.md) — append-only project decision log
- `.claude/skills/` — [mattpocock/skills](https://github.com/mattpocock/skills) engineering/productivity skills for Claude Code
