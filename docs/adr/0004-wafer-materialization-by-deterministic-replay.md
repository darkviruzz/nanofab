# ADR-0004: Wafer positions materialize by deterministic replay

- Status: accepted (design interview 2026-08-24/25) — implementation pending
- Detail: `docs/plans/v2-structure-model.md` §5.2, §8

Wafer position is a property of **materialization**, not of the structure: the 2D
solver is position-blind and receives only locally resolved parameters
(`effective_params(recipe, position, step)`); recipe parameters may be functions
over the wafer (interpolants; sampled lists are just their data). A Run is one
recipe over an extensible position set (default `{center}`), each position an
independent revision chain. Adding a position later **replays** the chain from the
start with that position's parameters — lazily, cached per
(recipe hash, position, step, code version).

This is only sound under a hard invariant, adopted here: every step's outcome is a
pure function of (input structure, recipe params, position, step index, code
version), and all stochastic behaviour (particles, roughness) draws from an RNG
seeded by (recipe, position, step). Breaking this later would silently invalidate
every cached and every compared position — hence recorded as an ADR although it
constrains rather than structures the code.

Rejected alternatives: eager fan-out over a fixed position set (cannot add
positions later, pays for unviewed positions); one run carrying N cross-sections
(forces a position axis into every view, metric and artifact). Determinism is
promised per machine + code version; cross-machine float drift is accepted and
absorbed by the code-version cache key.
