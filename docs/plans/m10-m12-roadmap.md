# Roadmap M10–M12: Auslieferung, gerichtete Prozesse, Anlage

- Geschrieben 2026-08-27, am Ende der M6–M9-Runde
- Entstanden aus einer Grilling-Session über eine Anmerkungsliste aus der
  Benutzung. **Jede Entscheidung unten ist dort explizit getroffen worden**, mit
  einer Alternative, die verworfen wurde, und einem Grund. Wo eine Messung den
  Ausschlag gab, steht sie dabei.
- Setzt `docs/plans/m6-m9-roadmap.md` fort; Entscheidungen zählen dort bei E18
  auf und hier ab **E19** weiter.
- Späteres steht in `docs/plans/backlog-later.md`.

## 0. Ausgangslage (gemessen, nicht vermutet)

M0–M9 fertig, **589 Tests grün, 0 übersprungen**, `nanofab_v3` v0.3.0.dev0,
31 Steps, 13 Prozessklassen, 11 Materialien als JSON, Exe 7/7 in 4.5 s.
`docs/plans/m6-m9-handoff.md` listet zehn offene Punkte (R1–R10); diese Roadmap
erledigt R1, R4, R6, R7, R8 und R9 und vertagt R2, R3, R5 und R10 begründet.

Sieben Dinge wurden für diese Roadmap **nachgemessen**, weil die Anmerkungsliste
sie als Vermutung enthielt. Sie stehen hier, weil vier davon eine Entscheidung
gedreht haben:

1. **Der `adjust`-Bug ist nicht der Filter.** `_on_revision_chosen` schreibt
   `form.set_values(revision.history.params)` **namensbasiert** in das gerade
   sichtbare Formular. Nach `rewind(1)` landet die Auswahl auf Revision #0
   (`substrate.select`, `material=silicon`, `thickness=0.0`), und genau diese
   zwei Namen kollidieren mit denen des Spin-Coats. Gemessen: gespeichert
   `{'material': 'resist', 'thickness': 90.0}`, angezeigt
   `{'material': 'silicon', 'thickness': 0.0}`.
2. **IBE und Sputterätzen sind eine Selektivitätsreihe bei zwei
   Geschwindigkeiten.** Auf Silizium normiert weichen die Spalten um 0–10.7 % ab,
   der Absolutfaktor ist 0.208–0.250. `sputter_etch` hat 5 Einträge, `ion_beam`
   alle 11.
3. **`etch.sputter` wird von keinem Szenario und keiner Demo benutzt**,
   `etch.ibe` von genau einem: S2c (`duration=30, scale=1.25`).
4. **Belichtung ist nicht kumulativ** — beide `expose_*` machen `with_field`,
   überschreiben also.
5. **Die Bilanz bricht unterhalb einer Zelle**, nicht wegen Mobility. Cr auf
   Fused Silica bei 1 nm/Zelle: 0.2 nm → gemessen 0.51 nm (153 % daneben, **null**
   Zellen Inneres); 0.5 nm → 0.59 nm (18 %); ab 1.0 nm exakt. Mit und ohne
   Mobility identisch.
6. **SEM und Profilometer erzeugen heute nichts.** Sie schreiben ein Artefakt nur
   bei gesetztem `ctx.artifacts`; `Session.sink` ist `None` und das Fenster setzt
   keinen. Die Leitung liegt, der Stecker fehlt.
7. **`film_thickness` hat drei Nutzer**, darunter das Profilometer — das
   Ellipsometer zu entfernen berührt es nicht.

## 1. Was das Datenmodell davon abbekommt

Die drei untersten Ebenen — **Geometrie** (`Grid`, `Structure`), **Felder**
(`FieldKey`, `FieldSpec`, Skopierungsregel) und **Laufzeit** (`Recipe`,
`Revision`, Cache-Schlüssel nach ADR-0004) — fasst keiner der drei Meilensteine
an. Alles unten ist Bibliotheksdatum, Prozessschema oder UI.

| Ebene | Änderung | wo |
| --- | --- | --- |
| `MaterialType` | `tags: tuple[str, ...]` (Stoffklasse) | M10 |
| Materialdatei | `inherits: MaterialId \| None` | M11 |
| `MaterialType` | `hard_bake: HardBakeModel \| None` | M12 |
| `MaterialType.rates` | eine Ionenätz-Spalte statt zwei | M11 |
| `ParamSpec` | Marker „Default aus der Domain" (`0`) | M10 |
| `FunctionStep` | Materialparameter deklariert sein Filterkriterium | M10 |
| `StepContext` | aufgelöster skalarer `rate_scale` | M12 |
| `Structure.metadata` | `substrate.roughness_nm` | M10 |
| Prozessschema | `uniformity_percent`; `angle` fällt bei ICP weg | M11/M12 |

## 2. Entscheidungen E19–E41

**E19 — Ein Verzeichnis, und die Bibliothek genau einmal.** PyInstaller
`--onedir`, Layout `nanofab.exe · bin/ · data/materials/ · data/demos/ ·
settings.ini`. Die eingebackene Kopie **entfällt**: „Materialien in der Exe *und*
daneben" heißt, dass bei einer Abweichung niemand weiß, welche gelten. Der Preis
ist der fehlende Fallback — fehlt `data/materials/`, bricht der Start **laut** ab
und nennt den erwarteten Pfad; fehlt `data/demos/`, startet die Anwendung mit
leerem Demos-Menü. Verworfen: Notkopie in `bin/` (wieder zwei Wahrheiten) und
das bisherige Onefile-mit-Ordner-daneben. Das Wheel behält seine `package-data`;
nur der Frozen Build verzichtet. `contents_directory="bin"` statt `_internal`.

**E20 — Ein Icon, aus einer SVG im Sourcetree.** Es gibt keinerlei Artwork im
Repo, auch nicht in `ui_backups/` (v2 nahm ein Qt-Theme-Icon mit gemaltem
Fallback). Also eine schlichte Marke — Querschnittsmotiv, hoher Kontrast, bei
16 px lesbar —, SVG versioniert, `.ico` mit 16/32/48/256 generiert, dieselbe
Datei für `setWindowIcon`. Ein Hochschullogo wäre eine Aussage über Urheberschaft
und braucht eine Freigabe, die nicht vorliegt.

**E21 — Materialien tragen Stoffklassen, keine Rollen.** `tags` sind
`metal`, `oxide`, `metal_oxide`, `dielectric`, `semiconductor`, `resist`,
`contamination` — Eigenschaften des Stoffs. **Keine** Rollen-Tags
(`deposit`/`etch`/`mask`): Chrom ist Hartmaske *und* Depositionsmaterial *und*
Ätzobjekt, und Rollen wandern bereits durch die Capabilities und die Raten. Ein
Rollen-Tag wäre eine zweite, konkurrierende Wahrheit über dasselbe.

**E22 — Materialdropdowns filtern hart, mit Begründung und Notausgang.** Ein
Schritt deklariert, welche Bibliotheksdaten er braucht — eine Prozessklasse
(`rates[<klasse>] > 0`), ein Untermodell (`spin_curve is not None`) oder ein Tag
(für ideale Schritte, die keine Rate lesen). Was das nicht erfüllt, ist nicht in
der Liste; ein Häkchen „alle anzeigen" hebt das auf, und die Liste **sagt, wonach
sie gefiltert hat**. Freitext bleibt (sonst stirbt E15). Zwei Filterquellen sind
nötig, weil `resist.spin_coat` **ideal** keine Spin-Kurve liest und Chrom dort
trotzdem Unsinn ist. Das *Ziel*material eines Ätzschritts wird nicht ausgewählt
und ist deshalb nicht betroffen — Alumina mit Fluor-Rate 0 bleibt ätzbar, was die
Ätzstopp-Demo ist.

**E23 — ICP hat keinen Winkel.** Das beschleunigende Feld steht makroskopisch
normal zur Probe; frei wählbar ist der Winkel nur bei IBE (gekippter Teller).
`angle` verschwindet aus dem Schema von `etch.icp_fluorine` und ist fest 0. Die
**Divergenz bleibt und ist fest 3°** — Ionen queren die Randschicht mit einer
Restquerenergie, das sind real 1–5°, und bei 0° gäbe es kein Bowing zu sehen. Ein
Parameter, den ein Prozess nicht hat, ist die einzige Formulierung, die niemand
falsch bedienen kann.

**E24 — Ein Ionenätzschritt, eine Ratenspalte, und es sind die gemessenen
Zahlen.** IBE und Sputterätzen sind dieselbe Physik (Ar⁺, Impulsübertrag, keine
Chemie); §0.2 zeigt, dass auch die Zahlen dieselbe Reihe sind. Also: `etch.ibe`
und `etch.sputter` werden **ein** Schritt, die Spalte `sputter_etch` verschwindet,
und die Spalte `ion_beam` übernimmt die **Tabellenwerte** (Cr 0.1667, Oxid 0.2,
Resist 0.25, Si 0.2333, Fused Silica 0.2 angenommen). Die sechs Materialien ohne
Tabelleneintrag behalten ihre didaktischen Werte, um 0.23 skaliert, mit
`rate_notes` „didaktisch, nicht in der Tabelle". Nacharbeit: **genau ein
Szenario**, S2c von `duration=30` auf `duration=120` samt Kommentar.

Verworfen: `rate_scale` pro Anlage. Ein Tool, das Cr anders skaliert als Resist,
hat keine skalierten Raten — es hat **eigene**, und das ist B7 (eine
Bibliothekswurzel pro Anlage), nicht ein Faktor. Damit entfällt auch
`data/tools/` ganz. Der `scale`-Parameter der Ätzschritte bleibt, was er ist:
ein didaktischer Vergleichsregler, perspektivisch entbehrlich.

**E25 — Ein Reflexionsbounce beim Ionenätzen, und daraus Trenching.** Was
`SputterYield` im streifenden Ast als Verlust wegwirft (`1 − Y(θ)/Y(0)`), verlässt
die Fläche **spiegelnd** und wirkt als zweite Ätzquelle — dieselbe
Quadratur-Maschinerie und derselbe `_FLUX_REFRESH`-Takt wie die Redeposition.
Das reflektierte Ion trägt **kein** Material: die Sputterprodukte rechnet die
Redeposition schon, sie ein zweites Mal mitzuführen wäre Physik, die man nicht
mehr auseinanderhalten kann. Voller Mehrfach-Bounce ist ein anderes Projekt.

**E26 — Redeponiertes Material behält seine Identität.** Beim Abtragen entsteht
**nie** ein neues Material — sonst verwandelte schon das Überätzen ins Glas alles
in „Cr+AZ10XT". Redeponiertes Cr *ist* `chrome`, und eine Cr-Fahne an der
Resistflanke, die nach dem Lift-off als Zaun stehenbleibt, ist genau das Bild,
das ein Student sehen soll.

Dass sich Redeponat trotzdem anders verhält (poröser, teiloxidiert, anderes
Nassätzverhalten), wird über ein neues Schemafeld **`inherits`** ausgedrückt:
`chrome_redeposit.json` erbt alles von `chrome` und tippt nur die Abweichungen.
Zur **Bau**zeit, nicht zur Laufzeit — ein zur Laufzeit erzeugtes Material
verletzte §3.4 (die Bibliothek wird hereingereicht und ist unveränderlich) und
bräche ADR-0004. Wo niemand eine Datei anlegt, gilt die Identitätsregel. Zyklen
sind verboten.

**E27 — Keine Reflexion bei der Deposition.** Ein ankommendes Metallatom hat
~5 eV und haftet (s ≈ 0.9–1); es reflektiert nicht spiegelnd. Wo ein
Haftkoeffizient ≪ 1 wirklich zählt, ist CVD/ALD — und die sind hier **schon**
ideal-konform gerechnet, der Effekt ist als Geometrie drin statt als Zahl. Der
Haftkoeffizient wird notiert als das, was er ist: die Erklärung dafür, warum ALD
konform gerechnet wird, in einem Satz im Steptext. Ebenfalls verworfen:
asymmetrische Mobility bei streifendem Einfall — ein Effekt, dessen Größe niemand
begründen kann, mit einem Regler, den niemand kalibriert (B11).

**E28 — Die Belichtung färbt eine Fläche, nicht eine Kontur.** `exposed` (binär)
wird eine flache halbtransparente Graufläche; `dose` wird in **4–5 diskreten
Bändern relativ zur Clearing-Dose des Resists** getönt — unter D₀ hell, bei D₀
die Referenzstufe, darüber dunkler —, plus die D₀-Kontur als einzige Linie, weil
genau sie die Entwicklungskante vorhersagt. Diskrete Bänder statt Gradient, weil
man daraus *ablesen* kann („hier ist es 2× überdosiert").

Das weicht §10 auf: `ui.scene` bekommt die Clearing-Dose, kannte also Physik.
Vertretbar, weil `scene.build` die Bibliothek für die Farben ohnehin erhält —
aber es ist eine Regel, die aufgeweicht wird, und das steht hier, damit es nicht
unbemerkt weiter aufweicht.

**E29 — Eine Vorschauebene, zwei Darstellungen, absoluter Maßstab.** `StepPreview`
ist Qt-frei wie `LightPreview`, ein Erzeuger pro Steptyp, **rein geometrisch**:
Raycast gegen `solid_phi`, kein Yield, keine Abschattung zweiter Ordnung. Live an
`ParameterForm.valueChanged` (Mikrosekunden; das echte Flussmodell wäre nicht
live-tauglich, und eine Vorschau, die beim Tippen ruckelt, schaltet man ab).

- **Strahlen** für die gerichteten Schritte: Winkel, Divergenz als Fächerung,
  Redeposition als kurze Rückpfeile, Mobility als andersfarbiger Stummel entlang
  der Oberfläche. Nur Linien, **keine Flächen**, damit niemand sie für das
  Ergebnis hält.
- **Normalen** für die isotropen: nass, RIE, Entwicklung.
- **Partikel**: x Stück gleichmäßig verteilt (nicht zufällig — der Seed greift
  erst bei der Ausführung), gestrichelte Outline, bei Varianz > 1 Zelle drei
  Linien min/mittel/max.

Die **Pfeillänge ist die naive Rechnung in nm**: „bei dieser Rate und dieser Zeit
kommt hier so viel weg" — damit ist die Vorschau ein Werkzeug, um die Ätzzeit
einzustellen, ohne die Bibliothek zu öffnen. `view.thickness_preview_scale` ist
ein dimensionsloser Multiplikator dieser physikalischen Länge (Default 1); erst
der Canvas rechnet nm über die Domainauflösung in Anzeige-Pixel um. `0` schaltet
die Pfeile aus. Pfeile dürfen aus der Domain ragen, weil das eine ehrliche Aussage
über die Parameter ist; logarithmische Länge wäre die Lüge, die der absolute
Maßstab gerade vermeidet.

Schritte ohne `duration` sind zwei Sorten und beide sind gelöst: die vier
Depositionsschritte tragen eine **Dicke**, dort ist die Pfeillänge direkt die
lokal ankommende Dicke in nm; die übrigen bewegen keine Front oder sind ideale
Mengenoperationen — sie bekommen **keine** Pfeile, weil ein idealer Schritt keine
Geschwindigkeit hat.

**E30 — Rauhigkeit ist eine Zahl, keine Geometrie.** Bei 1 nm/Zelle und Ra ≈ 0.5 nm
ist eine polierte Oberfläche unterhalb dessen, was das Level-Set trägt, und der
Reinit zöge sie in wenigen Schritten glatt; eine unpolierte Rückseite (Ra ~ 1 µm)
wäre umgekehrt größer als die ganze Domain. Also: `substrate.roughness_nm` in
`Structure.metadata`, aus dem Preset, in `select_substrate` überschreibbar, und
**Instrumente lesen sie** — das Profilometer addiert sie als Rauschen. Das lehrt
genau das Richtige: *das Profilometer misst Rauhigkeit, die Domain zeigt sie
nicht.* Defaults: Wafer poliert 0.5 nm, Maske 0.3 nm, semi-infinit 0.0.

**E31 — Ein Schritt, der ein Material einführt, fragt vorher.** `engine.run_step`
prüft **vor** der Ausführung jeden als Material deklarierten Parameter gegen die
Bibliothek; fehlt einer, kommt E15s Dialog **vorher**, und Abbrechen heißt: der
Schritt läuft nicht. Das dreht E15 um, und für `anneal` ist es zwingend — heute
tauscht er auf ein `resist_hardbaked`, dessen Existenz niemand prüft. Die
Bake-Trilogie (`bake.soft` / `bake.post_exposure` / `bake.hard` mit je eigener
Feldregel, und ein PEB, der das latente Bild *verarbeitet* statt es zu löschen)
ist M12 und wird dort im Detail festgelegt.

**E32 — Spin-Coat: der Ideal/Didaktisch-Schnitt jetzt, die Planarisierung
später.** Ideal = Dicke tippen. Didaktisch = Drehzahl über die Spin-Kurve, **ohne**
Dicken-Override — womit sich E17s halbgebaute Read-only-Anzeige von selbst
erledigt, weil es nichts mehr anzuzeigen gibt.

Die Planarisierung ist **offen** und wird zu Beginn von M12 geklärt. §3 unten
listet die Randbedingungen, an denen jede Lösung gemessen wird; die naheliegende
Formel `w = h·e^{−t/αh}` ist bereits als unzureichend erkannt (kein laterales
Längenmaß, §3.9).

**E33 — Litho: Defaults aus der Domain, und Kumulativität heißt zweierlei.**
`center` → Domainmitte, `period` → Domainbreite/3, `phase` → umbenannt zu
`grating_center`, Default Domainmitte. Ausgedrückt über den Marker `0` = „aus der
Domain", weil das die Konvention ist, die im Repo schon zweimal gilt
(`thickness=0` = „aus der Kurve", `material=""` = „aus dem Preset").

Mehrere Belichtungen: **`dose` summiert** (physikalisch richtig, zwei Belichtungen
addieren Energie), **`exposed` ODER-t** und sagt es im Log als Information, nicht
als Warnung — dieselbe Ehrlichkeit über den Informationsverlust, die
`threshold_dose` schon leistet.

**E34 — Inhomogenität lebt am Prozess, mit festem Bezugsradius.** Ein Parameter
`uniformity_percent` an jedem **didaktischen** Depositions- und Ätzschritt (nicht
an den idealen — ein idealer Schritt hat keine Anlage), Bedeutung: „bei **150 mm**
vom Anlagenzentrum ist die Rate um so viel Prozent niedriger", dazwischen
quadratisch. Ein fester Bezugsradius ist eine Konvention wie „Raten sind nm/s";
zwei Felder für zwei Freiheitsgrade kosten mehr Verständnis, als der zweite
bringt.

**Mitte = Nennwert**, damit die 589 Tests und die sieben Szenarien unverändert
bleiben und die Physik trotzdem sofort da ist, sobald jemand den Positions-Fan
benutzt. `r` läuft über die **Substrat**ausdehnung gegen eine auf den
Anlagenradius normierte Kurve — damit sieht ein 15-mm-Chip in einer 300-mm-Anlage
automatisch 0.02 % Abweichung, ohne dass das irgendwo als Sonderfall steht.
Defaults pro Prozessklasse (ALD ~2 %, Sputtern ~8 %), global in `settings.ini`
vorbelegbar.

**E35 — SEM bleibt, Ellipsometer geht, kein FIB.** Der SEM zeigt den Querschnitt,
und das ist genau die Sicht, die ein FIB-Schnitt freilegt — er wird umbenannt in
**„SEM (Querschnitt)"** und im Text so erklärt. Ein echter FIB als *neuer* Schnitt
quer zur Ebene erzwänge 3D und kommt nicht. Das Ellipsometer wird **ersatzlos
entfernt** (Step, Implementierung, Tests, Doku): kein Demo und kein Rezept
benutzt es, und `film_thickness` bleibt ohnehin, weil das Profilometer es liest.

**E36 — `--selftest` bleibt und bekommt einen Fingerabdruck.** Er ist der
Auslieferungsbeweis (M5s DoD), nicht die Entwicklertestsuite: die 589 Tests laufen
im Quellbaum und sehen die Klasse „nur im Binary" prinzipiell nicht. Mit E19 gibt
es im Frozen Build nur noch **eine** Bibliothekswurzel, also hängen die
Szenariozahlen an den Dateien des Nutzers — das wird sichtbar gemacht statt
kaschiert: `--selftest` und `--version` drucken einen Hash über alle geladenen
Dateien. Im Quellbaum bleiben die zwei Wurzeln, dort ist die Trennung echt.

**E37 — Ein Fenster für Bibliothek und Demos: Nachschlagewerk *und* Editor.**
Liste links, alle Felder rechts inklusive `rate_notes` (also „angenommen, nicht
gemessen" sichtbar), unten die Datei, aus der es kam, plus die **fehlgeschlagenen**
Dateien mit ihrem Grund. Zwei Reiter, Materialien und Demos — dieselbe Frage
(„was ist geladen und woher").

Der Editor schreibt **direkt und kanonisch** (`write_material`, dessen Kodierung
ein M6-Test byteweise pinnt, damit ein Speichern keine unbeteiligten Felder
umschreibt), atomar per `os.replace`, nach Schema-Validierung — keine Editierfehler
durch ein vergessenes Komma. Zwei Regeln dazu:

- Der Auslieferungszustand liegt als `data/materials/.original/` daneben, damit
  „zurücksetzen" existiert. Das ist genau *eine* zusätzliche Kopie, nämlich die
  unveränderte, und sie wird nie gelesen außer beim Zurücksetzen — kein
  Zweideutigkeitsfall im Sinne von E19.
- Wer eine Rate ändert, macht aus „Studententabelle, Zeile 1" eine Behauptung, die
  nicht mehr stimmt. Der Editor **schreibt die Provenienz fort** statt sie zu
  löschen: `rate_notes` wird zu „Bearbeitet am <Datum> (vorher: <Wert>, <Notiz>)".

**E38 — Autosave rettet das Rezept, nicht die Rechnung.** Ein Rezept ist ~1 kB
und schreibt in Millisekunden; ein Build ist 23 MB pro Revision (§23.7, gemessen),
also 230 MB bei zehn Schritten — und die Zeit, in der die Anwendung nicht
reagiert. Die Strukturen liegen ohnehin schon im **Replay-Cache**, der eine
Wiederholung 68× schneller macht als die Rechnung. Also: nach jedem Schritt nur
das Rezept, atomar per `os.replace` (auf allen drei Plattformen atomar, ein
halbgeschriebenes Rezept kann nicht entstehen). Beim Start „Letzte Sitzung
wiederherstellen?" → Rezept laden, **nicht** automatisch rechnen — womit auch ein
Rezept, dessen Nachrechnen abstürzt, niemanden am Starten hindert.

Ort: die Cache-Leiter, um eine Sprosse erweitert — `$NANOFAB_CACHE` →
**`%LOCALAPPDATA%` (nur Windows)** → `$XDG_CACHE_HOME` → `~/.cache`, mit
getrennten Unterordnern `replay/` und `session/`, damit ein Cache-Leeren die
Sitzung nicht mitnimmt. Heute landet der Cache auf Windows in
`C:\Users\<name>\.cache\` — eine Unix-Konvention an einem Ort, an dem ein
Windows-Nutzer nicht sucht. System-Temp ist der falsche Ort: Windows räumt ihn auf.

**E39 — `settings.ini` stellt Anwendungsverhalten ein, nicht Physik.** Welche
Overlays und Vorschauen beim Start an sind, der Pfeilmaßstab, Startdemo,
Log-Ausführlichkeit, Domainpolitik-Obergrenze — und **Vorbelegungen** für
Prozessparameter. Vorbelegung, nicht Vorschrift: jeder Schritt schreibt die
aufgelösten Werte ins Rezept, also bleibt ein gespeichertes Rezept auf jedem
Rechner dasselbe (§5.2, ADR-0004). Die Datei wird mit **allen** Defaults und
Kommentaren erzeugt, dokumentiert sich selbst, und wird **nie zurückgeschrieben**
— zur Laufzeit umgeschaltete Toggles bleiben zur Laufzeit.

Alpha-Korrektur: Jeder View-Toggle und jedes Overlay hat zwei unabhängige
Schalter: den Startwert und `<name>_hidden`. Ein versteckter Schalter wendet den
Startwert weiterhin an, entfernt aber seine Bedienung aus dem UI und sperrt ihn
damit. Der Bildselector folgt derselben Regel mit `picture` und
`picture_hidden`.

**E40 — Artefakte in den Speicher, beim Speichern in den Ordner.** Ein
Verzeichnis-Sink zwänge eine noch nicht gespeicherte Sitzung, sich einen Pfad
auszudenken. Also `MemoryArtifactSink` (existiert bereits, kostet nichts), und
`save_build` nimmt die Artefakte in den Ordner mit, der ohnehin entsteht. Damit ist
der Stecker aus §0.6 drin, und das Profilometer-Overlay hat einen Weg.

## 3. Die Randbedingungen der Planarisierung (für M12)

Gesammelt, damit die Formelwahl nicht bei null anfängt. Getrennt nach dem, was
**dieses Modell** erzwingt, und dem, was **die Physik** erzwingt.

Modell — harte Bedingungen, an denen eine Lösung scheitert oder nicht:

1. **Volumenerhaltung wird geprüft.** Der Commit-Gate rechnet
   `Nenndicke × Grundfläche` gegen die gemessene Änderung, Toleranz 5 %.
   „Auffüllen bis Höhe des höchsten Punktes + t" verletzt das sofort.
2. **Das Ergebnis muss eine Höhenfunktion sein.** Überhänge, Tropfen, Kehlen sind
   als Level-Set ausdrückbar, aber keine geschlossene Formel liefert sie — sobald
   Entnetzung ins Spiel kommt, bricht diese Annahme zuerst.
3. **Erreichbarkeit.** Lack fließt nicht in einen abgeschlossenen Hohlraum; eine
   Formel, die nur eine Höhe setzt, füllt ihn.
4. **Sub-Zell-Genauigkeit.** Welligkeiten unter ~2 Zellen sind nicht darstellbar —
   bei 2 nm/Zelle und h = 200 nm ist das eine DOP-Auflösung von etwa 2 %.
5. **Auf einer ebenen Fläche bitgleich wie heute**, sonst bewegen sich S1, S3, S4
   und alle vier Demos.
6. **Kein zweiter Solver.** Die Nivellierung ist eine Dünnfilmgleichung vierter
   Ordnung; was hier hineinpasst, ist eine geschlossene Form oder ein Filter.
7. **Keine unkalibrierbaren Regler** (B11).
8. **Benetzung ist eine Paar-Eigenschaft** — und die Bibliothek hat einen Eintrag
   pro Stoff, keinen für „Lack auf Chrom" gegen „Lack auf Oxid". Wer einen
   Kontaktwinkel braucht, braucht zuerst einen Ort dafür: entweder eine Matrix
   (passt nicht ins Schema) oder Oberflächenenergien pro Material, aus denen der
   Winkel nach Young folgt (passt).

Physik — die Fälle, die eine Formel unterscheiden können muss:

9. **`t/h` hat kein Längenmaß.** Ein 300-nm-Graben und ein 50-µm-Graben derselben
   Tiefe planarisieren völlig verschieden. Die DOP hängt von **Merkmalsbreite/
   Dicke** ab, nicht nur von Tiefe/Dicke — für ein Gitter ist die Periode die
   entscheidende Größe. Das ist der Fehler der naheliegenden Formel.
10. **Die Nivellierung wird eingefroren, nicht abgeschlossen** — der Film
    verfestigt, während er fließt; deshalb ist DOP < 1 auch bei dickem Lack.
11. **Konvexe und konkave Ecken sind verschieden**, auch bei geschlossenem Film —
    eine Aussage über lokale Krümmung, unabhängig von der globalen DOP.
12. **Entnetzung hat eine eigene Schwelle** (Disjoining-Pressure, Kontaktwinkel),
    die *nicht* aus der Topographie folgt. „t < 0.5 h" ist eine Geometrieregel und
    keine Entnetzungsregel; sie fallen nur oft zufällig zusammen.
13. **Nicht modellierbar im Querschnitt:** Randwulst, Striations, Kometenschweife
    — alle drei radial oder azimutal, und der Querschnitt hat keine Rotation.

Gemessen für die Diskussion: mit `w = h·e^{−t/0.6h}` auf h = 200 nm bleiben bei
t = 0.25 h noch **16 nm** Lack über dem Steg — der Film ist überall geschlossen,
wo er real längst aufgerissen wäre. Bei t = 0.5 h sind es 44 nm, bei t = 0.75 h
79 nm. Die Formel ist unterhalb t ≈ 0.5 h nicht ungenau, sondern **qualitativ
falsch**.

**E41 — Spin-Coat ist ein konservativer eingefrorener
Vierte‑Ordnung‑Filter, kein zweiter Dünnfilmsolver.** Die linearisierte
Dünnfilmgleichung dämpft eine laterale Fouriermode mit `exp(−C·k⁴·τ)`; genau diese
`k⁴`-Abhängigkeit ist der Teil, den sowohl Experimente an gestuften Polymerfilmen
als auch numerische Thin-Film-Arbeiten tragen
([McGraw et al.](https://pubmed.ncbi.nlm.nih.gov/23005996/),
[Salez et al.](https://pubmed.ncbi.nlm.nih.gov/23138477/)). M12 nimmt deshalb die
Höhenfunktion der obersten erreichbaren Oberfläche, transformiert sie mit
Neumann-Randbedingung per DCT und dämpft jede Mode um
`exp(−(|k|·ℓ)⁴)`. Eingefroren wird bei **`ℓ = Nenndicke`**: eine physikalisch
lesbare Länge, kein neuer Fitregler. Damit hängt die Planarisierung von
Merkmalsbreite/Dicke ab und bleibt bei breiten Strukturen unvollständig.

Nach dem Filter wird die Oberfläche an der ursprünglichen Topographie geklippt
(keine negative Filmdicke) und nur vertikal so verschoben, dass die mittlere
Filmdicke wieder exakt der Nenndicke entspricht. Das erhält im Höhenmodell das
Volumen; der Geometrietest hält die Abweichung des gesampelten Level-Sets unter
5 %. Nur vom oberen Domainrand erreichbarer Leerraum plus ein Kontaktkragen darf
Lack werden, also bleiben geschlossene Hohlräume leer. Eine ebene, hohlraumfreie
Oberfläche nimmt bitgleich den alten Konstruktorpfad.

Die Grenze ist Teil der Entscheidung: Ohne Oberflächenenergien je Material kann
das Modell weder Benetzungspaare noch Disjoining Pressure ableiten und behauptet
deshalb **keine Entnetzung**. Kontaktwinkel, Filmabriss und Tropfen bleiben bis zu
solchen Bibliotheksdaten außerhalb. Verworfen wurden (a) „höchster Punkt +
Dicke“, weil es Volumen erzeugt, (b) ein exponentieller DOP nur aus `t/h`, weil
ihm die laterale Länge fehlt, und (c) ein zeitintegrierter PDE-Solver, weil er
Viskosität, Oberflächenspannung und Verfestigungszeit als unkalibrierbare Regler
einführen würde.

## 4. Die Meilensteine

### M10 — Auslieferung und Auswahl ✅ *erledigt 2026-08-27*

**Fasst keine einzige gemessene Zahl an.** Das ist der Grund für die Reihenfolge:
M10 kann komplett grün bleiben, und danach ist jede rote Zahl nachweislich Physik.

1. ✅ **Paket** (E19): `--onedir`, `contents_directory="bin"`, `data/` und `demos/`
   als einzige Kopie, lauter Abbruch ohne Materialien, Icon (E20),
   `settings.ini` mit allen Defaults und Kommentaren (E39),
   Bibliotheks-Fingerabdruck in `--version`/`--selftest` (E36).
2. ✅ **Materialtypisierung** (E21/E22): `tags` in den 11 Dateien, Filterkriterium
   pro Materialparameter, Dropdown mit Begründung und „alle anzeigen", Freitext
   bleibt.
3. ✅ **Bibliotheks- und Demofenster** (E37): lesen, `.original/`, kanonisch
   schreiben, Provenienz fortschreiben, Fehlerliste, „neu laden". Der Demo-Reiter
   ist **lesend** — ein zweiter Rezept-Editor neben „öffnen, ändern, speichern"
   wäre eine zweite Definition davon, was ein Rezept ist.
4. ✅ **Sitzung** (E38/E40): Autosave des Rezepts, Wiederherstellungsfrage beim
   Start, `MemoryArtifactSink`, Artefakte im `save_build`.
5. ✅ **Bugs und kleine Formulierungen**: der `adjust`-Bug (§0.1 — und es waren
   **zwei** Schreibvorgänge, siehe Plan §26.2) und `adjust` löscht den Filter;
   Index-Map/Konturen als Radiobutton-Paar; Ellipsometer raus, SEM umbenannt
   (E35); Warnung, wenn eine verlangte Dicke unter einer Zelle liegt (§0.5).
6. ✅ **Bild und Litho** (E28/E33): Belichtung als Fläche mit D₀-Linie,
   Litho-Defaults aus der Domain, `grating_center`, kumulative Belichtung.
7. ✅ **Substrat** (E30): Preset „semi-infinit, 50 nm Oberfläche", `surface`-Default
   100 nm für Wafer und Maske, `roughness_nm` in den Presets, und das
   Profilometer liest sie.

Zusätzlich erledigt, weil die R1-Übung (§2 gegen §4 prüfen) sie fand bzw. der
Handoff sie hier fällig machte: **E31s erste Hälfte** (ein Schritt, der ein
Material einführt, fragt vorher — stand in *keiner* §4-Liste, nur die
Bake-Trilogie war M12 zugewiesen) sowie **R1, R6, R7, R8 und R9**.

**DoD — gemessen, alle erfüllt:** Der ausgelieferte Ordner enthält Exe, `bin/`,
`data/materials/`, `data/demos/`, `settings.ini` und sonst nichts; eine dort
geänderte Rate wirkt nach einem Neustart und `--version` weist sie über den
Fingerabdruck aus (im ausgelieferten Ordner gemessen: eine geänderte Cr-Rate
bewegt ihn und ein `.original/`-Reset bewegt ihn zurück; der aktuelle ist
82f5c67a11d3); ein Materialdropdown
zeigt für `resist.spin_coat` keine Metalle und sagt warum; „Anpassen" lädt die
gelaufenen Werte, auch bei aktivem Filter; das Programm startet nach einem
Absturz mit der Frage nach der letzten Sitzung und rechnet sie nicht ungefragt;
die Tests sind grün (**589 → 672**, 0 übersprungen) und die Exe 7/7.

Eine Zahl hat sich bewegt, und sie ist keine Physik: **31 → 30 Schritte**, weil
E35 das Ellipsometer entfernt. Der Preis der Onedir-Auslieferung ist ebenfalls
gemessen: 304 MB unkomprimiert gegen 115 MiB als Onefile (Plan §26.1).

### M11 — Gerichtete Prozesse und ihr Bild ✅ *erledigt 2026-08-28*

**Fasst Raten und den Flusskern an.** Die Vorschau gehört hierher, weil sie die
*Erklärung* der gerichteten Prozesse ist und beide dasselbe Flussmodell anfassen.

1. ✅ **Ratenvereinheitlichung** (E24): ein `etch.ion_beam`, eine Spalte mit den
   Tabellenwerten, S2c nachgezogen, `rate_notes` überall korrekt.
2. ✅ **ICP** (E23): `angle` raus, Divergenz fest 3°.
3. ✅ **Reflexion und Trenching** (E25).
4. ✅ **Redeposition** (E26): Identität erhalten, `inherits` im Schema,
   `chrome_redeposit.json` als erstes Beispiel; keine Reflexion bei Deposition
   (E27), mit dem Satz, warum ALD konform gerechnet wird.
5. ✅ **Live-Vorschau** (E29): `StepPreview`, Strahlen und Normalen, Partikelraster,
   absoluter Maßstab aus `settings.ini`, und der Live-Bug (Vorschau nur bei
   Toggle) fällt dabei weg.

**DoD:** Ein IBE durch eine Resistmaske zeigt Trenching am Grabenfuß und eine
Cr-Fahne an der Resistflanke, die nach dem Strippen als Zaun stehenbleibt; die
Tabellenwerte stehen unverändert in den Materialdateien und `etch.sputter`
existiert nicht mehr; während man eine Ätzzeit tippt, ändern sich die Pfeile
sichtbar mit, und ihre Länge ist die abgetragene Tiefe; die Tests sind grün, S2c
mit angepasster Zeit.

**DoD — gemessen, alle Vertragsebenen erfüllt:** Der Registry hat **29** Schritte
und nur noch `etch.ion_beam`; dessen Schema hat kein `redeposit_as`, ICP weder
Winkel noch Divergenz. S2c läuft mit 120 s und 1.25 auf derselben Solltiefe.
Der Flusskerntest trifft nach genau einem spiegelnden Ionenbounce eine zweite
Fläche, während Deposition kein `reflected`-Feld erzeugt. Getrennte Release-Felder
halten Si und Cr auseinander; `chrome_redeposit` erbt Raten und Tags von `chrome`,
fehlende Eltern und Zyklen brechen laut ab. Die Qt-freie Vorschau rechnet für S2c
34.995 nm, reagiert auf Parameteränderungen und erklärt Pfeile unter 5 px. Nach
der E31-Nachkorrektur ging die Suite **673 → 681**, 0 übersprungen.

### M12 — Anlage und Prozessführung ✅ *erledigt 2026-08-28*

**Fasst Demos und Didaktik an**, und beginnt mit einer Klärung.

1. ✅ **Inhomogenität** (E34): `uniformity_percent` an den didaktischen Depo- und
   Ätzschritten, Defaults pro Prozessklasse, Positions-Fan zeigt sie.
2. ✅ **Spin-Coat** (E32): Ideal/Didaktisch-Schnitt bauen; die Planarisierung
   **zuerst gegen §3 klären** und die Entscheidung als E41 nachtragen, bevor eine
   Zeile Code entsteht.
3. ✅ **Bake-Trilogie** (E31): `bake.soft` / `bake.post_exposure` / `bake.hard`, je
   eigene Feldregel; nur der Hardbake tauscht das Material, und welches sagt die
   Bibliothek.

**DoD:** Derselbe Prozess an fünf Waferpositionen liefert fünf verschiedene
Dicken, in der Mitte den Nennwert; ein Spin-Coat auf ein Gitter zeigt etwas
Verteidigbares und die Entscheidung dazu steht als E41 im Plan; ein
Post-Exposure-Bake **erhält** das latente Bild und ein Hardbake tauscht das
Material nur, wenn das Ziel existiert.

**DoD — gemessen, alle erfüllt:** Eine 20-nm-Evaporation mit 20 % Randabfall
liefert über 0 / 37.5 / 75 / 112.5 / 150 mm die fünf Dicken **20 / 19.75 / 19 /
17.75 / 16 nm**. Der didaktische Spin-Coat nivelliert das ausgelieferte Gitter
volumenerhaltend innerhalb der 5-%-Geometrietoleranz, lässt einen geschlossenen
Hohlraum leer und bleibt auf einer ebenen, hohlraumfreien Fläche bitgleich zum
idealen Konstruktor. PEB erhält das Dosisfeld samt Integral und die binäre
Belichtung; Hardbake tauscht Identität und Level-Set erst ab der in der
Bibliothek stehenden Aktivierungstemperatur und bricht bei fehlendem Ziel vor dem
Commit ab. Gemessener Endstand: **32 Schritte, 12 Materialien, 5 Demos,
`0.5.0.dev0`; 681 → 687 Tests**, 0 übersprungen; Source- und frisch gebauter
Onedir-Selftest jeweils **7/7**.

## 5. Was diese Roadmap bewusst *nicht* umfasst

Profilometer-Visualisierung (Messspitze über die Oberfläche, Höhenprofil als
Artefakt und Overlay) · Nukleation und Inselwachstum — ausdrücklich gewünscht,
aber ein eigenes Modell neben der Mobility, nicht eine Erweiterung davon ·
Haftkoeffizient als Zahl · FIB als echter zweiter Schnitt (erzwänge 3D) ·
B7 (kalibrierte Raten pro Anlage über eine eigene Bibliothekswurzel) · der Rest
von `backlog-later.md`.

Aus `docs/plans/m6-m9-handoff.md` bleiben offen und begründet vertagt:
**R2** (Konzavecken-Rest in `seeded_distance`, gemessen ≤ 1 Zelle, kein Test
bewegt sich), **R3** (die dreizehn Ein-Zell-Splitter des Gitters — die Ursache
liegt in der Ätzfront, nicht im Labeller, und ein Größenfilter würde die
Sub-Zell-Partikel löschen, auf denen S5 beruht), **R5** (die drei widerlegten
M9-Fixes — sie sind an vier Stellen im Code notiert, das *ist* die Erledigung)
und **R10** (`union_front` in 3D).
