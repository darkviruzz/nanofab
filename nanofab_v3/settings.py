"""`settings.ini` — what the *application* does, never what the physics is (E39).

The fourth thing in a delivered folder, beside the executable, `bin/` and
`data/`. It answers questions of the form "what is switched on when I start" and
"what number is already in the box", and deliberately none of the form "how fast
does chromium etch" — that is the material library, one directory away, and a
second place to change a rate would be exactly the two-truths problem E19 spent
the packaged copy to avoid.

Three rules, and each is a decision:

- **Prefill, not prescription.** `[parameters]` puts a number into a form field.
  The moment a step runs, the *resolved* value is written into the recipe
  (`Session.run` records what the form said), so a recipe saved on one machine
  runs identically on another whatever that machine's ini says. Plan §5.2 and
  ADR-0004 are what this is protecting: a recipe is reproducible or it is
  nothing. A settings file that reached the solver instead of the form would make
  every recipe a statement about the computer it was written on.
- **Never written back.** Toggles flipped at runtime stay at runtime. A file that
  rewrote itself would lose its comments the first time somebody ticked a box,
  and the comments are most of what it is for.
- **Value and visibility are separate.** Every view toggle and overlay has its
  startup value plus a `_hidden` switch. Hidden controls still apply their value;
  they merely stop the UI from changing it.
- **Complete and self-documenting.** `default_ini_text()` renders **every**
  setting with its default and a sentence about it, from the same table
  `parse()` reads, so the file cannot drift from the code that consumes it. The
  build writes that text into the delivered folder, and a start that finds the
  file missing writes it again — deleting `settings.ini` is how you ask for the
  documented defaults back.

`nanofab_v3.spec` writes the file at build time; `ensure_delivered_settings()`
restores it at startup. Outside a frozen build there is no file at all unless
`$NANOFAB_SETTINGS` names one — a checkout that quietly read an ini from the
working directory is the same trap `paths.portable_root()` refuses for the
library.
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from nanofab_v3 import paths

SETTINGS_ENV = "NANOFAB_SETTINGS"
"""Environment variable naming the settings file, for tests and for tools."""

PARAMETERS_SECTION = "parameters"
"""Section of `<step_id>.<parameter> = value` prefills — free-form, so not in `KEYS`."""


@dataclass(frozen=True)
class SettingSpec:
    """One documented key: where it lives, what it is, and why anybody would touch it."""

    section: str
    key: str
    kind: type
    default: Any
    comment: str
    choices: tuple[str, ...] | None = None

    @property
    def name(self) -> str:
        return f"{self.section}.{self.key}"

    def render(self, value: Any) -> str:
        """The value as it is written into the file."""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (tuple, list)):
            return ", ".join(str(item) for item in value)
        return str(value)

    def parse(self, raw: str) -> Any:
        """One raw string from the file, as the value the application uses.

        A value this cannot read falls back to the default rather than raising.
        A hand-edited ini is the one file in the delivery an operator is *invited*
        to break, and refusing to start over a stray word in it would make the
        invitation a trap. What it costs is reported by `Settings.problems`, so a
        typo is visible rather than merely survived.
        """
        text = raw.strip()
        if self.kind is bool:
            if text.lower() in ("true", "yes", "on", "1"):
                return True
            if text.lower() in ("false", "no", "off", "0"):
                return False
            raise ValueError(f"{self.name}: {raw!r} is not a yes/no value")
        if self.kind is tuple:
            return tuple(part.strip() for part in text.split(",") if part.strip())
        if self.kind is float:
            return float(text)
        if self.kind is int:
            return int(text)
        if self.choices is not None and text not in self.choices:
            raise ValueError(f"{self.name}: {raw!r} is not one of {list(self.choices)}")
        return text


def _view_toggle(key: str, default: bool, comment: str) -> tuple[SettingSpec, SettingSpec]:
    """A view value and the independent switch that removes its UI control."""
    return (
        SettingSpec("view", key, bool, default, comment),
        SettingSpec(
            "view",
            f"{key}_hidden",
            bool,
            False,
            f"Hide the '{key}' control while still applying its configured value.\n"
            "True locks the view to that value; false lets the UI change it.",
        ),
    )


KEYS: tuple[SettingSpec, ...] = (
    *_view_toggle(
        "overlay_exposed",
        True,
        "Show the binary exposed-field overlay at startup. On by default because\n"
        "an exposure result should not need a second action to become visible.",
    ),
    *_view_toggle(
        "overlay_dose",
        True,
        "Show the continuous dose-field overlay at startup. On by default because\n"
        "it is the didactic result of dose-based exposure.",
    ),
    *_view_toggle(
        "overlay_reachable",
        False,
        "Compute and show the reachability predicate overlay at startup.",
    ),
    *_view_toggle(
        "overlay_unsupported",
        False,
        "Compute and show the unsupported-material predicate overlay at startup.",
    ),
    *_view_toggle(
        "overlay_normals",
        False,
        "Compute and show surface-normal vectors at startup.",
    ),
    *_view_toggle(
        "overlay_voids",
        False,
        "Compute and show the enclosed-void predicate overlay at startup.",
    ),
    SettingSpec(
        "view",
        "picture",
        str,
        "contours",
        "Which picture of the sample to start with. 'contours' is the sub-cell\n"
        "outline the renderer derives; 'cell_grid' paints material_index directly,\n"
        "one pixel per cell — the honest picture of what the model stores.",
        choices=("contours", "cell_grid"),
    ),
    SettingSpec(
        "view",
        "picture_hidden",
        bool,
        False,
        "Hide the contours/cell-grid selector while still applying `picture`.\n"
        "True locks the application to the configured picture mode.",
    ),
    *_view_toggle(
        "true_to_scale",
        False,
        "Draw the domain 1:1 whatever its aspect ratio. Off by default because a\n"
        "very deep or very narrow domain is otherwise a sliver; the compression\n"
        "factor is shown in the picture either way, so it is never silent.",
    ),
    *_view_toggle(
        "light_preview",
        False,
        "Draw where the light would fall, from the mask parameters in the form,\n"
        "before the exposure runs. Only while a litho step is selected.",
    ),
    *_view_toggle(
        "wafer_map",
        False,
        "Show the wafer-position map at startup.",
    ),
    SettingSpec(
        "view",
        "preview_scale_px_per_nm",
        float,
        20.0,
        "Absolute scale for process-preview arrows in pixels per nanometre. The\n"
        "same value applies to every step, so arrow lengths remain comparable;\n"
        "arrows shorter than 5 px become a note instead of being exaggerated.\n"
        "Set this to 0.0 to disable process-preview geometry completely.",
    ),
    SettingSpec(
        "session",
        "autosave",
        bool,
        True,
        "Write the recipe (not the computed structures) after every step, so a\n"
        "crash costs the arithmetic and not the work. About a kilobyte, written\n"
        "atomically; roadmap E38 records why the structures stay in the replay\n"
        "cache instead.",
    ),
    SettingSpec(
        "session",
        "restore_prompt",
        bool,
        True,
        "Ask at startup whether to reopen the autosaved recipe. The answer only\n"
        "ever *loads* it — nothing is recomputed until you say so, so a recipe\n"
        "whose replay crashes cannot stop the program from starting.",
    ),
    SettingSpec(
        "session",
        "start_demo",
        str,
        "",
        "Demo to load into the window at startup, by key (see data/demos/). Empty\n"
        "means start on an empty domain. Loading is all it does: the steps are\n"
        "listed and Session -> Run the loaded recipe computes them.",
    ),
    SettingSpec(
        "log",
        "verbosity",
        str,
        "normal",
        "How much each step writes into the run log. 'quiet' is the one headline\n"
        "line per step; 'normal' adds what the step said, what it measured and\n"
        "what happened to the occurrences; 'verbose' adds the parameters it\n"
        "actually ran with and the commit gate's report.",
        choices=("quiet", "normal", "verbose"),
    ),
    SettingSpec(
        "domain",
        "cap_um",
        float,
        5.0,
        "How tall the domain may grow, in micrometres (roadmap E5). The window\n"
        "offers to raise it when a step hits it, with the memory cost named; this\n"
        "is where the offer starts from.",
    ),
)
"""Every documented key. `[parameters]` is free-form and handled separately."""

_BY_NAME = {spec.name: spec for spec in KEYS}


@dataclass(frozen=True)
class Settings:
    """What the ini said, with every key present whether the file mentioned it or not.

    Attributes:
        values: `{"section.key": value}` for every entry of `KEYS`.
        prefills: `{step_id: {parameter: raw string}}` from `[parameters]`.
        source: The file this came from, or `None` for the built-in defaults.
        problems: Lines describing what could not be read — a misspelt key, an
            unparseable value. Reported rather than raised: see `SettingSpec.parse`.
    """

    values: Mapping[str, Any] = field(default_factory=dict)
    prefills: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    source: Path | None = None
    problems: tuple[str, ...] = ()

    def __getitem__(self, name: str) -> Any:
        return self.values[name]

    def get(self, name: str, default: Any = None) -> Any:
        return self.values.get(name, default)

    def prefill(self, step_id: str) -> dict[str, str]:
        """The `[parameters]` entries for one step, as raw strings.

        Raw, because a `ParamSpec` is what knows how to read them — `float`,
        `int`, `str` and `bool` are the step's decision and this file has no
        business having a second opinion about which one a number is.
        """
        return dict(self.prefills.get(step_id, {}))

    def describe(self) -> tuple[str, ...]:
        """Lines for `--version` and for the run log."""
        where = "built-in defaults" if self.source is None else str(self.source)
        lines = [f"settings: {where}"]
        lines += [f"settings: {problem}" for problem in self.problems]
        return tuple(lines)


def defaults() -> Settings:
    """The settings a build with no file uses — the same values the file documents."""
    return Settings(values={spec.name: spec.default for spec in KEYS})


def default_ini_text() -> str:
    """The whole file, with every key, its default and a comment (E39).

    Rendered from `KEYS`, which is also what `parse()` reads, so the documentation
    and the behaviour cannot come apart. That is the point of generating it rather
    than keeping a hand-written template next to the code: a template is a second
    copy of the defaults, and a second copy is a copy that goes stale.
    """
    lines = [
        "# NanoFab — application settings.",
        "#",
        "# What is switched on, what is already in the box, and where the session",
        "# picks up. **Not physics**: rates, yields and develop models live in",
        "# data/materials/, one directory over, and this file has no opinion about",
        "# them.",
        "#",
        "# Every value below is the default; deleting the file gives you this text",
        "# back on the next start. Nothing is ever written back into it, so a",
        "# checkbox ticked while the program runs stays ticked only until it closes.",
        "",
    ]
    section = ""
    for spec in KEYS:
        if spec.section != section:
            section = spec.section
            lines.append(f"[{section}]")
        for comment in spec.comment.splitlines():
            lines.append(f"# {comment}" if comment else "#")
        if spec.choices:
            lines.append(f"# one of: {', '.join(spec.choices)}")
        lines.append(f"{spec.key} = {spec.render(spec.default)}")
        lines.append("")
    lines += [
        f"[{PARAMETERS_SECTION}]",
        "# Prefills for process parameters, as <step_id>.<parameter> = <value>.",
        "# They fill the form; they do not overrule anything. Every step writes the",
        "# values it actually ran with into the recipe, so a recipe saved here runs",
        "# the same on a machine whose file says something else (plan §5.2).",
        "#",
        "# Examples — remove the leading '#' to use them:",
        "# etch.icp_fluorine.duration = 120",
        "# deposit.evaporate.thickness = 80",
        "#",
        "# Delivered E34 uniformity prefills. These repeat the step-schema defaults",
        "# deliberately: edit them here to prefill every new form on this tool.",
        "deposit.evaporate.uniformity_percent = 5",
        "deposit.sputter.uniformity_percent = 8",
        "deposit.sputter_rate.uniformity_percent = 8",
        "deposit.ald.uniformity_percent = 2",
        "etch.wet.uniformity_percent = 2",
        "etch.rie.uniformity_percent = 5",
        "etch.icp_fluorine.uniformity_percent = 5",
        "etch.rie_chlorine.uniformity_percent = 5",
        "etch.rie_oxygen.uniformity_percent = 5",
        "etch.wet_cr.uniformity_percent = 2",
        "etch.wet_oxide.uniformity_percent = 2",
        "etch.ion_beam.uniformity_percent = 8",
        "",
    ]
    return "\n".join(lines)


def parse(text: str, *, source: Path | None = None) -> Settings:
    """Read an ini's text into a `Settings`, keeping every default it does not set."""
    values: dict[str, Any] = {spec.name: spec.default for spec in KEYS}
    prefills: dict[str, dict[str, str]] = {}
    problems: list[str] = []
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(text)
    except configparser.Error as error:
        return Settings(values=values, source=source, problems=(f"unreadable: {error}",))
    for section in parser.sections():
        for key, raw in parser.items(section):
            if section == PARAMETERS_SECTION:
                step_id, _, parameter = key.rpartition(".")
                if not step_id:
                    problems.append(f"[{section}] {key}: expected <step_id>.<parameter>")
                    continue
                prefills.setdefault(step_id, {})[parameter] = raw.strip()
                continue
            spec = _BY_NAME.get(f"{section}.{key}")
            if spec is None:
                problems.append(f"[{section}] {key} is not a setting this build reads")
                continue
            try:
                values[spec.name] = spec.parse(raw)
            except (TypeError, ValueError) as error:
                problems.append(f"{error}; keeping {spec.render(spec.default)}")
    return Settings(
        values=values, prefills=prefills, source=source, problems=tuple(problems)
    )


def settings_path() -> Path | None:
    """The ini this build reads, or `None` when there is none to read."""
    override = os.environ.get(SETTINGS_ENV)
    if override:
        candidate = Path(override)
        return candidate if candidate.is_file() else None
    return paths.portable_file(paths.SETTINGS_FILE)


def load(path: Path | None = None) -> Settings:
    """The settings this build runs on: the file's, or the documented defaults."""
    target = settings_path() if path is None else Path(path)
    if target is None or not target.is_file():
        return defaults()
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as error:  # pragma: no cover - depends on the machine
        return Settings(
            values={spec.name: spec.default for spec in KEYS},
            source=None,
            problems=(f"cannot read {target}: {error}",),
        )
    return parse(text, source=target)


def write_default_ini(path: Path) -> Path:
    """Write `default_ini_text()` to `path` — the build's job, and a repair."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(default_ini_text(), encoding="utf-8")
    return path


def ensure_delivered_settings() -> Path | None:
    """Put `settings.ini` back beside a delivered executable if it is gone.

    The one thing this module writes, and it writes the *defaults* — never the
    current state. A file somebody deleted is a request for the documented
    version; a file somebody edited is never touched.
    """
    root = paths.portable_root()
    if root is None:
        return None
    target = root / paths.SETTINGS_FILE
    if target.exists():
        return target
    try:
        return write_default_ini(target)
    except OSError:  # pragma: no cover - a read-only delivery is legitimate
        return None


_CACHE: list[Settings] = []


def application_settings() -> Settings:
    """The loaded settings, read once per process."""
    if not _CACHE:
        _CACHE.append(load())
    return _CACHE[0]


def invalidate_cache() -> None:
    """Forget the loaded settings — for tests, and after writing the file."""
    _CACHE.clear()


def overlay_names(settings: Settings, known: Sequence[str]) -> tuple[str, ...]:
    """Known overlays whose independent `[view]` startup switches are on."""
    return tuple(
        name
        for name in known
        if bool(settings.get(f"view.overlay_{name}", name in ("exposed", "dose")))
    )


__all__ = [
    "KEYS",
    "PARAMETERS_SECTION",
    "SETTINGS_ENV",
    "SettingSpec",
    "Settings",
    "application_settings",
    "default_ini_text",
    "defaults",
    "ensure_delivered_settings",
    "invalidate_cache",
    "load",
    "overlay_names",
    "parse",
    "settings_path",
    "write_default_ini",
]
