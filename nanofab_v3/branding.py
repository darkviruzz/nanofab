"""The application's name and its one piece of artwork (roadmap E20).

There was none. Not in `nanofab_v3`, not in `ui_backups/` — the v0.2.0 shell took
a Qt theme icon and painted a fallback when the theme had none, so a delivered
build has never had a mark of its own. E20 settles what that mark is: **not** a
university logo, because a logo is a claim about who made this and there is no
clearance for one, and instead the one motif the whole program is about — a
cross-section, a substrate slab with three patterned lines on it, at the contrast
a 16 px tab needs.

`nanofab.svg` is the source and is versioned; `nanofab.ico` is generated from it
by `scripts/make_icon.py` and is versioned too, because a build that rasterised
its own icon would need Qt's SVG plugin on the build machine and would emit a
different file per Qt version. The `.ico` is what both `setWindowIcon` and
PyInstaller's `icon=` take — one asset, read by Qt without the SVG plugin having
to be frozen.
"""

from __future__ import annotations

from pathlib import Path

ASSETS_SUBDIR = ("assets",)
"""Where the artwork sits, relative to the `nanofab_v3` package root."""

ICON_FILE = "nanofab.ico"
"""The window icon and the executable's icon — the same file, on purpose."""

SVG_FILE = "nanofab.svg"
"""The source the `.ico` is rendered from; see `scripts/make_icon.py`."""


def assets_dir() -> Path:
    """The package's asset directory, in a checkout and in a frozen build alike.

    The same two-candidate lookup as `materials.store.builtin_materials_dir()`,
    for the same reason: `importlib.resources` answers for a zip import and for a
    frozen loader with a resource reader, `__file__` answers for a plain
    directory. Unlike the material library this **stays inside the package** in a
    delivered build (E19 moved out the two directories an operator edits, and an
    icon is not one of them — a delivered folder holds the executable, `bin/`,
    `data/` and `settings.ini`, and nothing else).
    """
    try:
        from importlib import resources

        candidate = Path(str(resources.files("nanofab_v3").joinpath(*ASSETS_SUBDIR)))
        if candidate.is_dir():
            return candidate
    except (ImportError, ModuleNotFoundError, TypeError, OSError):  # pragma: no cover
        pass
    return Path(__file__).resolve().parent.joinpath(*ASSETS_SUBDIR)


def icon_file() -> Path | None:
    """The `.ico`, or `None` when this build did not collect it.

    `None` rather than an exception: a missing icon is a cosmetic defect and a
    window without one still runs every step. It is reported by `--version`, which
    is where a build that forgot its `datas` entry should be visible.
    """
    candidate = assets_dir() / ICON_FILE
    return candidate if candidate.is_file() else None


def svg_file() -> Path | None:
    """The versioned source of the icon, or `None` when it was not collected."""
    candidate = assets_dir() / SVG_FILE
    return candidate if candidate.is_file() else None


__all__ = ["ASSETS_SUBDIR", "ICON_FILE", "SVG_FILE", "assets_dir", "icon_file", "svg_file"]
