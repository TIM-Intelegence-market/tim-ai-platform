# S8: Prüfplan für drei Sequenzmerkmale

Uzi, 28.10.2026: „go, ergänze die drei Sequenzmerkmale in S8 und teste, ob sie gegenüber dem bisherigen
Modell einen messbaren Vorteil bringen. Den gesperrten Holdout nicht anfassen.“

Dieser Auftrag autorisiert die Implementierung und einen explorativen historischen Vergleich. Es gibt im
Ausgangsstand kein trainiertes S8-Modell; die Referenz wird aus den bestehenden 35 Merkmalen neu trainiert.
Keine Runtime, kein ursprüngliches Kampagnenregister und keine Originalbelege werden geändert.

## Festlegungen vor dem ersten Datenabruf

- Genau ein gemeinsamer Zusatzblock: `last_run_norm_1`, `sign_autocorr_1`, `burst_share_1`.
- Ausführliche Definitionen im S8-Datenwörterbuch. aggTrade-ID-Reihenfolge; keine Zuordnung zu Investoren.
  Exakte Duplikate werden vor allen Statistiken entfernt. Zeitrücksprünge/ID-Lücken schließen den Tag aus.
  Unter drei Ereignisse: Korrelation fehlt. Eine konstante linke oder rechte Randfolge: Konvention 0;
  diese ist kein Nachweis fehlender Abhängigkeit. Leere/alte Balken ohne Sequenzdaten bleiben fehlend.
- Ein Acht-Tage-Block je Kalendermonat 2020-2024. Starttag aus SHA-256 von Version, Seed 20261028 und Monat,
  modulo zulässiger Starttage. Insgesamt 480 Archivtagesdateien; kein Blick auf Kurse bei der Auswahl.
  Der erste Tag eines getrennten Blocks liefert die Vortagsprofile. Nutzbar sind typischerweise sieben Tage
  pro Block; zusätzliche Qualitätsausschlüsse werden ohne Ersatz offengelegt. Nicht gewählte Tage sind
  absichtliche Stichprobenlücken, keine Erfassungsfehler. Keine Aussage über vollständige Historienabdeckung.
- Training bis 31.12.2022, Validierung 2023-2024. Labels, Kostenboden und Purging unverändert. Keine zufällige
  Aufteilung von Minuten und keinerlei Laden des Holdouts ab 01.01.2025. Kein Holdout-Permission-Pfad.
- Beide Modelle nutzen dieselben vollständigen Zeilen einschließlich der drei Sequenzmerkmale. Dadurch
  kann ein Unterschied nicht durch andere Ausfälle erklärt werden. Der 35er-Vergleich ist die Ablation
  dieser gemeinsamen Kohorte, nicht eine Gegenüberstellung verschieden gefilterter Datensätze.
- Primärmodell: CatBoost, 500 Iterationen, Tiefe 4, Lernrate 0,05, Seed 20261028, zwei Threads, Multiclass.
  Keine Validierungsdaten für Training, Tuning oder frühes Stoppen. Genau dieselbe Konfiguration beiderseits.
- Sekundär, nur beschreibend: StandardScaler (nur Training) und logistische Regression, C=1, lbfgs,
  maximal 1000 Iterationen, Toleranz 1e-6. Keine Auswahl des günstigeren Modells nach Ergebnissen.
- Primärgröße: relative Log-Loss-Reduktion `(35er-Loss - 38er-Loss) / 35er-Loss`. Brier/Accuracy ergänzend.
  Referenz zur Einordnung: aus dem Training geschätzte Klassenbasisrate.
- Gepaarter Monatsblock-Bootstrap, 4000 Ziehungen, Seed 20261028, 95%-Perzentilintervall. Alle Minuten des
  ausgewählten Blocks bleiben zusammen. Mindestens 24 Validierungsmonate für ein numerisches Urteil.
- Als anfängliche praktische Prüfschwelle ist 1 % relative Verbesserung vorgeschlagen; die Nutzerfrage
  dazu wurde vor Datenabruf gestellt. Die konkrete im Lauf verwendete Schwelle wird vor Fit in `plan.json`
  eingefroren und im Ergebnis ausgewiesen. Die Rohverbesserung und das Intervall werden unabhängig davon
  vollständig berichtet. Keine rückwirkende Änderung nach Ergebnissen.
- Urteil: Untergrenze > praktische Schwelle → praktischer Vorteil in dieser Stichprobenvalidierung;
  Untergrenze > 0 → messbar, praktische Größe ggf. unbestätigt; Obergrenze < 0 → schlechter;
  Obergrenze < praktische Schwelle → kein praktischer Vorteil nachgewiesen; sonst unklar.
  Fehlende Mindestzahl Monatscluster → nicht beurteilbar. „Nicht nachgewiesen“ bedeutet nicht widerlegt.
- Keine ergebnisabhängige Erweiterung der Stichprobe, keine weiteren Parameterkonfigurationen nach Blick
  auf Resultate. Der Bootstrap ist Unsicherheitsbeschreibung, keine nachträglich behauptete a-priori-Power.
  Eine prospektive Bestätigung braucht weiterhin Effekt-/Power-Planung und eine eigene festgelegte Periode.

## Reproduktion

Python 3.13, separate uv-Umgebung. ML-Abhängigkeiten und tatsächlich verwendete Versionen im Ergebnisbericht
festhalten; keine Änderung produktiver Installationsskripte. Neue Daten in eigenem ignoriertem Laborpfad.

Installation: `uv venv --python 3.13 .venv-s8`, dann
`uv pip install --python .venv-s8/bin/python -r requirements.lock -r docs/research_lab/studien/S8_SEQUENCE_REQUIREMENTS.txt`.
Das vorhandene Runtime-Lockfile bleibt unverändert. Die folgende Befehlsfolge nutzt den Python dieser Umgebung.

```
python -m src.research_lab.orderflow_ml.sequence_study plan --root data/s8_sequence --out output/s8_sequence
python -m src.research_lab.orderflow_ml.sequence_study fetch --root data/s8_sequence --out output/s8_sequence
python -m src.research_lab.orderflow_ml.sequence_study export --root data/s8_sequence --out output/s8_sequence --code-version COMMIT
python -m src.research_lab.orderflow_ml.sequence_study compare --root data/s8_sequence --out output/s8_sequence
```

`plan.json` enthält exakte Tage, Modelle, Labels, Merkmale und Hash. Archive werden mit offizieller Prüfsumme
verifiziert. Modellartefakte und gemeinsame Validierungsprognosen werden gespeichert. Bericht enthält Code-,
Eingangs-, Merkmals-, Label- und Planhash sowie Versionsangaben und monatliche Unterschiede. Synthetische
Tests werden ausdrücklich nicht als Marktergebnis gezählt. Keine Änderung der Runtime oder echter Handel.
