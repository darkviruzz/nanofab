# NanoFab Process Manager

A PySide6 desktop app that simulates nanofabrication process runs as a **digital twin**: each process step (lithography, thin-film deposition, lift-off, etc.) consumes a sample state and produces a new, traceable revision. Built for education and R&D process planning.

## Running

```bash
pip install PySide6
python nanofab_manager.py
```

Multiple versioned entry files exist (`nanofab_manager.py`, `nanofab_manager_v0_2_0.py`) — see [`AGENTS.md`](AGENTS.md) for how to detect the currently active one.

## Project layout

- `nanofab_manager*.py` — UI entry points
- `nanofab_modular/` — modular process engine (domain, engine, registry, steps)
- `cross_section_general_prototype.py` — cross-section visualization prototype
- `NanoFab_Process_Manager_Documentation/` — product documentation chapters
- `ui_backups/` — versioned snapshots taken before breaking changes

## Working with this repo

- [`AGENTS.md`](AGENTS.md) — workflow guide for coding assistants (startup checklist, versioning, git workflow)
- [`CONTEXT.md`](CONTEXT.md) — domain glossary
- [`memory.md`](memory.md) — append-only project decision log
- `.claude/skills/` — [mattpocock/skills](https://github.com/mattpocock/skills) engineering/productivity skills for Claude Code
