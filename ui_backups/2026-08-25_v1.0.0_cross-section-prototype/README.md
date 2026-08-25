# Snapshot: cross-section prototype (v1), 2026-08-25

The cross-section visualization prototype, frozen on the day the v2 structure
model's acceptance scenarios S1–S4 went green.

## Why this is a snapshot

`docs/plans/v2-structure-model.md` §14 and `AGENTS.md` §7 both say the same
thing: v1 stays untouched next to v2 **until M3's acceptance tests pass**, and
then it becomes a `ui_backups/` snapshot. They passed (249 tests, 2026-08-25), so
this is that step. It was taken deliberately and on the user's go-ahead, not as a
side effect of the tests going green.

The successor is `nanofab_v3/` at the repository root — the only actively built
code base there now.

## Running it

One file, and its only dependency is PySide6:

```
pip install PySide6
python cross_section_general_prototype.py
```

## What it was, and what replaced it

The prototype is the origin of ADR-0001, which measured it and named the ten
findings the v2 model was designed against. Its central defect is recorded there
and is worth keeping in view, because it is the thing v2 exists to not repeat:
`QPainterPath` acted as the physics engine, geometry and analytic primitives were
a dual truth, and iterating a step therefore accumulated vertices without bound —
60 isotropic etch steps took the per-step cost from ~0.02 s to ~3.7 s and
transiently fragmented the shape into eight pieces.

- The autopsy: `docs/adr/0001-cross-section-model-for-iterative-process-steps.md`
- What replaced it: `docs/plans/v2-structure-model.md`, ADR-0002…0004
- The measurement that says the representation changed:
  `tests/test_performance.py` — per-step cost flat across a 60-step chain.
