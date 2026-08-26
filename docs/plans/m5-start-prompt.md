# Startprompt: nächste Coding-Session (Meilenstein M5)

Geschrieben 2026-08-26 am Ende von M4. Zum Kopieren in eine frische Session —
darunter stehen die Umgebungs-Hinweise, die eine Stunde sparen.

---

Setze den v2-Datenmodell-Plan für NanoFab fort mit Meilenstein M5
(Delivery: Plugins, Packaging, die letzten Prozesse, die Wafer-Ansicht).

Branch: `claude/datenmodell-iteratives-aetzen-14976q` (auschecken bzw. darauf
bleiben, nicht neu branchen).

Lies zuerst:
1. AGENTS.md
2. CONTEXT.md
3. `docs/plans/v2-structure-model.md` — insbesondere §5.4 (Registry/Plugins), §6
   (der didaktische Prozesssatz), §8 (Runs/Positionen), §11 (Packaging), §14
   (M5-DoD) sowie §17, §18, §19 und §20 (Korrekturen aus M0–M4 — verbindlich,
   ergänzen einzelne Aussagen im Haupttext)
4. `docs/plans/m5-delivery-handoff.md` — dein eigentlicher Bauplan: die bereits
   verdrahteten Nahtstellen, die eine Designentscheidung, die zuerst zu treffen
   ist, die Fallen aus M0–M4, das gemessene Budget, empfohlene Reihenfolge
5. ADR-0001…0004; memory.md-Einträge ab 2026-08-25

Kontext: M0–M4 sind fertig, 314 Tests grün, S1–S4 laufen. `nanofab_v3/` ist die
einzige aktiv gebaute Codebasis am Root und hat seit M4 eine eigene Anwendung
(`python -m nanofab_v3.ui`). Die v1-Anwendung liegt als Snapshot in
`ui_backups/`.

Aufgabe — Meilenstein M5 in der Reihenfolge aus Handoff §6:
- Triff zuerst die Designentscheidung aus Handoff §3 (was ist die „code version"
  im Cache-Key, sobald ein Plugin die Antwort ändern kann) und dokumentiere sie
  in memory.md. Empfehlung im Handoff mit gemessener Begründung: zwei Achsen —
  `code_version()` bleibt grob (`__version__`, deckt Kernel/numpy/Interpreter),
  und der *Recipe*-Hash bekommt pro benutztem Schritt einen
  Implementierungs-Digest. Nenne die Grenze ehrlich: der Digest deckt den
  Wrapper, nicht den Kernel dahinter.
- Partikel + Clean (§6): `ball`-Konstruktoren aus `ctx.rng`, ein
  Partikel-Material in der Library, `reachable_occurrences` für Clean. Der
  didaktische Kern ist **Mikromaskierung** — ein Partikel unter einem Film ist
  unerreichbar, Clean lässt es stehen, der Defekt bleibt. Das ist ein eigenes
  Akzeptanzszenario (S5) und der erste *registrierte* Schritt, der §5.2s
  RNG-Vertrag überhaupt ausübt.
- Inspektionsschritte (§6): SEM / Profilometer / Ellipsometer geben die
  Eingangsstruktur unverändert plus Artefakte und Messwerte zurück. Verdrahte
  hier `StepResult.artifacts` bis auf `Revision.artifacts` durch — Handoff §2
  sagt, warum das absichtlich noch offen ist.
- Anneal (§6): nur Felder und Materialmodelle, Reflow-Geometrie bleibt offen
  (Plan §16).
- Entry-Point-Plugins (§11, §5.4) über dieselbe `register()`-Naht, die jeder
  Builtin benutzt. Liefere **ein** In-Tree-Beispiel-Plugin in eigenem Paket mit,
  das ein Test installiert — ein Discovery-Mechanismus ohne zweiten Implementierer
  ist einer, der noch nicht funktioniert.
- Wafer-Ansicht (§8, §14): der Positions-Fächer über `Run`. Die Engine ist fertig
  (`Run.add_position`, `positions_on_radius`, Cache pro Position); das hier ist
  eine View plus ein Job-Runner. Partielle Ergebnisse zeigen, nicht blockieren.
- PyInstaller zuletzt (§11): eine Exe, Builtins und numpy/scipy eingefroren.
  **DoD ist, dass die Exe S1–S4 ausführt**, also brauchen die Szenarien einen Weg,
  der nicht durch pytest geht (`--selftest`-Flag oder Menüeintrag) — entscheide
  welchen und schreib es auf.

Validierung: pytest grün, `python -m compileall nanofab_v3 tests` (AGENTS.md §4).
Bei unklaren Designfragen selbst entscheiden im Sinne von Plan/Handoff, in
memory.md dokumentieren statt zu blockieren.

Committe fokussiert (feat:/test:/docs:/fix:/chore:), aktualisiere memory.md nach
AGENTS.md §5, push auf den oben genannten Branch. Falls sich am Plan etwas als
falsch/unvollständig herausstellt: wie bei §17/§18/§19/§20 vorgehen (Ergänzung
mit Messung, Verweis von der betroffenen Stelle, Originaltext bleibt stehen).

Hinweis: `ui_backups/`-Snapshots sind Aufzeichnungen, keine Branches — nie in
place bearbeiten (AGENTS.md §7). Der v0.2.0-`.spec` dort ist ein funktionierendes
PyInstaller-Rezept für die *alte* App und lohnt sich zu lesen, bevor du ein neues
schreibst.

---

## Umgebungs-Hinweise (nur für eine frische Container-Session nötig)

Auf einer lokalen Maschine mit eingerichteter `.venv` ist nichts davon nötig.
In einem frischen Container kostet es sonst eine Weile, das herauszufinden:

```bash
pip install numpy scipy pytest            # der Kern
pip install PySide6                       # nur für die Qt-Tests und die App
apt-get update -qq && apt-get install -y libegl1 libgl1 libxkbcommon0 \
    libdbus-1-3 libfontconfig1            # sonst: ImportError libEGL.so.1
export QT_QPA_PLATFORM=offscreen          # Qt headless
```

`tests/test_ui.py` setzt `QT_QPA_PLATFORM=offscreen` selbst und überspringt die
Qt-Hälfte per `importorskip`, wenn PySide6 fehlt — die 24 UI-Tests laufen dann
aber nicht mit. Die vollen 314 brauchen PySide6.

Ein Screenshot der laufenden App ohne Display:

```python
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from nanofab_v3.ui.window import MainWindow

app = QApplication([])
w = MainWindow(); w.resize(1280, 800); w.show(); app.processEvents()
w._on_demo()                              # S1 end-to-end
img = QImage(w.size(), QImage.Format_ARGB32); img.fill(0)
w.render(img); img.save("window.png")
```

Wenn du Pixel aus einem `QImage` in numpy liest: **kopieren**. `constBits()`
liefert eine View in den Puffer, und der wird freigegeben, sobald das `QImage`
aus dem Scope fällt — ohne Kopie meldet ein Canvas mit 831 Farben fünf.
