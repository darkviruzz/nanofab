"""Material library: `MaterialType` entries and `MaterialId` keys (plan §3.4).

Pure data and small model objects — rates per process class, angle-dependent
sputter response, `develop_rate(dose)`, dissolve models. Nothing here imports
`nanofab_v3.kernel` (see `material.py`'s docstring: `kernel.motion` imports
`MaterialId` from here, so the reverse would be a cycle). The seam that turns
these models into the kernel's `SurfaceRates` and `flux.AngularYield` is
`nanofab_v3.processes.rates`.

Since M6 the entries themselves are not in code: `store` reads them from
`data/materials/*.json` and `schema` is the one place that knows what a file
looks like (roadmap E14). `didactic_library()` is the shipped set, and
`application_library()` is that plus the operator's own directory. `unknown`
holds what happens when a sample carries a material none of them describes
(E15): a warning and a question, never a silent rate of zero.
"""

from __future__ import annotations

from nanofab_v3.materials.library import (
    ALUMINA,
    CHROME,
    FUSED_SILICA,
    TITANIA,
    HARD_RESIST,
    METAL,
    PARTICLE,
    OXIDE,
    RESIST,
    SILICON,
    UNDERLAYER,
    LibraryReport,
    MaterialLibrary,
    application_library,
    didactic_library,
)
from nanofab_v3.materials.material import (
    DEPOSIT,
    DEVELOP,
    DISSOLVE,
    DRY_ETCH,
    ICP_FLUORINE,
    ION_BEAM,
    PROCESS_CLASSES,
    RIE_CHLORINE,
    RIE_OXYGEN,
    SPUTTER_DEPOSIT,
    SPUTTER_ETCH,
    WET_ETCH,
    WET_ETCH_CR,
    WET_ETCH_OXIDE,
    DevelopModel,
    DissolveModel,
    MaterialId,
    MaterialType,
    SpinCurve,
    SputterResponse,
)
from nanofab_v3.materials.schema import (
    SCHEMA_VERSION,
    MaterialFileError,
    from_dict,
    from_json,
    read_material,
    to_dict,
    to_json,
    write_material,
)
from nanofab_v3.materials.store import (
    builtin_materials_dir,
    delivered_materials_dir,
    delivered_only,
    didactic_roots,
    invalidate_cache,
    library_fingerprint,
    load_library,
    material_roots,
    missing_library_reason,
    save_material,
    user_materials_dir,
)
from nanofab_v3.materials.unknown import (
    MissingMaterial,
    declared_materials,
    missing_before_running,
    UnknownMaterials,
    UnknownMaterialWarning,
    unknown_materials,
)

__all__ = [
    "ALUMINA",
    "CHROME",
    "DEPOSIT",
    "DEVELOP",
    "DISSOLVE",
    "DRY_ETCH",
    "HARD_RESIST",
    "ICP_FLUORINE",
    "ION_BEAM",
    "METAL",
    "OXIDE",
    "PARTICLE",
    "PROCESS_CLASSES",
    "RESIST",
    "RIE_CHLORINE",
    "RIE_OXYGEN",
    "SCHEMA_VERSION",
    "FUSED_SILICA",
    "SILICON",
    "SPUTTER_DEPOSIT",
    "SPUTTER_ETCH",
    "TITANIA",
    "UNDERLAYER",
    "WET_ETCH",
    "WET_ETCH_CR",
    "WET_ETCH_OXIDE",
    "DevelopModel",
    "DissolveModel",
    "LibraryReport",
    "MaterialFileError",
    "MaterialId",
    "MaterialLibrary",
    "MaterialType",
    "MissingMaterial",
    "SpinCurve",
    "SputterResponse",
    "UnknownMaterialWarning",
    "UnknownMaterials",
    "application_library",
    "builtin_materials_dir",
    "declared_materials",
    "delivered_materials_dir",
    "delivered_only",
    "didactic_library",
    "didactic_roots",
    "from_dict",
    "from_json",
    "invalidate_cache",
    "library_fingerprint",
    "load_library",
    "material_roots",
    "missing_before_running",
    "missing_library_reason",
    "read_material",
    "save_material",
    "to_dict",
    "to_json",
    "unknown_materials",
    "user_materials_dir",
    "write_material",
]
