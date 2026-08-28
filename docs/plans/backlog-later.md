# Backlog: bewusst zurückgestellt

- Geschrieben 2026-08-26, zusammen mit `docs/plans/m6-m9-roadmap.md`
- Alles hier ist **entschieden zurückgestellt**, nicht vergessen. Jeder Eintrag
  nennt, warum er nicht in M6–M9 gehört und was ihn auslösen würde.
- Ergänzt (nicht ersetzt) Plan §16 und die vier von M5 benannten offenen Punkte
  (schmalbandiger Solver, `--onedir`, Plugin-`WaferParameter`-Kodierung,
  Artefakt-Payloads im Austauschformat).

---

## B1 — Geteilte Doppel-Domain mit eigenen Origins

**Was:** Statt die Domain nach unten aufzublähen, zwei (oder mehr) vertikal
gestapelte Teil-Domains mit je eigenem `Grid.origin`, die der Front folgen. Jede
darf kleiner sein, wenn dort wenig passiert (z. B. an ruhigen Seitenwänden). Die
Ansicht wird oben/unten geteilt, potenziell mehrfach.

**Warum zurückgestellt:** Multipliziert die Rechenkosten, statt sie zu
potenzieren — das ist der Punkt und genau richtig. Aber es setzt voraus, dass ein
Resize überhaupt sauber funktioniert und deterministisch replaybar ist. M7 baut
diese Naht (*eine* gekapselte Resize-Funktion, `Grid.origin` als Versatz); B1 ist
die zweite Ausbaustufe darauf.

**Auslöser:** Sobald der 5-µm-Deckel aus E5 in echter Arbeit regelmäßig
anschlägt.

**Vorarbeit in M7, die das billig macht — erledigt:** `kernel.domain.resize` ist
die eine Funktion, die eine Domain-Form ändert; `Grid.origin` trägt den Versatz
(nichts rechnet Koordinaten um); und die vermutete Grid-Konsistenzprüfung beim
Laden gab es nie (Plan §23.1), Revisionen verschiedener Größe speichern und laden
bereits. Was B1 aus M7 mitnehmen muss, ist §23.4: der Commit-Gate-Parent und sein
Kind müssen dieselbe Grid haben, also darf eine Teil-Domain ihre Form nur dort
ändern, wo nichts gerade zwei Revisionen vergleicht.

---

## B2 — Rückseitenprozesse, Vias, Membranen

**Was:** Durchätzen des Substrats ist erlaubt statt FAIL (E7 kehrt sich um). Das
Loch öffnet zur Rückseite, y-min wird dort zur freien Fläche; Prozesse dürfen von
unten angreifen.

**Warum zurückgestellt:** Zieht mehr mit, als es aussieht — eine zweite freie
Fläche, die Flächenpolitik in `kernel/gate.py:194-207` und
`kernel/invariants.py:172-193`, Rückseiten-Schritte als eigene Step-Familie und
eine Ansicht, die zwei Oberflächen zeigt. Eigener Meilenstein, nicht ein Feld.

**Damit es nicht bricht:** M7 führt die Substratdicke **von Anfang an als echtes
Feld** (E7), sodass B2 kein Datenmodell-Bruch wird, sondern eine Verhaltensänderung.

**Verwandt:** M5s Fund 9 (`memory.md`) nennt den Fall bereits — ein
durchgeätzter Graben ist die eine Situation, in der eine Spalte ohne Festkörper
entsteht und die Partikel-Saat aussetzt.

---

## B3 — Anisotropes `spacing`

**Was:** `Grid.spacing` ist heute ein **einziger Skalar**, also isotrop.
Vertikal gröber als lateral wäre der einzige Weg zu "5 µm breites Via durch
625 µm Wafer" bei brauchbarer lateraler Auflösung.

**Warum zurückgestellt:** Macht die SDF nicht-euklidisch. Reinit und
Eikonal-Löser müssten anisotrop rechnen, und jede Distanzaussage im Kernel
(Bandbreiten, Toleranzen, `reinit`s `|grad| = 1`) hängt daran. Größter Eingriff
aller offenen Punkte.

**Auslöser:** Wenn tiefe Strukturen mit feinen lateralen Details wirklich
gebraucht werden — B1 kauft vorher schon einiges.

**Wechselwirkung:** Sollte **nach** M9 kommen. Ein anisotroper Stencil auf einem
Randmodell zu bauen, das nachweislich kaputt ist, wäre die teuerste mögliche
Reihenfolge.

---

## B4 — SEM-Kontrastmodell

**Was:** `inspect.sem` liefert heute eine *Label-Map* (Connected Components +
`material_index` als Artefakt, `processes/inspection.py:159-199`) — kein
simuliertes Elektronenbild. Kein Kantenhelligkeits-, Kippwinkel- oder
Materialkontrastmodell.

**Warum zurückgestellt:** Die Metrologie liest bereits echte Geometrie und ist
damit ehrlich; ein Kontrastmodell ist Zugabe, keine Korrektur. Der
Profilometer hat mit der Tastspitzen-Faltung (`stylus_trace()`, `:82-116`) sogar
schon den didaktisch wertvollsten Effekt.

**Verwandt:** M5s Fund 4 — das SEM-Artefakt ist `.npy` statt Bild, und
`Revision.artifacts` wird im UI nirgends angezeigt. Ein Bild zu rendern lohnt
erst, wenn es jemand anschauen kann.

---

## B5 — Instrumenten-Rausch- und Fehlermodell

**Was:** Keine der Messungen (SEM, Profilometer, Ellipsometer) hat Rauschen,
Drift oder Kalibrierfehler. Ein Messwert ist heute exakt.

**Warum zurückgestellt:** Für ein didaktisches Werkzeug ist die exakte Messung
zunächst das Richtige — man will den Prozess sehen, nicht das Instrument. Sinnvoll
wird es, sobald *Messunsicherheit selbst* Lehrinhalt ist.

**Vorsicht:** Braucht `ctx.rng` (§5.2s RNG-Vertrag) und macht Messungen
replay-abhängig — vorher klären, ob eine Messung reproduzierbar sein muss.

---

## B6 — Positionsabhängige Rate innerhalb eines Querschnitts

**Was:** Heute ist die Quelle im Unendlichen: reine Winkelquadratur, kein
Quellenabstand, keine spaltenabhängige Rate (`kernel/flux.py:11-30,160-280`). Der
Löser ist ausdrücklich positions-blind (`processes/contract.py:18,181-190`).
Zwischen Wafer*positionen* gibt es dagegen echte Variation (`RadialProfile`,
`LinearTilt`, `runtime/run.py:52-142`).

**Warum zurückgestellt:** Die Zweiteilung ist eine bewusste Architektur, keine
Lücke — laterale Variation *innerhalb* eines Querschnitts kommt aus Geometrie und
Abschattung, und das ist auf der Skala eines Querschnitts auch physikalisch
richtig. Ein endlicher Quellenabstand (Aufdampfen: unterschiedliche Winkel über
den Wafer) gehört auf die Wafer-Ebene, wo er schon modelliert ist.

**Auslöser:** Erst wenn ein Querschnitt so breit wird, dass der Quellwinkel über
ihn merklich variiert — bei µm-Breiten gegen cm-Quellenabstände ist das nicht der
Fall.

---

## B7 — Kalibrierte statt didaktischer Raten

**Was:** `materials/library.py:14-18` sagt es selbst: die Zahlen sind
didaktisch, nur ihre *Verhältnisse* sind bedeutsam. Die Studenten-Tabelle aus M6
ändert das nicht — sie ist konsistenter, aber nicht rückführbar auf eine
Anlagenkalibrierung.

**Warum zurückgestellt:** Erfordert echte Prozessdaten pro Anlage und eine
Aussage darüber, welche Anlage gemeint ist. Ein Werkzeug, das kalibriert *aussieht*
und es nicht ist, ist schlechter als eines, das seine Grenze im Docstring nennt.

**Wenn es kommt:** Die JSON-Bibliothek aus M6 (E14) ist genau die Naht dafür —
ein Satz Dateien pro Anlage, ohne Codeänderung.

---

## B8 — Revisions-Branching

**Was:** Ein echter Baum statt einer Kette; alte Historie bleibt beim Verzweigen
erhalten.

**Warum zurückgestellt:** Widerspricht einer ausdrücklichen Architekturaussage
(`ui/window.py:6`: *"a snapshot is a record, not a branch"*), und M8 setzt
bewusst Truncate um (E12). Falls es je kommt, ist es ein bewusster
Architekturentscheid mit eigener ADR — nicht ein UI-Feature.

---

## B9 — Laterale Domain-Ausdehnung im UI festlegbar

**Was:** Die Breite kommt heute aus `cross_section_grid()` und hat kein
Bedienelement. E6 hält fest: **kein** dynamisches Wachstum nach x — aber
festlegen können sollte man sie.

**Warum zurückgestellt:** Klein und unblockierend; im aktuellen Stadium reicht
der Wert, den das Preset setzt (E2).

---

## B11 — Schleuderkurven für die benannten Resiste

**Was:** M6 legt `SpinCurve` an (E17) und füllt sie mit der einen vorliegenden
Kurve für den generischen `resist` (Roadmap §3.1). Die im Brainstorm genannten
Presets — FEP171, AZ10XT, EN038 — brauchen je eine eigene Kurve, ebenso eigene
`DevelopModel`-Werte (Tone, Dose to clear, Kontrast).

**Warum zurückgestellt:** Die Daten liegen nicht vor. Eine Kurve zu erfinden wäre
schlimmer als keine zu haben: ein Preset namens „AZ10XT", das plausible, aber
ausgedachte Dicken liefert, ist genau die Art von stillem Fehler, gegen die E15
antritt.

**Auslöser:** Sobald die Datenblätter oder gemessene Kurven vorliegen. Der
Aufwand ist dann eine JSON-Datei pro Resist — kein Code (E14).

**Zu beachten:** Die vorliegende Kurve hat keine Zeitachse (Roadmap §3.1,
offener Punkt 2). Wenn echte Resistdaten kommen, ist zu prüfen, ob die
Schleuderzeit dort eine Rolle spielt; `SpinCurve` müsste dafür erweitert werden.

---

## B12 — Prozessraten für TiO₂ ✅ *erledigt in M8*

**Ergebnis:** M8s Ätzstopp-Demo hat die Entscheidung erzwungen, und sie ist so
gefallen, wie dieser Eintrag es verlangt hat — **entschieden, nicht geraten**:
`titania` und `alumina` haben je eine `icp_fluorine`-Rate, das *Verhältnis*
(25:1) ist didaktisch gewählt, die *Richtung* ist Physik (Fluorplasma bildet
AlF₃, nicht flüchtig — deshalb stoppt Al₂O₃ eine Fluorätzung und TiO₂ nicht), und
`rate_notes` sagt in beiden Dateien genau das. Alle übrigen Chemieklassen bleiben
bei TiO₂ leer. Plan §24.6.

Der ursprüngliche Eintrag, als Begründung:

---


**Was:** `titania` ist seit M6 in der Bibliothek (E16), trägt aber **keine**
tabellengestützte Rate: die Studenten-Tabelle hat keine TiO₂-Zeile. Es hat nur
didaktische Werte auf den vier alten Prozessklassen (`deposit`, `dry_etch`,
`ion_beam`, `wet_etch`) und gar nichts auf den Chemie-Klassen.

**Warum zurückgestellt:** Dieselbe Regel wie B11, eine Ebene höher. Eine
erfundene ICP- oder RIE-Rate für TiO₂ wäre plausibel und nicht bemerkbar; eine
fehlende ist bemerkbar. Der `notes`-Text des Eintrags sagt deshalb ausdrücklich,
dass eine 0 dort „niemand hat eine Rate genannt" heißt und nicht „inert" — genau
die Unterscheidung, gegen deren Verwischen E15 antritt.

**Auslöser:** M8s TiO₂-Gitter-Demo (Al₂O₃-Ätzstopp auf Fused Silica) braucht
mindestens eine Ätzchemie für TiO₂. Dann ist zu entscheiden — nicht zu raten —,
ob die Zahl aus einer Messung kommt oder als *didaktisch* markiert wird, wie es
`rate_notes` für die anderen erfundenen Werte tut.

**Aufwand:** eine JSON-Datei, kein Code (E14).

---

## B10 — Lokalisierung tatsächlich ausliefern

**Was:** M8 legt die Übersetzungs-Indirektion an (E10), aber es gibt nur eine
Sprache.

**Warum zurückgestellt:** Ein Katalog ohne zweite Sprache ist unbewiesene
Infrastruktur. Die Indirektion jetzt zu bauen kostet fast nichts und verhindert,
dass 24 Beschreibungen später angefasst werden müssen — mehr ist verfrüht.
