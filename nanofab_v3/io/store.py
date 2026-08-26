"""Revision stores: where a chain spills what it is not holding (plan §8, §9).

Two implementations of `runtime.revision.RevisionStore`, and the difference
between them is only how long a spilled revision outlives the process.

`FileRevisionStore` is the one plan §8's laziness is built on: a directory of
`.npz` + `.json` pairs, one per revision, written on eviction and read back on
demand. At the measured 22–28 ms to write and 10 ms to read, spilling is cheaper
than the step that produced the revision by two orders of magnitude, and faulting
one back is below a UI frame — which is what makes "keep the last few resident,
spill the rest" a policy rather than a compromise.

`ReplayCache` is the same directory keyed the way ADR-0004 requires — (recipe
hash, position, step index, code version) — so it survives the session and
answers "has this exact step at this exact position already been computed?"
across runs.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from nanofab_v3.io.exchange import load_revision, save_revision
from nanofab_v3.model.artifact import ArtifactRef
from nanofab_v3.io.manifest import code_version
from nanofab_v3.runtime.revision import Revision


class FileRevisionStore:
    """A `RevisionStore` backed by one directory of `.npz` + `.json` pairs.

    Attributes:
        directory: Where the pairs live. Created on first write.
        verify: Whether to check content hashes when faulting a revision back.
            On by default: a chain faults revisions into a running session, so a
            silently corrupted array would become a wrong answer rather than an
            error, and the check costs a few ms against a 10 ms load.
    """

    def __init__(self, directory: str | os.PathLike[str], *, verify: bool = True) -> None:
        self.directory = Path(directory)
        self.verify = verify

    def path(self, index: int) -> Path:
        """Where revision `index` is (or would be) stored."""
        return self.directory / f"rev-{index:04d}"

    def put(self, index: int, revision: Revision) -> None:
        save_revision(self.path(index), revision)

    def get(self, index: int) -> Revision | None:
        stem = self.path(index)
        if not stem.with_suffix(".json").exists():
            return None
        return load_revision(stem, verify=self.verify)

    def __contains__(self, index: object) -> bool:
        return isinstance(index, int) and self.path(index).with_suffix(".json").exists()

    def __repr__(self) -> str:  # pragma: no cover - debug convenience
        return f"FileRevisionStore({str(self.directory)!r})"


def recipe_hash(steps: Any, *, registry: Any = None) -> str:
    """A stable digest of a recipe's steps and their unresolved parameters.

    Part of the cache key of plan §8 and ADR-0004, and it has to change whenever
    the recipe would produce a different sample: a different step, a different
    parameter, a different order. It must **not** change when the same recipe is
    described by an object built a second time, which is why it digests the
    steps' own `fingerprint()` text rather than anything with an address in it.

    **Pass the `registry`.** With it, each step is hashed together with its
    `implementation_digest` — the second axis of the cache key decided in M5
    (plan §21.1). Without it a step's *code* is not in the key at all, and a
    plugin that changes its rate model, or a builtin wrapper edited during
    development, is then served out of a warm cache as if it were current
    (`code_version()` does not move for either). It is an argument rather than
    a lookup because a recipe names steps by id and which registry resolves
    those ids is the caller's fact; it defaults to `None` so that hashing a
    recipe for something *other* than a cache — comparing two recipes, labelling
    a file — does not need one.
    """
    digests = registry.digests() if registry is not None else {}
    digest = hashlib.blake2b(digest_size=16)
    for step in steps:
        digest.update(step.fingerprint(digests.get(step.step_id)).encode())
        digest.update(b"\x00")
    return digest.hexdigest()


def cache_key(recipe: str, position: tuple[float, float], index: int) -> str:
    """ADR-0004's cache key: `(recipe hash, position, step, code version)`.

    The code version is in it because determinism is promised per machine *and*
    code version (ADR-0004's last paragraph): cross-machine float drift is
    accepted, and this is what stops it being served out of a cache as if it
    were the same answer.
    """
    material = f"{recipe}|{position[0]!r}|{position[1]!r}|{index}|{code_version()}"
    return hashlib.blake2b(material.encode(), digest_size=16).hexdigest()


def replay_cache_for(
    directory: Any, recipe: Any, *, registry: Any = None, verify: bool = True
) -> "ReplayCache":
    """The `ReplayCache` for one recipe, keyed the way M5 decided (plan §21.1).

    One call so that "which hash does this cache go under" is answered in one
    place rather than at every call site that wants a cache. Pass the registry
    the run will use: it is what puts each step's implementation in the key, and
    the whole point of the two-axis decision is that it not be optional in
    practice while remaining optional in the API for the callers that hash a
    recipe for other reasons.
    """
    return ReplayCache(directory, recipe_hash(recipe, registry=registry), verify=verify)


class ReplayCache:
    """The persistent half of plan §8's materialization, keyed per ADR-0004.

    A chain's `RevisionStore` is about *this* chain's memory; the cache is about
    every chain that was ever computed, so adding a wafer position later can find
    the steps it shares with a position already materialized — which is the whole
    point of keying on the recipe and the position rather than on an index.

    Attributes:
        directory: Where cached revisions live.
        recipe: The recipe hash this cache is being used for.
        verify: Whether to check content hashes on read (see `FileRevisionStore`).
    """

    def __init__(
        self,
        directory: str | os.PathLike[str],
        recipe: str,
        *,
        verify: bool = True,
    ) -> None:
        self.directory = Path(directory)
        self.recipe = recipe
        self.verify = verify
        self.hits = 0
        self.misses = 0
        self.writes = 0

    def path(self, position: tuple[float, float], index: int) -> Path:
        """Where the revision for one (position, step) is (or would be) stored."""
        return self.directory / cache_key(self.recipe, position, index)

    def get(self, position: tuple[float, float], index: int) -> Revision | None:
        """The cached revision, or `None` — and count which it was."""
        stem = self.path(position, index)
        if not stem.with_suffix(".json").exists():
            self.misses += 1
            return None
        self.hits += 1
        return load_revision(stem, verify=self.verify)

    def put(self, position: tuple[float, float], revision: Revision) -> None:
        """Cache one revision under the position and index it belongs to."""
        save_revision(self.path(position, revision.index), revision)
        self.writes += 1

    def for_position(self, position: tuple[float, float]) -> "_PositionView":
        """A `RevisionStore` view of this cache for one wafer position."""
        return _PositionView(self, position)

    def stats(self) -> Mapping[str, int]:
        """Hits, misses and writes since this cache object was made."""
        return {"hits": self.hits, "misses": self.misses, "writes": self.writes}


class _PositionView:
    """One position's slice of a `ReplayCache`, shaped as a `RevisionStore`.

    Lets a `RevisionChain` spill straight into the replay cache: what the chain
    drops for memory is exactly what a later replay of the same position wants,
    so the two are one directory rather than two.
    """

    def __init__(self, cache: ReplayCache, position: tuple[float, float]) -> None:
        self._cache = cache
        self._position = position

    def put(self, index: int, revision: Revision) -> None:
        self._cache.put(self._position, revision)

    def get(self, index: int) -> Revision | None:
        return self._cache.get(self._position, index)


class DirectoryArtifactSink:
    """An `ArtifactSink` that writes payloads into one directory as `.npy`.

    The filesystem half of `model.artifact`: a step hands over an array, this
    writes it and hands back the `ArtifactRef` that names it. The `uri` is
    **relative** to `root`, which is what `ArtifactRef`'s own contract says ("a
    relative path is relative to the save file") — an absolute path baked into a
    revision would stop being true the moment the session was moved or reopened
    somewhere else.

    `.npy` rather than PNG or CSV, deliberately: the payloads the inspection
    steps produce are arrays (a profilometer trace, a material index map), and
    `numpy.save` is lossless, self-describing and already a dependency.
    Rendering one as a picture is a consumer's job, exactly as plan §10 has it
    for every other array in the model.

    Writing is **idempotent by name**: a replay of the same step at the same
    position writes the same bytes over the same file, which is what keeps a
    re-materialized position pointing at something true rather than accumulating
    a directory of near-duplicates.

    Attributes:
        root: Where payloads go. Created on first write.
        prefix: A relative sub-path prepended to every name — normally the
            position or the chain a sink belongs to, so one directory can serve
            a whole wafer fan without two positions overwriting each other.
    """

    SUFFIX = ".npy"

    def __init__(self, root: str | os.PathLike[str], *, prefix: str = "") -> None:
        self.root = Path(root)
        self.prefix = prefix.strip("/")

    def path(self, name: str) -> Path:
        """Where the payload called `name` is (or would be) written."""
        return self.root / self.relative(name)

    def relative(self, name: str) -> str:
        """The `uri` a ref to `name` carries — relative to `root`, POSIX-separated."""
        stem = f"{name}{self.SUFFIX}"
        return f"{self.prefix}/{stem}" if self.prefix else stem

    def put(
        self,
        name: str,
        payload: np.ndarray,
        *,
        kind: str = "table",
        label: str = "",
    ) -> ArtifactRef:
        target = self.path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        np.save(target, np.asarray(payload))
        return ArtifactRef(
            kind=kind,
            uri=self.relative(name),
            label=label or name,
            media_type="application/x-npy",
        )

    def read(self, ref: ArtifactRef) -> np.ndarray:
        """Load back what `ref` points at — the reader a viewer needs."""
        return np.load(self.root / ref.uri)

    def __repr__(self) -> str:  # pragma: no cover - debug convenience
        return f"DirectoryArtifactSink({str(self.root)!r}, prefix={self.prefix!r})"
