# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for the v2 application (plan §11, roadmap E19).

    pyinstaller nanofab_v3.spec

Interview decision Q2 and plan §11: *modular registry in source, monolith in
delivery.* One application, with the builtin process set and numpy/scipy frozen
in. Explicitly no multi-exe delivery, and heavy external solvers — when they come
— run as subprocesses with their own environment and talk through §9's exchange
format rather than being linked in here.

## What a delivered folder holds, and why it is a folder at all

    nanofab_v3            the executable
    bin/                  everything PyInstaller collected — DLLs, numpy, Qt
    data/materials/       the library: one JSON file per material
    data/demos/           the worked examples
    settings.ini          what is switched on, and what is already in the box

**and nothing else.** M9's follow-up shipped a one-file exe with the two data
directories placed beside it, which left the library in two places at once: the
sealed copy the exe carried and the visible copy an operator edits. Roadmap E19
ends that, and the argument is not about size — it is that when the two disagree
nobody can say which one ran, and the visible one silently winning is worse than
not having it. So `--onedir`, `contents_directory="bin"` to keep the several
hundred collected files out of the way, and the data directories as the **only**
copy.

The price is stated rather than mitigated: there is no fallback. A delivery whose
`data/materials/` is missing stops at startup and says where it looked
(`materials.store.missing_library_reason`), and one whose `data/demos/` is
missing opens with an empty Demos menu. And `didactic_library()` loses its
isolation in a delivered build, because the only root is the operator's — which
is why `--selftest` and `--version` print a library fingerprint (E36) instead of
claiming a separation they no longer have.

The wheel is unaffected: `pyproject.toml`'s `package-data` still carries the
library, and only the frozen build gives up its packaged copy.

## The rest of the recipe, six decisions read against v0.2.0's spec

`ui_backups/2026-08-25_v0.2.0_nanofab-manager/nanofab_manager.spec` is a working
recipe for the *old* application and a record rather than a branch
(`AGENTS.md` §7). Where this differs:

1. **`console=True`**, where v0.2.0 froze a windowed app. Plan §14's DoD for M5
   is *"packaged exe runs S1-S4"*, and the way it does that is `--selftest`
   (`nanofab_v3.acceptance` records why a flag and not a menu entry). A flag
   with no stdout is a flag with no result, so the console stays. The cost is
   recorded rather than hidden: on Windows this means a terminal behind the
   application window. `--report PATH` is there for a build that would rather
   read a file.

2. **`hiddenimports` names the process modules.** `registry.builtin_registry()`
   imports them inside the function — deliberately, so a plugin host can import
   the registry without pulling in every process — and PyInstaller's static
   analysis does not follow a function-local import. Without these the exe
   starts, shows an empty step list, and passes no scenario. This is exactly the
   failure handoff §4 warns about: it cannot happen in a source checkout, only
   in the frozen build.

3. **`scipy` is a `collect_submodules`**, not a bare import. `kernel.reinit`,
   `kernel.regions` and `kernel.predicates` reach `scipy.ndimage` and its
   compiled backends through lazy submodule imports that the analyser misses in
   the same way.

4. **`upx=False`**, where v0.2.0 had it on. UPX and numpy's compiled extensions
   are a known source of build-machine-specific breakage, and the thing being
   delivered here is a model whose answers have to be the same on somebody
   else's machine. A smaller download is not worth a class of failure that only
   appears there.

5. **`datas` carries the artwork and *not* the library.** The icon is not a file
   an operator edits, so it stays inside `bin/` where the rest of the collection
   is; the library and the demos are exactly the files an operator edits, so they
   are placed beside the executable by the block after `COLLECT(...)` and are not
   collected at all. That block is also what writes `settings.ini`, from
   `nanofab_v3.settings.default_ini_text()` — the same text the application
   restores if the file is deleted, so there is one definition of the defaults.

6. **`icon=`** points at `nanofab_v3/assets/nanofab.ico` (roadmap E20), rendered
   from the versioned SVG by `scripts/make_icon.py`. Ignored when the build host
   is not Windows or macOS, which is why the window sets the same file itself.

`excludes` drops the test and packaging machinery: pytest is not part of the
delivery, and `--selftest` runs the scenarios out of `nanofab_v3.acceptance`
instead — which is the whole reason that module is in the package.
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# See note 5: the artwork travels inside the collection; the library does not.
datas = collect_data_files("nanofab_v3", includes=["assets/*"])

hiddenimports = [
    # `builtin_registry()` imports these inside the function (see note 2).
    "nanofab_v3.processes.anneal",
    "nanofab_v3.processes.contamination",
    "nanofab_v3.processes.deposition",
    "nanofab_v3.processes.etching",
    "nanofab_v3.processes.inspection",
    "nanofab_v3.processes.lithography",
    "nanofab_v3.processes.removal",
    "nanofab_v3.processes.substrate",
    # The scenarios the DoD is about, and the shell they run next to.
    "nanofab_v3.acceptance",
    "nanofab_v3.cli",
    "nanofab_v3.settings",
    "nanofab_v3.ui.window",
    "nanofab_v3.ui.library_window",
    "nanofab_v3.ui.wafer_view",
] + collect_submodules("scipy")

a = Analysis(
    ["nanofab_v3/__main__.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "_pytest", "pluggy", "setuptools", "pip", "tkinter"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="nanofab_v3",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="nanofab_v3/assets/nanofab.ico",
    # See E19: the several hundred collected files go here, so what is left in the
    # delivered folder is the executable and the four things somebody opens.
    # On `EXE` rather than on `COLLECT`, although it describes the collected
    # layout — PyInstaller reads it off the executable's options table, and set on
    # `COLLECT` it is silently ignored and the folder comes out as `_internal`.
    contents_directory="bin",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="nanofab_v3",
)


# The editable half of the delivery: the only copy of the library and the demos,
# and the settings file that documents itself. See E19 and E39.
import shutil
import sys
from pathlib import Path

_APP = Path(DISTPATH) / "nanofab_v3"

for _name in ("materials", "demos"):
    _source = Path(SPECPATH) / "nanofab_v3" / "data" / _name
    _target = _APP / "data" / _name
    if _source.is_dir():
        shutil.rmtree(_target, ignore_errors=True)
        shutil.copytree(_source, _target)
        print(f"placed {_target} ({len(list(_target.glob('*')))} files)")

# `data/materials/.original/` is E37's "reset to what was delivered": exactly one
# extra copy, the unchanged one, read only when somebody asks for it back. It is
# not a second library — nothing loads from it — which is what keeps it outside
# E19's "two truths" problem.
_original = _APP / "data" / "materials" / ".original"
_shipped = Path(SPECPATH) / "nanofab_v3" / "data" / "materials"
if _shipped.is_dir():
    shutil.rmtree(_original, ignore_errors=True)
    shutil.copytree(_shipped, _original)
    print(f"placed {_original} (the delivered state, for 'reset')")

sys.path.insert(0, str(Path(SPECPATH)))
from nanofab_v3.settings import default_ini_text  # noqa: E402

_ini = _APP / "settings.ini"
_ini.write_text(default_ini_text(), encoding="utf-8")
print(f"wrote {_ini} ({len(default_ini_text().splitlines())} lines, all defaults)")
