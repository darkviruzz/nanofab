"""Presets and what happens to the fields they fill in (roadmap M7, item 2).

The handoff asks for this **generically** rather than as a substrate special
case, and names the reason: resist presets and etch recipes are coming, and a
rule about overwriting somebody's typing should exist once. So nothing here
knows what a substrate is. A `PresetOption` is a labelled bundle of parameter
values; `apply_preset` decides which of them may be written silently and which
have to be asked about; `PRESET_SOURCES` is where a step says it has some.

**The rule, and the whole of it:** a field the operator has *changed by hand* is
theirs, and a preset may not take it back without asking. Everything else the
preset fills in silently. That is the difference between a preset that helps and
one that has to be fought — and it is only expressible if the form tracks which
fields were touched, which is why `touched` is an argument here rather than
something guessed from whether a value differs from its default. A value that
happens to equal what somebody typed is not the same fact as a value they typed.

Qt-free, like `ui.scene`, `ui.session` and `ui.wafer`: everything that decides is
on this side of ADR-0001's line and `ui.panels` only renders the decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class PresetOption:
    """One entry of a preset list: what it is called and what it sets.

    Attributes:
        key: Stable id — what the recipe parameter stores.
        label: What the dropdown shows.
        section: Heading it sits under, `""` for an ungrouped list. E3's
            two-section substrate dropdown is this and nothing more.
        values: `{parameter: value}` this preset drives. A parameter the form
            does not have is ignored, so a preset may name more than one step's
            worth of fields without knowing which form it lands in.
    """

    key: str
    label: str
    section: str = ""
    values: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PresetApplication:
    """What choosing a preset would do to a form, split by whether it may be silent.

    Attributes:
        silent: `{parameter: value}` to write without asking — untouched fields,
            and fields that already hold the value anyway.
        conflicts: `{parameter: (what is there, what the preset wants)}` for
            fields the operator changed by hand. These are the questions.
        missing: Parameters the preset names that this form does not have.
            Reported rather than dropped, because a preset that silently sets
            nothing looks exactly like one that worked.
    """

    silent: Mapping[str, Any] = field(default_factory=dict)
    conflicts: Mapping[str, tuple[Any, Any]] = field(default_factory=dict)
    missing: tuple[str, ...] = ()

    @property
    def needs_asking(self) -> bool:
        """Whether anything here would overwrite something somebody typed."""
        return bool(self.conflicts)

    def resolved(self, overwrite: Iterable[str] = ()) -> dict[str, Any]:
        """The values to write, given which conflicts the operator agreed to.

        `overwrite` is the subset of `conflicts` they said yes to; everything not
        named keeps what it has. Answering nothing is therefore the safe default,
        which is the right way round for a question about losing work.
        """
        values = dict(self.silent)
        agreed = set(overwrite)
        for name, (_, proposed) in self.conflicts.items():
            if name in agreed:
                values[name] = proposed
        return values

    def describe(self) -> tuple[str, ...]:
        """One line per question, for a dialog or a log."""
        return tuple(
            f"{name}: keep {current!r} or take the preset's {proposed!r}?"
            for name, (current, proposed) in sorted(self.conflicts.items())
        )


def apply_preset(
    option: PresetOption,
    current: Mapping[str, Any],
    touched: Iterable[str] = (),
) -> PresetApplication:
    """Split a preset's values into what may be written and what must be asked.

    `current` is what the form holds now; `touched` is the set of parameters the
    operator has edited themselves. A touched field whose value the preset agrees
    with is *not* a conflict — there is nothing to lose — which keeps the dialog
    for the cases that are really questions.
    """
    edited = set(touched)
    silent: dict[str, Any] = {}
    conflicts: dict[str, tuple[Any, Any]] = {}
    missing: list[str] = []
    for name, proposed in option.values.items():
        if name not in current:
            missing.append(name)
            continue
        existing = current[name]
        if name in edited and not _same(existing, proposed):
            conflicts[name] = (existing, proposed)
        else:
            silent[name] = proposed
    return PresetApplication(
        silent=silent, conflicts=conflicts, missing=tuple(sorted(missing))
    )


def _same(left: Any, right: Any) -> bool:
    """Whether two form values are the same to the precision a form has.

    A form's numbers come back through a spin box, so `1.0` and `0.9999999` are
    the same answer typed twice. Comparing them exactly would raise a question
    about a field nobody actually disagrees on.
    """
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        if isinstance(left, bool) or isinstance(right, bool):
            return bool(left) == bool(right)
        return abs(float(left) - float(right)) <= 1e-9 * max(1.0, abs(float(right)))
    return left == right


def grouped(options: Sequence[PresetOption]) -> dict[str, tuple[PresetOption, ...]]:
    """`{section: options}` in the order the sections first appear."""
    sections: dict[str, list[PresetOption]] = {}
    for option in options:
        sections.setdefault(option.section, []).append(option)
    return {section: tuple(entries) for section, entries in sections.items()}


# -- who has presets ----------------------------------------------------------

PresetSource = Callable[[], tuple[PresetOption, ...]]
"""A function returning the options for one `(step_id, parameter)` pair."""


def substrate_options() -> tuple[PresetOption, ...]:
    """`processes.substrate.SUBSTRATE_PRESETS` as form values (E2, E3).

    The adapter, and the only place in the UI that knows a substrate has a
    diameter. Sorting and sectioning are the table's, not this function's — E3's
    order is decided once, where the table is (see `SUBSTRATE_PRESETS`).
    """
    from nanofab_v3.processes.substrate import SUBSTRATE_PRESETS

    options = []
    for preset in SUBSTRATE_PRESETS:
        values: dict[str, Any] = {
            "material": str(preset.material),
            "form_factor": preset.form_factor,
            # Millimetres, because that is the unit the form's own `ParamSpec`
            # declares — a preset fills a form, it does not convert for it.
            "thickness": preset.thickness_mm,
            "diameter": 0.0 if preset.diameter_mm is None else preset.diameter_mm,
            "size_x": 0.0 if preset.side_mm is None else preset.side_mm,
            "size_y": 0.0 if preset.side_mm is None else preset.side_mm,
            "domain_width": preset.domain.width,
            "headroom": preset.domain.headroom,
            "spacing": preset.domain.spacing,
        }
        options.append(
            PresetOption(
                key=preset.key,
                label=preset.label,
                section="Wafers" if preset.section == "wafer" else "Mask blanks",
                values=values,
            )
        )
    return tuple(options)


PRESET_SOURCES: dict[tuple[str, str], PresetSource] = {
    ("substrate.select", "preset"): substrate_options,
}
"""`{(step_id, parameter): source}` — where a form looks for a dropdown.

A registry rather than a flag on `ParamSpec`, because a preset list is a *UI*
fact: the same parameter is a plain string to a recipe file, to the engine and to
a plugin host, and only a form needs to know there is a menu behind it. Adding
resist presets later is one entry here and one adapter beside `substrate_options`.
"""


def options_for(step_id: str, parameter: str) -> tuple[PresetOption, ...]:
    """The preset options for one parameter of one step, or `()` when it has none."""
    source = PRESET_SOURCES.get((step_id, parameter))
    return () if source is None else tuple(source())
