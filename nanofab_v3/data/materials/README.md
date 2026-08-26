# `data/materials/` — the material library

One JSON file per material, named after the `material_id` it defines. This
directory **is** the library: since milestone M6 (roadmap E14) no `MaterialType`
is constructed in code, and `nanofab_v3.materials.library.didactic_library()`
reads what is here.

- The format is `nanofab_v3/materials/schema.py`, version `1`. Every file carries
  `"schema": 1`; an unknown version is refused rather than read best-effort.
- A field left out takes the dataclass default, so a file says what is *special*
  about its material. A submodel that is present is written whole.
- `nanofab_v3/materials/store.py` decides which directories are read: this one
  (shipped, read-only) and a writable one outside the package
  (`$NANOFAB_MATERIALS`, else `$XDG_DATA_HOME/nanofab_v3/materials`). A later
  root shadows an earlier one, so a local file overrides a shipped material
  without touching the installation.

## The numbers are didactic, not calibrated

Plan §1's fidelity tier (a), and backlog B7 spells out what would have to happen
for that to change. The eight entries this directory started with were chosen so
an acceptance scenario shows its mechanism at a readable scale: what carries the
physics is their *ratios* — a mask that does not etch, a resist that dissolves
and a metal that does not, an oxide a wet etchant attacks and silicon it does
not.

A rate that is *absent* is a rate nobody stated: `MaterialType.rate_for` answers
0.0, which means "this does not move", and that is a deliberate statement
everywhere it appears — it is how a hard mask behaves without being modelled as
one.

## Adding one

Copy an existing file, change the id and the numbers, and drop it into the
writable root — no rebuild, no code change. The application will pick it up on
the next start. An unknown material met during a run produces a warning and, in
the shell, a dialog that writes the file for you (roadmap E15).
