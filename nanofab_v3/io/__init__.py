"""Persistence and exchange (plan §9).

One format serves three jobs — saving a session, the replay cache of plan §8, and
handing a structure to an external solver (fidelity tier c): per revision a
compressed `.npz` of the `phi` and `Field` arrays plus a JSON manifest
(`schema_id: "structure.v2"`, `Grid`, material ids, capabilities, history and
content hashes). `ArtifactRef`s stay URI-referenced files exactly as docs §4.2.2
has them. Forward compatibility is `schema_id` plus ignored unknown keys (docs
§4.1 invariant 5, carried over).

The property everything else rests on is that a round trip is **bit-identical**,
not merely close: the cache faults structures back into a running chain, so an
"almost" would turn a deterministic model into a non-deterministic one and quietly
invalidate every replay guarantee in ADR-0004.

- `manifest` — the JSON half: dataclasses to plain values and back, content hashes
- `exchange` — `save_structure` / `save_revision` / `save_chain` and their readers
- `store` — `FileRevisionStore` (a chain's spill directory) and `ReplayCache`
  (keyed per ADR-0004: recipe hash, position, step index, code version)
"""

from __future__ import annotations

from nanofab_v3.io.exchange import (
    CHAIN_MANIFEST,
    load_chain,
    load_revision,
    load_structure,
    revision_stem,
    save_chain,
    save_revision,
    save_structure,
)
from nanofab_v3.io.manifest import SCHEMA_ID, code_version, content_hash
from nanofab_v3.io.store import FileRevisionStore, ReplayCache, cache_key, recipe_hash

__all__ = [
    "CHAIN_MANIFEST",
    "FileRevisionStore",
    "ReplayCache",
    "SCHEMA_ID",
    "cache_key",
    "code_version",
    "content_hash",
    "load_chain",
    "load_revision",
    "load_structure",
    "recipe_hash",
    "revision_stem",
    "save_chain",
    "save_revision",
    "save_structure",
]
