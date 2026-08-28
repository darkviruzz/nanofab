"""Reading and writing the exchange format (plan §9).

A revision on disk is `<stem>.npz` plus `<stem>.json`. Everything here is thin —
the interesting decisions are in `io.manifest`; this module is what turns them
into files, and the one number that justifies its shape is from the M4 handoff:

| | |
|---|---|
| one revision, raw | 5.83 MB |
| the same revision, `savez_compressed` | **0.04 MB** |
| `savez_compressed` | 22–28 ms |
| `np.load` round-trip | 10 ms |

137x, lossless, bit-identical. The reason is structural rather than lucky: a
signed-distance field on a grid is piecewise linear, so it takes very few
distinct values — 2964 distinct float32 values in 648 000 cells on a scene that
had just been ion-beam etched. So saving is **always** compressed and always
eager: at 40 KB and 30 ms there is nothing to be clever about, and the same call
serves a save, a cache write and an external-solver handoff.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from nanofab_v3.io import manifest as _manifest
from nanofab_v3.io.manifest import SCHEMA_ID, check_schema, code_version
from nanofab_v3.model.structure import Structure
from nanofab_v3.runtime.revision import Revision, RevisionChain

MANIFEST_SUFFIX = ".json"
ARRAYS_SUFFIX = ".npz"


def _stem(path: str | os.PathLike[str]) -> Path:
    """The pair's shared stem, so callers may pass either file or neither."""
    path = Path(path)
    if path.suffix in (MANIFEST_SUFFIX, ARRAYS_SUFFIX):
        return path.with_suffix("")
    return path


def _write(stem: Path, manifest: Mapping[str, Any], arrays: Mapping[str, np.ndarray]) -> Path:
    stem.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(stem.with_suffix(ARRAYS_SUFFIX), **arrays)
    stem.with_suffix(MANIFEST_SUFFIX).write_text(
        json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8"
    )
    return stem


def _read(stem: Path) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    manifest_path = stem.with_suffix(MANIFEST_SUFFIX)
    arrays_path = stem.with_suffix(ARRAYS_SUFFIX)
    if not manifest_path.exists():
        raise FileNotFoundError(f"no manifest at {manifest_path}")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    check_schema(data)
    with np.load(arrays_path) as archive:
        arrays = {name: archive[name] for name in archive.files}
    return data, arrays


# -- a structure on its own (the external-solver exchange) --------------------


def save_structure(path: str | os.PathLike[str], structure: Structure) -> Path:
    """Write one `Structure` as `.npz` + `.json`, returning the shared stem."""
    manifest, arrays = _manifest.structure_to_json(structure)
    manifest["schema_id"] = SCHEMA_ID
    manifest["code_version"] = code_version()
    return _write(_stem(path), manifest, arrays)


def load_structure(path: str | os.PathLike[str], *, verify: bool = True) -> Structure:
    """Read one `Structure` back, bit-identically."""
    data, arrays = _read(_stem(path))
    return _manifest.structure_from_json(data, arrays, verify=verify)


# -- a revision (a structure and its whole provenance) ------------------------


def save_revision(path: str | os.PathLike[str], revision: Revision) -> Path:
    """Write one `Revision` — plan §3.6's fields, all of them."""
    manifest, arrays = _manifest.revision_to_json(revision)
    return _write(_stem(path), manifest, arrays)


def load_revision(path: str | os.PathLike[str], *, verify: bool = True) -> Revision:
    """Read one `Revision` back."""
    data, arrays = _read(_stem(path))
    return _manifest.revision_from_json(data, arrays, verify=verify)


# -- a chain (one wafer position's whole session) -----------------------------

CHAIN_MANIFEST = "chain.json"
"""Name of the index file in a saved chain's directory."""


def revision_stem(directory: str | os.PathLike[str], index: int) -> Path:
    """Where revision `index` of a chain lives inside `directory`."""
    return Path(directory) / f"rev-{index:04d}"


def save_chain(directory: str | os.PathLike[str], chain: RevisionChain) -> Path:
    """Write a whole revision chain: one file pair per revision plus an index.

    Every revision is written, including the ones the chain had spilled — saving
    a session is not the moment to be lazy, and faulting one back costs the 10 ms
    plan §9's numbers already budget for.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for index in range(len(chain)):
        save_revision(revision_stem(directory, index), chain[index])
    index_file = directory / CHAIN_MANIFEST
    index_file.write_text(
        json.dumps(
            {
                "schema_id": SCHEMA_ID,
                "code_version": code_version(),
                "recipe_id": chain.recipe_id,
                "position": list(chain.position),
                "revisions": len(chain),
            },
            indent=1,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return directory


def load_chain(
    directory: str | os.PathLike[str],
    *,
    store: Any = None,
    resident: int = 3,
    verify: bool = True,
) -> RevisionChain:
    """Read a whole revision chain back, ready to be continued or replayed."""
    directory = Path(directory)
    data = json.loads((directory / CHAIN_MANIFEST).read_text(encoding="utf-8"))
    check_schema(data)
    position = tuple(float(v) for v in data.get("position", (0.0, 0.0)))
    chain = RevisionChain(
        recipe_id=str(data.get("recipe_id", "recipe")),
        position=(position[0], position[1]),
        store=store,
        resident=resident,
    )
    for index in range(int(data["revisions"])):
        chain.append(load_revision(revision_stem(directory, index), verify=verify))
    return chain
