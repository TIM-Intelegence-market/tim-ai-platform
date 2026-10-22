# PR #365: Nachprüfung der fünf offenen Befunde

Stand 22.10.2026; geprüft und korrigiert auf Ausgangs-Head
`477121f00bcb97e648172ff0e7a34549c9359a30`, Basis `e98597178ec15d3c1d21434f9e31a484366ce2c7`.
Dieser Bericht dokumentiert die gezielte Korrektur, keine Merge- oder Betriebsfreigabe.

| Befund | Korrektur | Nachweis / verbleibende Grenze |
|---|---|---|
| R1 Wissenszeit | Externe, an die exakte Inhaltsversion gebundene Verfügbarkeitszeiten; fehlender Nachweis schließt Inhalte aus. Anker ebenfalls geprüft, Filter vor Begrenzung, unveränderter Kontext während Modellaufruf durch Kopien. | Tests für verspätete Daten, Revisionen, fehlende Zeiten und Limit. Noch kein produktiver Lieferant vertrauenswürdiger Verfügbarkeitsbelege; Experiment bleibt gesperrt. |
| R2 Zitate | Ungültige Quelle oder Antworttypen verwerfen die gesamte Antwort; neutraler Enthaltungstext, keine geretteten Behauptungen. | Gemischte Quellen, 11. Quelle, falsche Typen, Modellfehler, gültige Antwort getestet. Kontext-ID beweist noch keine semantische Treue. |
| R3 Regression | Signal 98 h, Einstieg 99 h, Fit-Ende 100 h statt Einstieg am ausgeschlossenen Rand. | Derselbe Test scheitert erwartungsgemäß mit dem Originalcode aus der Basis und besteht mit dem Fix. |
| R4 Hashvertrag | D01/D02 getrennte kompatible Entscheidungen, vollständige Referenzen/Registry, persistierter Stichtag im Hash. | Originalvorschlag als Referenz aufgenommen und Ersatztext abgeglichen; keine behauptete Vertragsfreigabe oder Validator-Implementierung. |
| R5 S2 | Reale Wissenszeit versus idealisiertes Archiv, expliziter Test/Holm/Cluster/Baseline/Regime, Power-Gate und fester prospektiver Start nach separater Registrierung. | Dokumentprüfung; Simulation und unabhängige Methodenabnahme bleiben Voraussetzungen. Keine Studiendaten geladen. |

## Prüfung

Isolierte lokale uv-Umgebung, Python 3.13.16 wie die CI-Hauptversion, Projektanforderungen aus
`requirements.txt`. Kein Zugriff der Tests auf Live-Datenbank, Netzwerkmodell oder echte Marktdaten.
Ausgeführt mit niedriger Prozesspriorität:

```sh
rtk proxy nice -n 15 .venv-review/bin/python -m pytest -q \
  tests/test_assistant_rag_qwen.py tests/test_research_lab_stats.py \
  tests/test_market_memory.py tests/test_research_cases.py \
  tests/test_research_case_lifecycle.py tests/test_research_lab_backtest.py \
  tests/test_repository_json.py tests/test_repository_governance.py
```

Ergebnis: **80 bestanden**, Exit 0. `git diff --check`: Exit 0.
Die ursprüngliche Implementierung wurde aus Git in ein getrenntes In-Memory-Modul geladen und
der korrigierte Regressionstest dagegen ausgeführt: erwartetes AssertionError; derselbe Test
gegen die korrigierte Implementierung: bestanden. Kein Austausch produktiver Dateien.

Ein früherer erweiterter Lauf unter Python 3.12 wurde nach 48 Sekunden bei einer größeren
synthetischen Guard-Simulation gestoppt (64 bis dahin bestanden, Exit 2/KeyboardInterrupt).
Er gilt ausdrücklich nicht als vollständiger Erfolg. Die abschließende Auswahl oben enthält
keine große Simulation und lief unter der CI-Python-Hauptversion in unter zwei Sekunden.

**Nicht ausgeführt:** vollständige CI, Doctor/Validate mit Betriebsabhängigkeiten, Power-Simulation,
R4-Neulauf, echtes Ollama-Benchmarking. Diese Nachweise bleiben vor einer späteren Abnahme offen.
Die große CI auf dem selbst gehosteten Mac wird für diesen Korrektur-Commit mit `[skip ci]`
ausgesetzt; keine Workflow-Datei oder Schutzregel geändert. Ausstehende Pflichtchecks bleiben
Pflichtchecks, ein übersprungener Lauf gilt niemals als bestanden. Der separate PR-Gate-Workflow
reagiert auch auf `[skip ci]`; für diesen PR ausstehende Läufe werden deshalb abgebrochen.

## Kampagnenschutz und Rücknahme

Änderungen ausschließlich in separater Entwicklungs-Arbeitskopie. Keine Änderung von Live-Checkout,
Live-Umgebung, Dienstkonfiguration, Datenbank, Kampagnenvertrag oder historischem Ergebnisbericht.
Live-Head beim Kontrolllesen weiterhin `f469ad66d2796ec39d6c8e646acd222ae5826f14`.
Core-Manifest SHA256 `6c977a4a3bfb4a30321e92261c2cb72f1f8122fab39799d051b92b8d86532acc`.
Vorhandener Betriebsbericht um 01:54 UTC: Runtime aktiv, Kerzenalter 60,1 s bei Grenze 180 s,
0 fehlende Kerzen der letzten 60 Minuten. Gesamtstatus weiterhin RED durch den schon zuvor
unlesbaren Backup-Pfad; Zeitsynchronisation AMBER. Dies ist eine Momentaufnahme, kein
lückenloser Nachweis jeder Sekunde während der Bearbeitung.

Auto-Merge wurde für PR #365 deaktiviert, PR zusätzlich auf Entwurf gesetzt. Nicht gemergt.
Keine Migration nötig. Rücknahme bei Bedarf durch Revert des Korrektur-Commits ausschließlich
im Entwicklungsbranch; kein Live-Rollback erforderlich. Eine unabhängige Prüfung und spätere
explizite Freigabe bleiben nötig. Die fünf Review-Korrekturen schließen nicht alle 14 Planpakete ab.
