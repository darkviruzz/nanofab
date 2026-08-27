"""Editing the library in place, without losing what the numbers meant (E37).

The library window is a reference work *and* an editor, and the editor half is
where a project like this quietly goes wrong. Two rules, and both are about
provenance rather than about files:

**A number's provenance is part of the number** (handoff §3.3, promoted to a rule
after four separate precedents). Every rate in `data/materials/` is measured,
assumed or didactic, and `rate_notes` says which. Somebody who edits chromium's
ion-beam rate has just turned "student process table, row 1" into a sentence that
is no longer true — and an editor that left the note alone would ship a file
claiming a measurement for a number nobody measured. So the note is **carried
forward**, never dropped and never silently kept: `carry_provenance` rewrites it
to say what it was, what it said, and when it changed.

**"Reset" has to exist, and it costs exactly one copy.** `data/materials/.original/`
holds the delivered state, written by the build and read by nothing at load
time — it is not a second library root, so it does not reopen E19's two-truths
problem. It is the unmodified copy, and its only purpose is to be copied back.

Qt-free, like everything else that decides something: the window is a view of
these functions.
"""

from __future__ import annotations

import shutil
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Iterable

from nanofab_v3.materials.material import PROCESS_CLASSES, MaterialId, MaterialType
from nanofab_v3.materials.schema import read_material, write_material
from nanofab_v3.materials.store import invalidate_cache, user_materials_dir

ORIGINAL_DIR = ".original"
"""Where the delivered state of the library sits, for "reset" and nothing else.

A dot directory, so `read_root`'s `*.json` glob never sees it — it is not a root,
it is a backup. `nanofab_v3.spec` writes it at build time; a source checkout has
git instead and does not need one.
"""


def original_dir(root: Path | None = None) -> Path | None:
    """The delivered copy of the library, or `None` when this build has none."""
    base = user_materials_dir() if root is None else Path(root)
    candidate = base / ORIGINAL_DIR
    return candidate if candidate.is_dir() else None


def original_of(material: MaterialId, root: Path | None = None) -> MaterialType | None:
    """What was delivered for one material, or `None` if it was not delivered."""
    base = original_dir(root)
    if base is None:
        return None
    path = base / f"{material}.json"
    if not path.is_file():
        return None
    try:
        return read_material(path)
    except Exception:  # pragma: no cover - a corrupt backup is not worth raising over
        return None


def changed_rates(new: MaterialType, old: MaterialType | None) -> tuple[str, ...]:
    """Which process classes have a different rate than before, in table order."""
    if old is None:
        return ()
    return tuple(
        process_class
        for process_class in PROCESS_CLASSES
        if new.rate_for(process_class) != old.rate_for(process_class)
    )


def provenance_note(
    process_class: str, new: MaterialType, old: MaterialType, today: date | None = None
) -> str:
    """The `rate_notes` entry a changed rate gets (roadmap E37).

    "Edited <date> (was <value>; <what the note used to say>)". The old note is
    kept **inside** the new one rather than beside it, because the claim it makes
    is now historical: it described where the previous number came from, and it
    is still true about that number.
    """
    stamp = (today or date.today()).isoformat()
    was = old.rate_for(process_class)
    previous = old.rate_note(process_class).strip()
    tail = f"; {previous}" if previous else ""
    return f"Edited {stamp} (was {was:g} nm/s{tail})"


def carry_provenance(
    new: MaterialType, old: MaterialType | None, today: date | None = None
) -> MaterialType:
    """Rewrite the notes of every rate this edit changed; leave the rest alone.

    Only the changed ones. An editor that stamped every note on every save would
    make the ten untouched rates look edited, which destroys exactly the
    information this is here to preserve.
    """
    changed = changed_rates(new, old)
    if not changed or old is None:
        return new
    notes = dict(new.rate_notes)
    for process_class in changed:
        # The note the *editor* typed wins: somebody who wrote a new provenance
        # by hand knows more about it than this function does. What is replaced
        # is a note that survived unchanged from the previous value.
        if notes.get(process_class, "") == old.rate_note(process_class):
            notes[process_class] = provenance_note(process_class, new, old, today)
    return replace(new, rate_notes=notes)


def save_edit(
    entry: MaterialType,
    *,
    previous: MaterialType | None = None,
    root: Path | None = None,
    today: date | None = None,
) -> Path:
    """Validate, carry the provenance forward, and write the file atomically.

    The whole of the editor's write path, in one function, so the window is a
    view. Validation is the `MaterialType` constructor's — the caller has already
    passed it by having an `entry` — and the canonical encoding is
    `write_material`'s, which a test pins byte for byte so an edit to one rate
    cannot reformat the fields nobody touched.
    """
    base = user_materials_dir() if root is None else Path(root)
    if previous is None:
        path = base / f"{entry.material_id}.json"
        previous = read_material(path) if path.is_file() else None
    written = write_material(carry_provenance(entry, previous, today), base / f"{entry.material_id}.json")
    invalidate_cache()
    return written


def reset_material(material: MaterialId, root: Path | None = None) -> Path | None:
    """Put the delivered file back, or `None` when there is nothing to put back."""
    base = user_materials_dir() if root is None else Path(root)
    source = original_dir(base)
    if source is None:
        return None
    origin = source / f"{material}.json"
    if not origin.is_file():
        return None
    target = base / f"{material}.json"
    scratch = target.with_name(target.name + ".part")
    shutil.copyfile(origin, scratch)
    import os

    os.replace(scratch, target)
    invalidate_cache()
    return target


def resettable(materials: Iterable[MaterialId], root: Path | None = None) -> set[MaterialId]:
    """Which of these have a delivered copy to go back to."""
    source = original_dir(root)
    if source is None:
        return set()
    return {material for material in materials if (source / f"{material}.json").is_file()}


__all__ = [
    "ORIGINAL_DIR",
    "carry_provenance",
    "changed_rates",
    "original_dir",
    "original_of",
    "provenance_note",
    "reset_material",
    "resettable",
    "save_edit",
]
