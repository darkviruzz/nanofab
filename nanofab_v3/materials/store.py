"""Where the material library lives on disk, and who is allowed to add to it.

Roadmap E14: *the library moves to `data/materials/*.json`, one file per
material, and the eight built-in materials move **with** it — no split between a
few in code and a few on disk.* This module is the other half of that sentence:
`schema` says what one file looks like, and this says which files there are.

**Two roots, and the split is the same one plugins already have.**
`builtin_materials_dir()` is `nanofab_v3/data/materials/`, shipped inside the
package and read-only; `user_materials_dir()` is a writable directory outside it,
which is where E15's unknown-material dialog puts what an operator answers. A
later root shadows an earlier one, so a local `silicon.json` overrides the
shipped one — the seam B7 (calibrated rates) is meant to arrive through, one set
of files per tool, no code change.

`didactic_library()` reads the **shipped root only**, deliberately, and
`application_library()` reads both. That is plan §21.6's rule about
`builtin_registry()` versus `application_registry()`, applied one layer down and
for the same reason: a test or a `--selftest` whose numbers depended on what
happened to be in somebody's home directory would answer differently on every
machine, and a library is the one input the acceptance scenarios are least able
to notice a change in.

**In a frozen build there is exactly one root, and it is the visible one**
(roadmap E19). The packaged copy is gone: two libraries, one of which silently
wins, means that when they disagree nobody can say which one ran. The
consequences are all deliberate and all named here rather than mitigated:

- `didactic_roots()` and `material_roots()` collapse to the same single root, so
  `didactic_library()` **loses its isolation** in a delivered build. That is why
  `LibraryReport.fingerprint` exists (E36) — a `--selftest` whose numbers depend
  on the operator's files says which files those were, instead of pretending to a
  separation it no longer has.
- There is no fallback. `missing_library_reason()` is the sentence a build with
  no `data/materials/` prints before it stops.

**Why inside the package and not `data/` at the repo root** (the question the M6
start prompt asked to settle): a root-level `data/` is not part of the
distribution. `pip install nanofab-v3` would install `nanofab_v3/` and leave the
library behind, and plan §11's one-file exe would need a `datas` entry pointing
at a directory that only exists in a checkout. Inside the package it travels with
every install form, `pyproject.toml`'s `package-data` picks it up for a wheel,
and `nanofab_v3.spec` collects it for the exe — where its absence would otherwise
only show up as a `--selftest` failure on somebody else's machine.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Mapping, Sequence

from nanofab_v3 import paths
from nanofab_v3.materials.material import MaterialId, MaterialType
from nanofab_v3.materials.schema import (
    MaterialFileError,
    read_material,
    to_json,
    write_material,
)

if TYPE_CHECKING:  # `library` imports this module, so the runtime import is local
    from nanofab_v3.materials.library import MaterialLibrary

MATERIALS_SUBDIR = ("data", "materials")
"""Where the shipped files sit, relative to the `nanofab_v3` package root."""

MATERIALS_ENV = "NANOFAB_MATERIALS"
"""Environment variable that replaces the writable root, for tests and for tools."""


def builtin_materials_dir() -> Path:
    """The shipped library directory — inside the package, in every install form.

    `importlib.resources` first, because that is the answer that also holds for a
    zip import and for a frozen build whose loader provides a resource reader;
    the package directory as the fallback, because PyInstaller's one-file mode
    unpacks `nanofab_v3/data/materials/` under `sys._MEIPASS` and `__file__`
    points straight at it. Both are checked rather than one assumed: this is the
    kind of path that works in a checkout and fails only in the exe, which is the
    trap the M6 start prompt names.
    """
    try:
        from importlib import resources

        candidate = Path(str(resources.files("nanofab_v3").joinpath(*MATERIALS_SUBDIR)))
        if candidate.is_dir():
            return candidate
    except (ImportError, ModuleNotFoundError, TypeError, OSError):  # pragma: no cover
        pass
    return Path(__file__).resolve().parent.parent.joinpath(*MATERIALS_SUBDIR)


def delivered_materials_dir() -> Path | None:
    """`data/materials/` beside a frozen executable, or `None`.

    `$NANOFAB_MATERIALS` wins over it, which is how a test stands in for a
    delivered folder without freezing anything. `None` outside a frozen build, and
    `None` in one where the directory is simply not there — the second case is
    what `missing_library_reason()` turns into a sentence.
    """
    override = os.environ.get(MATERIALS_ENV)
    if override:
        return Path(override)
    return paths.portable_dir(*MATERIALS_SUBDIR)


def user_materials_dir() -> Path:
    """The writable root E15's dialog saves to; never created until something writes.

    `$NANOFAB_MATERIALS` overrides it. Then, in a frozen build, `data/materials/`
    **next to the executable** — since E19 that is not merely the writable root
    but the *only* one, which is what makes an edit there take effect at all.

    Otherwise `$XDG_DATA_HOME` or `~/.local/share`, and a temp directory when the
    home directory cannot be determined — the same ladder
    `ui.wafer.default_cache_dir()` climbs, so an operator has one place for their
    own materials rather than one per entry point.
    """
    delivered = delivered_materials_dir()
    if delivered is not None:
        return delivered
    if paths.frozen():
        # A delivered build with no directory: name where it *should* be, so a
        # save creates the folder the next start will read rather than one in a
        # home directory nobody will look in.
        expected = paths.expected_dir(*MATERIALS_SUBDIR)
        if expected is not None:
            return expected
    try:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    except (OSError, RuntimeError):  # pragma: no cover - depends on the machine
        base = tempfile.gettempdir()
    return Path(base) / "nanofab_v3" / "materials"


def delivered_only() -> bool:
    """Whether this build has given up its packaged library (E19).

    True in a frozen build with no `$NANOFAB_MATERIALS` override — the case where
    the only root is the operator's own folder, which is what makes both the
    single-root collapse above and the leniency below correct rather than lax.
    """
    return paths.frozen() and not os.environ.get(MATERIALS_ENV)


def didactic_roots() -> tuple[Path, ...]:
    """The roots the *shipped* library is read from — one in a delivered build.

    In a source checkout this is the packaged directory alone, which is what keeps
    a test's numbers independent of anybody's home directory. In a frozen build
    the packaged directory does not exist, so this is the visible one and the
    isolation is gone; `LibraryReport.fingerprint` is what makes that legible
    instead of silent (E36).
    """
    if delivered_only():
        return (user_materials_dir(),)
    return (builtin_materials_dir(),)


def material_roots() -> tuple[Path, ...]:
    """The roots an *application* reads, shipped first and writable last.

    One root in a delivered build, for E19's reason: the shipped one is not there
    to read.
    """
    if delivered_only():
        return (user_materials_dir(),)
    return (builtin_materials_dir(), user_materials_dir())


def missing_library_reason() -> str | None:
    """Why this build has no material library, or `None` when it has one.

    E19 took the fallback away on purpose, so this is the whole of the safety net:
    a delivered build with no `data/materials/` **stops**, saying where it looked.
    Running on with an empty library would put a program that computes nothing in
    front of somebody with no way to find out why — every step would report rate
    zero and every scenario would fail at its first lookup, which is a bug report
    about the model rather than about a missing folder.
    """
    roots = [root for root in material_roots() if Path(root).is_dir()]
    if roots and any(any(Path(root).glob("*.json")) for root in roots):
        return None
    expected = material_roots()[0] if material_roots() else None
    where = f"\n  expected: {expected}" if expected is not None else ""
    return (
        "no material library: this build reads its materials from files beside the "
        "executable and found none." + where + "\n"
        "  A delivered NanoFab folder holds the executable, bin/, data/materials/, "
        "data/demos/ and settings.ini — restore data/materials/ from the delivery "
        "and start again."
    )


@dataclass(frozen=True)
class LibraryReport:
    """What a load found: where it looked, what it read, what it could not.

    The counterpart of `processes.plugins.DiscoveryReport`, and lenient for the
    same reason: one malformed file in an operator's own directory must cost that
    material and nothing else. A delivered application whose material list is
    empty because of a stray comma is the failure this exists to prevent.

    Attributes:
        roots: The directories that were read, in the order they were read.
        loaded: `{material_id: file}` for everything that parsed.
        overridden: `{material_id: [earlier files]}` — a later root shadowing an
            earlier one *with a different definition* is the intended mechanism
            (B7), so it is reported rather than warned about. An identical file in
            two roots is not an override and is not listed: a delivered build has
            the whole library twice by construction, and reporting that would bury
            the one entry somebody actually changed.
        failures: `(path, reason)` per file that did not parse.
        fingerprint: A short hash over every entry that was loaded (E36) — see
            `library_fingerprint`.
    """

    roots: tuple[Path, ...] = ()
    loaded: Mapping[MaterialId, Path] = field(default_factory=dict)
    overridden: Mapping[MaterialId, tuple[Path, ...]] = field(default_factory=dict)
    failures: tuple[tuple[Path, str], ...] = ()
    fingerprint: str = ""

    def describe(self) -> tuple[str, ...]:
        """Lines for a log or a `--selftest` banner."""
        lines = [f"materials: {len(self.loaded)} from {len(self.roots)} root(s)"]
        if self.fingerprint:
            lines.append(f"materials: fingerprint {self.fingerprint}")
        for material, shadowed in sorted(self.overridden.items()):
            lines.append(f"materials: {material} overrides {len(shadowed)} earlier definition(s)")
        for path, reason in self.failures:
            lines.append(f"materials: skipped {path.name} ({reason})")
        return tuple(lines)


def library_fingerprint(entries: Mapping[MaterialId, MaterialType]) -> str:
    """A short hash over the material set a build actually loaded (roadmap E36).

    E19 leaves a delivered build with one library root, the operator's own, so the
    acceptance scenarios no longer run against files this project shipped — they
    run against whatever is in that folder. That is the intended trade and it is
    made **visible** rather than repaired: `--version` and `--selftest` print this,
    so a result carries the identity of the numbers that produced it and "my
    chromium etches wrong" is answerable from a screenshot.

    Over the **canonical encoding** of each entry rather than over the file bytes.
    The claim being made is "these are the models that ran", and reformatting a
    file or reordering its keys does not change that; changing a rate does.
    """
    digest = hashlib.sha256()
    for material in sorted(entries, key=str):
        digest.update(str(material).encode("utf-8"))
        digest.update(b"\0")
        digest.update(to_json(entries[material]).encode("utf-8"))
    return digest.hexdigest()[:12]


RootContents = tuple[
    dict[MaterialId, MaterialType], dict[MaterialId, Path], tuple[tuple[Path, str], ...]
]
"""What one directory yielded: the entries, the file each came from, the failures."""


def read_root(root: Path) -> RootContents:
    """Every `*.json` in one directory, as `(entries, files, failures)`.

    A missing directory is empty, not an error: the writable root does not exist
    until something has been saved into it, and that is the ordinary case.
    """
    entries: dict[MaterialId, MaterialType] = {}
    files: dict[MaterialId, Path] = {}
    failures: list[tuple[Path, str]] = []
    root = Path(root)
    if not root.is_dir():
        return entries, files, tuple(failures)
    for path in sorted(root.glob("*.json")):
        try:
            entry = read_material(path)
        except MaterialFileError as error:
            failures.append((path, str(error)))
            continue
        if entry.material_id != path.stem:
            failures.append(
                (
                    path,
                    f"holds material {entry.material_id!r}, but a file is named after the "
                    "material it defines",
                )
            )
            continue
        entries[entry.material_id] = entry
        files[entry.material_id] = path
    return entries, files, tuple(failures)


def load_library(
    roots: Iterable[Path] | None = None, *, strict: bool = False
) -> tuple["MaterialLibrary", LibraryReport]:
    """Read a `MaterialLibrary` from one or more directories, later roots winning.

    `strict` turns a malformed file into an exception instead of a report entry.
    The shipped root is read strictly — a broken file there is a build defect and
    must not degrade into a quietly smaller library — and a writable root is not.
    """
    from nanofab_v3.materials.library import MaterialLibrary

    paths = tuple(Path(root) for root in (material_roots() if roots is None else roots))
    merged: dict[MaterialId, MaterialType] = {}
    files: dict[MaterialId, Path] = {}
    overridden: dict[MaterialId, tuple[Path, ...]] = {}
    failures: list[tuple[Path, str]] = []
    for root in paths:
        entries, found, root_failures = read_root(root)
        if strict and root_failures:
            path, reason = root_failures[0]
            raise MaterialFileError(reason if str(path) in reason else f"{path}: {reason}")
        failures.extend(root_failures)
        for material, entry in entries.items():
            # Only a *different* definition counts as an override. Since the
            # delivered exe carries its own copy of the library and reads the
            # editable one beside it, every material shadows an identical twin —
            # eleven lines saying nothing, which is exactly how the one line that
            # means something (a lab's own chromium) becomes invisible. "A count
            # is not a list" cuts both ways: a list of non-events is not one
            # either.
            if material in files and merged.get(material) != entry:
                overridden[material] = overridden.get(material, ()) + (files[material],)
            merged[material] = entry
            files[material] = found[material]
    report = LibraryReport(
        roots=paths,
        loaded=files,
        overridden=overridden,
        failures=tuple(failures),
        fingerprint=library_fingerprint(merged),
    )
    return MaterialLibrary(merged), report


def save_material(entry: MaterialType, root: Path | None = None) -> Path:
    """Write one material into a root as `<material_id>.json` (E15's dialog).

    Defaults to the writable root, never the shipped one: a build's own files are
    part of the delivery, and an application that edits them in place would make
    two installs of the same version disagree — which is exactly what
    `nanofab_v3.__version__` promises does not happen (ADR-0004).
    """
    target = user_materials_dir() if root is None else Path(root)
    path = write_material(entry, target / f"{entry.material_id}.json")
    invalidate_cache()
    return path


# -- the two libraries an application and a test respectively read -------------

_CACHE: dict[tuple[str, ...], tuple["MaterialLibrary", LibraryReport]] = {}


def invalidate_cache() -> None:
    """Forget every cached load — called after a save, and by tests."""
    _CACHE.clear()


def cached_library(
    roots: Sequence[Path], *, strict: bool = False
) -> tuple["MaterialLibrary", LibraryReport]:
    """`load_library`, memoised on the root paths.

    A `MaterialLibrary` is a frozen value over frozen values, so handing the same
    instance to every caller is safe and `with_entry` still returns a new one.
    Worth doing because `processes.engine.run_step` falls back to the shipped
    library when no library is passed, i.e. once per step: fourteen file reads
    per step would turn a warm replay (10 ms for a five-position fan, plan §21.5)
    into a disk-bound one.
    """
    key = tuple(str(Path(root)) for root in roots)
    hit = _CACHE.get(key)
    if hit is None:
        hit = load_library(roots, strict=strict)
        _CACHE[key] = hit
    return hit
