"""The JSON half of the exchange format (plan §9).

A revision on disk is two files with the same stem: a compressed `.npz` holding
the arrays and a `.json` manifest describing them. The split is what makes the
format serve all three of plan §9's jobs — a saved session, the replay cache, and
handing a structure to an external solver, which can read the manifest with any
JSON parser and the arrays with any numpy.

Three rules the format keeps, and each is a decision rather than a convention:

- **The manifest is the authority on what the arrays mean.** Array entries in the
  `.npz` are named `a0`, `a1`, … and the manifest says which material or field
  each one is. Encoding a material id into an archive member name would make the
  set of legal material ids a function of what a zip entry may be called.
- **The manifest carries a content hash per array.** The cache faults structures
  back into a running chain, so a silently corrupted array would become a wrong
  answer rather than an error. `blake2b` over the raw bytes, 4.4 ms per `phi` at
  the reference grid, checked on load.
- **Unknown keys are ignored, an unknown `schema_id` is not.** Plan §9 and docs
  §4.1 invariant 5: a reader must tolerate fields it has never heard of, which is
  what lets the format grow. It must *not* tolerate a different format claiming
  to be this one.

This module is data conversion only — dataclasses to plain JSON values and back.
`io.exchange` is what writes the files.
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

import numpy as np

from nanofab_v3 import __version__
from nanofab_v3.model.field import FieldKey
from nanofab_v3.model.grid import Grid
from nanofab_v3.model.occurrence import LineageEntry, LineageReport
from nanofab_v3.model.quantity import Quantity
from nanofab_v3.model.reports import BalanceCheck, ValidationReport
from nanofab_v3.model.structure import Structure
from nanofab_v3.runtime.revision import ArtifactRef, HistoryEntry, Revision
from nanofab_v3.runtime.run import LinearTilt, RadialProfile, Recipe, RecipeStep

SCHEMA_ID = "structure.v2"
"""What this format is (plan §9). A file claiming anything else is refused."""


def code_version() -> str:
    """The **coarse** axis of the cache key (plan §8, §21.1, ADR-0004).

    Determinism is promised per machine **and code version**; cross-machine float
    drift is accepted and absorbed here. Bumping `nanofab_v3.__version__` retires
    every cached revision everywhere, which is what this axis is for: it covers
    the things a recipe cannot name — the kernel, numpy/scipy, the interpreter.

    It deliberately stays coarse and deliberately does **not** try to see a step.
    M4 wrote that bumping it was "the intended and only mechanism" for retiring a
    cache, which was honest while this package was the only code that could
    change. M5 added the second axis where a step belongs: the per-step
    `implementation_digest` inside the *recipe* hash
    (`processes.registry.implementation_digest`, `io.store.recipe_hash`), so
    editing one step retires the recipes that use it rather than everything, and
    a plugin's step is in the key at all.
    """
    return __version__


def content_hash(array: np.ndarray) -> str:
    """`blake2b` of an array's raw bytes, with its dtype and shape.

    Dtype and shape are in the digest because two arrays with the same bytes and
    different shapes are different arrays, and a hash that could not tell them
    apart would be checking less than it claims.
    """
    contiguous = np.ascontiguousarray(array)
    digest = hashlib.blake2b(digest_size=16)
    digest.update(str(contiguous.dtype).encode())
    digest.update(str(contiguous.shape).encode())
    digest.update(contiguous.tobytes())
    return digest.hexdigest()


# -- grid ---------------------------------------------------------------------


def grid_to_json(grid: Grid) -> dict[str, Any]:
    return {
        "origin": list(grid.origin),
        "spacing": grid.spacing,
        "shape": list(grid.shape),
        "axes": list(grid.axes),
    }


def grid_from_json(data: Mapping[str, Any]) -> Grid:
    return Grid(
        origin=tuple(float(v) for v in data["origin"]),
        spacing=float(data["spacing"]),
        shape=tuple(int(v) for v in data["shape"]),
        axes=tuple(str(v) for v in data["axes"]),
    )


# -- structure ----------------------------------------------------------------


def structure_to_json(structure: Structure) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """Split a `Structure` into its manifest section and its arrays.

    Returns `(manifest, arrays)` where `arrays` is what goes into the `.npz`
    under the generated names the manifest points at.
    """
    arrays: dict[str, np.ndarray] = {}
    materials: list[dict[str, Any]] = []
    for material in structure.materials:
        values = np.asarray(structure.phi_of(material))
        name = f"a{len(arrays)}"
        arrays[name] = values
        materials.append(
            {
                "id": material,
                "array": name,
                "dtype": str(values.dtype),
                "hash": content_hash(values),
            }
        )
    fields: list[dict[str, Any]] = []
    for key, values in structure.fields.items():
        values = np.asarray(values)
        name = f"a{len(arrays)}"
        arrays[name] = values
        fields.append(
            {
                "name": key.name,
                "material": key.material,
                "array": name,
                "dtype": str(values.dtype),
                "hash": content_hash(values),
            }
        )
    manifest = {
        "grid": grid_to_json(structure.grid),
        "materials": materials,
        "fields": fields,
        # Scalars, so they go in the manifest rather than the archive — which is
        # also what makes them readable by an external solver that only parses
        # the JSON (plan §9's third job). See `Structure`'s docstring for why the
        # substrate's thickness is one of these and not a `Field`.
        "metadata": dict(structure.metadata),
    }
    return manifest, arrays


def structure_from_json(
    data: Mapping[str, Any], arrays: Mapping[str, np.ndarray], *, verify: bool = True
) -> Structure:
    """Rebuild a `Structure` from its manifest section and the loaded arrays."""
    grid = grid_from_json(data["grid"])
    phi = {
        entry["id"]: _array(arrays, entry, verify=verify) for entry in data.get("materials", ())
    }
    fields = {
        FieldKey(entry["name"], entry.get("material")): _array(arrays, entry, verify=verify)
        for entry in data.get("fields", ())
    }
    # `.get` with a default rather than `data["metadata"]`: a file written before
    # M7 has no metadata key, and this format's own rule is that a reader
    # tolerates what it has never heard of (plan §9, docs §4.1 invariant 5).
    metadata = dict(data.get("metadata", {}))
    return Structure(grid, phi, fields, metadata)


def _array(
    arrays: Mapping[str, np.ndarray], entry: Mapping[str, Any], *, verify: bool
) -> np.ndarray:
    """One array named by a manifest entry, in the dtype the manifest recorded."""
    try:
        values = np.asarray(arrays[entry["array"]])
    except KeyError:
        raise ValueError(
            f"the manifest names array {entry['array']!r}, which the archive does not have"
        ) from None
    declared = entry.get("dtype")
    if declared is not None and str(values.dtype) != declared:
        values = values.astype(np.dtype(declared))
    expected = entry.get("hash")
    if verify and expected is not None and content_hash(values) != expected:
        raise ValueError(
            f"array {entry['array']!r} does not match its content hash — "
            "the file was changed or truncated after it was written"
        )
    return values


# -- provenance ---------------------------------------------------------------


def history_to_json(history: HistoryEntry) -> dict[str, Any]:
    return {
        "index": history.index,
        "step_id": history.step_id,
        "display_name": history.display_name,
        "params": dict(history.params),
        "recipe_id": history.recipe_id,
        "position": list(history.position),
        "started_at": history.started_at,
        "duration_s": history.duration_s,
    }


def history_from_json(data: Mapping[str, Any]) -> HistoryEntry:
    position = tuple(float(v) for v in data.get("position", (0.0, 0.0)))
    return HistoryEntry(
        index=int(data["index"]),
        step_id=str(data["step_id"]),
        display_name=str(data.get("display_name", "")),
        params=dict(data.get("params", {})),
        recipe_id=str(data.get("recipe_id", "recipe")),
        position=(position[0], position[1]),
        started_at=str(data.get("started_at", "")),
        duration_s=float(data.get("duration_s", 0.0)),
    )


def report_to_json(report: ValidationReport) -> dict[str, Any]:
    balance = report.balance
    return {
        "failures": list(report.failures),
        "warnings": list(report.warnings),
        "reinit_displacement": report.reinit_displacement,
        "reinit_measure_moved": report.reinit_measure_moved,
        "band_gradient_error": report.band_gradient_error,
        "max_overlap_depth": report.max_overlap_depth,
        "boundary_faces": [list(face) for face in report.boundary_faces],
        "balance": None
        if balance is None
        else {
            "expected": balance.expected,
            "measured": balance.measured,
            "tolerance": balance.tolerance,
        },
        "field_resets": dict(report.field_resets),
        "capabilities": sorted(report.capabilities),
        "shared_with_parent": list(report.shared_with_parent),
    }


def report_from_json(data: Mapping[str, Any]) -> ValidationReport:
    balance = data.get("balance")
    return ValidationReport(
        failures=tuple(data.get("failures", ())),
        warnings=tuple(data.get("warnings", ())),
        reinit_displacement=float(data.get("reinit_displacement", 0.0)),
        reinit_measure_moved=float(data.get("reinit_measure_moved", 0.0)),
        band_gradient_error=float(data.get("band_gradient_error", 0.0)),
        max_overlap_depth=float(data.get("max_overlap_depth", 0.0)),
        boundary_faces=tuple((str(a), str(b)) for a, b in data.get("boundary_faces", ())),
        balance=None
        if balance is None
        else BalanceCheck(
            expected=float(balance["expected"]),
            measured=float(balance["measured"]),
            tolerance=float(balance["tolerance"]),
        ),
        field_resets={str(k): int(v) for k, v in data.get("field_resets", {}).items()},
        capabilities=frozenset(data.get("capabilities", ())),
        shared_with_parent=tuple(data.get("shared_with_parent", ())),
    )


def lineage_to_json(lineage: LineageReport) -> list[dict[str, Any]]:
    return [
        {
            "material": entry.material,
            "kind": entry.kind,
            "parents": list(entry.parents),
            "children": list(entry.children),
        }
        for entry in lineage.entries
    ]


def lineage_from_json(data: Any) -> LineageReport:
    return LineageReport(
        entries=tuple(
            LineageEntry(
                material=str(entry["material"]),
                kind=entry["kind"],
                parents=tuple(int(v) for v in entry.get("parents", ())),
                children=tuple(int(v) for v in entry.get("children", ())),
            )
            for entry in data or ()
        )
    )


def revision_to_json(revision: Revision) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """A whole `Revision` as `(manifest, arrays)` — plan §3.6's fields, all of them."""
    manifest, arrays = structure_to_json(revision.structure)
    manifest.update(
        {
            "schema_id": SCHEMA_ID,
            "code_version": code_version(),
            "index": revision.index,
            "parent": revision.parent,
            "capabilities": sorted(revision.capabilities),
            "history": history_to_json(revision.history),
            "artifacts": [
                {
                    "kind": ref.kind,
                    "uri": ref.uri,
                    "label": ref.label,
                    "media_type": ref.media_type,
                }
                for ref in revision.artifacts
            ],
            "validation": report_to_json(revision.validation),
            "lineage": lineage_to_json(revision.lineage),
            "measurements": {
                name: {"value": q.value, "unit": q.unit}
                for name, q in revision.measurements.items()
            },
            "logs": list(revision.logs),
        }
    )
    return manifest, arrays


def revision_from_json(
    data: Mapping[str, Any], arrays: Mapping[str, np.ndarray], *, verify: bool = True
) -> Revision:
    """Rebuild a `Revision`, tolerating keys this version has never heard of."""
    check_schema(data)
    parent = data.get("parent")
    return Revision(
        index=int(data["index"]),
        parent=None if parent is None else int(parent),
        structure=structure_from_json(data, arrays, verify=verify),
        capabilities=frozenset(data.get("capabilities", ())),
        history=history_from_json(data["history"]),
        artifacts=tuple(
            ArtifactRef(
                kind=str(ref.get("kind", "")),
                uri=str(ref.get("uri", "")),
                label=str(ref.get("label", "")),
                media_type=str(ref.get("media_type", "")),
            )
            for ref in data.get("artifacts", ())
        ),
        validation=report_from_json(data.get("validation", {})),
        lineage=lineage_from_json(data.get("lineage")),
        measurements={
            name: Quantity(float(q["value"]), str(q.get("unit", "")))
            for name, q in data.get("measurements", {}).items()
        },
        logs=tuple(data.get("logs", ())),
    )


# -- the recipe ---------------------------------------------------------------


def _value_to_json(value: Any) -> Any:
    """One recipe parameter value, wafer-parameterised ones included.

    A parameter that varies over the wafer is data, not a resolved number, so a
    saved recipe has to carry the *function* — otherwise reopening a session and
    adding a wafer position would silently apply the old position's values. The
    two built-ins encode themselves; anything else raises rather than being
    written as its resolved value at some arbitrary position, because that is the
    failure that would look like it worked.
    """
    if isinstance(value, RadialProfile):
        return {"kind": "radial", "radii": list(value.radii), "values": list(value.values)}
    if isinstance(value, LinearTilt):
        return {"kind": "tilt", "center": value.center, "gradient": list(value.gradient)}
    if isinstance(value, Quantity):
        return {"kind": "quantity", "value": value.value, "unit": value.unit}
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    if hasattr(value, "at"):
        raise ValueError(
            f"{type(value).__name__} varies over the wafer and this format does not know "
            "how to write it; RadialProfile and LinearTilt are the two it does"
        )
    raise ValueError(f"cannot write a recipe parameter of type {type(value).__name__}")


def _value_from_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        kind = value.get("kind")
        if kind == "radial":
            return RadialProfile(
                radii=tuple(float(v) for v in value["radii"]),
                values=tuple(float(v) for v in value["values"]),
            )
        if kind == "tilt":
            gradient = tuple(float(v) for v in value.get("gradient", (0.0, 0.0)))
            return LinearTilt(center=float(value["center"]), gradient=(gradient[0], gradient[1]))
        if kind == "quantity":
            return Quantity(float(value["value"]), str(value.get("unit", "")))
        raise ValueError(f"unknown parameter encoding {kind!r}")
    return value


def recipe_to_json(recipe: Recipe) -> dict[str, Any]:
    """A whole `Recipe` as plain JSON values — steps, wafer parameters and grid."""
    return {
        "schema_id": SCHEMA_ID,
        "code_version": code_version(),
        "recipe_id": recipe.recipe_id,
        "grid": grid_to_json(recipe.grid),
        "steps": [
            {
                "step_id": step.step_id,
                "params": {name: _value_to_json(v) for name, v in step.params.items()},
            }
            for step in recipe.steps
        ],
    }


def recipe_from_json(data: Mapping[str, Any]) -> Recipe:
    """Rebuild a `Recipe`, tolerating keys this version has never heard of."""
    check_schema(data)
    return Recipe(
        grid=grid_from_json(data["grid"]),
        steps=tuple(
            RecipeStep(
                step_id=str(entry["step_id"]),
                params={
                    name: _value_from_json(value)
                    for name, value in entry.get("params", {}).items()
                },
            )
            for entry in data.get("steps", ())
        ),
        recipe_id=str(data.get("recipe_id", "recipe")),
    )


def check_schema(data: Mapping[str, Any]) -> None:
    """Refuse a file that is not this format; say nothing about extra keys.

    The asymmetry is the whole of plan §9's forward compatibility: a reader that
    refused unknown *keys* could never be extended, and a reader that accepted an
    unknown *schema* would read another format's bytes as this one's.
    """
    found = data.get("schema_id")
    if found != SCHEMA_ID:
        raise ValueError(
            f"this file declares schema_id {found!r}; {SCHEMA_ID!r} is what this "
            "version of nanofab_v3 can read"
        )
