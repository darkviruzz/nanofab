"""The demos a picker offers, each with the sentence that says what to watch for.

Roadmap M8's sixth item: *"Demo-Picker statt des einen hartcodierten Demos, mit
Erklärtext je Demo"*. Until now the application opened with one lift-off wired
into the window, which meant the only recipe anybody saw was the only recipe
anybody could see.

A `Demo` is a recipe plus prose, and the prose is the point. A demo that runs and
produces a shape teaches nothing on its own — what teaches is knowing what the
shape was supposed to show and what would have happened otherwise, which is why
every entry carries `watch_for` as well as a description.

**Qt-free**, like `scene`, `session`, `wafer` and `presets`: these are recipes and
sentences, and a headless test runs every one of them. The picker is a menu in
`ui.window` and decides nothing.

The recipes are written against the material library, not against numbers typed
here. If a rate is wrong the demo shows the wrong thing, which is the correct
failure — a demo that hard-coded its own physics would keep working while the
library it is supposed to illustrate drifted away from it.

**The demos are JSON, for the same reason the materials are** (roadmap E14, one
milestone later). They live in `nanofab_v3/data/demos/`, one file per demo, and a
frozen build places that directory next to the executable so an operator can open
one, change a duration, and see the result — without a checkout, a toolchain, or
this file. The code holds no recipe; `lift_off()` and its three siblings are
lookups by key, kept because they read better at a call site than a string does.

Two roots, shipped then writable, exactly like `materials.store`: a later root
shadows an earlier one, so an edited `titania_stop.json` beside the exe replaces
the packaged one, and a demo file that does not parse costs **that demo** and not
the menu.

Every step carries an optional `note`, which is where the comments that used to
sit in this module's Python went. "480 s at the table's 0.0833 nm/s is 40 nm of
chromium" is the reason for a number, and the one place it is worth anything is
next to the number, in the file somebody is editing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from nanofab_v3 import paths
from nanofab_v3.io.manifest import grid_from_json, grid_to_json
from nanofab_v3.model.grid import Grid
from nanofab_v3.runtime.run import RecipeStep

DEMOS_SUBDIR = ("data", "demos")
"""Where the shipped demo files sit, relative to the `nanofab_v3` package root."""

DEMOS_ENV = "NANOFAB_DEMOS"
"""Environment variable that replaces the writable root, for tests and for tools."""

SCHEMA_VERSION = 1
"""Version of the demo file format; a file that declares another one is refused."""


@dataclass(frozen=True)
class Demo:
    """One runnable recipe, and what somebody is supposed to see in it.

    Attributes:
        key: Stable id, what a menu action carries.
        title: The menu entry.
        summary: One line, for the menu's tooltip.
        watch_for: What to look at while it runs, and what it would look like if
            the mechanism it demonstrates were absent. The reason a demo is worth
            more than a screenshot.
        grid: The domain it needs.
        steps: The chain, in order.
    """

    key: str
    title: str
    summary: str
    watch_for: str
    grid: Grid
    steps: tuple[RecipeStep, ...] = ()
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Pad `notes` to the steps, so index `i` is always step `i`'s reason.

        A parallel tuple rather than a mapping, because JSON object keys are
        strings and `{"3": "..."}` next to a list of steps is an invitation to
        misalign the two by one. Padding here means a file may leave `note` off
        every step, most of them, or none.
        """
        if len(self.notes) > len(self.steps):
            raise ValueError(
                f"demo {self.key!r} has {len(self.notes)} notes for {len(self.steps)} steps"
            )
        object.__setattr__(
            self, "notes", self.notes + ("",) * (len(self.steps) - len(self.notes))
        )

    def describe(self) -> str:
        """Title, summary and what to watch for — what the run log gets."""
        return f"{self.title} — {self.summary}\n{self.watch_for}"

    def note(self, index: int) -> str:
        """Why step `index` has the numbers it has, or `""` if the file says nothing."""
        return self.notes[index] if 0 <= index < len(self.notes) else ""


def _step(step_id: str, **params: object) -> RecipeStep:
    return RecipeStep(step_id, dict(params))


# -- the file format ----------------------------------------------------------


class DemoFileError(ValueError):
    """A demo file that cannot be read, naming the file and what is wrong with it."""


def to_dict(entry: Demo) -> dict[str, Any]:
    """One demo as plain JSON values, `note` written only where there is one."""
    steps: list[dict[str, Any]] = []
    for index, step in enumerate(entry.steps):
        written: dict[str, Any] = {"step_id": step.step_id, "params": dict(step.params)}
        if entry.note(index):
            written["note"] = entry.note(index)
        steps.append(written)
    return {
        "schema_version": SCHEMA_VERSION,
        "key": entry.key,
        "title": entry.title,
        "summary": entry.summary,
        "watch_for": entry.watch_for,
        "grid": grid_to_json(entry.grid),
        "steps": steps,
    }


def from_dict(data: Mapping[str, Any]) -> Demo:
    """Rebuild a `Demo`, refusing another schema and any field this version cannot use.

    Unknown fields are an error rather than ignored — the opposite of §9's rule for
    a *revision* file, and for the opposite reason. A revision is written by this
    program and read by a later one, so tolerance is forward compatibility; a demo
    is written by a person in a text editor, where a silently ignored `duration`
    typed as `durration` is a demo that quietly does the wrong thing.
    """
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise DemoFileError(
            f"this file declares schema_version {version!r}; {SCHEMA_VERSION} is what "
            "this version of nanofab_v3 reads"
        )
    known = {"schema_version", "key", "title", "summary", "watch_for", "grid", "steps"}
    unknown = sorted(set(data) - known)
    if unknown:
        raise DemoFileError(f"unknown field(s) {unknown} in a demo; it takes {sorted(known)}")
    for required in ("key", "title", "grid"):
        if required not in data:
            raise DemoFileError(f"a demo needs a {required!r}")
    steps: list[RecipeStep] = []
    notes: list[str] = []
    for position, entry in enumerate(data.get("steps", ())):
        extra = sorted(set(entry) - {"step_id", "params", "note"})
        if extra:
            raise DemoFileError(
                f"unknown field(s) {extra} in step {position}; a step takes "
                "['note', 'params', 'step_id']"
            )
        if "step_id" not in entry:
            raise DemoFileError(f"step {position} has no step_id")
        steps.append(RecipeStep(str(entry["step_id"]), dict(entry.get("params", {}))))
        notes.append(str(entry.get("note", "")))
    return Demo(
        key=str(data["key"]),
        title=str(data["title"]),
        summary=str(data.get("summary", "")),
        watch_for=str(data.get("watch_for", "")),
        grid=grid_from_json(data["grid"]),
        steps=tuple(steps),
        notes=tuple(notes),
    )


def read_demo(path: str | Path) -> Demo:
    """One demo from one file, with the file named in whatever goes wrong."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DemoFileError(f"{path}: {error}") from None
    if not isinstance(data, dict):
        raise DemoFileError(f"{path}: a demo file holds one JSON object")
    try:
        return from_dict(data)
    except (DemoFileError, ValueError, KeyError, TypeError) as error:
        raise DemoFileError(f"{path}: {error}") from None


def write_demo(directory: str | Path, entry: Demo) -> Path:
    """Write `entry` to `<directory>/<key>.json`, creating the directory."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{entry.key}.json"
    target.write_text(json.dumps(to_dict(entry), indent=2) + "\n", encoding="utf-8")
    return target


# -- where they live ----------------------------------------------------------


def builtin_demos_dir() -> Path:
    """The shipped demo directory — inside the package, in every install form.

    The same two-candidate lookup as `materials.store.builtin_materials_dir()`,
    for the same reason: `importlib.resources` answers for a zip import and for a
    frozen loader with a resource reader, and the package directory answers under
    PyInstaller's one-file unpacking. Both are checked rather than one assumed.
    """
    try:
        from importlib import resources

        candidate = Path(str(resources.files("nanofab_v3").joinpath(*DEMOS_SUBDIR)))
        if candidate.is_dir():
            return candidate
    except (ImportError, ModuleNotFoundError, TypeError, OSError):  # pragma: no cover
        pass
    return Path(__file__).resolve().parent.parent.joinpath(*DEMOS_SUBDIR)


def user_demos_dir() -> Path | None:
    """The editable demo directory, or `None` when there is not one.

    `$NANOFAB_DEMOS`, else `data/demos/` next to a frozen executable. Unlike the
    material library this has **no** home-directory fallback: a material an
    operator invented has to survive a reinstall, and a demo is a worked example
    that ships with the program. Somewhere under `~/.local/share` is not where
    anybody would look for one.
    """
    import os

    override = os.environ.get(DEMOS_ENV)
    if override:
        return Path(override)
    return paths.portable_dir(*DEMOS_SUBDIR)


def demo_roots() -> tuple[Path, ...]:
    """The directories a demo is looked for in, shipped first and editable last.

    A delivered build has **no** shipped root (roadmap E19: the packaged copy is
    gone, so that there is only ever one file per demo), which is why a directory
    that is not there is dropped rather than read as empty. The consequence is the
    one E19 chose: a delivery whose `data/demos/` is missing opens with an empty
    Demos menu, where a missing `data/materials/` stops the program. The
    difference is what each absence costs — a demo is a worked example and the
    library is the physics.
    """
    import os

    editable = user_demos_dir()
    if paths.frozen() and not os.environ.get(DEMOS_ENV):
        return () if editable is None else (editable,)
    shipped = builtin_demos_dir()
    return (shipped,) if editable is None or editable == shipped else (shipped, editable)


@dataclass(frozen=True)
class DemoReport:
    """What a load found — the counterpart of `materials.store.LibraryReport`.

    Lenient for the same reason and with the same shape: one unparseable file
    costs that demo and nothing else, because a picker with no entries because of
    a stray comma is worse than a picker missing the entry somebody broke.
    """

    roots: tuple[Path, ...] = ()
    loaded: Mapping[str, Path] = field(default_factory=dict)
    failures: tuple[tuple[Path, str], ...] = ()

    def describe(self) -> tuple[str, ...]:
        """One line per finding, for a run log or `--version`."""
        lines = [f"demos: {len(self.loaded)} from {len(self.roots)} root(s)"]
        lines += [f"  root: {root}" for root in self.roots]
        lines += [f"  skipped {path.name}: {reason}" for path, reason in self.failures]
        return tuple(lines)


def load_demos(roots: Sequence[Path] | None = None) -> tuple[tuple[Demo, ...], DemoReport]:
    """Every demo in `roots`, a later root shadowing an earlier one by key.

    Ordered by filename, which is why the shipped files carry a numeric prefix
    (`01_lift_off.json`) while `write_demo` writes a plain `<key>.json`: the menu
    keeps the order somebody chose for it, and a demo an operator drops in beside
    the exe lands at the end instead of reshuffling the four. A key already seen
    keeps its position and takes the later file's content, which is what makes an
    edited `03_titania_stop.json` beside the exe *replace* the packaged one rather
    than appear twice.
    """
    used = tuple(roots) if roots is not None else demo_roots()
    found: dict[str, Demo] = {}
    where: dict[str, Path] = {}
    order: list[str] = []
    failures: list[tuple[Path, str]] = []
    for root in used:
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.json")):
            try:
                entry = read_demo(path)
            except DemoFileError as error:
                failures.append((path, str(error).split(": ", 1)[-1]))
                continue
            if entry.key not in found:
                order.append(entry.key)
            found[entry.key] = entry
            where[entry.key] = path
    return (
        tuple(found[key] for key in order),
        DemoReport(roots=used, loaded=where, failures=tuple(failures)),
    )


# -- the demos themselves -----------------------------------------------------


_LOADED: tuple[tuple[Demo, ...], DemoReport] | None = None


def _cached() -> tuple[tuple[Demo, ...], DemoReport]:
    """Load once. A menu is built on every window and the files do not move."""
    global _LOADED
    if _LOADED is None:
        _LOADED = load_demos()
    return _LOADED


def invalidate_cache() -> None:
    """Forget the loaded demos — for tests, and after writing a file."""
    global _LOADED
    _LOADED = None


def demos() -> tuple[Demo, ...]:
    """Every demo the picker offers, in the order it offers them.

    Lift-off first because it is the one the application has always opened with
    and the one the acceptance scenarios are written around; the three the
    roadmap names after it, in increasing order of how much of the model they
    lean on. The order is the shipped root's, so dropping a file beside the exe
    adds an entry at the end rather than reshuffling the menu.
    """
    return _cached()[0]


def report() -> DemoReport:
    """Where the demos came from and which files did not parse."""
    return _cached()[1]


def demo(key: str) -> Demo:
    """One demo by key."""
    for entry in demos():
        if entry.key == key:
            return entry
    raise ValueError(f"no demo {key!r}; there are {sorted(e.key for e in demos())}")


def lift_off() -> Demo:
    """S1, which is what the application has always opened with."""
    return demo("lift_off")


def chrome_hard_mask_grating() -> Demo:
    """A fused-silica grating patterned through a chromium hard mask."""
    return demo("chrome_grating")


def titania_grating_on_an_etch_stop() -> Demo:
    """A TiO2 grating that stops on a thin alumina layer."""
    return demo("titania_stop")


def black_silicon() -> Demo:
    """Micromasking, the mechanism S5 already proves, as a surface rather than a defect."""
    return demo("black_silicon")


def __getattr__(name: str) -> object:
    """`DEMOS` as a module attribute, resolved on first use rather than at import.

    It was a tuple built at import time until M9's follow-up moved the recipes to
    disk. Keeping the name means `from nanofab_v3.ui.demos import DEMOS` still
    works; making it lazy means importing this module no longer reads four files —
    which matters because `ui.session` imports it for `demo_recipe()` and a
    headless test should not touch the filesystem to find out what a lift-off is.
    """
    if name == "DEMOS":
        return demos()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "DEMOS_ENV",
    "DEMOS_SUBDIR",
    "SCHEMA_VERSION",
    "Demo",
    "DemoFileError",
    "DemoReport",
    "black_silicon",
    "builtin_demos_dir",
    "chrome_hard_mask_grating",
    "demo",
    "demo_roots",
    "demos",
    "from_dict",
    "invalidate_cache",
    "lift_off",
    "load_demos",
    "read_demo",
    "report",
    "titania_grating_on_an_etch_stop",
    "to_dict",
    "user_demos_dir",
    "write_demo",
]
