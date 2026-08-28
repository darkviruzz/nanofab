# `data/materials/` — the material library

One JSON file per material, named after the `material_id` it defines. This
directory **is** the library: since milestone M6 (roadmap E14) no `MaterialType`
is constructed in code, and `nanofab_v3.materials.library.didactic_library()`
reads what is here.

- The format is `nanofab_v3/materials/schema.py`, version `1`. Every file carries
  `"schema": 1`; an unknown version is refused rather than read best-effort.
- A field left out takes the dataclass default, so a file says what is *special*
  about its material. A submodel that is present is written whole.
- `"inherits": "parent_id"` starts from a material in the same or an earlier
  root, then applies the child file's fields; mapping fields merge. Missing
  parents and cycles are refused. `chrome_redeposit.json` is the first example.
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
  the named material rows under `ion_beam`, `icp_fluorine`, `rie_chlorine`,
  `rie_oxygen`, `wet_etch_cr`, `wet_etch_oxide` and `sputter_deposit`;
- **chosen so an acceptance scenario shows its mechanism at a readable scale** —
  everything under the older `wet_etch`, `dry_etch` and `deposit` classes, the
  six `ion_beam` materials absent from the table, and every develop and dissolve
  model. What carries the physics there is the *ratios*: a mask that does not
  etch, a resist that dissolves and a metal that does not, an oxide a wet etchant
  attacks and silicon it does not.

M11 removed the duplicate `sputter_etch` class: one physical ion-beam technique
now has one `ion_beam` rate. The five table materials use the table values; the
six materials the table does not name preserve their former didactic ratios,
scaled by 0.23 and marked as didactic in `rate_notes`. The one affected scenario,
S2c, compensates explicitly with its duration and scale.

M12 adds `hard_bake` to the generic resist: the target identity
`resist_hardbaked` is the semantic transition the process demonstrates, while
the 150 C activation threshold is **didactic, not measured**. It is deliberately
stored on the source material rather than typed into a bake recipe; a calibrated
resist replaces that model in its own material file.

`notes` says what an entry as a whole is; `rate_notes` says it per process class,
and is where an **assumption** is recorded. The table names "silicon oxide" for
ion-beam etching and "fused silica" for the plasma chemistries, and both are
carried here as separate materials; where it is silent about one, that one takes
the other's value and the note begins with `Assumed` (roadmap §3.1).

A rate that is *absent* is a rate nobody stated: `MaterialType.rate_for` answers
0.0, which means "this does not move", and that is a deliberate statement in the
didactic classes — it is how a hard mask behaves without being modelled as one.
Under a chemistry class it means the table has no row for that pair; `titania`
has no table chemistry rate, and says so in its `notes` rather than leaving a
reader to guess whether TiO2 is inert.

## Adding one

Copy an existing file, change the id and the numbers, and drop it into the
writable root — no rebuild, no code change. The application will pick it up on
the next start.

A material a sample carries that no file describes is never silent (roadmap
E15): the step still runs — trying something uncalibrated is the didactic point —
but it warns, says so in the run log, and in the shell raises a dialog that
writes the file for you. It goes to the writable root and is marked uncalibrated,
which is what tells a later reader that nothing in it came from a measurement.

A rate a file simply does not list is a different thing and does **not** warn:
`rate_for` answers 0.0, which is the deliberate statement "this does not move".

## Provenance: the rule every number in here follows

Handoff §3.3 promoted this from four precedents to a rule, and M10 wrote it down,
because backlog **B7** — calibrated rates, one file set per tool — arrives through
exactly this seam, and whoever writes those files should not have to infer the
convention from examples.

**Every rate is measured, assumed, or didactic.**

- **Measured** — it comes from a source that measured it. The source is named in
  `rate_notes`: *"Student process table, roadmap §3 row 5 (1000 nm/min)."* The
  number and where it came from travel together; a rate without a source is a
  rate nobody can check.
- **Assumed** — a real number, taken from somewhere it does not strictly belong.
  The two SiO₂ entries are the standing example: the table names "silicon oxide"
  for ion-beam etching and "fused silica" for the plasma chemistries, this library
  carries both as separate materials, and each borrows the other's value where
  the table is silent. `rate_notes` begins with `"Assumed, not measured."` — a
  **field**, not a comment, so a UI can print "assumed" beside the number and a
  reader of the file cannot miss it.
- **Didactic** — chosen so a scenario shows its mechanism at a readable scale.
  The etch-stop selectivity (25:1 between `titania` and `alumina`) is the
  example: the *ratio* is chosen, the *direction* is physics — a fluorine plasma
  makes AlF₃, which is not volatile — and both files say exactly that.

Three consequences, and they are the parts that are easy to get wrong:

1. **Absent beats invented.** A rate the file does not list reads 0.0, which is a
   statement, not a gap. `titania` carries no chemistry rates at all and its
   `notes` say that a zero there means "nobody stated one" rather than "inert".
   Inventing a plausible number is worse than leaving it out, because a plausible
   wrong number is indistinguishable from a right one.
2. **Invented-and-marked beats invented.** A number is dishonest when it cannot
   be told apart from a measured one, not when it is chosen. Choose it, and say
   in `rate_notes` that you did.
3. **One physical technique has one key.** M11's E24 retired `sputter_etch` and
   kept provenance per value instead: table rows remain measured, absent rows
   remain explicitly didactic. Saved recipes that name the removed process fail
   loudly rather than being reinterpreted.

The library window (roadmap E37) enforces the rule where it is easiest to break:
editing a rate rewrites its `rate_notes` to *"Edited &lt;date&gt; (was &lt;value&gt;;
&lt;what the note used to say&gt;)"*, so the file never keeps a provenance for a
number that no longer has it. A note you write yourself is left alone — somebody
who typed a provenance knows more about it than the editor does.
