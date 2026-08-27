"""Which materials a step's dropdown may offer, and the sentence saying why (E22).

A material parameter with an unfiltered list is a list that offers chromium to a
spin coater. Roadmap E22 settles the shape of the fix, and the substance of it is
that there are **two** sources of truth about "would this material make sense
here", not one:

- **Library data**, for a step that reads it. A didactic spin coat needs
  `spin_curve is not None`; a wet chromium etch needs `rates["wet_etch_cr"] > 0`.
  This is the strongest form, because the criterion *is* the thing the step will
  go and look up — a material that passes it is a material the step can run on.
- **Tags**, for a step that reads nothing. `resist.spin_coat` at ideal fidelity
  takes a thickness and puts a layer down; it consults no curve and no rate, so
  by the first rule every material qualifies, and chromium is still nonsense.
  E21's substance classes answer that question and only that question.

Three rules the filter keeps:

1. **It says what it filtered by.** A list that silently omits what somebody is
   looking for is worse than a long list — they will conclude the material is
   missing from the library.
2. **There is a way out.** "Show all" turns the filter off, because a didactic
   tool whose point is experimenting must not decide that an experiment is
   illegal. So must free text (E15): a material the library has never heard of is
   still typeable, and the unknown-material dialog is what catches it.
3. **The material an etch *attacks* is not filtered, because it is not chosen.**
   An etch step takes a duration and a chemistry; what it removes is whatever the
   sample is made of. Alumina has fluorine rate 0 and that is exactly the
   etch-stop demo — a filter over "etchable materials" would delete the point.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence

from nanofab_v3.materials.material import MATERIAL_TAGS, PROCESS_CLASSES, MaterialId, MaterialType

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nanofab_v3.materials.library import MaterialLibrary

_SUBMODELS = ("spin_curve", "develop", "dissolve", "sputter_response")
"""The `MaterialType` submodels a step can require the presence of."""

_SUBMODEL_WORDS = {
    "spin_curve": "have a measured spin curve",
    "develop": "have a develop model",
    "dissolve": "dissolve in a solvent",
    "sputter_response": "have an angular sputter yield",
}


@dataclass(frozen=True)
class MaterialFilter:
    """What a step needs of a material before offering it in a dropdown.

    All three criteria are *disjunctive within* themselves and *conjunctive
    between* — a material passes when it satisfies every criterion that is set.
    In practice a parameter sets one, which is the point: two criteria on one
    parameter usually means two parameters.

    Attributes:
        process_class: A key of `PROCESS_CLASSES` the material must have a rate
            above zero for. The strongest criterion, because it is the lookup the
            step is about to do.
        submodel: The name of a `MaterialType` submodel that must be present.
        tags: Substance classes (E21), any one of which qualifies. For steps that
            read no library data at all.
        what: A noun phrase naming the offered set, e.g. "resists". Used in the
            sentence the list shows; a filter without one still explains itself
            from the criteria, less readably.
    """

    process_class: str = ""
    submodel: str = ""
    tags: tuple[str, ...] = ()
    what: str = ""

    def __post_init__(self) -> None:
        if self.process_class and self.process_class not in PROCESS_CLASSES:
            raise ValueError(f"unknown process class {self.process_class!r} in a material filter")
        if self.submodel and self.submodel not in _SUBMODELS:
            raise ValueError(
                f"unknown submodel {self.submodel!r} in a material filter; "
                f"a step may require one of {_SUBMODELS}"
            )
        for tag in self.tags:
            if tag not in MATERIAL_TAGS:
                raise ValueError(f"unknown tag {tag!r} in a material filter")
        if not (self.process_class or self.submodel or self.tags):
            raise ValueError("a material filter with no criterion filters nothing")

    def matches(self, entry: MaterialType) -> bool:
        """Whether this material satisfies every criterion that is set."""
        if self.process_class and entry.rate_for(self.process_class) <= 0.0:
            return False
        if self.submodel and getattr(entry, self.submodel, None) is None:
            return False
        if self.tags and not entry.has_tag(*self.tags):
            return False
        return True

    def select(self, library: "MaterialLibrary") -> tuple[MaterialId, ...]:
        """The library's matching ids, sorted, so a list has a stable order."""
        return tuple(sorted(key for key, entry in library.entries.items() if self.matches(entry)))

    def describe(self) -> str:
        """The one line the dropdown shows about what it left out.

        Written as a statement about the *offered* set rather than about the
        omitted one: "showing resists" is readable, and "hiding 8 materials" is a
        number nobody can act on.
        """
        clauses: list[str] = []
        if self.process_class:
            clauses.append(f"have a {self.process_class} rate above zero")
        if self.submodel:
            clauses.append(_SUBMODEL_WORDS.get(self.submodel, f"have a {self.submodel} model"))
        if self.tags:
            clauses.append("are " + " or ".join(self.tags))
        noun = self.what or "materials"
        return f"showing {noun}: materials that " + " and ".join(clauses)


def filtered_choices(
    filter_: MaterialFilter | None,
    library: "MaterialLibrary",
    *,
    keep: Sequence[str] = (),
) -> tuple[tuple[MaterialId, ...], str]:
    """`(ids, reason)` for one dropdown — everything the widget needs.

    `keep` is what must be offered whatever the filter says: the value already in
    the recipe. A step that ran on a material the filter now rejects — because
    somebody edited its rate to zero, or because it was typed as free text —
    must still show that value, or "adjust" would silently substitute another
    one. That is the same defect as the `adjust` bug, arriving from the other
    side.
    """
    if filter_ is None:
        return tuple(sorted(library.entries)), ""
    chosen = list(filter_.select(library))
    for extra in keep:
        if extra and extra not in chosen:
            chosen.append(MaterialId(str(extra)))
    return tuple(chosen), filter_.describe()


__all__ = ["MaterialFilter", "filtered_choices"]
