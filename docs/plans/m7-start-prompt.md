# Startprompt: Coding-Session Meilenstein M7

Geschrieben 2026-08-26 zusammen mit dem M6-Prompt. Zum Kopieren in eine frische
Session, **nachdem M6 fertig ist** — M7 setzt die JSON-Bibliothek und die neuen
Materialien voraus. Umgebungs-Hinweise: siehe `docs/plans/m5-start-prompt.md`.

---

Setze den v2-Datenmodell-Plan für NanoFab fort mit Meilenstein M7
(Substrat & Domain: Semistandard-Presets, Form-Faktor, Dicke, dynamisches
y-Resize).

Branch: `claude/substrate-process-brainstorm-5fpff8` (auschecken bzw. darauf
bleiben, nicht neu branchen).

Lies zuerst:
1. AGENTS.md
2. CONTEXT.md
3. `docs/plans/m6-m9-roadmap.md` — dein Bauplan. Besonders §1 (das
   Speicherbudget, das alles hier begrenzt — die Zahlen sind gemessen, nicht
   geschätzt), §2 (E1–E7), §4 „M7" mit den vier vorab benannten Fallen
4. `docs/plans/v2-structure-model.md` §3.1 (Domain wird bei der Substratwahl
   erzeugt), §3.6 (Revisionen), §8 (Runs/Positionen), §17–§21
5. `docs/plans/backlog-later.md` — B1 (geteilte Doppel-Domain) und B2
   (Rückseite/Vias) sind die direkten Fortsetzungen; B9 grenzt ab, was hier
   *nicht* dazugehört
6. ADR-0001…0004; memory.md ab 2026-08-25

Kontext: M6 hat die Materialbibliothek nach `data/materials/*.json` migriert und
die Prozessklassen erweitert. Heute kennt `SELECT_SUBSTRATE`
(`processes/substrate.py:51-98`) nur `material` und `surface`; die Domainmaße
kommen getrennt aus `cross_section_grid()` (`:26-48`). Genau diese Trennung löst
M7 auf.

Aufgabe — Meilenstein M7:

- **Substrat-Step ausbauen** (E1, E3): Form-Faktor-Dropdown (`Chip`, `Maske`,
  `Wafer` (Default), `semi-infinit`), Material, Dimensionen (Durchmesser bzw. x/y
  als zwei Werte), Dicke, Surface Finish. `semi-infinit` ist die Kodierung für
  „Dicke egal" — **ein** Step, kein zweiter, kein gespaltenes Rezept-Format.
- **Semistandard-Presets** in zwei Abschnitten (Wafer / Maskblank), innerhalb
  sortiert nach Material und aufsteigend nach Größe bzw. Dicke. Default: rund,
  100 mm, 1 mm, Fused Silica. Maskblanks nach SEMI-Kurzcode (5006, 5009, 5018,
  6009, 6012, 6025, 9012, 9020, 9025) mit Seitenlänge 126.6 / 152.0 / 228.6 mm
  und Dicken 1.52 / 2.30 / 3.05 / 3.80 / 4.60 / 5.00 / 6.35 mm.
- **Preset-Override-Muster generisch bauen**, nicht als Sonderfall: überschreibt
  manuell geänderte Folgefelder nur nach Rückfrage, sonst still. Es wird für
  weitere Presets wiederverwendet (Resiste, Ätzrezepte), also gehört es hinter
  eine gemeinsame Naht.
- **Preset treibt die Grid-Erzeugung mit** (E2). Ein Substrat „100 mm Wafer" bei
  zufällig gewählter Domainbreite ist der Zustand, den M7 beseitigt.
- **Registry-Validierung „Substrat muss Step #0 sein"** (E4) — UI-/Registry-Ebene
  mit Hinweistext, **kein** Kernel-Verhalten. Vor dem ersten Step existiert gar
  keine Domain.
- **Dynamisches y-Resize** (E5), der Kern des Meilensteins: nach y-min *und*
  y-max wachsen, und wieder schrumpfen, wenn die Domain groß und leer ist.
  Vollautonom, ohne Rückfrage. Deckel bei 5 µm; beim Anschlagen eine UI-Warnung
  mit **transparent geschätztem RAM- und Plattenbedarf** und der Möglichkeit, den
  Deckel zu erhöhen. **Kein** Wachstum nach x (E6).
- **Substratdicke als Metadatum**, nicht als Domaingröße (Roadmap §1). Die Domain
  zeigt das Fenster mit Struktur; die 625 µm eines Wafers sind gewusst, nicht
  dargestellt. Durchätzen ergibt einen FAIL „Substrat durchgeätzt" (E7) — aber die
  Dicke wird von Anfang an als echtes Feld geführt, damit B2 später keine
  Datenmodelländerung braucht.

**Vier Fallen, vorab benannt** (Roadmap §4, M7):

1. `Grid` ist „the sole spatial authority" und `Structure` ist frozen — ein Resize
   erzeugt eine neue Grid **und** neu gepaddete Arrays, nichts wird in place
   verändert.
2. Die Grid wird **pro Revision** gespeichert (`io/manifest.py:143`) *und* einmal
   am Recipe (`:404`), und `manifest.py:18` spricht von „the reference grid,
   checked on load". Sobald Revisionen unterschiedlich große Grids haben dürfen,
   muss dieser Konsistenzpfad angefasst werden — **hier trifft M7 zuerst auf
   Widerstand.**
3. Replay ist Cache-Fallback *und* Mechanismus für neue Waferpositionen
   (`runtime/revision.py`, ADR-0004). Ein Resize muss deterministisch replaybar
   bleiben, sonst zerfällt der Cache — und ein warmer Replay ist 68x.
4. `Grid.origin` existiert und ist heute immer `(0,0)`. Beim Wachsen nach unten
   ist sie der natürliche Träger des Versatzes; Koordinaten überall umzurechnen
   wäre der teure Weg. Halte das Resize hinter **einer** Funktion — B1 (geteilte
   Doppel-Domain) baut genau darauf auf.

**DoD:** Ein 100-mm-Fused-Silica-Preset erzeugt Substrat und Domain konsistent;
ein Ätzschritt, der die Domain unten verlassen würde, lässt sie automatisch
wachsen statt zu scheitern; ein sehr tiefer Schritt schlägt am Deckel mit lesbarer
Schätzung an; Durchätzen sagt „durchgeätzt", statt etwas Falsches zu rechnen; die
Tests bleiben grün.

Validierung: pytest grün, `python -m compileall nanofab_v3 tests` (AGENTS.md §4).
Miss das Resize (Zeit und Speicher bei 1 µm / 5 µm Tiefe) und schreib die Zahlen
in memory.md — §17.7s Befund, dass der Upwind-Stencil über die ganze Domain die
Kosten dominiert, gilt seit fünf Meilensteinen und wird durch eine wachsende
Domain direkt teurer.

Bei unklaren Designfragen selbst entscheiden im Sinne von Roadmap/Plan, in
memory.md dokumentieren statt zu blockieren.

Committe fokussiert (feat:/test:/docs:/fix:/chore:), aktualisiere memory.md nach
AGENTS.md §5, push auf den oben genannten Branch.

Hinweis zum Randbug: M9 repariert das Rand-/Reinit-Verhalten an den **lateralen**
Flächen (Roadmap §4, M9). M7 fasst nur y an und baut deshalb *nicht* auf dem
kaputten Teil auf — das ist der Grund für diese Reihenfolge. Falls dir beim
Resize an x-min/x-max etwas auffällt: notieren, nicht mitfixen.
