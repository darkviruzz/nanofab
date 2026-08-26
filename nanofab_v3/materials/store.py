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

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Mapping, Sequence

from nanofab_v3.materials.material import MaterialId, MaterialType
from nanofab_v3.materials.schema import MaterialFileError, read_material, write_material

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


def user_materials_dir() -> Path:
    """The writable root E15's dialog saves to; never created until something writes.

    `$NANOFAB_MATERIALS` overrides it; otherwise `$XDG_DATA_HOME` or
    `~/.local/share`, and a temp directory when the home directory cannot be
    determined — the same ladder `ui.wafer.default_cache_dir()` climbs, so an
    operator has one place for their own materials rather than one per entry
    point.
    """
    override = os.environ.get(MATERIALS_ENV)
    if override:
        return Path(override)
    try:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    except (OSError, RuntimeError):  # pragma: no cover - depends on the machine
        base = tempfile.gettempdir()
    return Path(base) / "nanofab_v3" / "materials"


def material_roots() -> tuple[Path, ...]:
    """The roots an *application* reads, shipped first and writable last."""
    return (builtin_materials_dir(), user_materials_dir())


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
            earlier one is the intended mechanism (B7), so it is reported rather
            than warned about.
        failures: `(path, reason)` per file that did not parse.
    """

    roots: tuple[Path, ...] = ()
    loaded: Mapping[MaterialId, Path] = field(default_factory=dict)
    overridden: Mapping[MaterialId, tuple[Path, ...]] = field(default_factory=dict)
    failures: tuple[tuple[Path, str], ...] = ()

    def describe(self) -> tuple[str, ...]:
        """Lines for a log or a `--selftest` banner."""
        lines = [f"materials: {len(self.loaded)} from {len(self.roots)} root(s)"]
        for material, shadowed in sorted(self.overridden.items()):
            lines.append(f"materials: {material} overrides {len(shadowed)} earlier definition(s)")
        for path, reason in self.failures:
            lines.append(f"materials: skipped {path.name} ({reason})")
        return tuple(lines)


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
            if material in files:
                overridden[material] = overridden.get(material, ()) + (files[material],)
            merged[material] = entry
            files[material] = found[material]
    report = LibraryReport(
        roots=paths, loaded=files, overridden=overridden, failures=tuple(failures)
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
