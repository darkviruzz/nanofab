"""An unknown material warns and asks, instead of quietly etching at zero (E15).

The failure this module exists to end, from a real project: a **chromium
particle** on a sample the library had never heard of. Every rate lookup skipped
it — `processes.rates` filters on `material in library` — so it sat there at rate
0 through every process, behaving exactly like a perfect hard mask, and nothing
anywhere said a word. The picture was wrong and looked right, which is the worst
shape a didactic tool can fail in.

**Free text stays legal.** That is not a compromise, it is the didactic point:
being able to drop `tungsten` into a scene and see what happens before anybody
has measured it is worth keeping, and plan §5.4 already lets a plugin bring a
material the library has never seen. What ends is the *silence*. So:

- a material in a `Structure` that the library cannot answer for produces an
  `UnknownMaterialWarning` and a line in the run log, once per step;
- `MissingMaterial` below says what would have to be answered to fix it, in a
  form a dialog can render and a headless caller can print;
- the answer is written to `data/materials/` as an ordinary file
  (`store.save_material`), so the next session simply knows it.

**A missing *rate* is not this.** `MaterialType.rate_for` answering 0.0 for a
process class a material has no entry for is a deliberate, documented statement —
"this does not move" — and it is how a hard mask behaves without being modelled
as one. Warning about it would fire on nearly every step and teach everybody to
ignore the warnings. The difference is exactly whether the library was asked and
had an answer, or was never able to be asked at all.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from nanofab_v3.materials.library import MaterialLibrary
from nanofab_v3.materials.material import PROCESS_CLASSES, MaterialId, MaterialType


class UnknownMaterialWarning(UserWarning):
    """A `Structure` carries a material the `MaterialLibrary` cannot answer for."""


@dataclass(frozen=True)
class MissingMaterial:
    """One unknown material, and what would have to be said about it.

    A value rather than a dialog, so the same object serves the Qt shell, a
    headless run log and a test. `ui.material_dialog` renders it; nothing here
    imports Qt (ADR-0001's rule: whatever decides is on this side of the line).

    Attributes:
        material_id: The id the structure used.
        seen_in: Where it turned up — a step id, normally.
        process_classes: The rate keys worth asking about. All of them by
            default; a caller that knows the step only reads one may narrow it,
            which is the difference between a form with thirteen fields and one
            with the field that matters.
    """

    material_id: MaterialId
    seen_in: str = ""
    process_classes: tuple[str, ...] = PROCESS_CLASSES

    def question(self) -> str:
        """The sentence a warning or a dialog leads with."""
        where = f" during {self.seen_in}" if self.seen_in else ""
        return (
            f"no MaterialType {self.material_id!r} in this library{where}: every rate "
            "for it reads 0, so it behaves like a perfect mask. Describe it, or pick a "
            "material the library knows."
        )

    def draft(
            self,
            *,
            name: str | None = None,
            display_color: str = "#808080",
            rates: Mapping[str, float] | None = None,
            notes: str = "",
    ) -> MaterialType:
        """A `MaterialType` from the answers, ready for `store.save_material`.

        The dataclass validates, as everywhere else (`schema.from_dict` leans on
        the same thing): a negative rate or an unknown process class fails here
        rather than becoming a file somebody has to find later.
        """
        return MaterialType(
            material_id=self.material_id,
            name=name or str(self.material_id).replace("_", " ").capitalize(),
            display_color=display_color,
            rates=dict(rates or {}),
            notes=notes
                  or (
                      "Added from the unknown-material prompt (roadmap E15). Uncalibrated: "
                      "nothing here came from a measurement or from the process table."
                  ),
        )


class MissingMaterialsError(RuntimeError):
    """A step named materials that must be described before it can run (E31).

    The engine raises this value before calling the step.  It carries the
    Qt-free questions so an interactive shell can ask them, while a headless
    caller gets the same refusal and enough information to resolve it.
    """

    def __init__(self, missing: Sequence[MissingMaterial]) -> None:
        self.missing = tuple(missing)
        super().__init__("; ".join(entry.question() for entry in self.missing))


@dataclass(frozen=True)
class UnknownMaterials:
    """Every unknown material one step met, with the lines that report them."""

    missing: tuple[MissingMaterial, ...] = ()
    seen_in: str = ""

    def __bool__(self) -> bool:
        return bool(self.missing)

    def __iter__(self):
        return iter(self.missing)

    def __len__(self) -> int:
        return len(self.missing)

    @property
    def ids(self) -> tuple[MaterialId, ...]:
        return tuple(entry.material_id for entry in self.missing)

    def describe(self) -> tuple[str, ...]:
        """Lines for the run log — one per material, each naming the fix."""
        return tuple(entry.question() for entry in self.missing)

    def warn(self, stacklevel: int = 3) -> None:
        """Raise the warning, once per material.

        `warnings.warn` rather than a print or a logger: it is the mechanism a
        caller can already turn into an error (`-W error`), filter, or capture in
        a test, and it reaches a headless script that never opens the dialog.
        """
        for entry in self.missing:
            warnings.warn(entry.question(), UnknownMaterialWarning, stacklevel=stacklevel)


def unknown_materials(
        library: MaterialLibrary,
        materials: Iterable[MaterialId],
        *,
        seen_in: str = "",
        process_classes: Sequence[str] = PROCESS_CLASSES,
) -> UnknownMaterials:
    """Which of `materials` the library cannot answer for, in the order they came.

    `materials` is normally `Structure.materials`. Deliberately the **structure's**
    materials rather than the recipe's: a material can arrive without any step
    naming it — `particle.seed` scatters one, a plugin deposits its own — and the
    chromium particle this module is named after arrived exactly that way.
    """
    seen: list[MaterialId] = []
    for material in materials:
        key = MaterialId(str(material))
        if key not in library and key not in seen:
            seen.append(key)
    return UnknownMaterials(
        missing=tuple(
            MissingMaterial(
                material_id=key, seen_in=seen_in, process_classes=tuple(process_classes)
            )
            for key in seen
        ),
        seen_in=seen_in,
    )


def declared_materials(step: object, params: Mapping[str, object]) -> tuple[MaterialId, ...]:
    """Every material a step's parameters *name*, in schema order (roadmap E31).

    Read off the schema rather than guessed from parameter names: since E22 a
    material parameter says so (`ParamSpec.material`), and a step whose
    `material` means something else — or whose material lives under another name
    entirely — is answered correctly for free.

    The old generic anneal was the case that made this necessary: a typed target
    could introduce an unknown material. `bake.hard` now derives its target from
    the source library entry and performs the same check explicitly.
    """
    schema = getattr(step, "parameter_schema", None)
    if schema is None:
        return ()
    named: list[MaterialId] = []
    for spec in schema():
        if getattr(spec, "material", None) is None and spec.name not in _MATERIAL_NAMES:
            continue
        value = str(params.get(spec.name, "") or "").strip()
        if value and MaterialId(value) not in named:
            named.append(MaterialId(value))
    return tuple(named)


_MATERIAL_NAMES: tuple[str, ...] = ()
"""Legacy non-filtered material parameter names; built-ins currently need none."""


def missing_before_running(
        step: object, params: Mapping[str, object], library: "MaterialLibrary"
) -> tuple[MissingMaterial, ...]:
    """The materials this step names that the library cannot answer for (E31).

    **Before** the step, which is the whole of E31 and reverses E15's ordering:
    E15 asks after a step, because a material can arrive without any step naming
    it — a scattered particle, a plugin's own film — and that case is real and
    stays. But a material the recipe *typed* is knowable in advance, and asking
    afterwards means the step has already run at rate zero.
    """
    step_id = str(getattr(step, "step_id", ""))
    return tuple(
        MissingMaterial(material, seen_in=step_id)
        for material in declared_materials(step, params)
        if material not in library
    )
