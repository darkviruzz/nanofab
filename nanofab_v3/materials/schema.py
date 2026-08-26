"""`MaterialType` to JSON and back, losslessly (roadmap E14).

The whole library moved to `data/materials/*.json` in M6, one file per material,
and this module is the only place that knows what those files look like. It
exists because the migration's acceptance criterion is **bit-identical models**:
a library read from disk must be the same value the code used to hold, down to
the last float, or a saved session's rates would quietly differ from the ones it
ran under.

That is possible at all because of a property the roadmap measured rather than
assumed (§0): `MaterialType` and every submodel it carries — `SputterResponse`,
`DevelopModel`, `DissolveModel`, and `SpinCurve` since M6 — are frozen dataclasses
of **scalars only**. No
callables, no arrays, no state. So the encoding is mechanical and the decoding is
the dataclass constructor, which is also the validator: an out-of-range number
fails in `__post_init__` exactly where it would have failed had a human typed it
into the source.

Two rules the format follows, both for the benefit of the person reading a file
rather than of the parser:

- **A top-level field equal to its default is not written.** A material with no
  develop model has no `develop` key, not `"develop": null`, so what a file says
  is what is *special* about that material. Round-tripping is unaffected: the
  decoder applies the same defaults the dataclass does.
- **A submodel that *is* written is written whole.** The opposite rule, for the
  opposite reason: `"develop": {}` is a legal encoding of the default develop
  model and a useless thing to hand somebody who is here to change a clearing
  dose. Once a material has a develop model, all five of its numbers are on the
  page.
- **`schema` is a version, and an unknown one is refused.** A file from a later
  format is not read on a best-effort basis — a rate silently dropped because a
  key moved is the failure mode this whole milestone is about.
"""

from __future__ import annotations

import json
from dataclasses import MISSING, fields as dataclass_fields
from pathlib import Path
from typing import Any, Mapping

from nanofab_v3.materials.material import (
    DevelopModel,
    DissolveModel,
    MaterialId,
    MaterialType,
    SpinCurve,
    SputterResponse,
)

SCHEMA_VERSION = 1
"""The format version every file carries, and the only one this decoder reads."""

_SUBMODELS: dict[str, Any] = {
    "sputter_response": SputterResponse,
    "develop": DevelopModel,
    "dissolve": DissolveModel,
    "spin_curve": SpinCurve,
}
"""Fields of `MaterialType` that are themselves dataclasses of scalars.

`SpinCurve` needs no special case even though its one field is a tuple of pairs:
JSON has arrays, the dataclass normalises them back to tuples of floats in
`__post_init__`, and the round-trip is therefore exact like every other."""

_MAPPINGS = ("rates", "rate_notes")
"""Fields that are `{key: scalar}` and are written with their keys sorted."""


class MaterialFileError(ValueError):
    """A material file is malformed, of an unknown schema, or not a material."""


# -- encoding -----------------------------------------------------------------


def _is_default(spec: Any, value: Any) -> bool:
    """Whether a field still holds the value the dataclass would have given it."""
    if spec.default is not MISSING:
        return bool(value == spec.default)
    if spec.default_factory is not MISSING:
        return bool(value == spec.default_factory())
    return False


def _without_defaults(instance: Any) -> dict[str, Any]:
    """The dataclass's fields, minus every one that still holds its default."""
    return {
        spec.name: getattr(instance, spec.name)
        for spec in dataclass_fields(instance)
        if not _is_default(spec, getattr(instance, spec.name))
    }


def to_dict(entry: MaterialType) -> dict[str, Any]:
    """One `MaterialType` as the JSON object a `data/materials/*.json` holds."""
    encoded: dict[str, Any] = {"schema": SCHEMA_VERSION}
    for name, value in _without_defaults(entry).items():
        if name in _MAPPINGS:
            encoded[name] = {key: value[key] for key in sorted(value)}
        elif name in _SUBMODELS:
            encoded[name] = {
                spec.name: getattr(value, spec.name) for spec in dataclass_fields(value)
            }
        else:
            encoded[name] = value
    return encoded


def to_json(entry: MaterialType) -> str:
    """One material as the text of its file: two-space indent, trailing newline."""
    return json.dumps(to_dict(entry), indent=2, ensure_ascii=False) + "\n"


# -- decoding -----------------------------------------------------------------


def _submodel(payload: Any, factory: Any, what: str) -> Any:
    if payload is None:
        return None
    if not isinstance(payload, Mapping):
        raise MaterialFileError(f"{what} must be a JSON object, got {payload!r}")
    known = {spec.name for spec in dataclass_fields(factory)}
    unknown = sorted(set(payload) - known)
    if unknown:
        raise MaterialFileError(f"{what} has unknown field(s) {unknown}; it takes {sorted(known)}")
    return factory(**dict(payload))


def from_dict(payload: Mapping[str, Any]) -> MaterialType:
    """A JSON object back into a `MaterialType`, with the dataclass validating.

    Nothing here range-checks a number: `MaterialType.__post_init__` and the
    submodels already do, and duplicating the rules is how two of them end up
    disagreeing. What this *does* check is the shape — the schema version, the
    presence of an id, and that no key was silently ignored.
    """
    if not isinstance(payload, Mapping):
        raise MaterialFileError(f"a material file must hold a JSON object, got {payload!r}")
    fields = dict(payload)
    version = fields.pop("schema", None)
    if version != SCHEMA_VERSION:
        raise MaterialFileError(
            f"material schema {version!r} is not the {SCHEMA_VERSION} this build reads"
        )
    known = {spec.name for spec in dataclass_fields(MaterialType)}
    unknown = sorted(set(fields) - known)
    if unknown:
        raise MaterialFileError(
            f"unknown field(s) {unknown} in material {fields.get('material_id')!r}; "
            f"a material takes {sorted(known)}"
        )
    if "material_id" not in fields or "name" not in fields:
        raise MaterialFileError("a material file needs at least 'material_id' and 'name'")
    fields["material_id"] = MaterialId(str(fields["material_id"]))
    for name, factory in _SUBMODELS.items():
        fields[name] = _submodel(fields.get(name), factory, name)
    try:
        return MaterialType(**fields)
    except (TypeError, ValueError) as error:
        raise MaterialFileError(
            f"material {fields.get('material_id')!r} is not valid: {error}"
        ) from None


def from_json(text: str) -> MaterialType:
    """One material from the text of its file."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise MaterialFileError(f"not valid JSON: {error}") from None
    return from_dict(payload)


def read_material(path: Path) -> MaterialType:
    """One material from a file, with the path in any error it raises."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise MaterialFileError(f"cannot read {path}: {error}") from None
    try:
        return from_json(text)
    except MaterialFileError as error:
        raise MaterialFileError(f"{path}: {error}") from None


def write_material(entry: MaterialType, path: Path) -> Path:
    """Write one material to `path`, creating the directory if it is missing."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_json(entry), encoding="utf-8")
    return path
