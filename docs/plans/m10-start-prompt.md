# Startprompt: Coding-Session Meilenstein M10

Geschrieben 2026-08-27, direkt nach der Grilling-Session, die
`docs/plans/m10-m12-roadmap.md` erzeugt hat. Zum Kopieren in eine **frische**
Session. Umgebungs-Hinweise: siehe `docs/plans/m5-start-prompt.md`.

Alles unterhalb der Linie ist der Prompt.

---

Setze den v2-Datenmodell-Plan für NanoFab fort mit Meilenstein **M10**
(Auslieferung und Auswahl: ein Installationsverzeichnis, typisierte Materialien,
Bibliotheksfenster, Autosave, und die Bugs aus der Benutzung).

Branch: `claude/nanofab-v2-m6-datamodel-ez9dqu` (auschecken bzw. darauf bleiben,
nicht neu branchen).

## Zuerst lesen

1. `AGENTS.md` und `CONTEXT.md`
2. **`docs/plans/m10-m12-roadmap.md`** — dein Bauplan. Besonders §0 (sieben
   nachgemessene Befunde; vier davon haben eine Entscheidung gedreht, du musst
   sie nicht neu messen), §1 (was das Datenmodell abbekommt — und was nicht),
   §2 E19–E40 mit Begründung *und* der jeweils verworfenen Alternative, §4 „M10"
3. `docs/plans/m6-m9-handoff.md` — R1 (E13/E17 fielen durch, weil eine §2-
   Entscheidung nie in einer §4-Aufgabenliste stand: **prüf das für E19–E40, bevor
   du anfängst**), R6, R7, R8, R9 sind hier fällig
4. `docs/plans/v2-structure-model.md` §3.3/§3.4 (Felder und warum die Bibliothek
   hereingereicht wird), §5.3 (Capabilities), §9 (Persistenz), §10 („die UI
   entscheidet Didaktik"), §11 (Packaging), §17 ff. (Korrekturen M0–M9)
5. `docs/plans/m6-m9-roadmap.md` §2 für E1–E18 — E14/E15/E17 setzt M10 fort
6. `docs/plans/backlog-later.md`; ADR-0001…0004; `memory.md` ab 2026-08-26

## Ausgangslage (gemessen)

M0–M9 fertig. **589 Tests grün, 0 übersprungen**, `compileall` sauber, Exe
7/7 in 4.5 s bei 115 MiB. 31 Steps, 13 Prozessklassen, 11 Materialien als JSON in
`nanofab_v3/data/materials/`, 4 Demos als JSON in `nanofab_v3/data/demos/`.
`nanofab_v3/paths.py` kennt schon den Ordner neben der Exe. Speichern ist seit
gestern in `save_recipe` und `save_build` geteilt, und `load_recipe` rechnet
nicht.

## Reihenfolge, und warum

**Das Paket zuerst** (E19/E20/E39/E36). Es ist die einzige Aufgabe, deren
Scheitern man im Quellbaum nicht sieht — dieselbe Klasse Fehler, die M6s
`data/`-Migration hatte. Bau die Exe früh und oft, nicht am Ende.

Danach in beliebiger Reihenfolge, sie hängen nicht aneinander: Materialtypisierung
(E21/E22) · Bibliotheks- und Demofenster (E37) · Sitzung und Artefakte (E38/E40) ·
Bugs und Formulierungen · Bild und Litho (E28/E33) · Substrat (E30).

## Fallen, die diese Roadmap schon kennt

- **Der `adjust`-Bug ist nicht der Filter.** Ursache steht in Roadmap §0.1,
  reproduziert. Repariere die *Ursache* (`_on_revision_chosen` schreibt
  namensbasiert in ein fremdes Formular), nicht das Symptom.
- **E19 nimmt der Anwendung den Fallback.** Ohne `data/materials/` muss der Start
  *laut* abbrechen und den erwarteten Pfad nennen — nicht mit leerer Bibliothek
  weiterlaufen. Und `didactic_library()` verliert im Frozen Build seine Isolation;
  das ist gewollt und wird durch den Fingerabdruck sichtbar gemacht (E36), nicht
  repariert.
- **E22 hat zwei Filterquellen, nicht eine.** Bibliotheksdaten für didaktische
  Schritte, Tags für ideale — `resist.spin_coat` ideal liest keine Spin-Kurve und
  Chrom ist dort trotzdem Unsinn. Das *Ziel*material eines Ätzschritts wird nicht
  ausgewählt und darf nicht gefiltert werden (Alumina hat Fluor-Rate 0 und ist
  genau deshalb die Ätzstopp-Demo).
- **E28 weicht §10 auf.** Der Renderer bekommt die Clearing-Dose. Schreib in den
  Docstring, dass das eine bewusste Ausnahme ist und warum, sonst weicht es weiter
  auf.
- **E33 braucht einen `ParamSpec`-Marker**, keine neue Mechanik: `0` heißt „aus
  der Domain", wie `thickness=0` „aus der Kurve" heißt und `material=""` „aus dem
  Preset". Dritte Instanz derselben Konvention.
- **E37 schreibt in Dateien.** Benutz `write_material` (kanonische Kodierung, von
  einem M6-Test byteweise gepinnt) und schreib atomar. Ein Editor, der
  `rate_notes` unverändert lässt, während er eine Rate ändert, bricht die
  Provenienzregel aus dem Handoff §3.3.
- **E38 rettet das Rezept, nicht die Rechnung** — 1 kB gegen 23 MB pro Revision.
  Die Strukturen liegen im Replay-Cache; erfinde keinen zweiten Speicher daneben.

## Definition of Done (Roadmap §4 „M10")

Der ausgelieferte Ordner enthält Exe, `bin/`, `data/materials/`, `data/demos/`,
`settings.ini` und sonst nichts. Eine dort geänderte Rate wirkt nach einem
Neustart, und `--version` weist sie über den Fingerabdruck aus. Ein
Materialdropdown zeigt für `resist.spin_coat` keine Metalle **und sagt warum**.
„Anpassen" lädt die gelaufenen Werte, auch bei aktivem Filter. Nach einem Absturz
fragt das Programm nach der letzten Sitzung und rechnet sie **nicht** ungefragt.
589 Tests bleiben grün und die Exe besteht 7/7.

## Arbeitsweise

Validierung ist beides (AGENTS.md §4): `python -m compileall nanofab_v3 tests`
und `python -m pytest`. Dazu die Paketstrecke: `pyinstaller nanofab_v3.spec`,
`--version`, `--selftest`, und einmal eine Datei im ausgelieferten `data/`
ändern und prüfen, dass die Änderung ankommt.

Bei unklaren Designfragen selbst entscheiden im Sinne von Roadmap und Plan und in
`memory.md` dokumentieren, statt zu blockieren — **außer** bei etwas, das eine
gemessene Zahl bewegt: das gehört nicht in M10 (dafür sind M11/M12 da) und ist
ein Grund zurückzufragen.

Committe fokussiert (`feat:`/`test:`/`docs:`/`fix:`/`chore:`), schreib die
Korrekturen als Plan **§26** („Corrections from implementation (M10)"), aktualisiere
`memory.md` nach AGENTS.md §5, hak die erledigten Punkte in der Roadmap ab und
pushe auf den oben genannten Branch.

Am Ende: kurzer Bericht, was gemessen wurde, welche Entscheidung sich unter der
Messung gedreht hat, und was M11 davon erbt.
