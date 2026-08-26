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
for that to change. Two provenances live side by side here, and every entry says
per rate which one a number has:

- **the student process table** (roadmap §3, converted from nm/min to nm/s) —
  everything under `sputter_etch`, `icp_fluorine`, `rie_chlorine`, `rie_oxygen`,
  `wet_etch_cr`, `wet_etch_oxide` and `sputter_deposit`;
- **chosen so an acceptance scenario shows its mechanism at a readable scale** —
  everything under the older `wet_etch`, `dry_etch`, `ion_beam` and `deposit`
  classes, and every develop and dissolve model. What carries the physics there
  is the *ratios*: a mask that does not etch, a resist that dissolves and a metal
  that does not, an oxide a wet etchant attacks and silicon it does not.

The two never mix under one key. That is why the table's sputter-etch row is
`sputter_etch` and not `ion_beam`: the didactic `ion_beam` numbers are what S1-S5
are tuned to, and overwriting them with the table's would have changed what every
existing scenario means. Same technique, two rate sets, two keys.

`notes` says what an entry as a whole is; `rate_notes` says it per process class,
and is where an **assumption** is recorded. The table names "silicon oxide" for
sputter etching and "fused silica" for the plasma chemistries, and both are
carried here as separate materials; where it is silent about one, that one takes
the other's value and the note begins with `Assumed` (roadmap §3.1).

A rate that is *absent* is a rate nobody stated: `MaterialType.rate_for` answers
0.0, which means "this does not move", and that is a deliberate statement in the
didactic classes — it is how a hard mask behaves without being modelled as one.
Under a chemistry class it means the table has no row for that pair; `titania` has
none at all, and says so in its `notes` rather than leaving a reader to guess
whether TiO2 is inert.

## Adding one

Copy an existing file, change the id and the numbers, and drop it into the
writable root — no rebuild, no code change. The application will pick it up on
the next start. An unknown material met during a run produces a warning and, in
the shell, a dialog that writes the file for you (roadmap E15).
