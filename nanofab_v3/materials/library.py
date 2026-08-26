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

The numbers in `didactic_library()` are **didactic, not calibrated** (plan §1
tier a): they are chosen so the four acceptance scenarios show the mechanism at a
readable scale, and their ratios carry the physics that matters — a mask that
does not etch, a resist that dissolves and a metal that does not, an oxide that a
wet etchant attacks and silicon that it does not.
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
    ION_BEAM,
    WET_ETCH,
    DevelopModel,
    DissolveModel,
    MaterialId,
    MaterialType,
    SputterResponse,
)

SILICON = MaterialId("silicon")
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


def didactic_library() -> MaterialLibrary:
    """The material set the built-in processes of plan §6 are written against.

    Eight materials, chosen to be exactly what S1-S5 need and no more:

    - `silicon` — the substrate. Etched by the dry techniques, untouched by the
      developer and by the buffered-oxide wet etchant, which is what makes the
      wet etch of S2 stop at the interface instead of running away.
    - `oxide` — thermal SiO2, the S2 masking/etched layer: the wet etchant's
      target, so its undercut is the ratio S2 measures.
    - `resist` — a positive-tone polymer with a develop model and a solvent. The
      only material in the set that both develops and dissolves, which is what
      makes it the resist rather than a naming convention.
    - `underlayer` — the non-imaging lower half of a bilayer lift-off stack (a
      real LOR). Lower contrast and a faster developer rate than the imaging
      resist, which is what makes it clear wider and leave the **undercut**
      profile S4 needs; it dissolves in the same bath.
    - `metal` — the evaporated/sputtered film of S1 and S4. No develop model, no
      solvent: it is what survives lift-off, and it survives because nothing in
      the bath attacks it.
    - `alumina` — the conformal ALD film of S3. Its only job is to be deposited
      over a resist sidewall and seal it, so its rates matter less than its
      presence.
    - `resist_hardbaked` — what `resist` becomes above its own bake temperature,
      and the reason `anneal.thermal` needs no mutable library (plan §21.2). Same
      geometry, a different entry: the develop model is gone, the solvent no
      longer attacks it (`dissolve=None`), and it etches half as fast. A resist
      hard-baked before lift-off is a resist lift-off cannot remove, which is a
      real mistake with a shape in this model rather than a table of numbers.
    - `particle` — airborne debris, and the only material in the set that is not
      *deposited* by anything: it arrives. Inert in every bath (a `WET_ETCH` rate
      of zero and no `dissolve` model), which is exactly what makes S5's
      micromasking a **reachability** finding rather than a chemistry one — the
      particle a clean leaves behind is one it could not reach, never one it
      could not attack. It erodes slowly under the dry techniques, because a
      particle that survived an ion beam untouched would be a wall rather than a
      defect.
    """
    return MaterialLibrary.of(
        MaterialType(
            material_id=SILICON,
            name="Silicon",
            display_color="#6b7a8f",
            rates={DRY_ETCH: 2.0, ION_BEAM: 1.0, WET_ETCH: 0.0},
            sputter_response=SputterResponse(rise=2.0, fall=1.0),
            density=2.33,
            optical_n=1.57,
            optical_k=3.57,
        ),
        MaterialType(
            material_id=OXIDE,
            name="Silicon dioxide",
            display_color="#cfd8dc",
            rates={WET_ETCH: 1.0, DRY_ETCH: 1.5, ION_BEAM: 0.8},
            sputter_response=SputterResponse(rise=1.8, fall=1.0),
            density=2.20,
            optical_n=1.47,
            optical_k=0.0,
        ),
        MaterialType(
            material_id=RESIST,
            name="Positive resist",
            display_color="#e8b84b",
            rates={DRY_ETCH: 0.5, ION_BEAM: 1.2, WET_ETCH: 0.0},
            sputter_response=SputterResponse(rise=1.5, fall=1.0),
            develop=DevelopModel(
                clearing_dose=100.0, clear_rate=20.0, dark_rate=0.05, contrast=4.0
            ),
            dissolve=DissolveModel(solvent="acetone", rate=40.0, swells=True),
            density=1.19,
            optical_n=1.51,
            optical_k=0.0,
            absorption=0.0015,
        ),
        MaterialType(
            material_id=HARD_RESIST,
            name="Hard-baked resist",
            display_color="#8a6d1f",
            rates={DRY_ETCH: 0.25, ION_BEAM: 0.9, WET_ETCH: 0.0},
            sputter_response=SputterResponse(rise=1.5, fall=1.0),
            density=1.28,
            optical_n=1.58,
            optical_k=0.0,
            absorption=0.0015,
        ),
        MaterialType(
            material_id=UNDERLAYER,
            name="Lift-off underlayer",
            display_color="#c98a3a",
            rates={DRY_ETCH: 0.6, ION_BEAM: 1.3, WET_ETCH: 0.0},
            sputter_response=SputterResponse(rise=1.5, fall=1.0),
            develop=DevelopModel(
                clearing_dose=60.0, clear_rate=35.0, dark_rate=0.4, contrast=1.5
            ),
            dissolve=DissolveModel(solvent="acetone", rate=60.0, swells=True),
            density=1.15,
            optical_n=1.55,
            optical_k=0.0,
            absorption=0.0,
        ),
        MaterialType(
            material_id=METAL,
            name="Metal",
            display_color="#d9a441",
            rates={DEPOSIT: 1.0, ION_BEAM: 1.5, DRY_ETCH: 0.2, WET_ETCH: 0.0},
            sputter_response=SputterResponse(rise=2.2, fall=1.0),
            density=19.3,
            optical_n=0.47,
            optical_k=2.83,
        ),
        MaterialType(
            material_id=PARTICLE,
            name="Particle",
            display_color="#8d6e63",
            rates={DRY_ETCH: 0.3, ION_BEAM: 0.6, WET_ETCH: 0.0},
            sputter_response=SputterResponse(rise=1.6, fall=1.0),
            density=2.5,
            optical_n=1.60,
            optical_k=0.10,
        ),
        MaterialType(
            material_id=ALUMINA,
            name="ALD alumina",
            display_color="#9ccfd8",
            rates={DEPOSIT: 1.0, WET_ETCH: 0.2, DRY_ETCH: 0.6, ION_BEAM: 0.7},
            density=3.0,
            optical_n=1.77,
            optical_k=0.0,
        ),
    )


__all__ = [
    "ALUMINA",
    "HARD_RESIST",
    "PARTICLE",
    "METAL",
    "UNDERLAYER",
    "OXIDE",
    "RESIST",
    "SILICON",
    "MaterialLibrary",
    "didactic_library",
    "DEPOSIT",
    "DEVELOP",
    "DISSOLVE",
    "DRY_ETCH",
    "ION_BEAM",
    "WET_ETCH",
]
