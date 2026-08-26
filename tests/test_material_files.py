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
    DEPOSIT,
    DRY_ETCH,
    HARD_RESIST,
    ION_BEAM,
    METAL,
    OXIDE,
    PARTICLE,
    RESIST,
    SILICON,
    UNDERLAYER,
    WET_ETCH,
    DevelopModel,
    DissolveModel,
    MaterialFileError,
    MaterialLibrary,
    MaterialType,
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

_M6_ADDITIONS: dict[str, dict] = {}
"""Every change M6 made to a migrated entry, as `{material: {field: value}}`.

Empty at the migration commit, by construction: the migration's job was to change
nothing. Later M6 commits add the student table's rates here as they add them to
the files, so the diff of this dict is the diff of the library.
"""


def _expected() -> MaterialLibrary:
    """The eight pre-migration entries, plus exactly the changes M6 declared."""
    entries = []
    for entry in _PRE_MIGRATION:
        changes = _M6_ADDITIONS.get(str(entry.material_id))
        if changes:
            merged = dict(changes)
            if "rates" in merged:
                merged["rates"] = {**entry.rates, **merged["rates"]}
            entry = replace(entry, **merged)
        entries.append(entry)
    return MaterialLibrary.of(*entries)


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

    assert sorted(loaded) == sorted(expected)
    for material in expected:
        assert loaded[material] == expected[material], material


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

    for material in (SILICON, OXIDE, RESIST, UNDERLAYER, METAL, ALUMINA, PARTICLE, HARD_RESIST):
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
        assert from_json(path.read_text(encoding="utf-8")).material_id == path.stem


def test_the_shipped_files_are_the_canonical_encoding_of_what_they_hold() -> None:
    """Re-encoding a file reproduces it byte for byte — so a diff is a real change.

    Worth pinning because the files are meant to be read and edited by hand: if
    the writer normalised anything the reader tolerated, every save through E15's
    dialog would rewrite unrelated files and bury the one change that mattered.
    """
    for path in sorted(builtin_materials_dir().glob("*.json")):
        text = path.read_text(encoding="utf-8")
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
