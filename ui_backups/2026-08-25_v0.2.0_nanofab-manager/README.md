# Snapshot: NanoFab Manager v0.2.0, 2026-08-25

The v0.2.0 application — UI shell plus the `nanofab_modular` process engine —
frozen on the day the v2 structure model's acceptance scenarios S1–S4 went green.

## Contents

| | |
|---|---|
| `nanofab_manager.py` | `APP_VERSION = "0.2.0"`; was `nanofab_manager_v0_2_0.py` at the repository root |
| `nanofab_modular/` | the modular process engine (domain, engine, registry, step API, steps) |
| `nanofab_manager.spec` | PyInstaller recipe; was `nanofab_manager_v0_2_0.spec` |

## Running it

Self-contained apart from PySide6, and `nanofab_modular/` sits next to the entry
file, which is what the entry file's imports expect:

```
pip install PySide6
python nanofab_manager.py
```

## Two renames, and why

The entry file is called `nanofab_manager.py` here rather than
`nanofab_manager_v0_2_0.py`, following the `2026-03-05_v0.1.0_baseline` pattern:
the version belongs in the folder name, so a snapshot's entry file always has the
same name. The `.spec`'s `Analysis` entry was repointed to match — otherwise the
snapshot would carry a build recipe naming a file that is not in it, and
`AGENTS.md` §7 asks for backups that are runnable and self-contained. The exe
name it produces (`nanofab_manager_v0_2_0`) is left as v0.2.0 built it.

`nanofab_modular/` is byte-identical to the copy in
`../2026-03-05_v0.1.0_baseline/`: the engine did not change between 0.1.0 and
0.2.0, all of 0.2.0's changes are in the UI file. It is duplicated here anyway so
this snapshot stands on its own.

## Where the code went

`nanofab_modular` has a successor rather than a continuation: `nanofab_v3/` at the
repository root, the v2 structure model of `docs/plans/v2-structure-model.md`. It
keeps `nanofab_modular`'s good ideas as *concepts* — append-only revisions,
artifacts, history, gating (now capability contracts) — and none of its code, by
decision (plan §2, I5). ADR-0001's finding D9 is the reconciliation note.

The UI shell itself is expected to carry over in milestone M4 (plan §10): the step
list, gating, parameter forms and run log are reusable; the cross-section canvas
is rewritten against the kernel's outputs instead of QPainterPaths.
