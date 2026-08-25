"""Runtime: revisions, runs, wafer materialization (plan §3.6, §8).

Empty in M0 by design. This is where the append-only `Revision` chain, the step
registry, capability gating and the replay-based `Materialization` of wafer
positions (ADR-0004) will live — the `ProcessEngine` ideas worth keeping, carried
over as concepts rather than as v1 code. Milestone M4.
"""

from __future__ import annotations

__all__: list[str] = []
