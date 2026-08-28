"""Where a *delivered* application keeps the files an operator is meant to edit.

One question, asked once: **is there a folder next to this program, and where is
it?** A source checkout answers "no" and everything falls back to the roots it
already had; a frozen build answers "yes, next to the executable", which is what
makes `data/materials/`, `data/demos/` and `settings.ini` visible and editable
rather than sealed inside the exe.

## The delivery is one directory, and the library is in it exactly once

Plan §11 froze the delivery as one file and M9's follow-up placed the two data
directories beside it — which left the library in **two** places, the sealed copy
and the visible one. Roadmap **E19** ends that: `--onedir`, the several hundred
DLLs pushed into `bin/` by `contents_directory`, and the editable directories as
the *only* copy. The reasoning is not about size: two copies of a rate table mean
that when they disagree nobody can say which one ran, and the visible one silently
winning is a worse answer than not having it.

The price is that there is **no fallback**. A delivered build whose
`data/materials/` is missing has no library at all, and the correct response is to
say so and stop — `materials.store.missing_library_reason()` produces the sentence
and `cli.main` prints it. Starting with an empty library would put a program that
computes nothing in front of somebody who would have to find out why on their own.

`sys.executable` rather than `sys._MEIPASS`: under `--onedir` the two are now
genuinely different directories — the executable's own, and `bin/` beside it,
where PyInstaller keeps everything it collected. Editing a file in `bin/` is
editing a copy that will be overwritten by the next build, which is exactly the
silent failure the one-file version of this warning was about.
"""

from __future__ import annotations

import sys
from pathlib import Path

SETTINGS_FILE = "settings.ini"
"""Name of the application-behaviour file beside the executable (roadmap E39)."""


def frozen() -> bool:
    """Whether this is a PyInstaller build rather than a source checkout."""
    return bool(getattr(sys, "frozen", False))


def portable_root() -> Path | None:
    """The directory the executable sits in, or `None` outside a frozen build.

    `None` rather than the source tree, deliberately. A checkout's "next to the
    program" would be the repository root, and quietly reading an operator-editable
    directory out of a working copy is how a test starts depending on somebody's
    scratch files — the same trap `didactic_library()` avoids by reading the
    shipped root only.
    """
    if not frozen():
        return None
    try:
        return Path(sys.executable).resolve().parent
    except (OSError, ValueError):  # pragma: no cover - depends on the machine
        return None


def portable_dir(*parts: str) -> Path | None:
    """`<next to the exe>/<parts>` if it is really there, else `None`.

    Existence is checked rather than assumed, because "the exe was copied
    somewhere on its own" is a normal thing for a portable application and has to
    keep working. Since E19 the caller has no packaged copy to fall back to, so
    `None` here is a diagnosis rather than a shrug: see `expected_dir`.
    """
    root = portable_root()
    if root is None:
        return None
    candidate = root.joinpath(*parts)
    return candidate if candidate.is_dir() else None


def expected_dir(*parts: str) -> Path | None:
    """Where `portable_dir` *looked*, whether or not anything was there.

    The half of the answer an error message needs. "No materials" is not
    actionable; "no materials — expected them in `<path>/data/materials`" is, and
    the difference is this function.
    """
    root = portable_root()
    return None if root is None else root.joinpath(*parts)


def portable_file(name: str = SETTINGS_FILE) -> Path | None:
    """`<next to the exe>/<name>` if the file is there, else `None`."""
    root = portable_root()
    if root is None:
        return None
    candidate = root / name
    return candidate if candidate.is_file() else None


__all__ = [
    "SETTINGS_FILE",
    "expected_dir",
    "frozen",
    "portable_dir",
    "portable_file",
    "portable_root",
]
