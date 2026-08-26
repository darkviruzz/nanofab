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
`application_library()` is that plus the operator's own directory.
"""

from __future__ import annotations

from nanofab_v3.materials.library import (
    ALUMINA,
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
    ION_BEAM,
    PROCESS_CLASSES,
    WET_ETCH,
    DevelopModel,
    DissolveModel,
    MaterialId,
    MaterialType,
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
    invalidate_cache,
    load_library,
    material_roots,
    save_material,
    user_materials_dir,
)

__all__ = [
    "ALUMINA",
    "DEPOSIT",
    "DEVELOP",
    "DISSOLVE",
    "DRY_ETCH",
    "HARD_RESIST",
    "ION_BEAM",
    "METAL",
    "OXIDE",
    "PARTICLE",
    "PROCESS_CLASSES",
    "RESIST",
    "SCHEMA_VERSION",
    "SILICON",
    "UNDERLAYER",
    "WET_ETCH",
    "DevelopModel",
    "DissolveModel",
    "LibraryReport",
    "MaterialFileError",
    "MaterialId",
    "MaterialLibrary",
    "MaterialType",
    "SputterResponse",
    "application_library",
    "builtin_materials_dir",
    "didactic_library",
    "from_dict",
    "from_json",
    "invalidate_cache",
    "load_library",
    "material_roots",
    "read_material",
    "save_material",
    "to_dict",
    "to_json",
    "user_materials_dir",
    "write_material",
]
