"""Where a *delivered* application keeps the files an operator is meant to edit.

One question, asked once: **is there a folder next to this program, and where is
it?** A source checkout answers "no" and everything falls back to the roots it
already had; a frozen build answers "yes, next to the executable", which is what
makes `data/materials/` and `data/demos/` visible and editable rather than sealed
inside the exe.

Plan §11 froze the delivery as **one file**, and that decision stands — a
one-directory build would put the library among several hundred DLLs, which is
worse than sealing it. So the exe still carries its own copy and runs alone;
`nanofab_v3.spec` additionally *places* the two directories beside it at build
time, and this module is how the running program finds them. Nothing here creates
anything: a folder that is not there simply means the packaged copy is the only
one, which is the correct behaviour for an exe somebody moved on its own.

`sys.executable` rather than `sys._MEIPASS`: `_MEIPASS` is the temp directory the
one-file bootloader unpacks *into*, which is exactly the place an operator cannot
edit and which disappears when the program exits. The two are easy to confuse and
the failure is silent — an edit that appears to work until the next start.
"""

from __future__ import annotations

import sys
from pathlib import Path


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
    keep working. The caller's fallback is then the packaged copy.
    """
    root = portable_root()
    if root is None:
        return None
    candidate = root.joinpath(*parts)
    return candidate if candidate.is_dir() else None


__all__ = ["frozen", "portable_dir", "portable_root"]
