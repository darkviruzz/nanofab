"""The material library on disk: the migration's proof, and the format's (E14).

Roadmap E14 moved every material out of `materials/library.py` and into
`data/materials/*.json`. The milestone's own completion criterion was not "the
library still works" but **bit-identical models**, and this file is where that is
checked: `_PRE_MIGRATION` below holds the eight entries exactly as
`didactic_library()` constructed them in code, copied out of the commit before
the migration, and `_M6_ADDITIONS` names every change M6 then made to one of
them.

Keeping both is what makes the test worth running twice. The first half says the
migration lost nothing. The second says every *later* difference between the code
that was and the files that are was deliberate and is listed here — so a rate
that changes because somebody edited a JSON file by hand shows up as a failing
test naming the material, rather than as a scenario that still passes with
slightly different numbers.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from nanofab_v3.materials import (
    ALUMINA,
    CHROME,
    DEPOSIT,
    DRY_ETCH,
    FUSED_SILICA,
    HARD_RESIST,
    ICP_FLUORINE,
    ION_BEAM,
    METAL,
    OXIDE,
    PARTICLE,
    PROCESS_CLASSES,
    RESIST,
    RIE_CHLORINE,
    RIE_OXYGEN,
    SILICON,
    SPUTTER_DEPOSIT,
    TITANIA,
    UNDERLAYER,
    WET_ETCH,
    WET_ETCH_CR,
    WET_ETCH_OXIDE,
    DevelopModel,
    DissolveModel,
    HardBakeModel,
    MaterialFileError,
    MaterialLibrary,
    MaterialType,
    SpinCurve,
    SputterResponse,
    application_library,
    builtin_materials_dir,
    didactic_library,
    from_json,
    load_library,
    save_material,
    to_json,
)
from nanofab_v3.materials import library as library_module
from nanofab_v3.materials import store

# -- what the code held, the commit before `data/materials/` existed -----------

_PRE_MIGRATION: tuple[MaterialType, ...] = (
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

_M6_RATE_ADDITIONS: dict[str, dict[str, float]] = {
    "silicon": {
        ICP_FLUORINE: 0.6667,
        SPUTTER_DEPOSIT: 0.1667,
        WET_ETCH_CR: 0.0,
        WET_ETCH_OXIDE: 0.0,
    },
    "oxide": {
        SPUTTER_DEPOSIT: 0.0667,
        WET_ETCH_OXIDE: 16.6667,
        WET_ETCH_CR: 0.0,
        ICP_FLUORINE: 0.8333,
        RIE_CHLORINE: 0.0,
        RIE_OXYGEN: 0.0,
    },
    "resist": {
        ICP_FLUORINE: 1.0,
        RIE_CHLORINE: 0.1667,
        RIE_OXYGEN: 1.6667,
        WET_ETCH_OXIDE: 1.6667,
        WET_ETCH_CR: 0.0,
    },
}
"""Every rate M6 added to a *migrated* entry, from the table of roadmap §3.

Empty at the migration commit by construction — the migration's job was to change
nothing — and filled by the commit that entered the student table. So the diff of
this dict is the diff of the library, and a rate that changes because somebody
edited a file by hand fails a test naming the material instead of quietly
changing what a scenario means.

Not the *didactic* classes: no `wet_etch`, `dry_etch`, `ion_beam`, `deposit`,
`develop` or `dissolve` value moved in M6, which is roadmap §3's "additiv
erweitern, nichts umbenennen" as an assertion rather than as an intention.
"""

_M6_MODEL_ADDITIONS: dict[str, dict] = {
    "resist": {
        "spin_curve": SpinCurve(
            points=((1000.0, 150.0), (2000.0, 99.8), (3000.0, 82.0), (4000.0, 74.0),
                    (5000.0, 72.0))
        )
    },
}
"""Everything else M6 added to a migrated entry — one spin curve (E17, §3.1)."""

_M12_MODEL_ADDITIONS: dict[str, dict] = {
    "resist": {
        "hard_bake": HardBakeModel(
            target=HARD_RESIST, activation_temperature=150.0
        )
    },
}
"""E31: the hard-bake target and threshold belong to the source material."""

_M8_RATE_ADDITIONS: dict[str, dict[str, float]] = {
    "alumina": {ICP_FLUORINE: 0.02},
}
"""Rates a *later* milestone added to a migrated entry, with the reason it did.

M8's grating demo needs an etch stop, and backlog B12 asked for that number to be
**decided** rather than guessed: the ratio is didactic, the direction is physics
(a fluorine plasma makes AlF3, which is not volatile, so alumina stops a fluorine
etch where titania does not), and `rate_notes` on the file says so.

A second dict rather than an entry in the first, because which milestone changed
what is exactly the thing this file exists to keep legible.
"""

_M11_RATE_CHANGES = {
    "silicon": {ION_BEAM: 0.2333},
    "oxide": {ION_BEAM: 0.2},
    "resist": {ION_BEAM: 0.25},
    "resist_hardbaked": {ION_BEAM: 0.207},
    "underlayer": {ION_BEAM: 0.299},
    "metal": {ION_BEAM: 0.345},
    "particle": {ION_BEAM: 0.138},
    "alumina": {ION_BEAM: 0.161},
}


def _expected() -> MaterialLibrary:
    """The pre-migration entries, plus exactly the changes since, milestone by milestone."""
    return MaterialLibrary.of(
        *(
            replace(
                entry,
                rates={
                    **entry.rates,
                    **_M6_RATE_ADDITIONS.get(str(entry.material_id), {}),
                    **_M8_RATE_ADDITIONS.get(str(entry.material_id), {}),
                    **_M11_RATE_CHANGES.get(str(entry.material_id), {}),
                },
                **_M6_MODEL_ADDITIONS.get(str(entry.material_id), {}),
                **_M12_MODEL_ADDITIONS.get(str(entry.material_id), {}),
            )
            for entry in _PRE_MIGRATION
        )
    )


# -- the migration ------------------------------------------------------------


def test_the_shipped_library_is_the_pre_migration_one_bit_for_bit() -> None:
    """E14's completion criterion, and the only one that means anything.

    "The library still loads" would pass with a rate off by a digit. A
    `MaterialType` is a frozen dataclass of scalars, so `==` compares every float
    exactly — which is the comparison a cached revision's meaning depends on,
    because a revision computed under one rate table and replayed under another
    is silently a different sample.
    """
    loaded = didactic_library()
    expected = _expected()

    for material in expected:
        # `notes`/`rate_notes` are prose about provenance and are checked by the
        # tests below; `tags` are M10's substance classes (E21), data the
        # pre-migration models did not carry at all and which no rate depends on.
        # What has to be bit-identical is the model a revision was computed under.
        assert (
                replace(loaded[material], notes="", rate_notes={}, tags=())
                == expected[material]
        ), material


def test_no_material_is_left_in_the_code() -> None:
    """E14 forbids the split "a few in code, a few on disk" — checked, not trusted.

    Not a style rule: a `MaterialType` constructed in `library.py` would be one an
    operator cannot correct without a rebuild, which is the whole point of moving
    the library to files.
    """
    source = Path(library_module.__file__).read_text(encoding="utf-8")
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    _, _, body = code.partition('"""')
    _, _, body = body.partition('"""')  # past the module docstring

    assert "MaterialType(" not in body
    assert "DevelopModel(" not in body and "DissolveModel(" not in body


def test_every_id_constant_names_a_material_that_ships() -> None:
    """The one thing that stayed in code is a set of names, so the names are checked."""
    library = didactic_library()

    for material in (
            SILICON, OXIDE, RESIST, UNDERLAYER, METAL, ALUMINA, PARTICLE, HARD_RESIST,
            CHROME, FUSED_SILICA, TITANIA,
    ):
        assert material in library, material


# -- the format ---------------------------------------------------------------


def test_every_material_survives_a_round_trip_through_json() -> None:
    """`from_json(to_json(m)) == m` for every shipped material, exactly.

    The property the migration rests on (roadmap §0's second side-finding): every
    submodel is a frozen dataclass of scalars, so the encoding is lossless rather
    than approximately faithful. Floats included — `json` writes `repr`, which
    round-trips a double exactly.
    """
    library = didactic_library()

    for material in library:
        assert from_json(to_json(library[material])) == library[material], material


def test_a_file_is_named_after_the_material_it_defines() -> None:
    """Otherwise `chrome.json` could define `silicon` and shadow it from nowhere."""
    for path in sorted(builtin_materials_dir().glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["material_id"] == path.stem


def test_the_shipped_files_are_the_canonical_encoding_of_what_they_hold() -> None:
    """Re-encoding a file reproduces it byte for byte — so a diff is a real change.

    Worth pinning because the files are meant to be read and edited by hand: if
    the writer normalised anything the reader tolerated, every save through E15's
    dialog would rewrite unrelated files and bury the one change that mattered.
    """
    for path in sorted(builtin_materials_dir().glob("*.json")):
        text = path.read_text(encoding="utf-8")
        payload = json.loads(text)
        if "inherits" in payload:
            assert json.dumps(payload, indent=2, ensure_ascii=False) + "\n" == text, path.name
        else:
            assert to_json(from_json(text)) == text, path.name


def test_an_unknown_schema_version_is_refused_rather_than_guessed() -> None:
    """A rate silently dropped because a key moved is what this milestone is about."""
    with pytest.raises(MaterialFileError, match="schema"):
        from_json(json.dumps({"schema": 99, "material_id": "x", "name": "X"}))
    with pytest.raises(MaterialFileError, match="schema"):
        from_json(json.dumps({"material_id": "x", "name": "X"}))


def test_an_unknown_field_is_an_error_and_not_ignored() -> None:
    """The same rule `validate_params` follows: a misspelt key must not vanish."""
    with pytest.raises(MaterialFileError, match="unknown field"):
        from_json(json.dumps({"schema": 1, "material_id": "x", "name": "X", "rate": 3.0}))


def test_the_dataclass_stays_the_validator() -> None:
    """A bad number fails where it would have failed had somebody typed it in code."""
    with pytest.raises(MaterialFileError, match="unknown process class"):
        from_json(json.dumps({"schema": 1, "material_id": "x", "name": "X",
                              "rates": {"plasma": 1.0}}))
    with pytest.raises(MaterialFileError, match="non-negative"):
        from_json(json.dumps({"schema": 1, "material_id": "x", "name": "X",
                              "rates": {"wet_etch": -1.0}}))


# -- the roots ----------------------------------------------------------------


def test_a_later_root_overrides_an_earlier_one(tmp_path: Path) -> None:
    """The seam B7 (calibrated rates) arrives through: one set of files per tool."""
    faster = replace(didactic_library()[SILICON], rates={DRY_ETCH: 99.0})
    save_material(faster, tmp_path)

    library, report = load_library((builtin_materials_dir(), tmp_path))

    assert library[SILICON].rate_for(DRY_ETCH) == 99.0
    assert SILICON in report.overridden
    assert didactic_library()[SILICON].rate_for(DRY_ETCH) == 2.0  # shipped root untouched


def test_a_malformed_file_in_a_writable_root_costs_that_material_and_no_other(
        tmp_path: Path,
) -> None:
    """`plugins.discover_plugins`' rule, one layer down: report, never raise.

    A delivered application whose material list is empty because of a stray comma
    is worse than one missing a material it can be told about again.
    """
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "gold.json").write_text(
        json.dumps({"schema": 1, "material_id": "gold", "name": "Gold"}), encoding="utf-8"
    )

    library, report = load_library((builtin_materials_dir(), tmp_path))

    assert "gold" in library and SILICON in library
    assert len(report.failures) == 1 and report.failures[0][0].name == "broken.json"
    assert any("broken.json" in line for line in report.describe())


def test_the_shipped_root_is_read_strictly(tmp_path: Path) -> None:
    """A broken file *there* is a build defect, not a degraded library."""
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(MaterialFileError):
        load_library((tmp_path,), strict=True)


def test_the_application_library_reads_the_operators_directory_too(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E15 writes there, so the next session has to see it without a rebuild."""
    monkeypatch.setenv(store.MATERIALS_ENV, str(tmp_path))
    store.invalidate_cache()
    try:
        save_material(MaterialType(material_id="tungsten", name="Tungsten"))

        library, report = application_library()

        assert "tungsten" in library
        assert (tmp_path / "tungsten.json").is_file()
        assert tmp_path in report.roots
        assert "tungsten" not in didactic_library()  # the shipped set is not affected
    finally:
        store.invalidate_cache()


# -- the student process table (roadmap §3) -----------------------------------

_TABLE_CLASSES = (
    ION_BEAM,
    ICP_FLUORINE,
    RIE_CHLORINE,
    RIE_OXYGEN,
    WET_ETCH_CR,
    WET_ETCH_OXIDE,
    SPUTTER_DEPOSIT,
)
"""The classes M6 added. Every rate under one of these came from the table."""


def test_the_table_rows_are_in_the_library_as_the_table_gives_them() -> None:
    """Roadmap §3, converted from nm/min to nm/s. The numbers, verbatim.

    One assertion per cell the table fills, because the alternative — trusting
    that a file says what a table says — is exactly the transcription error a
    didactic tool cannot notice: every rate here is plausible, and a wrong one
    produces a picture that looks right.
    """
    library = didactic_library()
    expected = {
        ION_BEAM: {CHROME: 0.1667, OXIDE: 0.2, SILICON: 0.2333, RESIST: 0.25},
        ICP_FLUORINE: {CHROME: 0.0333, FUSED_SILICA: 0.8333, SILICON: 0.6667, RESIST: 1.0},
        RIE_CHLORINE: {CHROME: 0.8333, FUSED_SILICA: 0.0, RESIST: 0.1667},
        RIE_OXYGEN: {CHROME: 0.0, FUSED_SILICA: 0.0, RESIST: 1.6667},
        WET_ETCH_CR: {CHROME: 16.6667, OXIDE: 0.0, SILICON: 0.0, RESIST: 0.0},
        WET_ETCH_OXIDE: {OXIDE: 16.6667, RESIST: 1.6667, CHROME: 0.0, SILICON: 0.0},
        SPUTTER_DEPOSIT: {OXIDE: 0.0667, SILICON: 0.1667, CHROME: 0.0833},
    }

    for process_class, rates in expected.items():
        for material, rate in rates.items():
            assert library[material].rate_for(process_class) == rate, (material, process_class)


def test_a_rate_the_table_did_not_measure_says_so_where_a_reader_will_see_it() -> None:
    """Roadmap §3.1's instruction: mark the SiO2 cross-assumption, do not take it silently.

    The table names "silicon oxide" for sputter etching and "fused silica" for the
    plasma chemistries, and this library carries both. Each borrows the other's
    value where the table is silent — and says so in `rate_notes`, which is a
    field rather than a comment precisely so the program can repeat it.
    """
    library = didactic_library()

    assumed = {
        (OXIDE, ICP_FLUORINE), (OXIDE, RIE_CHLORINE), (OXIDE, RIE_OXYGEN),
        (FUSED_SILICA, ION_BEAM), (FUSED_SILICA, WET_ETCH_OXIDE),
    }
    for material, process_class in assumed:
        note = library[material].rate_note(process_class)
        assert note.startswith("Assumed"), (material, process_class, note)
        assert "not measured" in note

    # ... and a rate the table *does* give is not marked as an assumption.
    assert not library[FUSED_SILICA].rate_note(ICP_FLUORINE).startswith("Assumed")
    assert not library[OXIDE].rate_note(WET_ETCH_OXIDE).startswith("Assumed")


def test_no_rate_in_the_shipped_library_is_without_a_stated_provenance() -> None:
    """Every number on a chemistry class says where it came from.

    E15's rule one level up: the failure this milestone is about is a value
    nobody can trace. A rate under one of M6's classes is either the table's, or
    the table's other SiO2 value, or it should not be there.
    """
    library = didactic_library()

    for material in library:
        entry = library[material]
        for process_class in _TABLE_CLASSES:
            if process_class in entry.rates:
                assert entry.rate_note(process_class), (material, process_class)


def test_m11_consolidates_the_ion_beam_rate_without_changing_other_classes() -> None:
    """E24 gives every ion-beam process one rate key and preserves other contrasts."""
    assert PROCESS_CLASSES[:6] == (WET_ETCH, DRY_ETCH, ION_BEAM, DEPOSIT, "develop", "dissolve")
    assert "sputter_etch" not in PROCESS_CLASSES

    library = didactic_library()
    assert library[SILICON].rate_for(ION_BEAM) == 0.2333
    assert library[OXIDE].rate_for(WET_ETCH) == 1.0  # didactic BOE, not the table's 16.6667
    assert library[OXIDE].rate_for(WET_ETCH_OXIDE) == 16.6667


def test_titania_marks_every_non_table_rate_as_didactic() -> None:
    """E16 puts TiO2 in the library; the table has no TiO2 row, so nothing is invented.

    Backlog B11's rule about spin curves, applied to rates: a plausible made-up
    number is worse than an absent one, because only the absent one can be
    noticed. What keeps a number that *is* needed from being a silent invention
    is the note — M8's etch-stop demo forced exactly that decision (B12), and the
    result is one rate that says out loud where it came from.
    """
    library = didactic_library()
    titania = library[TITANIA]

    assert "nothing here is table-derived" in titania.notes and "B12" in titania.notes
    for process_class in _TABLE_CLASSES:
        if process_class in {ICP_FLUORINE, ION_BEAM}:
            continue
        assert process_class not in titania.rates, process_class
    assert titania.rate_note(ICP_FLUORINE).startswith("Didactic, not from the process table")
    assert titania.rate_note(ION_BEAM).startswith("Didactic, not in the process table")
    # The one thing the number has to do: stop a fluorine etch at the alumina.
    assert titania.rate_for(ICP_FLUORINE) / library[ALUMINA].rate_for(ICP_FLUORINE) == 25.0


def test_chromium_is_the_material_the_table_exercises_everywhere() -> None:
    """The contrasts the table is actually about, as ratios rather than numbers.

    Chromium is the reason the rate table had to be keyed on chemistry at all: one
    `dry_etch` number per material cannot say that the same machine takes it 25x
    faster in chlorine than in fluorine.
    """
    library = didactic_library()
    chrome = library[CHROME]

    # `rel` rather than exact: the table is nm/min and the library is nm/s rounded
    # to four decimals, so 50/2 comes back as 25.02. That rounding is the reason
    # every ratio here is asserted loosely and every *rate* above is asserted
    # exactly — the stored number is the fact, the ratio is the reading.
    assert chrome.rate_for(RIE_CHLORINE) / chrome.rate_for(ICP_FLUORINE) == pytest.approx(
        25.0, rel=2e-3
    )
    assert chrome.rate_for(RIE_OXYGEN) == 0.0  # an oxygen plasma does not touch it
    # The wet etchant takes chromium exactly 100x faster than the ion beam does —
    # 1000 against 10 nm/min. That is the didactic contrast of row 5.
    assert chrome.rate_for(WET_ETCH_CR) / chrome.rate_for(ION_BEAM) == pytest.approx(
        100.0, rel=2e-3
    )
    # ... and the chromium etchant attacks nothing else the table names.
    for material in (OXIDE, SILICON, RESIST, FUSED_SILICA):
        assert library[material].rate_for(WET_ETCH_CR) == 0.0


def test_the_oxygen_plasma_is_a_resist_strip_and_the_fluorine_one_is_not() -> None:
    """The selectivity a student is meant to read off the table, as one assertion."""
    library = didactic_library()

    assert library[RESIST].rate_for(RIE_OXYGEN) == 1.6667
    for material in (CHROME, FUSED_SILICA, OXIDE):
        assert library[material].rate_for(RIE_OXYGEN) == 0.0
    # Fluorine takes the resist faster than chromium by a factor of 30 — which is
    # why an ICP etch through a chromium hard mask works and one through resist
    # does not.
    assert library[RESIST].rate_for(ICP_FLUORINE) / library[CHROME].rate_for(ICP_FLUORINE) > 25.0


# -- E21/E22: substance classes, and the dropdowns they let a step filter -----


def test_every_shipped_material_carries_a_substance_class():
    """E21: `tags` is what an *ideal* step filters on, so a gap is an unfiltered list."""
    from nanofab_v3.materials.material import MATERIAL_TAGS

    library = didactic_library()
    for material, entry in library.entries.items():
        assert entry.tags, f"{material} has no substance class"
        assert set(entry.tags) <= set(MATERIAL_TAGS)


def test_tags_are_substance_classes_and_never_roles():
    """The decision E21 turned on: chromium is a mask *and* a film *and* a target."""
    from nanofab_v3.materials.material import MATERIAL_TAGS

    assert "mask" not in MATERIAL_TAGS and "deposit" not in MATERIAL_TAGS
    library = didactic_library()
    assert library["chrome"].tags == ("metal",)
    assert library["particle"].tags == ("contamination",)
    assert set(library["alumina"].tags) == {"metal_oxide", "dielectric"}


def test_an_unknown_tag_is_refused_where_it_is_written_not_where_it_is_read():
    from nanofab_v3.materials import MaterialId, MaterialType

    with pytest.raises(ValueError, match="unknown tag"):
        MaterialType(material_id=MaterialId("x"), name="X", tags=("Dielectric",))


def test_tags_survive_the_canonical_round_trip(tmp_path):
    from nanofab_v3.materials import read_material, write_material

    entry = didactic_library()["titania"]
    path = write_material(entry, tmp_path / "titania.json")
    assert read_material(path).tags == entry.tags


def test_material_inheritance_is_resolved_before_the_library_is_built() -> None:
    library = didactic_library()

    inherited = library["chrome_redeposit"]
    base = library["chrome"]
    assert inherited.rates == base.rates
    assert inherited.tags == base.tags == ("metal",)
    assert inherited.name == "Chromium redeposit"


def test_material_inheritance_cycles_are_refused(tmp_path: Path) -> None:
    for material, parent in (("a", "b"), ("b", "a")):
        (tmp_path / f"{material}.json").write_text(
            json.dumps({"schema": 1, "material_id": material, "inherits": parent}),
            encoding="utf-8",
        )

    with pytest.raises(MaterialFileError, match="inheritance cycle"):
        load_library((tmp_path,), strict=True)


def test_the_spin_coat_offers_no_metals_and_says_what_it_filtered_by():
    """The DoD's sentence, at the level below the widget.

    The didactic step requires both a resist tag and a measured spin curve. The
    ideal sibling consults only the substance tag.
    """
    from nanofab_v3.materials.selection import filtered_choices
    from nanofab_v3.processes.registry import builtin_registry

    spec = next(
        spec
        for spec in builtin_registry()["resist.spin_coat"].parameter_schema()
        if spec.name == "material"
    )
    offered, why = filtered_choices(spec.material, didactic_library())
    assert "chrome" not in offered and "metal" not in offered
    assert "resist" in offered
    assert "resist" in why and "spin curve" in why and why.startswith("showing ")


def test_the_target_of_an_etch_is_never_filtered_because_it_is_never_chosen():
    """Alumina has fluorine rate 0 and that *is* the etch-stop demo (E22)."""
    from nanofab_v3.processes.registry import builtin_registry

    registry = builtin_registry()
    for step_id in registry.steps:
        if not step_id.startswith("etch."):
            continue
        for spec in registry[step_id].parameter_schema():
            assert spec.material is None, f"{step_id}.{spec.name} filters an etch target"
    library = didactic_library()
    assert 0.0 < library["alumina"].rate_for("icp_fluorine") < library[
        "titania"
    ].rate_for("icp_fluorine")


def test_the_recipes_own_value_is_offered_even_when_the_filter_rejects_it():
    """Otherwise 'adjust' would silently substitute another material."""
    from nanofab_v3.materials.selection import MaterialFilter, filtered_choices

    offered, _ = filtered_choices(
        MaterialFilter(tags=("resist",)), didactic_library(), keep=("chrome",)
    )
    assert "chrome" in offered


def test_a_filter_with_no_criterion_is_refused():
    """A filter that filters nothing is a filter whose reason line lies."""
    from nanofab_v3.materials.selection import MaterialFilter

    with pytest.raises(ValueError, match="no criterion"):
        MaterialFilter()
