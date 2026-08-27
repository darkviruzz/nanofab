# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for the v2 application (plan §11).

    pyinstaller nanofab_v3.spec

Interview decision Q2 and plan §11: *modular registry in source, monolith in
delivery.* **One** exe, with the builtin process set and numpy/scipy frozen in.
Explicitly no multi-exe delivery, and heavy external solvers — when they come —
run as subprocesses with their own environment and talk through §9's exchange
format rather than being linked in here.

Read against `ui_backups/2026-08-25_v0.2.0_nanofab-manager/nanofab_manager.spec`,
which is a working recipe for the *old* application and a record rather than a
branch (`AGENTS.md` §7). Six things differ, and each is a decision:

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

5. **`datas` carries `nanofab_v3/data/`.** Since M6 the material library is JSON
   files rather than a Python literal (roadmap E14), and since M9's follow-up the
   demos are too; PyInstaller collects data only when told to. Without this the
   exe starts, finds not a single `MaterialType`, and every scenario dies at the
   first rate lookup — the same class of build-only failure as note 2, which is
   why `materials.store.builtin_materials_dir()` checks `importlib.resources`
   first and the package directory second, and why `--selftest` prints how many
   materials and demos it loaded.

6. **The same two directories are also *placed beside* the exe** (the block after
   `EXE(...)`). Those are the copies an operator edits: a rate, a duration, a new
   demo. The exe keeps its own sealed copy and runs alone without them, and
   `paths.portable_dir()` is what prefers the visible one at runtime.

   This is deliberately **not** a one-directory build. `--onedir` would put
   `data/` beside the executable for free and bury it among several hundred DLLs,
   which is worse than sealing it: the point is a folder somebody can find. Plan
   §11's one-file decision therefore stands, and the cost is these twelve lines.

`excludes` drops the test and packaging machinery: pytest is not part of the
delivery, and `--selftest` runs the scenarios out of `nanofab_v3.acceptance`
instead — which is the whole reason that module is in the package.
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# See note 5: the library and the demos are data files inside the package.
datas = collect_data_files(
    "nanofab_v3", includes=["data/materials/*.json", "data/demos/*.json"]
)

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
    "nanofab_v3.ui.window",
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
    a.binaries,
    a.datas,
    [],
    name="nanofab_v3",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)


# See note 6: the editable copies, beside the exe rather than inside it.
import shutil
from pathlib import Path

for _name in ("materials", "demos"):
    _source = Path(SPECPATH) / "nanofab_v3" / "data" / _name
    _target = Path(DISTPATH) / "data" / _name
    if _source.is_dir():
        shutil.copytree(_source, _target, dirs_exist_ok=True)
        print(f"placed {_target} ({len(list(_target.glob('*')))} files) beside the exe")
