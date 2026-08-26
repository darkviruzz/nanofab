# Startprompt: nächste Coding-Session (Meilenstein M6)

Geschrieben 2026-08-26 nach der Grilling-Session zu Substrat/Domain/UI. Zum
Kopieren in eine frische Session — die Umgebungs-Hinweise aus
`docs/plans/m5-start-prompt.md` gelten unverändert weiter.

---

Setze den v2-Datenmodell-Plan für NanoFab fort mit Meilenstein M6
(Datenfundament: Materialbibliothek nach JSON, Prozessklassen, die didaktischen
Standardraten).

Branch: `claude/substrate-process-brainstorm-5fpff8` (auschecken bzw. darauf
bleiben, nicht neu branchen).

Lies zuerst:
1. AGENTS.md
2. CONTEXT.md
3. `docs/plans/m6-m9-roadmap.md` — dein eigentlicher Bauplan. Besonders §0
   (gemessener Ist-Zustand — mehrere verbreitete Annahmen darüber sind falsch),
   §2 (die Entscheidungen E14, E15, E16), §3 (die Prozesstabelle und was sie am
   Schema erzwingt, mit den umgerechneten Raten) und §4 „M6"
4. `docs/plans/v2-structure-model.md` §3.3/§3.4 (Materialmodelle), §4.3
   (Flussnormierung — der Grund, warum Raten skalar sind), §17–§21 (Korrekturen
   aus M0–M5, verbindlich)
5. `docs/plans/backlog-later.md` — was bewusst *nicht* zu M6 gehört, insbesondere
   B7 (kalibrierte Raten)
6. memory.md ab 2026-08-25

Kontext: M0–M5 sind fertig, 394 Tests grün, S1–S5 laufen, `nanofab_v3`
v0.3.0.dev0. Plan §14s Meilensteinliste endet mit M5; die Roadmap setzt sie fort.

Aufgabe — Meilenstein M6 in dieser Reihenfolge:

- **Zuerst die Migration, dann alles andere.** Die Materialbibliothek wandert
  vollständig nach `data/materials/*.json`, ein File pro Material (E14). Die acht
  eingebauten Materialien wandern **mit** — es darf danach kein Material mehr im
  Code stehen. `MaterialType` und alle Untermodelle (`SputterResponse`,
  `DevelopModel`, `DissolveModel`, `materials/material.py:71-292`) sind frozen
  Dataclasses mit ausschließlich skalaren Feldern, also verlustfrei
  serialisierbar — das ist geprüft, keine Vermutung. Schreibe einen Round-Trip-
  Test, der die geladene Bibliothek gegen das heutige `didactic_library()`
  vergleicht: **bitgleiche Modelle**, sonst ist die Migration nicht fertig.
- **`PROCESS_CLASSES` additiv erweitern** (`materials/material.py:64`). Neu:
  `icp_fluorine`, `rie_chlorine`, `rie_oxygen`, `wet_etch_cr`, `wet_etch_oxide`,
  `sputter_deposit`. **Nichts umbenennen** — S1–S5 und 394 Tests hängen an
  `wet_etch`/`dry_etch`/`ion_beam`/`deposit`/`develop`/`dissolve`.
- **Neue Materialien**: `chrome`, `fused_silica`, `titania` (E16). `alumina`
  existiert bereits und ist der Ätzstopp für eine der späteren Demos.
- **Die Studenten-Raten eintragen** (Roadmap §3, bereits von nm/min nach nm/s
  umgerechnet). Zwei Dinge dabei ernst nehmen:
  - Die Tabelle unterscheidet „horizontal = vertikal" von „vertical". Das sind
    **keine zwei Raten**: die Rate ist ein Skalar („offene, normal zugewandte
    Fläche", `material.py:213-218`), und die Richtungsabhängigkeit kommt aus der
    Winkelverteilung im Step (`kernel/flux.py:160-280`). Isotrop → breite
    Verteilung, „vertical" → Delta bzw. enge Lobe.
  - Die Tabelle nennt bei Sputterätzen „silicon oxide", bei ICP/RIE „fused
    silica". Beide werden als zwei Materialien geführt. Wo die Tabelle eine
    Kombination nicht nennt, übernimm die jeweils andere SiO₂-Rate und **markiere
    das im JSON als Annahme** — nicht stillschweigend.
- **Steps für die Chemien** aus der Tabelle anlegen, jeweils mit der
  Winkelverteilung aus dem vorigen Punkt. Wafer-Reinigung existiert seit M5.
- **Unbekanntes Material warnt und fragt nach** (E15). Der stille Fallback auf
  Rate 0 endet — er hat in einem echten Projekt dazu geführt, dass ein
  Chrom-Partikel überall Rate 0 hatte, ohne dass irgendetwas es gesagt hätte.
  Freitext bleibt aber erlaubt (didaktischer Wert: schnell etwas Unkalibriertes
  ausprobieren); ein Dialog erfragt die fehlenden Werte und schreibt sie nach
  `data/materials/`.

**DoD:** Die Bibliothek kommt vollständig von Platte, kein Material mehr im Code;
die 394 Tests bleiben grün; die zehn Tabellenprozesse sind als Steps aufrufbar;
ein unbekanntes Material erzeugt eine sichtbare Warnung statt einer stillen Null.

Validierung: pytest grün, `python -m compileall nanofab_v3 tests` (AGENTS.md §4).
Bei unklaren Designfragen selbst entscheiden im Sinne von Roadmap/Plan, in
memory.md dokumentieren statt zu blockieren.

Committe fokussiert (feat:/test:/docs:/fix:/chore:), aktualisiere memory.md nach
AGENTS.md §5, push auf den oben genannten Branch.

Hinweis: `data/` ist neu — kläre beim Anlegen gleich mit, wie es ins Packaging
kommt (`nanofab_v3.spec`, plan §11/§21.5). Eine Bibliothek, die aus dem Source-
Baum lädt und in der Exe fehlt, fällt erst beim `--selftest` auf.
