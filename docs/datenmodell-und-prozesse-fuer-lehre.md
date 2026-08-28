# NanoFab: Datenmodell, Prozessmodelle und didaktische Einordnung

## Zweck und Leserkreis

Dieses Dokument beschreibt den technischen Stand der aktiven Anwendung `nanofab_v3` fuer die fachliche Begutachtung und fuer die Planung studentischer Aufgaben. Es erklaert erst das gemeinsame Datenmodell und danach jeden der 32 im eingebauten Prozessregister enthaltenen Prozessschritte.

Die zentrale Einordnung vorweg: NanoFab ist derzeit **kein kalibrierter Prozesssimulator und kein Ersatz fuer TCAD, CFD, Molekulardynamik oder eine 3D-Topographiesimulation**. Es ist ein deterministisches, zweidimensionales Querschnittsmodell mit drei ausgewiesenen Modellstufen:

- **ideal**: exakte geometrische Mengenoperationen ohne Zeit- oder Ratenmodell;
- **didactic**: zeit-, raten-, sichtbarkeits- und materialabhaengige Modelle, die die wesentlichen Mechanismen qualitativ und teilweise quantitativ nachvollziehbar machen;
- **physical**: als Erweiterungspunkt vorgesehen, wenn kalibrierte Material- und Maschinenmodelle vorliegen; im eingebauten Prozesssatz derzeit nicht belegt.

Damit ist das Werkzeug vor allem fuer Fragen geeignet wie: Warum erzeugt ein isotroper Aetzprozess Unteraetzung? Warum funktioniert Lift-off nach gerichteter Verdampfung besser als nach konformer Beschichtung? Was ist der Unterschied zwischen einem binaeren Belichtungsbild und einem Dosisfeld? Welche Messabweichung verursacht eine endliche Profilometerspitze? Nicht behauptet wird dagegen, dass die aktuelle Geometrie ohne Kalibrierung einen konkreten Laborprozess exakt vorhersagt.

Technischer Bezugspunkt dieses Textes ist der Quellstand `0.5.0a3` vom 28.08.2026. Massgeblich sind insbesondere [Structure und Grid](../nanofab_v3/model/), der [numerische Kernel](../nanofab_v3/kernel/), der [Prozessvertrag](../nanofab_v3/processes/contract.py), das [Prozessregister](../nanofab_v3/processes/registry.py) und der [Ausfuehrungsweg](../nanofab_v3/processes/engine.py).

## 1. Das Prinzip in einem Satz

Jede Revision ist ein unveraenderlicher Zustand eines diskretisierten Probenquerschnitts. Ein Prozess liest diesen Zustand und validierte Parameter, berechnet daraus einen neuen Zustand und gibt zusaetzlich Messwerte, Protokollzeilen und gegebenenfalls Artefaktverweise zurueck.

```text
Rezept + Waferposition + Materialbibliothek
                    |
                    v
       Parameterpruefung und Faehigkeits-Gate
                    |
                    v
       Prozessfunktion: Structure -> StepResult
                    |
                    v
     Commit-Gate: Normalisierung, Invarianten,
      Feldregeln, Bilanz, Topologie, Faehigkeiten
                    |
                    v
          neue append-only Revision
```

Wichtig ist die Trennung der Verantwortlichkeiten:

- Die `Structure` beschreibt **was geometrisch und lokal im Querschnitt vorhanden ist**.
- Die Materialbibliothek beschreibt **wie ein Material auf Prozesse reagiert**.
- Der Prozess beschreibt **welcher Mechanismus und welche Parameter angewendet werden**.
- Der Kernel stellt wiederverwendbare Geometrie-, Bewegungs-, Sichtbarkeits- und Topologieoperationen bereit.
- Die Runtime dokumentiert **wann, wo und mit welchem Prozess** eine neue Revision entstand.

## 2. Das raeumliche Datenmodell

### 2.1 `Grid`: die einzige raeumliche Autoritaet

Ein `Grid` enthaelt Ursprung, isotropen Zellabstand, Arrayform und benannte Achsen. Im aktuellen Querschnitt ist die Achsreihenfolge `("y", "x")`: `y` ist die Stapelrichtung, `x` die laterale Richtung. Eine Zelle mit Index `(i, j)` liegt bei

`position = origin + spacing * index`.

Alle geometrischen und lokalen Felder einer `Structure` muessen exakt auf diesem Grid liegen. Der Zellabstand, typischerweise 1 nm, ist deshalb ein sichtbarer Modellparameter und kein reines Darstellungsdetail. Er bestimmt unmittelbar:

- die kleinste sinnvoll darstellbare Schichtdicke;
- den Speicherbedarf;
- die CFL-Zeitschrittweite bei Frontbewegungen;
- die Genauigkeit von Kanten, engen Spalten und kleinen Partikeln.

Eine angeforderte Schicht unterhalb einer Zellbreite kann keine echte Innenzelle besitzen. Die Prozesse warnen deshalb bei Sub-Zell-Schichten, anstatt eine nicht vorhandene Genauigkeit zu suggerieren.

### 2.2 `Structure`: ein Distanzfeld pro Material

Die gespeicherte geometrische Wahrheit ist kein Layer-Stack und kein Polygonnetz, sondern eine Abbildung

`phi: MaterialId -> float32-Array`.

Jedes Array ist ein vorzeichenbehaftetes Distanzfeld (Signed Distance Field, SDF):

- `phi_m(x) < 0`: Punkt beziehungsweise Zelle liegt im Material `m`;
- `phi_m(x) = 0`: Materialgrenze;
- `phi_m(x) > 0`: Punkt liegt ausserhalb dieses Materials;
- der Betrag beschreibt in der Naehe der Grenzflaeche den Abstand zur Grenze.

Diese Darstellung ist fuer iterative Prozesse wichtig. Eine Schicht kann sich aufspalten, Hohlraeume koennen sich schliessen, ein Film kann Seitenwaende bedecken und spaeter teilweise entfernt werden, ohne dass eine vorher festgelegte Layer-Reihenfolge repariert werden muss.

Aus den Materialfeldern werden Ansichten abgeleitet, aber nicht als zweite Wahrheit gespeichert:

- Festkoerpervereinigung: `solid_phi = min_m(phi_m)`;
- Festkoerpermaske: `solid_phi <= 0`;
- naechstes Material: `argmin_m(phi_m)`;
- exklusives Zellbild: naechstes Material innerhalb der Festkoerpermaske, sonst leer;
- Konturen, Flaechen/Volumina, Filmdicken und zusammenhaengende Materialvorkommen.

Die Innenraeume verschiedener Materialien sollen sich nicht ueberlappen. Beruehrende Materialien teilen jedoch ihre Grenzflaeche. Deshalb ist eine einfache Auswertung `phi_m <= 0` nicht fuer jede Materialabfrage ausreichend; der Kernel verwendet dafuer unter anderem die topologische Abschlussmenge des echten Inneren.

### 2.3 Warum nicht eine Liste von Schichten?

Eine Layer-Liste funktioniert fuer ebene, nie aufbrechende Stapel. Sie wird problematisch, sobald ein Prozess eines der folgenden Ergebnisse erzeugt:

- Unteraetzung unter einer Maske;
- getrennte Metallinseln nach Lift-off;
- Seitenwandzaeune;
- Pinch-off und eingeschlossene Hohlraeume;
- Partikel und Mikromaskierung;
- Zusammenwachsen oder Aufspalten von Bereichen.

Das SDF-Modell repraesentiert diese Topologie direkt. Eine UI-Schichtliste ist daher nur eine aus der aktuellen Geometrie abgeleitete Zusammenfassung.

### 2.4 Konstruktoren und CSG

Analytische Formen existieren nur beim Erzeugen von Geometrie. `half_space`, `box`, `rounded_box` und `ball` werden auf das Grid abgetastet; danach ist das Feld die Wahrheit und der urspruengliche Primitive wird nicht mitgefuehrt.

Fuer vorzeichenbehaftete Distanzfelder werden die ueblichen Mengenoperationen verwendet:

- Vereinigung: `min(phi_a, phi_b)`;
- Schnitt: `max(phi_a, phi_b)`;
- Differenz `A \ B`: `max(phi_a, -phi_b)`;
- Offset nach aussen: `phi - d`.

Diese Formeln sind als Mengenoperationen korrekt, ergeben aber nach komplexen Kombinationen nicht automatisch wieder ein ideales Distanzfeld. Deshalb folgt auf jeden Prozess das Commit-Gate mit einer schmalbandigen Reinitialisierung.

### 2.5 Lokale `Field`s

Neben Geometrie kann eine `Structure` benannte zellweise Felder tragen. Der Schluessel ist `(Feldname, MaterialId oder None)`.

- **materialbezogen**, zum Beispiel `dose@resist` oder `exposed@resist`;
- **global**, zum Beispiel `thermal_budget`.

Ein `FieldSpec` definiert Datentyp, Defaultwert, Einheit und Gueltigkeitsbereich. Materialbezogene Felder sind nur dort sinnvoll, wo das zugehoerige Material fortbesteht. Wenn ein Prozess Material entfernt oder neu erzeugt, setzt das Commit-Gate das Feld in den geaenderten Zellen auf seinen Defaultwert zurueck. Dadurch kann beispielsweise eine alte Belichtungsdosis nicht in spaeter neu aufgetragenen Resist „hineinvererbt“ werden.

### 2.6 Metadaten

`Structure.metadata` enthaelt kleine JSON-kompatible Skalare, die zur Probe gehoeren, aber nicht pro Zelle gespeichert werden sollen. Das wichtigste Beispiel ist die reale Substratdicke.

Ein 625 um dicker Wafer kann nicht sinnvoll mit 1 nm Aufloesung vollstaendig in den dargestellten Ausschnitt aufgenommen werden. Deshalb zeigt die Geometrie nur ein nanometergrosses Prozessfenster an der Oberflaeche; reale Dicke, Durchmesser, Formfaktor, Oberflaechenlage, Finish und Rauheit werden als Metadaten mitgefuehrt. Ein Durchbruch kann so gegen die reale Dicke geprueft werden, ohne den gesamten Wafer zu diskretisieren.

### 2.7 Materialtyp versus Materialvorkommen

Eine `MaterialId` in der `Structure` bezeichnet nur die Identitaet eines geometrischen Feldes. Physikalische beziehungsweise didaktische Eigenschaften liegen ausserhalb der Struktur in einer dateibasierten `MaterialLibrary`.

Ein `MaterialType` kann unter anderem enthalten:

- Anzeigename, Farbe und Stoffklassen-Tags;
- Prozessraten in nm/s fuer konkrete Prozessklassen und Chemien;
- winkelabhaengige Sputterantwort;
- Absorptionskoeffizient fuer Belichtung;
- Entwicklungskurve mit Ton, Clearing-Dosis, Dunkel- und Klar-Rate sowie Kontrast;
- Loesemittel- und Aufloeserate;
- gemessene Spin-Kurve `Dicke(rpm)`;
- Hard-Bake-Zielmaterial und Aktivierungstemperatur.

Damit ist zum Beispiel „Chrom ist eine Hartmaske“ keine fest programmierte Rolle. Chrom wirkt als Hartmaske, wenn seine Rate fuer den betrachteten Aetzprozess klein oder null ist. Ein neues oder kalibriertes Materialmodell kann daher eingefuegt werden, ohne den Bewegungsloeser zu aendern.

Die Bibliothek ist zugleich eine wichtige Grenze der Aussagekraft: Viele ausgelieferte Werte sind bewusst didaktisch oder aus einer einfachen Prozesstabelle uebernommen. Die Provenienz wird in `data/materials/README.md` dokumentiert. Fuer belastbare Vorhersagen waeren material-, maschinen- und rezeptbezogene Kalibrierungen erforderlich.

### 2.8 `Occurrence`: zusammenhaengende Vorkommen und Topologie

Ein `Occurrence` ist eine zusammenhaengende Region eines Materials in genau einer Revision. Es wird durch Connected-Component-Labeling aus der Geometrie abgeleitet und nicht dauerhaft als Objektidentitaet in der `Structure` gespeichert.

Zwischen Eltern- und Kindrevision werden Komponenten ueber ihre Ueberlappung zugeordnet. Daraus entstehen Lineage-Ereignisse:

- unveraendert;
- aufgespalten;
- zusammengefuehrt;
- neu erschienen;
- verschwunden.

Das ist fuer Lift-off, Filmabriss oder Pinch-off fachlich nuetzlicher als kuenstliche IDs. Eine ID wuerde beim Aufspalten willkuerlich entscheiden muessen, welcher Teil „das alte Objekt“ bleibt; die Rekonstruktion berichtet stattdessen die tatsaechliche topologische Aenderung.

## 3. Numerischer Kernel

### 3.1 Zwei Arten der Geometrieaenderung

**Ideale Mengenoperationen** entfernen oder erzeugen eine vollstaendig bestimmte Region in einem Schritt. Beispiele sind ideale Entwicklung, ideales Aufloesen und das Entfernen nicht gestuetzter Komponenten.

**Zeitabhaengige Frontbewegungen** verwenden eine Level-Set-Advektion. Der allgemeine Geschwindigkeitsbetrag ist

`F(x) = Rate(Material an der Front) * Flussfaktor(x)`.

Die Union-Front wird mit einem Godunov-Upwind-Schema erster Ordnung unter einer CFL-Bedingung bewegt. Ein Prozessschritt von beispielsweise 60 s bleibt fuer den Benutzer eine Revision, wird intern aber in stabile Subschritte zerlegt. Materialraten und Fluss werden waehrend der Bewegung an der aktuellen Front neu ausgewertet. Trifft ein Aetzprozess nach Material A auf Material B, wechselt die Front deshalb ohne Sonderregel auf die Rate von B.

Fuer einen gleichfoermigen isotropen Offset existiert ein exakter schneller Pfad: `phi <- phi - d` fuer Wachstum beziehungsweise der entsprechende negative Offset fuer Abtrag. Er benoetigt keine zeitliche Integration.

### 3.2 Fluss, Sichtbarkeit und Winkelabhaengigkeit

Der `FluxModel2D` berechnet einen nichtnegativen Ankunftsfaktor pro Frontzelle. Unterstuetzt werden unter anderem:

- Delta- beziehungsweise schmale Quellen fuer Verdampfung;
- schmale Ionenkeulen fuer RIE und Ionenstrahlaetzen;
- `cos^n`-Verteilungen fuer Sputterdeposition;
- winkelabhaengige Sputterausbeute;
- ein orientierungsunabhaengiger chemischer Sockel;
- Oberflaechenmobilitaet als Verteilung entlang der Front;
- genau eine spekulare Ionenreflexion bei streifendem Einfall;
- ein separater Rueckdepositionsfluss.

Sichtbarkeit wird durch Rueckwaertsmarschieren von der Front zur Quelle bestimmt. Die Trefferpruefung liest das feine Distanzfeld interpoliert; eine groebere Sichtbarkeitsstruktur begrenzt nur die sichere Schrittweite und soll die Geometrie nicht veraendern.

### 3.3 Erreichbarkeit und Zusammenhang

Nicht jeder isotrope Mechanismus ist ueberall wirksam. Der Kernel unterscheidet deshalb:

- leeren Raum, der von offenen Domaenenseiten erreichbar ist;
- Frontbereiche, die ein Bad oder ein isotroper Precursor erreichen kann;
- ganze Materialvorkommen, von denen wenigstens ein Teil erreichbar ist;
- Festkoerperkomponenten, die noch mit der Substratseite beziehungsweise einem Anker verbunden sind;
- eingeschlossene Hohlraeume.

Diese wenigen topologischen Praedikate tragen mehrere Prozesse. ALD stoppt nach dem Verschluss eines Hohlraums, Entwickler entfernt keine versiegelte Resisttasche, ein Clean erreicht kein eingebettetes Partikel, und Lift-off entfernt nur nach dem Aufloesen tatsaechlich freischwebende Komponenten.

### 3.4 Dynamischer Domaenenausschnitt

Vor einem Prozess kann das Ausfuehrungssystem den vertikalen Ausschnitt erweitern oder uebermaessigen Leerraum abschneiden. Verbraucht ein einzelner Prozess dennoch den verbleibenden Rand, wird er auf einem erweiterten Grid deterministisch erneut ausgefuehrt. Die laterale Breite bleibt dabei fest.

Der Mechanismus trennt die reale Probe vom betrachteten Simulationsfenster. Er verhindert viele kuenstliche Randfehler, ersetzt aber keine vollstaendige Wafergeometrie.

## 4. Prozessvertrag und Ausfuehrung

### 4.1 `ProcessStep`

Ein registrierbarer Prozess muss strukturell folgende Angaben besitzen:

- stabile, eindeutige `step_id`;
- Anzeigename und Fidelity-Stufe;
- typisiertes Parameterschema;
- benoetigte und bereitgestellte Faehigkeiten;
- `run(StepContext) -> StepResult`.

`ParamSpec` prueft Typ, Einheit, Wertebereich und Auswahlmenge. Fehlende Pflichtwerte sowie unbekannte Parameternamen sind Fehler. Dadurch faellt ein Tippfehler auf, anstatt unbemerkt den Defaultwert zu verwenden.

`StepContext` enthaelt nur den Eingabezustand, bereits validierte lokale Parameter, Materialbibliothek, Faehigkeiten, eine deterministisch gesetzte Zufallsquelle, Waferposition, lokalen Uniformitaetsfaktor und optional einen Artefaktspeicher.

`StepResult` enthaelt den neuen Zustand sowie optional die integrierte Frontbilanz, Faehigkeiten, Feldspezifikationen, Messwerte, Artefaktverweise und Logs.

### 4.2 Faehigkeiten statt fester Schrittfolgen

Das Gating basiert nicht auf „Schritt 4 muss vorher gelaufen sein“, sondern auf Eigenschaften des aktuellen Zustands. Beispiele:

- `domain`: eine Probe beziehungsweise Domaene existiert;
- `material:resist`: Resist ist vorhanden;
- `resist.exposed`: ein binaeres Belichtungsfeld ist vorhanden;
- `resist.dose`: ein kontinuierliches Dosisfeld ist vorhanden.

Damit fordert `develop.ideal` ein `exposed`-Feld und `develop.rate` ein `dose`-Feld. Unterschiedliche Fidelity-Stufen koennen nebeneinander existieren, ohne voneinander als konkrete Prozessnamen wissen zu muessen. Strukturelle Faehigkeiten werden nach jedem Commit aus der tatsaechlichen Struktur neu abgeleitet; verschwindet der Resist, verschwinden auch seine Material- und Feldfaehigkeiten.

### 4.3 Determinismus und Waferposition

Zufaellige Prozesse duerfen ausschliesslich `StepContext.rng` verwenden. Der Seed wird aus Rezept-ID, Waferposition und Schrittindex gehasht. Dasselbe Rezept an derselben Position erzeugt damit denselben Zustand; eine andere Position erhaelt einen anderen, aber ebenfalls reproduzierbaren Zufallsstrom.

Waferuniformitaet wird am Ausfuehrungsrand zu einem lokalen Skalar aufgeloest:

`rate_scale = max(0, 1 - uniformity_percent/100 * (r/150 mm)^2)`.

Der Geometriekernel kennt weder Waferkoordinaten noch eine radiale Funktion. Er simuliert pro Position einen lokalen 2D-Querschnitt. Ein Wafer-Fan besteht daher aus mehreren unabhaengigen, deterministisch materialisierten Revisionsketten.

### 4.4 Commit-Gate

Jeder Prozessausgang muss durch denselben Commit-Pfad:

1. Geaenderte Materialfelder werden im schmalen Band wieder zu Distanzfeldern normalisiert; unveraenderte Arrays werden mit der Elternrevision geteilt.
2. Materialbezogene Felder werden in neu erzeugten oder entfernten Materialzellen auf Default gesetzt.
3. Endliche Werte, Gradientenqualitaet, Materialueberlappung und Domaenenkontakt werden geprueft.
4. Falls eine Front bewegt wurde, wird die integrierte Soll-Aenderung mit der gemessenen Flaechen-/Volumenaenderung verglichen.
5. Materialvorkommen und ihre Lineage werden rekonstruiert.
6. Faehigkeiten werden aus dem Ergebnis neu abgeleitet und deklarierte Versprechen geprueft.

Invariantenverletzungen machen den Commit fehlerhaft. Eine Bilanzabweichung ist eine Warnung, weil reale Topologieaenderungen die Frontintegral-Approximation ebenfalls stoeren koennen. Das Ziel lautet: Ein numerisch oder semantisch auffaelliger Schritt bleibt sichtbar und wird nicht still akzeptiert.

### 4.5 Revision, Rezept und Run

Eine `Revision` umfasst:

- die committed `Structure`;
- Index und Elternindex;
- Prozess-ID, Anzeigename, aufgeloeste Parameter, Position und Laufzeit;
- Faehigkeiten;
- Validierungs- und Lineage-Berichte;
- Messwerte, Artefaktverweise, Logs und Domaenenaenderung.

Eine `RevisionChain` ist append-only. Beim erneuten Ausfuehren ab einer frueheren Stelle werden die spaeteren Revisionen bewusst verworfen, nicht ueberschrieben. Kleine Zusammenfassungen bleiben im Speicher; grosse Strukturen koennen in einen Store ausgelagert und bei Bedarf nachgeladen werden.

Ein `Recipe` ist die geordnete Folge von Prozess-IDs und Parametern. Ein `Run` materialisiert dieses Rezept fuer eine oder mehrere Waferpositionen. Schwere Ausgaben wie SEM-Zellbilder oder Profilometerkurven liegen nicht in der `Structure`, sondern werden als `ArtifactRef` referenziert.

## 5. Die 32 eingebauten Prozesse

Die folgende Beschreibung bezieht sich ausschliesslich auf die in `builtin_registry()` registrierten Schritte. Die nicht mehr registrierte Altimplementierung `anneal.thermal` und externe Plugins gehoeren nicht zu dieser Liste.

### 5.1 Substrat

#### `substrate.select` - Substrat auswaehlen (`ideal`)

**Vorgehen.** Der Schritt liest ein Preset und optionale Overrides, erzeugt bei Bedarf ein passendes 2D-Grid und legt mit `half_space` ein Material unterhalb der Oberflaechenhoehe an. Wafer-, Masken-, Chip- und semi-infinite-Formfaktoren werden als Substratspezifikation behandelt. Presets koppeln reale Abmessungen mit einem vorgeschlagenen Prozessfenster; explizite Domaenenparameter haben Vorrang.

**Wirkung auf das Datenmodell.** Er erzeugt die erste `Structure`, ein SDF fuer das Substratmaterial sowie Metadaten fuer Material, Formfaktor, reale Dicke, laterale Abmessungen, Oberflaechenlage, Finish, Rauheit und Preset. Er liefert `domain` und `material:<id>`.

**Simulationsabsicht.** Der Schritt trennt die reale, makroskopische Probe vom nanometergrossen Rechenausschnitt. Die planare Halbebene ist auf dem Grid exakt repraesentierbar und bildet eine reproduzierbare Referenzoberflaeche.

**Grenze.** Waferkante, Rueckseite, Kristallorientierung, Bow und reale Rauheit werden nicht geometrisch simuliert. Die Rauheit ist ein Messmetadatum; `semi_infinite` schaltet eine Durchbruchpruefung aus, weil keine reale Dicke behauptet wird.

### 5.2 Resistauftrag und Lithographie

#### `resist.spin_coat_ideal` - idealer Spin-Coat (`ideal`)

**Vorgehen.** `spin_coat()` fuellt den freien Raum bis zu einer horizontalen Ebene mit Resist. Ohne explizite Ebene liegt die Oberkante um die eingegebene Dicke ueber dem hoechsten Festkoerperpunkt.

**Datenwirkung.** Ein Resist-SDF wird ueber `add_material` hinzugefuegt; bestehende Materialien werden nicht ueberlappt. Der neue Film besitzt eine exakt ebene Oberseite.

**Simulationsabsicht.** Der Schritt stellt die uebliche ideale Annahme „planarer Resist mit vorgegebener Dicke“ bereit und ist fuer reproduzierbare Basisrezepte geeignet.

**Grenze.** Drehzahl, Viskositaet, Zeit, Topographiefluss, Randwulst und Entnetzung spielen keine Rolle.

#### `resist.spin_coat` - Spin-Coat mit Levelling (`didactic`)

**Vorgehen.** Die nominale Dicke wird aus der im Resist gespeicherten Messkurve ueber die Drehzahl bestimmt; zwischen Messpunkten wird log-log interpoliert, ausserhalb des Bereichs geklemmt. Aus der oberen Probenkontur wird per diskreter Kosinustransformation ein konservativ geglaettetes Profil berechnet. Der Filter `exp(-(k * thickness)^4)` daempft kurze Wellen staerker als lange. Nach dem Clipping gegen die urspruengliche Topographie wird die Hoehe so verschoben, dass das Filmvolumen erhalten bleibt. Nur von oben erreichbarer Leerraum kann gefuellt werden.

**Datenwirkung.** Ein Resist-SDF mit nicht notwendig ebener Oberseite wird angelegt. Messwerte enthalten Dicke, Drehzahl und die verwendete Levelling-Laenge.

**Simulationsabsicht.** Das Modell zeigt, dass schmale Strukturen staerker nivelliert werden als breite und dass Spitzen duenn beschichtet sein koennen, ohne einen vollstaendigen Fluidfilmloeser einzufuehren. Versiegelte Hohlraeume bleiben leer.

**Grenze.** Spin-Zeit wird dokumentiert, beeinflusst die nur drehzahlabhaengige Messkurve aber nicht. Es gibt keine Viskositaets-, Loesungsmittel-, Kontaktwinkel-, Oberflachenenergie- oder Dewetting-Dynamik.

#### `litho.expose_ideal` - ideale Belichtung (`ideal`)

**Vorgehen.** Ein prozedurales Fenster- oder Gittermuster wird als SDF erzeugt. Alle Zellen innerhalb des offenen Musters werden binaer als belichtet markiert. Mehrfachbelichtungen werden logisch ODER-verknuepft.

**Datenwirkung.** Geometrie bleibt unveraendert; angelegt oder aktualisiert wird das materialbezogene `int8`-Feld `exposed`. Der Schritt liefert die Faehigkeit `<material>.exposed`.

**Simulationsabsicht.** Er isoliert die reine Maskenlogik ohne Optik und stellt den Grenzfall unendlichen Resistskontrasts bereit.

**Grenze.** Keine Dosis, Beugung, Fokuslage, Tiefenabsorption oder Diffusion. Die OR-Verknuepfung merkt nicht, wie oft eine Zelle belichtet wurde.

#### `litho.expose_dose` - Dosisbelichtung (`didactic`)

**Vorgehen.** Das binaere Maskenmuster wird mit einem Gaussfilter der Breite `blur` in ein Luftbild ueberfuehrt, auf die Spitzendosis skaliert und innerhalb des Resists nach Beer-Lambert mit der aus der Materialbibliothek gelesenen Absorption abgeschwaecht. Die Tiefe wird aus der aktuellen Resistgeometrie bestimmt. Mehrere Belichtungen addieren ihre Energie.

**Datenwirkung.** Geometrie bleibt unveraendert; das materialbezogene `float32`-Feld `dose` in mJ/cm2 wird angelegt oder additiv aktualisiert. Der Schritt liefert `<material>.dose`.

**Simulationsabsicht.** Er erzeugt ein kontinuierliches latentes Bild, aus dem Unterschnitt, Fuss und geneigte Entwicklungsprofile qualitativ entstehen koennen.

**Grenze.** Der Gauss-Blur ist kein elektromagnetischer Projektionsloeser. Wellenlaenge, NA, partielle Kohaerenz, Fokus, Resistchemie und Reflexionsschichten werden nicht explizit gerechnet.

#### `litho.threshold_dose` - Dosis in binaeres Bild umwandeln (`ideal`)

**Vorgehen.** Das vorhandene Dosisfeld wird an einem Schwellwert verglichen; oberhalb wird `exposed = 1`, darunter `0` gesetzt.

**Datenwirkung.** Das Dosisfeld bleibt erhalten, zusaetzlich entsteht `exposed`; die Faehigkeit `<material>.exposed` wird geliefert.

**Simulationsabsicht.** Der Schritt macht einen Informationsverlust explizit und erlaubt bewusst den Uebergang von der didaktischen zur idealen Entwicklung.

**Grenze.** Aus einem binaeren Bild kann umgekehrt keine urspruengliche Dosis rekonstruiert werden; daher existiert kein Upgrade-Adapter.

#### `develop.ideal` - ideale Entwicklung (`ideal`)

**Vorgehen.** Je nach positiver oder negativer Tonalitaet wird `Resist AND exposed` beziehungsweise `Resist AND NOT exposed` als loesliche Region gebildet. Nur zusammenhaengende loesliche Bereiche, die der Entwickler von einer offenen Domaenenseite erreicht, werden in einer Mengenoperation entfernt.

**Datenwirkung.** Das Resist-SDF wird ausgeschnitten oder bei vollstaendiger Entfernung geloescht. Das Commit-Gate setzt beziehungsweise entfernt zugehoerige Felder und Faehigkeiten.

**Simulationsabsicht.** Es modelliert Entwicklung als Grenzfall ohne Zeit und mit unendlichem Kontrast, behaelt aber die wichtige Erreichbarkeitsbedingung bei.

**Grenze.** Keine partielle Entwicklung, Dunkelabtrag, Quellung oder lokale Rate.

#### `develop.rate` - dosisabhaengige Entwicklung (`didactic`)

**Vorgehen.** Das Resistmaterial liefert eine `DevelopModel`-Kurve. Daraus wird pro Zelle eine Rate zwischen Dunkel- und Klar-Rate bestimmt; der Kontrast steuert die Steilheit um die Clearing-Dosis. Die normalisierte Ratenkarte wird mit dem Erreichbarkeits-Gate multipliziert und die Front fuer die angegebene Zeit advectiert.

**Datenwirkung.** Das Resist-SDF zieht sich lokal verschieden schnell zurueck. Das Dosisfeld bleibt als latentes Feld erhalten, wird aber durch die Feldscoping-Regel dort auf Default gesetzt, wo Resist verschwindet.

**Simulationsabsicht.** Der Schritt macht aus Dosis und Resistkontrast ein Profil. Unterbelichtung, Wandneigung, Resistfuss und Filmduennung bei langer Entwicklung werden qualitativ sichtbar.

**Grenze.** Keine Entwicklerdiffusion, Quellung, Reaktionsprodukte oder temperaturabhaengige Kinetik; die lokale Rate ist eine didaktische Materialkurve.

### 5.3 Abscheidung

#### `deposit.evaporate` - Verdampfung (`didactic`)

**Vorgehen.** Eine Deltaquelle beziehungsweise schmale Winkelverteilung wird von der aktuellen Front aus auf Sichtbarkeit geprueft. Die angeforderte Dicke wird ueber die Rate in eine Laufzeit umgerechnet; die Front waechst mit `rate * arrival`. Winkel und Divergenz formen die Quelle. Der radiale Uniformitaetsfaktor skaliert die lokale Dicke.

**Datenwirkung.** Das SDF des Zielmaterials wird neu angelegt oder erweitert. Neu gewachsener Festkoerper wird diesem Material zugeordnet; andere Materialgrenzen bleiben erhalten.

**Simulationsabsicht.** Gerichteter Stofftransport laesst vertikale Seitenwaende bei idealem Normaleinfall weitgehend unbeschichtet. Dadurch entstehen getrennte Metallbereiche, die einen sauberen Lift-off ermoeglichen.

**Grenze.** Keine Quellgeometrie, Gasstreuung, Sticking-Abhaengigkeit, Keimbildung, Temperatur oder Mehrfachstreuung. Ankommende Atome haften im Modell.

#### `deposit.sputter` - Sputterdeposition mit Solldicke (`didactic`)

**Vorgehen.** Eine breite `cos^n`-Quelle wird sichtbarkeitsabhaengig auf die Front projiziert. Optional verteilt eine Mobilitaetslaenge den ankommenden Stoff entlang der Oberflaeche. Die eingegebene Dicke ist die Dicke auf einer offenen, normal orientierten Referenzflaeche.

**Datenwirkung.** Das Zielmaterial waechst auch an sichtbaren Seitenwaenden; je nach Geometrie und Mobilitaet kann ein zusammenhaengender Film entstehen.

**Simulationsabsicht.** Der Vergleich mit Verdampfung zeigt, wie eine breitere Winkelverteilung Step Coverage und Lift-off-Zaunbildung beeinflusst.

**Grenze.** `cos^n` und eine einzelne Mobilitaetslaenge ersetzen keine Kammer-, Plasma- oder atomistische Wachstumssimulation.

#### `deposit.conformal_offset` - geometrischer konformer Offset (`ideal`)

**Vorgehen.** Die gesamte Festkoerperfront wird in einer exakten SDF-Offsetoperation um die vorgegebene Dicke nach aussen verschoben.

**Datenwirkung.** Eine gleich dicke neue Schale wird dem Zielmaterial zugeordnet. Dosisaufteilung ist numerisch bit-identisch, weil keine Zeitschritte erforderlich sind.

**Simulationsabsicht.** Der Schritt beantwortet exakt die geometrische Frage „Wie sieht ein konstanter Oberflaechenoffset aus?“ und dient als Referenz fuer konformes Wachstum.

**Grenze.** Keine Erreichbarkeit. Das Material waechst auch in einem bereits versiegelten Hohlraum weiter und kann ihn verschwinden lassen. Genau deshalb ist dies nicht als reales ALD-Modell bezeichnet.

#### `deposit.ald` - Atomic Layer Deposition (`didactic`)

**Vorgehen.** Isotropes konformes Wachstum wird mit einem dynamischen `ReachableFront`-Gate kombiniert. Nach jedem relevanten Frontfortschritt wird geprueft, welche Oberflaeche der Precursor noch aus offenem Raum erreicht. Schliesst sich eine Oeffnung, stoppt das Wachstum an der eingeschlossenen Innenflaeche.

**Datenwirkung.** Das Zielmaterial waechst gleichmaessig auf allen erreichbaren Flaechen; versiegelte Void-Geometrie bleibt erhalten.

**Simulationsabsicht.** Das Modell trennt Konformitaet von Erreichbarkeit und macht Pinch-off sowie eingeschlossene Hohlraeume ohne Sonderregel sichtbar.

**Grenze.** Keine Zyklenzahl, Sattigungskinetik, Precursor-Depletion, Reaktionswahrscheinlichkeit oder Aspect-Ratio-Transportgleichung. Erreichbar bedeutet hier voll versorgt.

#### `deposit.sputter_rate` - zeitgesteuerte Sputterdeposition (`didactic`)

**Vorgehen.** Geometrisch wird dasselbe Modell wie bei `deposit.sputter` verwendet. Statt einer Solldicke gibt der Benutzer die Dauer vor; die Materialbibliothek liefert die Prozessrate `sputter_deposit`, und `thickness = local_rate * duration` wird zum Ergebnis. Fehlt eine positive Rate, verweigert der Prozess die Ausfuehrung.

**Datenwirkung.** Wie bei Sputterdeposition; Messwerte dokumentieren Dauer, nominale und lokale Rate, Uniformitaetsfaktor und resultierende Dicke.

**Simulationsabsicht.** Der Schritt entspricht der Laborlogik „Target und Zeit einstellen, Dicke erhalten“ und macht falsche Materialraten direkt als falsche Filmdicke sichtbar.

**Grenze.** Zeitliche Targetkonditionierung, Leistungsrampe, Druck und Anlagenzustand fehlen; die Rate ist ein einzelner Bibliothekswert.

### 5.4 Aetzen

Alle Aetzschritte beziehen die skalare Rate eines offenen, normal orientierten Materialbereichs aus der Materialbibliothek. Richtungsabhaengigkeit wird nicht als zweite laterale Rate gespeichert, sondern durch den Flussfaktor erzeugt. Eine Rate von null wirkt als Aetzstopp beziehungsweise Hartmaske.

#### `etch.wet` - allgemeines nasschemisches Aetzen (`didactic`)

**Vorgehen.** Fuer jedes Material wird die Bibliotheksrate `wet_etch` gelesen. Es gibt kein Richtungsflussmodell; die Geschwindigkeit ist in alle Richtungen gleich. Ein Erreichbarkeits-Gate verhindert Aetzen in versiegelten Bereichen. Dauer, globaler Skalierungsfaktor und radiale Uniformitaet bestimmen die lokale Abtragsstrecke.

**Datenwirkung.** Alle erreichbaren Materialfronten ziehen sich gemaess ihrer jeweiligen Rate zurueck. Materialien mit Rate null bleiben stehen.

**Simulationsabsicht.** Unter einer Maske entsteht Unteraetzung in derselben Groessenordnung wie die Aetztiefe. Der Quotient lateral/vertikal ergibt sich aus isotroper Bewegung, nicht aus einer programmierten Unteraetzungsregel.

**Grenze.** Keine Konzentrations-, Temperatur-, Kristallorientierungs-, Reaktionsprodukt- oder Transportlimitierung.

#### `etch.rie` - generisches Reactive Ion Etching (`didactic`)

**Vorgehen.** Eine schmale, einstellbare Ionenkeule wird mit einem orientierungsunabhaengigen chemischen Sockel addiert und anschliessend mit Erreichbarkeit gegated. Materialraten kommen aus `dry_etch`; Winkel, Divergenz, chemischer Anteil, Dauer, Skalierung und Uniformitaet sind Parameter.

**Datenwirkung.** Die Front zieht sich bevorzugt in Strahlrichtung zurueck, erhaelt aber durch den chemischen Anteil auch lateralen Abtrag.

**Simulationsabsicht.** Der Parameter `chemical_fraction` macht den Uebergang von nahezu physikalisch gerichtetem Abtrag zu unteraetzendem RIE unmittelbar untersuchbar.

**Grenze.** Ionenergie, Bias, Druck, Radikaldichte, Passivierung und Laden werden auf Keulenform, Rate und Sockel reduziert.

#### `etch.ion_beam` - Ionenstrahlaetzen (`didactic`)

**Vorgehen.** Eine schmale Ionenverteilung trifft sichtbare Frontbereiche. Die Materialbibliothek liefert neben der Normalrate eine winkelabhaengige Sputterausbeute. Bei streifendem Einfall kann genau eine spekulare Ionenreflexion zusaetzlichen Abtrag an einer zweiten Flaeche verursachen. Optional wird ein Anteil des entfernten Materials als statischer Rueckdepositionsfluss ein zweites Mal advectiert. Die Rueckdeposition wird pro Quellmaterial getrennt, sodass die Materialidentitaet erhalten bleibt.

**Datenwirkung.** Material wird gerichtet entfernt; bei aktivierter Rueckdeposition werden SDFs derselben Quellmaterialien an anderen sichtbaren Stellen wieder aufgebaut.

**Simulationsabsicht.** Das Modell zeigt geraden Seitenwandabtrag, winkelabhaengige Facettierung, Trenching durch eine Reflexion und materialtreue Rueckdeposition.

**Grenze.** Nur ein reflektierter Bounce und ein nachgelagerter, nicht gekoppelt iterierter Rueckdepositionspass. Keine Energie- und Ladungsverteilung, Kaskadenphysik oder Mehrfachstreuung.

#### `etch.icp_fluorine` - ICP in Fluorchemie (`didactic`)

**Vorgehen.** Verwendet `directional_etch()` mit der Rate `icp_fluorine`, festem Normaleinfall und 3 Grad Divergenz. Der chemische Anteil ist standardmaessig null, kann aber zu Lehrzwecken erhoeht werden. Dauer, Ratenskalierung und Plasmuniformitaet wirken wie bei anderen zeitabhaengigen Aetzungen.

**Datenwirkung.** Materialien werden mit ihren fluorchemiespezifischen Raten bevorzugt vertikal entfernt; die Selektivitaet folgt ausschliesslich der Bibliothek.

**Simulationsabsicht.** Der Prozess bildet die als „vertikal“ angegebene Tabellenchemie ab und zeigt, warum eine langsamer geaetzte Chrommaske einen Resist ersetzen kann.

**Grenze.** Das Tabellenmodell besitzt keine separat gemessene laterale Rate. Der zuschaltbare chemische Anteil ist eine didaktische Variation, keine kalibrierte ICP-Chemie.

#### `etch.rie_chlorine` - Chlor-RIE (`didactic`)

**Vorgehen.** Liest die materialspezifische Rate `rie_chlorine` und verwendet bewusst kein Winkelmodell, weil die zugrunde liegende Prozesstabelle horizontalen und vertikalen Abtrag gleichsetzt. Erreichbarkeit, Zeit, Skalierung und Uniformitaet bleiben aktiv.

**Datenwirkung.** Erreichbare Fronten werden isotrop gemaess Chlor-Selektivitaet entfernt; im ausgelieferten Satz wird Chrom schnell, Resist langsamer und Quarz nicht angegriffen.

**Simulationsabsicht.** Typischer Einsatz ist das Uebertragen eines Resistmusters in eine Chrommaske und das Beobachten isotroper Unteraetzung.

**Grenze.** Die Bezeichnung RIE bedeutet hier nicht automatisch gerichteten Abtrag; das Modell folgt bewusst der vorliegenden Rate-Tabelle. Diese Annahme sollte fachlich evaluiert werden.

#### `etch.rie_oxygen` - Sauerstoff-RIE / Plasma-Strip (`didactic`)

**Vorgehen.** Wie Chlor-RIE als isotroper, erreichbarkeitsgegater Prozess, jedoch mit `rie_oxygen`-Raten.

**Datenwirkung.** Polymer/Resist wird entfernt; Materialien mit Nullrate wie Chrom und Quarz bleiben im didaktischen Datensatz erhalten.

**Simulationsabsicht.** Modelliert Descum beziehungsweise Resiststrip und macht versiegelte, nicht erreichbare Polymerbereiche sichtbar.

**Grenze.** Keine Aschechemie, Oberflaechenaktivierung oder temperaturabhaengige Oxidation.

#### `etch.wet_cr` - Chrom-Nassatz (`didactic`)

**Vorgehen.** Isotroper, erreichbarkeitsgegater Abtrag mit der spezifischen Bibliotheksspalte `wet_etch_cr`.

**Datenwirkung.** Chrom wird im ausgelieferten Datensatz selektiv entfernt; andere genannte Materialien haben Rate null.

**Simulationsabsicht.** Zeigt eine einfache hochselektive Nasschemie und die Unteraetzung unter einer Resistmaske.

**Grenze.** Eine einzige konstante Rate ersetzt Badalterung, Konzentration, Temperatur und Abtransport.

#### `etch.wet_oxide` - gepufferter Oxid-Nassatz (`didactic`)

**Vorgehen.** Isotroper, erreichbarkeitsgegater Abtrag mit `wet_etch_oxide`-Raten.

**Datenwirkung.** Oxid und Quarz werden schnell, Resist langsam, Silizium und Chrom im didaktischen Satz gar nicht entfernt.

**Simulationsabsicht.** Der Vergleich mit `etch.icp_fluorine` trennt Materialselektivitaet von Richtungscharakter: Ein aehnlicher Tiefenabtrag kann ein vollstaendig anderes Seitenwandprofil erzeugen.

**Grenze.** Keine lokale HF-Verarmung, Blasenbildung, Oberflaechenzustands- oder Temperaturabhaengigkeit.

### 5.5 Aufloesen, Strip und Lift-off

#### `strip.dissolve` - ideales Aufloesen (`ideal`)

**Vorgehen.** Fuer das benannte Material werden zusammenhaengende Vorkommen ermittelt. Jedes Vorkommen, das der Solvent von aussen erreicht, wird vollstaendig in einer Mengenoperation entfernt.

**Datenwirkung.** Das entsprechende Material-SDF wird ausgeschnitten oder geloescht; Messwert ist die entfernte Querschnittsflaeche.

**Simulationsabsicht.** Ein erreichter Resistblock wird als Ganzes geloest, waehrend eine versiegelte Tasche bleibt. Das ist die ideale, zeitlose Version eines Loesevorgangs.

**Grenze.** Die Materialbenennung selbst behauptet hier Loeslichkeit; eine Rate oder reale Solventchemie wird nicht gelesen.

#### `strip.rate` - zeitabhaengiges Aufloesen (`didactic`)

**Vorgehen.** Fuer das angegebene Loesemittel werden pro Material Loeseraten aus der Bibliothek gebildet. Die erreichbare Front zieht sich fuer die Prozessdauer zurueck; unloesliche Materialien erhalten Rate null.

**Datenwirkung.** Teilweises oder vollstaendiges Aufloesen wird als SDF-Frontbewegung dargestellt.

**Simulationsabsicht.** Der zeitliche Verlauf und der Unterschied zwischen normalem und hartgebackenem Resist koennen beobachtet werden.

**Grenze.** Keine Quellung, Rissbildung, mechanisches Abheben oder Loesemitteltransport in engen Spalten.

#### `strip.lift_off` - Lift-off (`ideal`)

**Vorgehen.** Zuerst wird der erreichbare Opferresist ideal aufgeloest. Danach werden alle Festkoerperkomponenten entfernt, die nicht mehr mit der Substratseite beziehungsweise dem Anker verbunden sind.

**Datenwirkung.** Resist verschwindet soweit erreichbar; anschliessend verschwinden beliebige nicht gestuetzte Materialien. Substratverbundene Metallbereiche und Seitenwandzaeune bleiben.

**Simulationsabsicht.** „Welches Metall hebt ab?“ wird als Zusammenhangsfrage modelliert, nicht ueber eine Sonderrolle des Metalls. Dadurch ergeben sich unterschiedliche Resultate fuer Verdampfung, Sputtern und versiegelnde ALD aus der vorher entstandenen Geometrie.

**Grenze.** Keine mechanische Spannung, Ultraschallwirkung, Quellung oder Fragmentdynamik. Ein einziger Zellkontakt genuegt topologisch als Stuetzung.

#### `strip.remove_unsupported` - ungestuetzte Komponenten entfernen (`ideal`)

**Vorgehen.** Connected Components des gesamten Festkoerpers werden bestimmt; Komponenten ohne Verbindung zur Substratseite werden entfernt, ohne vorher etwas aufzuloesen.

**Datenwirkung.** Beliebige freischwebende Materialbereiche werden aus ihren SDFs entfernt.

**Simulationsabsicht.** Dieser Schritt isoliert die zweite Haelfte des Lift-off und macht die im Modell verwendete Definition von mechanischer Stuetzung sichtbar.

**Grenze.** Binaere Topologie statt realer Haftkraft, Kontaktflaeche, Spannung oder Bruchmechanik.

### 5.6 Kontamination und Reinigung

#### `particle.seed` - Partikelkontamination (`ideal`, stochastisch und reproduzierbar)

**Vorgehen.** Aus `StepContext.rng` werden laterale Positionen und gegebenenfalls Radienstreuungen gezogen. Fuer jede Position wird die oberste Festkoerperzelle bestimmt und ein Kreis so platziert, dass er auf der Oberflaeche ruht. Ueberlappende Kreise werden vor dem Hinzufuegen vereinigt; Spalten ohne Festkoerper werden uebersprungen.

**Datenwirkung.** Ein SDF des Kontaminationsmaterials wird hinzugefuegt. Gemessen werden gelandete Partikel und daraus tatsaechlich entstandene zusammenhaengende Vorkommen.

**Simulationsabsicht.** Der Schritt erzeugt reproduzierbare Defekte an physikalisch sinnvollen Oberflaechenpositionen und bereitet Mikromaskierungsversuche vor.

**Grenze.** Die laterale Verteilung und Radienstreuung sind uniform; Transport, Adhaesion, Partikelform, Ladung und Groessenverteilung realer Reinraeume fehlen. Im 2D-Querschnitt ist ein „Partikel“ ein Kreis, nicht eine 3D-Kugel.

#### `clean.particles` - Partikelreinigung (`ideal`)

**Vorgehen.** Zusammenhaengende Vorkommen des Kontaminationsmaterials werden auf Erreichbarkeit geprueft. Erreichbare Vorkommen werden ganz entfernt; eingebettete bleiben bestehen und werden als mikromaskiert gezaehlt.

**Datenwirkung.** Das Partikel-SDF wird teilweise oder vollstaendig entfernt. Messwerte nennen entfernte Vorkommen, verbleibende Vorkommen und deren Flaeche.

**Simulationsabsicht.** Reinigung und Mikromaskierung werden als Zugangsproblem dargestellt: Ein vor der Abscheidung eingeschlossenes Partikel ist nachher chemisch nicht einfach „wegzureinigen“.

**Grenze.** Keine Reinigungschemie, Scherwirkung, Megasonic-Kraft oder Haftenergie. Erreichbar bedeutet im idealen Schritt entfernbar.

### 5.7 Inspektion

Inspektionsschritte geben exakt dasselbe `Structure`-Objekt zurueck. Sie erzeugen eine Revision, damit Messung und betrachteter Zustand in der Prozesskette zusammenbleiben, bewegen aber keine Front.

#### `inspect.sem` - SEM-Querschnitt (`ideal`)

**Vorgehen.** Fuer ein ausgewaehltes Material oder den gesamten Stack werden zusammenhaengende Bereiche sowie Bounding-Box-Breite und -Hoehe bestimmt. Wenn ein Artefaktspeicher vorhanden ist, wird das exklusive Material-Zellbild abgelegt.

**Datenwirkung.** Keine Aenderung an Geometrie oder Feldern; nur Messwerte, Logs und optional ein Bild-Artefaktverweis.

**Simulationsabsicht.** Es bindet eine topologische Querschnittsinspektion an eine konkrete Revision und erlaubt Folgen wie „aetzen - messen - weiter aetzen - erneut messen“.

**Grenze.** Kein simuliertes Elektronenbild: keine Kantenaufhellung, Materialkontrastphysik, Aufladung, Tilt, Rauschen oder FIB-Schnittschaedigung. Das Artefakt ist eine Labelkarte der Modellgeometrie.

#### `inspect.profilometer` - Profilometer (`ideal`)

**Vorgehen.** Zunaechst wird pro lateraler Spalte die oberste Festkoerperhoehe ermittelt. Fuer eine endliche Spitzenradius wird ein kreisfoermiger Tastkopf als graumorphologische Dilatation ueber das Profil gerollt. Aus der resultierenden Spur folgen Stufenhoehe, mittlere Hoehe und arithmetische Rauheit. Die als Substratmetadatum gespeicherte Rauheit wird deterministisch quadratisch addiert.

**Datenwirkung.** Keine Zustandsaenderung; Messwerte und optional eine zweizeilige Tabelle aus x-Position und gemessener Hoehe.

**Simulationsabsicht.** Der Schritt zeigt einen realen Instrumenteneffekt: Eine breite Spitze erreicht einen schmalen Graben nicht vollstaendig und misst ihn zu flach; scharfe Kanten erscheinen gerundet.

**Grenze.** Keine Messkraft, Spitzendeformation, dynamische Abtastung, Rauschen oder 2D-Flaechenkartierung. Die Rauheitsaddition ist deterministisch und nicht als zufaellige Oberflaeche gezeichnet.

### 5.8 Thermische Prozesse

Alle drei Bake-Schritte addieren ein globales Feld

`thermal_budget += (temperature_C + 273.15) * duration_s`

in K*s. Dieses Feld speichert eine einfache kumulierte Temperatur-Zeit-Exposition, ist aber noch kein Reaktionskinetikmodell.

#### `bake.soft` - Soft Bake (`didactic`)

**Vorgehen.** Addiert ausschliesslich das globale thermische Budget.

**Datenwirkung.** Geometrie, Materialidentitaeten und alle materialbezogenen Felder bleiben bit-identisch; zusaetzlich entsteht oder waechst `thermal_budget` und die freie Faehigkeit `annealed`.

**Simulationsabsicht.** Der Schritt besitzt eine explizite Feldregel: Ein Soft Bake darf in diesem Modell ein vorhandenes latentes Bild nicht heimlich veraendern. Spaetere Modelle koennen den dokumentierten thermischen Verlauf auswerten.

**Grenze.** Keine Loesungsmittelverdampfung, Verdichtung, Reflow, Spannungs- oder Temperaturfeldsimulation.

#### `bake.post_exposure` - Post-Exposure Bake (`didactic`)

**Vorgehen.** Nach dem thermischen Budget wird ein vorhandenes `dose`-Feld innerhalb des gewaehlten Resists mit einem Gaussfilter der expliziten Diffusionslaenge geglaettet. Randverluste werden durch normierte Gewichte korrigiert und das Integral der Dosis im Resist anschliessend wiederhergestellt. Ein binaeres `exposed`-Feld bleibt unangetastet. Fehlt ein Dosisfeld, wird keines erfunden.

**Datenwirkung.** Kontinuierliche Dosis wird raeumlich verteilt, Feldidentitaet und Gesamtintegral bleiben erhalten; Geometrie bleibt gleich.

**Simulationsabsicht.** Der Schritt zeigt, wie ein thermischer Prozess ein latentes Bild verbreitert, ohne Belichtung oder Materialabtrag zu sein.

**Grenze.** Die Diffusionslaenge ist direkt eingegeben. Temperatur und Zeit werden nicht ueber eine kalibrierte Arrhenius- oder chemisch verstaerkte Resistkinetik in sie umgerechnet.

#### `bake.hard` - Hard Bake (`didactic`)

**Vorgehen.** Zielmaterial und Aktivierungstemperatur werden aus dem `HardBakeModel` des Quellmaterials gelesen. Unterhalb der Schwelle wird nur das thermische Budget addiert. Ab der Schwelle wird dasselbe SDF ohne Geometriebewegung unter der Ziel-MaterialId weitergefuehrt; existiert das Ziel bereits, werden die Geometrien vereinigt. Ein fehlendes Zielmaterial fuehrt vor dem Ergebnis zu einem Fehler.

**Datenwirkung.** Die Materialidentitaet kann beispielsweise von `resist` zu `resist_hardbaked` wechseln. Quellmaterialbezogene Felder und Faehigkeiten verschwinden gemaess Commit-Regel; alle spaeteren Raten und Loeslichkeitseigenschaften stammen aus dem neuen Materialtyp.

**Simulationsabsicht.** Das Modell macht eine irreversible Aenderung des nachfolgenden Prozessverhaltens sichtbar, ohne diese als blosses Flag auf demselben Material zu verstecken.

**Grenze.** Die Umwandlung ist eine harte Temperaturschwelle und gilt sofort fuer das gesamte Material. Dauerabhaengige Reaktionskinetik, Gradienten, Reflow, Vernetzungsgrad und Schrumpfung fehlen.

## 6. Was das Modell gut lehrbar macht

1. **Eine gemeinsame Zustandsrepraesentation.** Alle Prozesse arbeiten auf derselben `Structure`. Studierende muessen nicht fuer jeden Prozess ein inkompatibles Geometriemodell lernen.
2. **Mechanismen statt Ergebnis-Skripte.** Unteraetzung, Lift-off, Pinch-off, Mikromaskierung und Messspitzenfehler entstehen aus wiederverwendbaren Operationen und Praedikaten.
3. **Explizite Fidelity-Grenzen.** Ideal und didaktisch sind unterschiedliche Prozessschritte. Informationsverlust, etwa `dose -> exposed`, ist sichtbar und absichtlich.
4. **Reproduzierbarkeit.** Rezept, Position, Schrittindex, Materialdateien und Implementierungsdigest definieren einen reproduzierbaren Lauf. Stochastik ist kontrolliert.
5. **Revisionen und Diagnose.** Jede Zwischenstufe kann betrachtet, gemessen, gespeichert und mit Validierungsbefunden versehen werden.
6. **Aenderbare Materialdaten.** Studierende koennen Raten oder Materialmodelle variieren, ohne den Geometriekernel umzuschreiben, und die Folgen im gesamten Prozessfluss beobachten.

## 7. Wichtige Grenzen fuer eine fachliche Bewertung

- Das aktive Modell ist ein **2D-Querschnitt**. Es kann keine echte Top-down-Struktur, keine laterale 3D-Konnektivitaet und keinen FIB-Schnitt in einer zweiten Richtung vorhersagen.
- Viele Raten sind didaktische oder tabellarische Konstanten, keine maschinenspezifisch kalibrierten Funktionen von Temperatur, Druck, Leistung und Chemie.
- Der Level-Set-Loeser ist erster Ordnung. Die Reinitialisierung und das Commit-Gate kontrollieren Fehler, beseitigen aber nicht die Aufloesungsgrenze.
- Unterhalb einer Zelle sind Geometrieaussagen nicht belastbar. Das Programm warnt, kann die Physik aber nicht ersetzen.
- Erreichbarkeit ist eine topologische Naeherung. Konzentrationsabfall, Knudsen-Transport, Reaktionswahrscheinlichkeit und Aspect-Ratio-Dependent Etching sind nicht allgemein modelliert.
- Mechanik ist fast ausschliesslich Zusammenhang: keine Haftung, Spannung, Biegung, Bruch- oder Quellmechanik.
- Thermische Modelle besitzen kein Temperaturfeld und nur sehr begrenzte Kinetik.
- SEM und Profilometer sind abgeleitete virtuelle Messungen, keine vollstaendigen Instrumentensimulatoren.
- Das globale `thermal_budget` ist eine dokumentierte kumulierte Groesse, keine universell physikalisch aussagekraeftige Prozessdosis.
- Die automatische Domaenenanpassung betrifft die Stapelrichtung; ein zu schmal gewaehlter lateraler Ausschnitt bleibt eine Modellierungsentscheidung.

Diese Grenzen sind fuer ein Lernwerkzeug nicht nur Nachteile. Sie koennen als explizite Aufgabenstellung dienen: Welche Vereinfachung ist fuer welche Lehrfrage noch sinnvoll, und an welcher Stelle erzeugt sie eine falsche Schlussfolgerung?

## 8. Vorschlaege fuer studentische Aufgaben und Feedback

### A. Modellverstaendnis ohne Programmierung

- Dasselbe Maskenprofil mit `etch.wet`, `etch.rie` und `etch.ion_beam` bearbeiten; Unteraetzung, Tiefe und Seitenwandform vergleichen und mechanistisch begruenden.
- Verdampfung, Sputtern, geometrischen Offset und ALD auf einer re-entranten Struktur vergleichen. Vorher eine Hypothese zu Step Coverage, Pinch-off und Lift-off formulieren.
- Ideale und dosisabhaengige Lithographie mit unterschiedlichen Blur-, Dosis- und Kontrastwerten vergleichen. Diskutieren, welche Information beim Threshold-Schritt verloren geht.
- Profilometer-Spitzenradius variieren und die gemessene mit der dargestellten Grabenhoehe vergleichen.
- Ein Partikel vor und nach einer Beschichtung reinigen und Mikromaskierung erklaeren.

### B. Daten- und Kalibrierungsaufgaben

- Herkunft und Plausibilitaet einer Materialdatei pruefen; Einheiten und Prozessklassen dokumentieren.
- Eine Spin-Kurve aus Messpunkten einpflegen und Interpolation, Clamp-Verhalten und Unsicherheit bewerten.
- Ein Prozessratenverhaeltnis so kalibrieren, dass eine vorgegebene Selektivitaet erreicht wird; anschliessend pruefen, ob dieselben Werte in einem zweiten Geometrieszenario tragfaehig bleiben.
- Sensitivitaetsanalyse fuer Zellabstand, Prozesszeit, Divergenz und chemischen Anteil durchfuehren.

### C. Programmier- und Modellierungsaufgaben

- Einen neuen `ProcessStep` als Plugin implementieren und seinen Parameter-, Faehigkeits- und Determinismusvertrag testen.
- Ein neues virtuelles Messgeraet implementieren, das die `Structure` nicht veraendert und seine systematische Messabweichung explizit modelliert.
- Ein alternatives Entwicklungsmodell oder eine ARDE-Erweiterung implementieren und gegen den bestehenden didaktischen Prozess vergleichen.
- Property-basierte Tests fuer Massenerhaltung, Materialdisjunktheit, Dosisintegral oder Determinismus entwerfen.
- Den Einfluss des ersten Ordnung Upwind-Schemas durch Grid-Konvergenz untersuchen und eine Fehlerabschaetzung formulieren.

### D. Geeignete Evaluationsfragen fuer den Professor

- Verstehen Studierende nach der Nutzung besser den Unterschied zwischen Materialselektivitaet und Richtungscharakter eines Prozesses?
- Werden Idealmodell, didaktisches Modell und reale Vorhersage klar genug auseinandergehalten?
- Fuehren sichtbare Zwischenrevisionen zu besseren Prozesshypothesen als ein reines Endbild?
- Sind Materialdaten und Modellannahmen ausreichend nachvollziehbar, um falsche Sicherheit zu vermeiden?
- Welche aktuell fehlende Physik fuehrt in typischen Lehrversuchen zuerst zu einer fachlich falschen Aussage?
- Ist die Komplexitaet der Parameter fuer Einsteiger angemessen, und welche Parameter sollten erst in fortgeschrittenen Aufgaben erscheinen?
- Welche Mess- oder Laboraufgabe laesst sich sinnvoll mit einer Vorhersage im Tool und einer anschliessenden realen Messung koppeln?

## 9. Empfohlener Bewertungsrahmen

Fuer eine Erprobung mit Studierenden bietet sich an, nicht nur die Bedienbarkeit abzufragen, sondern vier getrennte Dimensionen zu bewerten:

| Dimension | Beispielindikator |
|---|---|
| Fachliches Lernen | Kann der beobachtete Profilunterschied mit dem richtigen Mechanismus erklaert werden? |
| Modellkritik | Erkennt der Student, welche Aussage das Modell nicht tragen kann? |
| Reproduzierbarkeit | Kann ein Ergebnis aus Rezept, Materialdaten und Revision nachvollzogen werden? |
| Entwicklungsnutzen | Fuehrt Feedback zu einer priorisierbaren Modell-, Daten- oder UI-Aenderung? |

Besonders aussagekraeftig waere ein Pre-/Post-Design: Zuerst prognostizieren Studierende Ergebnisse mehrerer Prozessvarianten ohne Tool, danach untersuchen sie dieselben Varianten im Tool und begruenden Abweichungen. Damit wird nicht nur gemessen, ob die Anwendung gefaellt, sondern ob sie mechanistisches Denken und Modellkritik tatsaechlich verbessert.
