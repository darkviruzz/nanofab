"""The `MaterialLibrary` and the didactic set the built-in processes run on.

Plan §3.4 separates the **type** (a library entry, pure data) from the
**assignment** (a `MaterialId` owning a `phi` array in a `Structure`). This
module is the type side: a frozen mapping of ids to `MaterialType`s that a
process consults for rates, yields and develop/dissolve models.

The library is passed *into* a process (`StepContext.library`), never stored in a
`Structure` — the same rule `FieldSpec` follows (plan §17's M1 note 8). A
`Structure` that carried its own rate table would be a `Structure` whose meaning
changed when the library was corrected, and every cached revision would have to
be replayed to find out.

**Since M6 there is no material in this file.** Roadmap E14 moved the whole
library to `data/materials/*.json`, one file per material, and `didactic_library()`
below is a *loader*: `materials.store` decides which directories it reads and
`materials.schema` decides what one file looks like. The migration's acceptance
criterion was bit-identity rather than equivalence — `tests/test_material_files.py`
holds the pre-migration models as literals and compares against them — because a
library that is only *nearly* what the code held is a library under which a
cached revision means something slightly different from what it meant when it was
computed.

What stayed in code is the `MaterialId` constants below, and those are names
rather than definitions: `RESIST` is the string the resist steps default to, not
a description of a resist. A constant naming a material nobody ships would be a
`KeyError` at its first lookup, so the suite checks that each one resolves.

The numbers on disk are **didactic, not calibrated** (plan §1 tier a, backlog
B7): they are chosen so the acceptance scenarios show the mechanism at a readable
scale, and their ratios carry the physics that matters — a mask that does not
etch, a resist that dissolves and a metal that does not, an oxide that a wet
etchant attacks and silicon that it does not.
`data/materials/README.md` says which numbers come from the student process table
of roadmap §3 and which were chosen for a scenario; a file may say so per rate.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from types import MappingProxyType
from typing import Iterator, Mapping

from nanofab_v3.materials.material import (
    DEPOSIT,
    DEVELOP,
    DISSOLVE,
    DRY_ETCH,
    ICP_FLUORINE,
    ION_BEAM,
    RIE_CHLORINE,
    RIE_OXYGEN,
    SPUTTER_DEPOSIT,
    SPUTTER_ETCH,
    WET_ETCH,
    WET_ETCH_CR,
    WET_ETCH_OXIDE,
    MaterialId,
    MaterialType,
)
from nanofab_v3.materials.store import (
    LibraryReport,
    builtin_materials_dir,
    cached_library,
    material_roots,
)

SILICON = MaterialId("silicon")
CHROME = MaterialId("chrome")
FUSED_SILICA = MaterialId("fused_silica")
TITANIA = MaterialId("titania")
OXIDE = MaterialId("oxide")
RESIST = MaterialId("resist")
UNDERLAYER = MaterialId("underlayer")
METAL = MaterialId("metal")
ALUMINA = MaterialId("alumina")
PARTICLE = MaterialId("particle")
HARD_RESIST = MaterialId("resist_hardbaked")


@dataclass(frozen=True)
class MaterialLibrary:
    """A frozen set of `MaterialType`s, keyed by `MaterialId`.

    Lookup of an unknown material raises rather than inventing a default: a
    process that etches a material nobody described would silently pick the
    default rate and produce a plausible, wrong answer. Where a *missing* rate is
    legitimate — a material this bath does not attack — the `MaterialType` itself
    answers zero (`rate_for`), which is a statement about that material rather
    than about the library.
    """

    entries: Mapping[MaterialId, MaterialType] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        entries = {}
        for key, entry in dict(self.entries).items():
            if entry.material_id != key:
                raise ValueError(
                    f"library key {key!r} does not match entry id {entry.material_id!r}"
                )
            entries[key] = entry
        object.__setattr__(self, "entries", MappingProxyType(entries))

    @classmethod
    def of(cls, *types: MaterialType) -> "MaterialLibrary":
        """Build a library from `MaterialType`s, keyed by their own ids."""
        return cls({entry.material_id: entry for entry in types})

    def __getitem__(self, material: MaterialId) -> MaterialType:
        try:
            return self.entries[material]
        except KeyError:
            raise KeyError(
                f"no MaterialType {material!r} in this library; it has {sorted(self.entries)}"
            ) from None

    def __contains__(self, material: object) -> bool:
        return material in self.entries

    def __iter__(self) -> Iterator[MaterialId]:
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def get(self, material: MaterialId) -> MaterialType | None:
        """The entry for `material`, or `None` — for callers that tolerate absence."""
        return self.entries.get(material)

    def with_entry(self, entry: MaterialType) -> "MaterialLibrary":
        """A new library with `entry` added or replaced."""
        updated = dict(self.entries)
        updated[entry.material_id] = entry
        return MaterialLibrary(updated)

    def blanket_rates(
        self, process_class: str, materials: Mapping[MaterialId, object] | None = None
    ) -> dict[MaterialId, float]:
        """`{material: nm/s}` for one process class — the input of `SurfaceRates`.

        Restricted to `materials` when given (normally `Structure.phi`), so a step
        never carries rates for materials the sample does not contain. A material
        the library does not know is left out, and the caller's default decides
        what happens to it — which for `SurfaceRates` is "it does not move".
        """
        keys = self.entries if materials is None else materials
        return {
            MaterialId(str(key)): self.entries[MaterialId(str(key))].rate_for(process_class)
            for key in keys
            if MaterialId(str(key)) in self.entries
        }

    def display_colors(self) -> dict[MaterialId, str]:
        """`{material: "#rrggbb"}` — everything rendering needs from the library."""
        return {key: entry.display_color for key, entry in self.entries.items()}


# -- the two libraries, and why there are two (plan §21.6's rule, one layer down)


def didactic_library() -> MaterialLibrary:
    """The shipped material set, read from `data/materials/*.json` (E14).

    The **shipped root only**, deliberately. This is what the process tests, the
    acceptance scenarios and `--selftest` run against, and plan §21.6 already
    settled the reason for its registry twin: a check whose numbers depended on
    what happened to be in somebody's home directory would answer differently on
    every machine, and the material library is the one input the scenarios are
    least able to notice a change in. `application_library()` is what an
    application takes.

    Strict: a malformed file in the shipped root is a build defect, and the
    honest failure is an exception rather than a library that is quietly one
    material short. Memoised on the root path, because
    `processes.engine.run_step` falls back to it once per step.
    """
    library, _ = cached_library((builtin_materials_dir(),), strict=True)
    return library


def application_library() -> tuple[MaterialLibrary, LibraryReport]:
    """The shipped set plus the operator's own directory, and what that found.

    The counterpart of `processes.plugins.application_registry()`: an application
    reads both roots, a later one shadowing an earlier one, so a material E15's
    dialog wrote is simply there next time. Lenient — one malformed file in a
    writable directory costs that material and nothing else, because an
    application whose material list is empty over a stray comma is worse than one
    that is missing a material it can be told about again.
    """
    return cached_library(material_roots(), strict=False)


__all__ = [
    "ALUMINA",
    "CHROME",
    "FUSED_SILICA",
    "TITANIA",
    "HARD_RESIST",
    "PARTICLE",
    "METAL",
    "UNDERLAYER",
    "OXIDE",
    "RESIST",
    "SILICON",
    "LibraryReport",
    "MaterialLibrary",
    "application_library",
    "didactic_library",
    "DEPOSIT",
    "DEVELOP",
    "DISSOLVE",
    "DRY_ETCH",
    "ICP_FLUORINE",
    "ION_BEAM",
    "RIE_CHLORINE",
    "RIE_OXYGEN",
    "SPUTTER_DEPOSIT",
    "SPUTTER_ETCH",
    "WET_ETCH",
    "WET_ETCH_CR",
    "WET_ETCH_OXIDE",
]
