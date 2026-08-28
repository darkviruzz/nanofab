"""The exchange format — plan §9, the first half of milestone M4.

One format serves three jobs: saving a session, the replay cache, and handing a
structure to an external solver (fidelity tier c). That is why the one property
asserted first and hardest here is **bit-identity**: a cache whose entries are
"almost" the structure that was computed is a cache that makes a deterministic
model non-deterministic, and every replay guarantee of ADR-0004 rests on it.

The other half is forward compatibility (plan §9, docs §4.1 invariant 5): a
manifest carries `schema_id: "structure.v2"`, and a reader **ignores keys it does
not know** rather than refusing the file. A format that cannot be extended
without breaking its readers is one that never gets extended.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from nanofab_v3 import FieldKey, Grid, Structure
from nanofab_v3.io import (
    SCHEMA_ID,
    FileRevisionStore,
    load_chain,
    load_revision,
    load_structure,
    save_chain,
    save_revision,
    save_structure,
)
from nanofab_v3.kernel import constructors as ctor
from nanofab_v3.materials import RESIST, SILICON, didactic_library
from nanofab_v3.model.quantity import Quantity
from nanofab_v3.processes import builtin_registry
from nanofab_v3.processes.substrate import cross_section_grid
from nanofab_v3.runtime import (
    ArtifactRef,
    HistoryEntry,
    Recipe,
    RecipeStep,
    Revision,
    RevisionChain,
    run_recipe,
)


@pytest.fixture
def structure(grid_2d: Grid) -> Structure:
    """Two materials and one material-scoped field — the shape of a real revision."""
    built = ctor.add_material(
        Structure(grid_2d),
        SILICON,
        ctor.half_space(grid_2d, normal=(1.0, 0.0), point=(60.0, 0.0)),
    )
    built = ctor.add_material(
        built, RESIST, ctor.box(grid_2d, lower=(55.0, 40.0), upper=(120.0, 260.0))
    )
    dose = np.linspace(0.0, 12.0, grid_2d.size, dtype=np.float32).reshape(grid_2d.shape)
    return built.with_field(FieldKey("dose", RESIST), dose)


@pytest.fixture
def chain(tmp_path) -> RevisionChain:
    """A four-step lithography chain, run for real through the registry."""
    registry = builtin_registry()
    recipe = Recipe(
        recipe_id="round-trip",
        grid=cross_section_grid(width=200.0, thickness=40.0, headroom=140.0),
        steps=(
            RecipeStep("substrate.select", {"material": SILICON, "surface": 40.0}),
            RecipeStep("resist.spin_coat_ideal", {"material": RESIST, "thickness": 60.0}),
            RecipeStep(
                "litho.expose_ideal", {"material": RESIST, "center": 100.0, "width": 60.0}
            ),
            RecipeStep("develop.ideal", {"material": RESIST}),
        ),
    )
    return run_recipe(recipe, registry=registry, library=didactic_library())


# -- 1. bit-identity, which everything else rests on --------------------------


def test_a_structure_survives_a_round_trip_bit_identically(structure, tmp_path) -> None:
    """Not "close": identical. The cache's correctness is exactly this property."""
    path = tmp_path / "revision"
    save_structure(path, structure)
    loaded = load_structure(path)

    assert loaded.grid == structure.grid
    assert loaded.materials == structure.materials
    for material in structure.materials:
        original = np.asarray(structure.phi_of(material))
        restored = np.asarray(loaded.phi_of(material))
        assert restored.dtype == original.dtype
        assert np.array_equal(restored, original)
    assert set(loaded.fields) == set(structure.fields)
    for key, values in structure.fields.items():
        assert np.asarray(loaded.field(key)).dtype == np.asarray(values).dtype
        assert np.array_equal(np.asarray(loaded.field(key)), np.asarray(values))


def test_a_field_keeps_its_dtype_rather_than_being_promoted(grid_2d: Grid, tmp_path) -> None:
    """`exposed` is `int8` by plan §3.3, and a round trip that floats it is a bug.

    Ideal development consumes `exposed`; a `float32` version of it still selects
    the same cells, so this would survive every scenario test and surface as a
    silent doubling of a saved session's field memory.
    """
    built = ctor.add_material(
        Structure(grid_2d), RESIST, ctor.box(grid_2d, lower=(0.0, 0.0), upper=(50.0, 50.0))
    )
    exposed = np.zeros(grid_2d.shape, dtype=np.int8)
    exposed[10:20, 10:20] = 1
    built = built.with_field(FieldKey("exposed", RESIST), exposed)

    save_structure(tmp_path / "structure", built)
    loaded = load_structure(tmp_path / "structure")

    assert np.asarray(loaded.field(FieldKey("exposed", RESIST))).dtype == np.int8
    assert np.array_equal(np.asarray(loaded.field(FieldKey("exposed", RESIST))), exposed)


def test_a_corrupted_array_is_caught_by_its_content_hash(structure, tmp_path) -> None:
    """The manifest carries hashes so a silent corruption cannot become a cache hit."""
    path = tmp_path / "revision"
    save_structure(path, structure)

    arrays = dict(np.load(path.with_suffix(".npz")))
    first = sorted(arrays)[0]
    arrays[first] = arrays[first] + np.asarray(1.0, dtype=arrays[first].dtype)
    np.savez_compressed(path.with_suffix(".npz"), **arrays)

    with pytest.raises(ValueError, match="content hash"):
        load_structure(path)


# -- 2. forward compatibility -------------------------------------------------


def test_the_manifest_names_the_schema(structure, tmp_path) -> None:
    save_structure(tmp_path / "revision", structure)

    manifest = json.loads((tmp_path / "revision.json").read_text(encoding="utf-8"))

    assert manifest["schema_id"] == SCHEMA_ID == "structure.v2"
    assert manifest["grid"]["spacing"] == structure.grid.spacing
    assert [entry["id"] for entry in manifest["materials"]] == list(structure.materials)


def test_an_unknown_key_is_ignored_rather_than_refused(structure, tmp_path) -> None:
    """Plan §9's forward compatibility, carried over from docs §4.1 invariant 5."""
    path = tmp_path / "revision"
    save_structure(path, structure)
    manifest = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    manifest["a_thing_from_the_future"] = {"nested": [1, 2, 3]}
    manifest["materials"][0]["provenance"] = "an argon ion source, 2031"
    path.with_suffix(".json").write_text(json.dumps(manifest), encoding="utf-8")

    loaded = load_structure(path)

    assert loaded.materials == structure.materials


def test_a_file_from_another_schema_is_refused(structure, tmp_path) -> None:
    """Ignoring unknown *keys* is not the same as ignoring an unknown *format*."""
    path = tmp_path / "revision"
    save_structure(path, structure)
    manifest = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    manifest["schema_id"] = "structure.v3"
    path.with_suffix(".json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="structure.v3"):
        load_structure(path)


# -- 3. a whole revision, not only its geometry -------------------------------


def test_a_revision_round_trips_with_its_provenance(chain, tmp_path) -> None:
    """Plan §3.6's fields are the ones a saved session has to still have."""
    original = chain[-1]
    path = tmp_path / "rev"
    save_revision(path, original)
    loaded = load_revision(path)

    assert loaded.index == original.index
    assert loaded.parent == original.parent
    assert loaded.capabilities == original.capabilities
    assert loaded.history == original.history
    assert loaded.validation.warnings == original.validation.warnings
    assert loaded.validation.failures == original.validation.failures
    assert loaded.validation.balance == original.validation.balance
    assert loaded.validation.shared_with_parent == original.validation.shared_with_parent
    assert loaded.lineage.entries == original.lineage.entries
    assert loaded.logs == original.logs
    for material in original.structure.materials:
        assert np.array_equal(
            np.asarray(loaded.structure.phi_of(material)),
            np.asarray(original.structure.phi_of(material)),
        )


def test_measurements_and_artifacts_keep_their_units_and_uris(structure, tmp_path) -> None:
    revision = Revision(
        index=0,
        parent=None,
        structure=structure,
        capabilities=frozenset({"material:silicon"}),
        history=HistoryEntry(index=0, step_id="inspect.sem"),
        artifacts=(ArtifactRef("image", "artifacts/sem-0.png", "SEM", "image/png"),),
        measurements={"width": Quantity(101.0, "nm"), "ratio": Quantity(0.9)},
    )
    path = tmp_path / "rev"
    save_revision(path, revision)
    loaded = load_revision(path)

    assert loaded.measurements == revision.measurements
    assert loaded.artifacts == revision.artifacts


# -- 4. a whole chain ---------------------------------------------------------


def test_a_chain_round_trips_and_stays_replayable(chain, tmp_path) -> None:
    """The DoD's save/load half: a loaded session is the session that was saved."""
    directory = tmp_path / "session"
    save_chain(directory, chain)
    loaded = load_chain(directory)

    assert len(loaded) == len(chain)
    assert loaded.recipe_id == chain.recipe_id
    assert loaded.position == chain.position
    assert [s.step_id for s in loaded] == [s.step_id for s in chain]
    assert loaded.capabilities == chain.capabilities
    for index in range(len(chain)):
        before, after = chain[index], loaded[index]
        assert after.capabilities == before.capabilities
        assert after.structure.materials == before.structure.materials
        for material in before.structure.materials:
            assert np.array_equal(
                np.asarray(after.structure.phi_of(material)),
                np.asarray(before.structure.phi_of(material)),
            )


def test_a_spilled_revision_is_faulted_back_from_disk(chain, tmp_path) -> None:
    """Plan §8's laziness, which is the *chain's* and not the revision's.

    A revision stores its structure (plan §3.6 as written); what the chain does
    is keep the recently touched ones and hand the rest to the store. Scrubbing
    back to step 0 of a long run therefore costs one `np.load`, measured at 10 ms
    — below a frame — rather than a replay.
    """
    store = FileRevisionStore(tmp_path / "cache")
    lazy = RevisionChain(recipe_id=chain.recipe_id, store=store, resident=1)
    for index in range(len(chain)):
        lazy.append(chain[index])

    assert not lazy.is_resident(0)
    assert lazy.spills == len(chain) - 1

    first = lazy[0]

    assert lazy.faults == 1
    assert first.step_id == chain[0].step_id
    assert np.array_equal(
        np.asarray(first.structure.phi_of(SILICON)),
        np.asarray(chain[0].structure.phi_of(SILICON)),
    )


def test_a_summary_is_readable_without_faulting_anything(chain, tmp_path) -> None:
    """A step list and a run log must not drag 6 MB per row back off disk."""
    store = FileRevisionStore(tmp_path / "cache")
    lazy = RevisionChain(recipe_id=chain.recipe_id, store=store, resident=1)
    for index in range(len(chain)):
        lazy.append(chain[index])

    summaries = [entry.step_id for entry in lazy]
    logs = lazy.logs()

    assert summaries == [chain[i].step_id for i in range(len(chain))]
    assert len(logs) >= len(chain)
    assert lazy.faults == 0
