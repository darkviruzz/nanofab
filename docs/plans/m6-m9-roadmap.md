# Roadmap M6–M9: Substrat, Domain, UI-Reife, Rand-Bugfix

- Geschrieben 2026-08-26, am Ende von M5
- Entstanden aus einer Grilling-Session über eine ungeordnete TODO-/Brainstorm-Liste;
  jede Entscheidung unten ist dort explizit getroffen worden, nicht abgeleitet
- Plan §14s Meilensteinliste endet mit M5. Dieses Dokument setzt sie fort.
- Späteres, bewusst *nicht* Eingeplantes steht in `docs/plans/backlog-later.md`

## 0. Ausgangslage (gemessen, nicht vermutet)

M0–M5 fertig, 394 Tests grün, S1–S5 laufen, `nanofab_v3` v0.3.0.dev0.
Die Session hat den Ist-Zustand gegen den echten Code geprüft — mehrere
verbreitete Annahmen waren falsch:

| Thema | Ist-Zustand | Fundstelle |
|---|---|---|
| Materialbibliothek | existiert, 8 Materialien, ausdrücklich *didaktisch, nicht kalibriert* | `materials/library.py:14-18,130-259` |
| Ätz-/Depositionsraten | echt, gelesen | `processes/rates.py:26-148` |
| SEM/Profilometer/Ellipsometer | **echt implementiert**, lesen echte Geometrie, nichts gemockt, kein Rauschmodell | `processes/inspection.py:68-296` |
| Inter-Wafer-Variation | **existiert** zwischen Wafer-*Positionen* (`RadialProfile`, `LinearTilt`) | `runtime/run.py:52-142` |
| … innerhalb eines Querschnitts | uniform; Quelle im Unendlichen, nur Winkel, kein Quellenabstand — bewusst positions-blind | `kernel/flux.py:11-30,160-280`, `processes/contract.py:18,181-190` |
| Headroom-Grenze | existiert, FAIL bei y-max-Kontakt, **kein** Auto-Resize | `kernel/gate.py:169-181` |
| Substrat-Step | nur `material` + `surface`; Domain-Maße kommen getrennt aus `cross_section_grid()` | `processes/substrate.py:26-98` |
| Litho `exposed`/`dose` | Felder existieren, werden **nirgends gerendert** | `ui/scene.py:124` (`OVERLAY_KINDS`) |
| Prozess-Doku | nur Parameter-Tooltips, kein Step-Langtext | `processes/contract.py:82,92`, `ui/panels.py:174` |
| Revisionen | flache Liste, klickbar; `rewind()` existiert, ist **nicht** ans UI gebunden | `ui/panels.py:272-320`, `runtime/revision.py:288-300` |
| Demos | genau **ein** hartcodiertes (S1 Lift-off), kein Picker | `ui/session.py:272-291` |

Zwei Nebenfunde mit Folgen:

- **`MaterialType` ist vollständig serialisierbar.** Alle Untermodelle
  (`SputterResponse`, `DevelopModel`, `DissolveModel`) sind frozen Dataclasses mit
  ausschließlich skalaren Feldern — keine Callables, kein Zustand
  (`materials/material.py:71-292`). Die Bibliothek kann verlustfrei nach JSON.
- **`DevelopModel` trägt bereits `tone`, `clearing_dose`, `clear_rate`,
  `dark_rate`, `contrast`** (`material.py:102-135`) — also genau das, was ein
  Resist-Preset mitbringen müsste. `DEVELOP_IDEAL` hat trotzdem einen
  *redundanten* eigenen `tone`-Parameter (`lithography.py:538-543`).

## 1. Das Speicherbudget, das alles andere begrenzt

Gemessen an der Referenz 540×1200 @ 1 nm: eine Revision mit 2 Materialien + 1 Feld
= 5.83 MB RAM (`runtime/revision.py:14`). Ein `phi`-Array kostet
`Zeilen × Spalten × 4 Byte`. Hochgerechnet bei 1.2 µm Breite und ~5 Materialien:

| Domain-Tiefe | pro Material | pro Revision |
|---|---|---|
| 1 µm | 4.8 MB | ~24 MB |
| 5 µm | 24 MB | ~120 MB |
| 10 µm | 48 MB | ~240 MB |
| 100 µm | 480 MB | ~2.4 GB |
| 625 µm | 3 GB | ~15 GB |

**Konsequenz:** Die Domain nach unten wachsen zu lassen ist *geometrisch* trivial
(Ober- und Unterkante sind homogen, die SDF dort linear und exakt fortsetzbar),
aber **nicht speichermäßig** — wachsen heißt Zellen allokieren. Physisches
Wachstum trägt bis ca. 5 µm. Ein 625-µm-Via bei 1 nm ist nie darstellbar; das ist
keine Implementierungsfrage, sondern Arithmetik.

Daraus folgt die Trennung, die M7 umsetzt: **Substratdicke ist Metadatum, nicht
Domain-Größe.** Die Domain zeigt das Fenster, in dem gerade Struktur ist; die
625 µm sind gewusst, nicht dargestellt.

## 2. Getroffene Entscheidungen

Nummeriert, damit die Handoffs darauf verweisen können.

**E1 — Ein Substrat-Step, nicht zwei.** `SELECT_SUBSTRATE` bekommt ein
Form-Faktor-Dropdown (`Chip`, `Maske`, `Wafer` (Default), `semi-infinit`). Die
Wahl `semi-infinit` ist die Kodierung für "Dicke unbekannt/egal" — kein zweiter
Step, kein gespaltenes Rezept-Format.

**E2 — Preset treibt Substrat *und* Domain.** Die Semistandard-Auswahl
konfiguriert die Grid-Erzeugung mit. Ein Substrat "100 mm Wafer" bei zufällig
50 µm Domainbreite wäre sonst eine ständige Fehlerquelle.

**E3 — Dropdown zweigeteilt und sortiert.** Zwei Abschnitte (Wafer /
Maskblank), innerhalb sortiert nach Material und aufsteigend nach Größe bzw.
Dicke. Default: rund, 100 mm, 1 mm, Fused Silica.

**E4 — "Substrat zuerst" ist Registry-/UI-Validierung, kein Kernel-Verhalten.**
Vor dem ersten Step gibt es gar keine Domain; ein anderer Step als #0 wird mit
Hinweistext blockiert, nicht mit einer Laufzeit-Physikwarnung.

**E5 — Domain wächst dynamisch nach y-min/y-max, gedeckelt bei 5 µm.**
Vollautonom, ohne Rückfrage, in beide Richtungen (auch schrumpfen, wenn groß und
leer). Beim Deckel: UI-Warnung, Deckel auf Nachfrage beliebig erhöhbar, mit
transparent geschätztem RAM- und Plattenbedarf.

**E6 — Kein dynamisches Wachstum nach x.** Die laterale Ausdehnung ist eine
Festlegung, kein Automatismus. (Ein UI dafür fehlt heute und wird jetzt nicht
gebraucht.)

**E7 — Durchätzen des Substrats ist zunächst ein FAIL.** Die Dicke wird aber von
Anfang an als echtes Feld geführt, damit Rückseiten-Prozesse später ohne
Datenmodellbruch nachrüstbar sind (→ Backlog B2).

**E8 — Darstellung: automatisch maßstabsgetreu bis ~4:1, darüber gestaucht** —
mit permanent sichtbarem Verzerrungsfaktor und einem Knopf zum
Umschalten/Deaktivieren. Eine stillschweigend gestauchte Ätzflanke ist für ein
didaktisches Werkzeug schlimmer als eine unbequeme Ansicht, weil Flankenwinkel
genau das sind, was beurteilt werden soll.

**E9 — Litho: Vorschau und Ergebnis sind zwei getrennte Darstellungen.**
Die *Licht-Vorschau* (Strahlen von oben, aus den Parametern gerechnet, ohne
Simulation) ist ein Toggle. Das *`exposed`-Overlay* (simuliertes Ergebnis inkl.
Beer-Lambert-Tiefenabfall und Blur) färbt **immer**. Die Differenz zwischen
beiden ist der didaktisch interessante Teil.

**E10 — Prozessbeschreibungen im Code an der Registrierung**, als neues
Langtext-Feld an `FunctionStep` neben `display_name`, aber von Anfang an durch
eine dünne Übersetzungs-Indirektion, damit später ein Sprachkatalog darüber
gelegt werden kann, ohne die Registry anzufassen. Keine zweite Quelle.

**E11 — Step-Filter: Textfeld + Fidelity-Tags.** Volltext über Name und
Beschreibung; `IDEAL`/`DIDACTIC` existieren bereits als Felder und werden als
Tags filterbar.

**E12 — Revisionen: Truncate, kein Branching.** Der Code-Kommentar
(`ui/window.py:6`, *"a snapshot is a record, not a branch"*) bleibt gültig.
"Entfernen" = `rewind()` ans UI gebunden (Entf-Taste + Kontextmenü).
"Anpassen" = truncate + neuer Step mit geänderten Parametern.
"Wiederholen" = denselben Step nochmal anhängen.

**E13 — Resist-Eigenschaften trägt das Material, nicht der Step.** Kein
Cross-Step-Preset-Durchreichen: `DevelopModel` ist bereits der richtige Ort. Der
Develop-Step liest `tone`/`clearing_dose` aus dem Resist-Material. Der redundante
`tone`-Parameter bleibt als **Override** erhalten, wird im UI aber **read-only**
angezeigt (sichtbar, woher der Wert kommt, ohne zum Pflichtfeld zu werden).

**E14 — Materialbibliothek nach JSON, vollständig.** Ein File pro Material in
`data/materials/`. Die 8 eingebauten Materialien wandern **mit** — keine
Zweiteilung "ein paar im Code, ein paar auf Platte". Der Code lädt nur noch.

**E15 — Unbekanntes Material warnt und fragt nach.** Freitext bleibt erlaubt
(didaktischer Wert: schnell mit etwas Unkalibriertem experimentieren), aber der
stille Fallback auf Rate 0 endet. Ein Dialog erfragt die fehlenden Werte und
schreibt sie nach `data/materials/`.

**E16 — Fehlende Standardmaterialien kommen in die Bibliothek**, nicht in die
Demos. Chrom und Fused Silica sind zu gängig, um demo-spezifisch zu sein.

**E18 — Die Sputterätz-Zeile der Tabelle bekommt eine *eigene* Prozessklasse**
(entschieden in M6, nachgetragen). §3 unten bildet Zeile 1 auf das bestehende
`ion_beam` ab. Das geht nicht: `ion_beam` trägt bereits die didaktischen Zahlen,
auf die S1–S5 abgestimmt sind (Silizium 1.0 gegen die 0.2333 der Tabelle), und
E14s Abnahmekriterium ist gerade die *Bitgleichheit* der migrierten Modelle —
derselbe Meilenstein hätte behauptet, nichts geändert zu haben, und etwas
geändert. Also ist Zeile 1 eine **siebte** neue Klasse `sputter_etch` geworden,
`ion_beam` blieb unangetastet: §3s eigene Regel („additiv erweitern, nichts
umbenennen") einen Schritt weiter als die Tabelle es vorsah. Dieselbe Technik,
derselbe Wrapper, zwei Spalten der Bibliothek — Plan §5.4 in der Ratentabelle
statt im Step. Ausführlich in Plan §22.1.

**E17 — Die Schleuderkurve trägt das Material, nicht der Step.** Ein neues
Untermodell `SpinCurve` an `MaterialType`, in derselben Reihe wie `develop`,
`dissolve` und `sputter_response`. Die Schichtdicke ist eine Eigenschaft des
Resists bei gegebener Drehzahl, nicht des Beschichtungsschritts — dieselbe
Begründung wie E13. Der `thickness`-Parameter am Spin-Coat-Step bleibt als
**Override** erhalten und wird im UI read-only angezeigt, solange er aus der
Kurve kommt (Muster wie E13s `tone`).

## 3. Die Prozesstabelle und was sie am Schema erzwingt

Die vorgegebenen Studenten-Werte (10 Prozesse) passen **nicht** in die heutigen
`PROCESS_CLASSES` (`materials/material.py:64`: `wet_etch`, `dry_etch`,
`ion_beam`, `deposit`, `develop`, `dissolve`), weil die Rate je *Chemie*
unterschiedlich ist und `rates` nach Prozessklasse geschlüsselt wird.

**Regel: additiv erweitern, nichts umbenennen.** S1–S5 und 394 Tests hängen an
den bestehenden Klassennamen.

Zweite Spannung: Die Tabelle nennt teils "horizontal = vertikal", teils nur
"vertical". Das sind **keine zwei Raten** — im Modell ist die Rate ein Skalar
("die Rate, mit der eine offene, normal zugewandte Fläche wandert",
`material.py:213-218`), und die Richtungsabhängigkeit kommt aus der
Winkelverteilung des Flussmodells (`kernel/flux.py:160-280`). Also:

- "horizontal = vertikal" → **isotrope** Winkelverteilung im Step
- "vertical" → **gerichtete** Verteilung (Delta bzw. enge Lobe) im Step
- die Zahl selbst geht unverändert in `rates[klasse]` am Material

### Umgerechnete Raten (Tabelle ist nm/min, Code ist nm/s)

| # | Prozess | Prozessklasse | Material → nm/s |
|---|---|---|---|
| 1 | Sputter etching | ~~`ion_beam` *(existiert)*~~ → `sputter_etch` *(neu, E18)* | chrome 0.1667 · oxide 0.2000 · silicon 0.2333 · resist 0.2500 |
| 2 | ICP etching (Fluor) | `icp_fluorine` *(neu)*, gerichtet | chrome 0.0333 · fused_silica 0.8333 · silicon 0.6667 · resist 1.0000 |
| 3 | RIE etching (Chlor) | `rie_chlorine` *(neu)*, isotrop | chrome 0.8333 · fused_silica 0.0 · resist 0.1667 |
| 4 | RIE etching (Sauerstoff) | `rie_oxygen` *(neu)*, isotrop | chrome 0.0 · fused_silica 0.0 · resist 1.6667 |
| 5 | Cr-Nassätzen | `wet_etch_cr` *(neu)*, isotrop | chrome 16.6667 · alles andere 0.0 |
| 6 | Oxid-Nassätzen | `wet_etch_oxide` *(neu)*, isotrop | oxide 16.6667 · resist 1.6667 · alles andere 0.0 |
| 7–9 | Sputter-Deposition | `sputter_deposit` *(neu)* | oxide 0.0667 · silicon 0.1667 · chrome 0.0833 |
| 10 | Wafer cleaning | — | existiert seit M5 (`reachable_occurrences`) |
| 11 | Spin coating photo resist | keine Rate — `SpinCurve` am Material (E17) | siehe §3.1 |

### 3.1 Die Schleuderkurve (Prozess #11)

Vorgegebene Stützstellen für den Photoresist:

| Drehzahl | 1000 rpm | 2000 rpm | 3000 rpm | 4000 rpm | 5000 rpm |
|---|---|---|---|---|---|
| Dicke | 150 nm | 99.8 nm | 82 nm | 74 nm | 72 nm |

**Das ist keine Rate und passt in keine Prozessklasse.** `rates` ist nach
Prozessklasse geschlüsselt und liefert nm/s; hier steht eine Dicke über einer
Drehzahl. Daher E17: ein eigenes Untermodell `SpinCurve` an `MaterialType`,
skalar und damit JSON-fähig wie alles andere (E14).

**Stützstellen interpolieren, keine Formel fitten** — nachgerechnet:

| | 1000 | 2000 | 3000 | 4000 | 5000 |
|---|---|---|---|---|---|
| gemessen | 150.0 | 99.8 | 82.0 | 74.0 | 72.0 |
| `d = k·rpm^-0.5` | 150.0 | 106.1 | 86.6 | 75.0 | 67.1 |
| Abweichung | 0.0 % | +6.3 % | +5.6 % | +1.4 % | **−6.8 %** |

Das klassische Wurzelgesetz trägt die Punkte nicht: die Abweichung wechselt das
Vorzeichen, und der effektive Exponent driftet von 0.588 (1000→2000) auf 0.456
(1000→5000) — die Kurve flacht zu hohen Drehzahlen hin ab. Ein Potenzgesetz
würde bei 5000 rpm 67 nm behaupten, wo 72 nm gemessen sind. Also die fünf Paare
ablegen und dazwischen interpolieren; außerhalb 1000–5000 rpm nicht
extrapolieren, sondern klemmen und das sagen.

**Zwei offene Punkte, die nicht erfunden werden dürfen:**

1. **Welcher Resist?** Die Tabelle sagt nur „photo resist". Die Kurve gilt daher
   für den generischen `resist` der Bibliothek. Die im ursprünglichen Brainstorm
   genannten Presets (FEP171, AZ10XT, EN038) brauchen **eigene** Kurven, die noch
   nicht vorliegen → Backlog B11.
2. **Die Schleuderzeit fehlt.** Die Tabelle parametrisiert nur die Drehzahl. Das
   ist physikalisch plausibel — oberhalb einer Mindestzeit läuft die Dicke in die
   Sättigung —, aber es ist eine Annahme. `SpinCurve` bekommt deshalb keine
   Zeitachse; der Step darf eine Schleuderzeit als dokumentierendes Feld führen,
   sie geht aber nicht in die Dicke ein, und **das gehört in den Hilfetext**
   (E10), nicht in eine stille Konvention.

**Annahme, die zu bestätigen ist:** Die Tabelle nennt bei #1 "silicon oxide", bei
#2–4 "fused silica". Beide werden als *zwei* Materialien geführt (abgeschiedenes/
thermisches SiO₂ vs. Quarzglas-Substrat), was der Tabelle entspricht. Für
Kombinationen, die die Tabelle nicht nennt, wird die jeweils andere SiO₂-Rate
übernommen und **im JSON als Annahme markiert**.

Depositionsraten sitzen am *abgeschiedenen* Material (das ist die Eigenschaft der
Quelle), Ätzraten am *angegriffenen* — beides passt ohne Umbau in
`rates: Mapping[process_class, float]`.

### Neue Materialien

`chrome`, `fused_silica`, `titania` (TiO₂ für die Gitter-Demo).
`alumina` (Al₂O₃, Ätzstopp) existiert bereits, ebenso `silicon`, `oxide`,
`resist`, `resist_hardbaked`, `underlayer`, `metal`, `particle`.

## 4. Meilensteine

### M6 — Datenfundament ✅ *erledigt 2026-08-26*

Berührt keinen Kernel, entblockt alles andere, sofort nützlich.

**Ergebnis:** Bibliothek in `nanofab_v3/data/materials/*.json` (11 Materialien,
kein Material mehr im Code), 13 Prozessklassen, 31 Steps, 448 Tests grün, exe
7/7. Eine Abweichung vom Plan unten, entschieden und dokumentiert: E18 oben und
Plan §22.1. Alles Weitere in Plan §22 und in memory.md 2026-08-26.

1. Materialbibliothek nach `data/materials/*.json` migrieren (E14), inkl. Loader,
   Schema-Validierung und Round-Trip-Test gegen `didactic_library()` — die
   migrierte Bibliothek muss **bitgleiche** Modelle liefern.
2. `PROCESS_CLASSES` additiv erweitern (§3), bestehende Namen unangetastet.
3. Neue Materialien anlegen (E16, §3), Studenten-Raten eintragen, Annahmen
   im JSON markieren.
4. Neue Prozess-Steps für die Chemien aus der Tabelle, jeweils mit der
   Winkelverteilung aus §3 (isotrop vs. gerichtet).
5. `SpinCurve` als viertes Untermodell an `MaterialType` (E17), Stützstellen aus
   §3.1, Interpolation mit Klemmen an den Rändern. Der Spin-Coat-Step
   (`processes/lithography.py:463-481`) bekommt `spin_speed` als Eingabe und
   leitet `thickness` daraus ab; `thickness` bleibt Override.
6. Unbekanntes-Material-Dialog (E15): Warnung statt stillem Rate-0-Fallback,
   Nachfrage der fehlenden Werte, Schreiben nach `data/materials/`.

**DoD:** Bibliothek kommt vollständig von Platte, kein Material mehr im Code;
394 Tests weiter grün; die 11 Tabellenprozesse sind als Steps aufrufbar; ein
Spin-Coat bei 3000 rpm liefert 82 nm ohne dass jemand eine Dicke eintippt; ein
unbekanntes Material erzeugt eine sichtbare Warnung statt einer stillen Null.

*Erfüllt.* Dazu, weil `data/` neu war und eine Bibliothek, die aus dem
Source-Baum lädt, erst in der Exe auffällt: das Verzeichnis liegt **im Paket**
(`nanofab_v3/data/materials/`), ein Wheel trägt es, eine Nicht-Editable-Install
lädt daraus, und die gebaute Exe meldet `materials: 11 from 2 root(s)` und läuft
7/7 durch. Plan §22.3.

### M7 — Substrat & Domain ✅ *erledigt 2026-08-26*

Der Block mit dem größten Nutzwert.

**Ergebnis:** `kernel/domain.py` (eine Resize-Funktion, `DomainPolicy`,
Speicherschätzung), `Structure.metadata` als Träger der echten Substratdicke,
`substrate.select` mit Form-Faktor, 17 Semistandard-Presets und Durchätz-FAIL,
`capability.DOMAIN` für E4, `ui/presets.py` als generisches Override-Muster.
485 Tests grün, Exe 7/7. Details in Plan §23 und memory.md 2026-08-26.

**Falle 2 gab es nicht.** `manifest.py:18`s „the reference grid, checked on load"
ist der Satz zur *Benchmark*-Grid einer Messung, keine Konsistenzprüfung;
`Grid.check_same_grid` wird nirgends im Paket aufgerufen, und jede Revision liest
ihre Grid aus ihrem eigenen Manifest. Eine Kette mit verschieden großen Grids
speichert und lädt auf Anhieb. Was das Resize *wirklich* berührt hat, steht in
Plan §23.4 — der Commit-Gate-Parent muss dieselbe Grid haben, weshalb der Fit
**vor** dem Step läuft.

1. Substrat-Step: Form-Faktor-Dropdown (E1), Semistandard-Presets zweigeteilt und
   sortiert (E3), Material, Dimensionen (Durchmesser bzw. x/y), Dicke,
   Surface Finish.
2. Preset-Override-Muster **generisch** bauen (wiederverwendbar für künftige
   Presets): überschreibt manuell geänderte Folgefelder nur nach Rückfrage,
   sonst still.
3. Preset treibt die Grid-Erzeugung mit (E2).
4. Registry-Validierung "Substrat muss Step #0 sein" (E4).
5. Dynamisches y-Resize (E5): wachsen und schrumpfen, gekapselt hinter *einer*
   Funktion; 5-µm-Deckel; UI-Warnung mit RAM-/Plattenschätzung; Deckel erhöhbar.
6. Substratdicke als Metadatum führen; Durchätzen ergibt FAIL (E7).

**Fallen, die vorher benannt sind:**
- `Grid` ist "the sole spatial authority" (`model/structure.py`), `Structure` ist
  frozen — ein Resize erzeugt eine neue Grid *und* neu gepaddete Arrays.
- Die Grid wird **pro Revision** gespeichert (`io/manifest.py:143`) *und* einmal
  am Recipe (`:404`), und `manifest.py:18` spricht von "the reference grid,
  checked on load". Wenn Revisionen unterschiedlich große Grids haben dürfen,
  muss dieser Konsistenzpfad angefasst werden — das ist die erste Stelle, an der
  M7 auf Widerstand trifft.
- Replay ist der Cache-Fallback *und* der Mechanismus für neue Waferpositionen
  (`runtime/revision.py`). Ein Resize muss deterministisch replaybar bleiben,
  sonst zerfällt der Cache.
- `Grid.origin` existiert und ist heute immer `(0,0)`. Beim Wachsen nach unten
  ist sie der natürliche Ort für den Versatz — sauberer als Koordinaten überall
  umzurechnen.

**DoD:** Ein 100-mm-Fused-Silica-Preset erzeugt Substrat und Domain konsistent;
ein Ätzschritt, der die Domain unten verlässt, wächst automatisch statt zu
scheitern; ein sehr tiefer Schritt schlägt am Deckel mit lesbarer Schätzung an;
Durchätzen sagt "durchgeätzt" statt etwas Falsches zu rechnen.

*Erfüllt*, jeweils als Test in `tests/test_substrate_domain.py`. Ein Punkt ist
schärfer geworden als geplant: eine kleine Marge allein liefert „wächst statt zu
scheitern" **nicht** — ein einzelner Step kann die Front weiter bewegen als jede
Marge, und eine an der Domainwand abgeschnittene Front kann man nicht fragen, wie
weit sie wollte. Deshalb zusätzlich ein Retry: Step laufen lassen, Platzmangel
sehen, Eingabe vergrößern, nochmal (höchstens zweimal, Wachstum verdoppelnd).
Plan §23.3.

### M8 — UI-Reife ✅ *erledigt 2026-08-26*

Alles voneinander unabhängig, gut parallelisierbar.

**Ergebnis:** 31 Step-Langtexte an der Registrierung mit
Übersetzungs-Indirektion (`nanofab_v3/text.py`), durchsuchbare Step-Liste,
`exposed`/`dose` als immer färbende Overlays plus Licht-Vorschau,
Revisions-Truncate mit Entf und Kontextmenü, AR-Darstellung mit permanent
sichtbarem Verzerrungsfaktor, vier Demos mit Picker. 547 Tests grün, Exe 7/7.
Details in Plan §24 und memory.md 2026-08-26.

**Zwei Punkte waren enger verzahnt als die Liste vermuten lässt.** E10 und E11
sind *ein* Feature: der Filter sucht über Namen **und Beschreibung**, also ist
eine nach „undercut" durchsuchbare Liste erst möglich, wenn die Steps sagen, was
sie tun (Plan §24.2). Und die neun Qt-Tests liefen seit M5 nicht — sie
übersprangen, weil PySide6 im Container fehlte. Nach der Installation fiel sofort
eine M7-Regression auf, die einen Tag lang niemandem aufgefallen war (§24.1).

1. Prozessbeschreibungen (E10) — Langtext an jedem der 24 Steps: was er tut,
   welche Felder was bedeuten, welche Inputs nötig sind.
2. Step-Filter (E11): Textfeld + Fidelity-Tags.
3. Litho-Licht-Vorschau als Toggle + `exposed`-Overlay das immer färbt (E9).
4. Revisions-Truncate ans UI (E12): Entf + Kontextmenü
   (wiederholen/anpassen/entfernen).
5. AR-Darstellung (E8) mit Verzerrungsanzeige und Umschaltknopf.
6. Demo-Picker statt des einen hartcodierten Demos, mit Erklärtext je Demo:
   Fused-Silica-Gitter mit Chrom-Hartmaske (steile Flanken) · TiO₂-Gitter mit
   dünner Al₂O₃-Ätzstoppschicht auf Fused Silica · Black Silicon durch
   Mikromaskierung (baut auf S5 auf, das den Mechanismus schon hat).

**DoD:** Jeder Step erklärt sich selbst; die Step-Liste ist durchsuchbar; man
sieht vor dem Belichten, wo Licht hinfällt, und danach, was belichtet wurde;
Revisionen sind löschbar; die Demos sind auswählbar und laufen.

*Erfüllt.* Die Demos laufen nicht nur, sie zeigen das, was ihr eigener Text
ankündigt — jeweils als Test: das Chrom-Gitter 200 nm tief mit steilen Flanken
und ohne Maske am Ende, der Ätzstopp mit unversehrtem Substrat nach 350 s, das
Black Silicon als *ein* zusammenhängender Wald mit dem Gegenversuch (vorher
reinigen → flach) daneben.

### M9 — Kernel-Bugfix: Domain-Rand

Reine Reparatur, bewusst zuletzt — sie blockiert M6–M8 nicht, weil M7 nur nach y
wächst und den x-Rand nicht anfasst (E6).

**Root Cause** (diagnostiziert an einem echten Projekt, `structure.v2`,
241×301 @ 1 nm, `develop_at_rate` mit 200 Sub-Steps und 19 Reinits):

1. Das Union-Feld ist **im Volumen keine Distanzfunktion**. `union_front()`
   (`kernel/motion.py:281-306`) nimmt `min_m phi_m`; an einer vergrabenen
   Materialnaht liest das ~0 und reproduziert darunter die eigene Tiefe des
   unteren Materials. Der eine Reinit-Pass ist schmalbandig, also überlebt dort
   ein Knick (beobachtet: flach `-4.0` über sechs Zeilen).
2. Jeder Mid-Motion-Reinit **marschiert diesen Knick tiefer**.
   `motion.py:531-537` löst bei Bandgradientenfehler > 0.25 aus; die Relaxation
   `v - dtau*sign*(|grad|-1)` (`kernel/reinit.py:161-168`) schiebt die Korrektur
   pro Pass einige Zellen weiter ins Volumen — 19 Pässe ≈ 60 Zeilen, was den
   beobachteten 45°-Keil ergibt.
3. **An der Domainwand kippt es ins Positive.**
   `stencil.one_sided_differences` (`kernel/stencil.py:217-247`) benutzt an
   Flächen *lineare Fortsetzung*, wodurch beide Upwind-Differenzen an der
   Randspalte gleich sind und nichts dem Wachsen von `|grad|` entgegenwirkt.
   Vorzeichenwechsel treten **nur** dort auf, wo Festkörper von der Wand
   abgeschnitten wird und deshalb in x keine Front hat.
4. `motion._clipped()` (`kernel/motion.py:216-228`) schreibt `max(phi_m,
   solid_new)` in **alle** Materialien — der kaputte Union stanzt damit positive
   Werte in unbeteiligte Materialien, was die Löcher tief im Volumen und die
   `"material interiors overlap"`-FAILs erzeugt (`kernel/gate.py:190-207`).

**Wichtig:** Periodische oder gespiegelte Randbedingungen sind **nicht** die
Lösung — der Fehler bestünde unter jeder Randbedingung fort. Zu tun ist:
(a) Ghost-Cell-/Neumann-Behandlung, damit `phi` an Wandflächen frei bleibt und
die Wand nicht als Grenzfläche gelesen wird, und (b) das Union-Feld im Volumen
gültig machen, statt einen schmalbandigen Reinit einen domainweiten Defekt
reparieren zu lassen.

Zur Einordnung: `predicates.open_faces` (`kernel/predicates.py:62-91`) hält die
lateralen Flächen bewusst *nicht* offen — die Absicht ist also richtig
hinterlegt, sie wird nur vom Stencil unterlaufen.

**DoD:** Der Reproduktionsfall (randgeschnittenes Partikel + Entwicklung) läuft
ohne Overlap-FAIL und ohne Materialaufspaltung durch; ein Regressionstest
fixiert genau ihn; die 394 Tests bleiben grün.

## 5. Was diese Roadmap bewusst *nicht* umfasst

Siehe `docs/plans/backlog-later.md`.
