# TIM in 10 Minuten

Stand 25.10.2026. Für jede Person oder jeden Agenten, die oder der neu dazukommt. Alles Ältere ist Geschichte und
liegt in `docs/`; was hier steht, gilt. Wer etwas Veraltetes findet, ändert diese Datei per PR und setzt das Datum neu.

## Was TIM ist

TIM beobachtet den Bitcoin-Spotmarkt (Binance, BTCUSDT) aus öffentlichen aggTrades, baut daraus Kerzen (1m, 5m, 15m, 1h)
und Orderflow-Metriken, beschreibt feste Schwellenkombinationen als „Beobachtungen“ (acht Arten, Regelversion 1.0.0) und
prüft später, wie der Preis 5, 15 und 30 Minuten danach stand. Seit 23.10. führt TIM außerdem ein Papier-Journal mit
Long- und Short-Plänen nach drei Regeln (TIM-, Struktur-, Level-Regel) unter `/journal`. TIM handelt nicht. Es gibt kein
Echtgeld, keine Order, keinen Zugang zu einer Börse mit Schreibrechten. Ziel bis Ende 2026: die **V2-Trading-Version** =
Paper Trading und Shadow Trading, beide ohne echte Order (`docs/TIM_GESAMTPLAN.md`, Abschnitt 0).

## Wo es läuft

Auf einem Mac mini bei Uzi, aus dem Ordner `~/TIM-live`. Der Server tim-core-01 ist seit 20.10. nicht Teil des Betriebs
(Uzi: „TIM soll 100 % auf dem Mac laufen“); er ist als zweiter CI-Runner vorbereitet (`ops/linux/README.md`).

Die V2-Qualifizierungskampagne vom 20.10. wurde am 23.10. auf Uzis Wunsch abgebrochen; die Daten liegen mit Prüfsummen
unter `~/Library/Application Support/TIM/campaign-archive/v2-qual-2026-10-20`. Seitdem folgt `~/TIM-live` wieder
`platform-main`: Der Dashboard-Agent (`com.tim.dashboard-refresh`) spielt jeden Merge ein und startet die Runtime neu
(1 bis 2 Minuten Datenlücke je Einspielen). **In `~/TIM-live` arbeitet niemand direkt**, auch Codex nicht; das hielt am
24.10. den Agenten an. Hängt der Agent länger als 2 Stunden aus demselben Grund (oder musste er zurückrollen), fragt er
die Claude-CLI auf dem Mac ohne Werkzeuge um eine Diagnose und legt dazu ein GitHub-Issue an (Label `dashboard-agent`);
die Behebung kommt als PR. Neuen grünen Agent-Code auf `platform-main` lädt er vor jeder Runde selbst.

Dienste (launchd, Stand Audit 25.10.): `com.tim.runtime` (Ingestion, Beobachtungen, Journal, Control Center auf
http://127.0.0.1:8765), `com.tim.watchdog`, `com.tim.validator`, `com.tim.server-health`, `com.tim.history-recovery`,
`com.tim.dashboard-refresh`, `com.tim.db-backup` (03:15 Ortszeit, drei Stände, dieselbe Platte), `com.tim.trading-team`,
der Issue-Worker (`~/TIM-worker`, Dashboard 8767) und der CI-Runner `mac-mini-tim`.
Datenbank: PostgreSQL 18 auf dem Mac, 127.0.0.1:5432. Ein Backup außerhalb des Mac gibt es noch nicht (Paket B1 bis B3
im Grün-Plan).

## Datenfluss in einem Satz

Binance-WebSocket → `DurableIngress` (aggTrades mit Cursor und Outbox in PostgreSQL) → `CandleAggregator`
(1-Minuten-Kerzen) → `OrderflowMetricsService` (60-s-Fenster) → `OrderflowObservationEngine` (Beobachtungen) →
`ResearchCaseEngine` (30-Minuten-Fälle) → `OrderflowValidationEngine` (Ergebnis 5/15/30 min) → Setup-Pfad und
Plan-Journal → Control Center. Alles in `main.py`; rund 11.000 von 81.000 Zeilen unter `src/` laufen live
(`docs/PAKETINVENTAR.md`).

## Wer entscheidet

- **Uzi** (Inhaber): Ziel, Freigaben, Merges auf `platform-main`. Schreibt Deutsch, will Ergebnisse statt Rückfragen,
  aber kein Echtgeld und keine Zugangsdaten in Dateien. Uhrzeiten in deutscher Ortszeit.
- **Chris** (Mitentwickler, Admin, GitHub `fleckbarti-ai`): Integrität, Code, Router und Tailnet.
- Agenten (Claude-Threads, Codex, ChatGPT, Qwen-Worker) arbeiten per PR gegen `platform-main`; Regeln in `CI.md`
  und `CLAUDE.md`. Threads liefern PRs merge-fertig (aktuell, konfliktfrei, volle Suite in der Cloud grün); gemergt
  wird nur auf Uzis „merge“. „go“ heißt bauen.

## Was gerade gilt (die drei nächsten Schritte)

1. Backup außerhalb des Mac und eine geübte Wiederherstellung (`docs/ops/restore_und_rollout_t02_t14.md`).
2. Studie S2 (Orderflow-Regeln auf Archivdaten) ist am 26.10.2026 am Power-Gate beendet worden: NICHT BEURTEILBAR,
   die Live-Orderflow-Regeln gelten als Beobachtungen, nicht als Signale
   (`docs/research_lab/studien/S2_ORDERFLOW_REGELN_PRAEREGISTRIERUNG.md`, Abschnitt 8). Offen bleibt die
   Nachprüfung um 1h, 4h und 24h (läuft seit 24.10., Auswertung nach 30 Tagen).
3. Die 11 Sichten der Gesamtbild-Analyse auf Grün bringen: `docs/audits/GRUEN_PLAN_11_SICHTEN.md`.

Der Erst-Audit mit dem Aufgabenregister A01 bis A25 steht in `docs/audits/TIM_AUTONOMOUS_INITIAL_AUDIT.md`.

## Wie man prüft

```sh
python -m pytest tests/ -q -m "not local_env and not serial" -n 4   # volle Suite, Python 3.13, ~5 900 Tests
python -m pytest tests/ -q -m "not local_env and serial"            # danach die seriellen Tests
python -m pytest tests/test_research_lab_*.py -q                    # Forschungsprotokoll 1.1
python scripts/v2_readiness_audit.py --no-write                     # Readiness nur lesend (auf dem Mac)
```

Pflicht-Checks auf `platform-main`: `test` und `PR gate` auf dem Mac-Runner (Testjob rund 3,3 Minuten seit PR #407).

Forschung: `docs/research_lab/PROTOKOLL.md` (Version 1.1) ist vor den Tests festgeschrieben; der Holdout ab 2025 ist
gesperrt. Ergebnis bisher: 48 Varianten ohne Vorteil (R4), Glückstest p ≈ 0,45, Studie S4 (Trefferquote 75 %) am 25.10.
als nicht testbar beendet. Kernbefund aller Studien: Gebühren und Slippage fressen enge Stops; ein Stop muss etwa 0,72 %
bis 1,0 % entfernt sein, damit die Kosten unter 0,25 R bleiben (`docs/research_lab/reports/`).

## Was TIM nicht ist

Kein Handelsbot, kein Signaldienst, keine KI, die Marktfragen beantwortet (Ollama ist in der Runtime aus; der
RAG-Baustein ist ein Experiment, `docs/v2_completion/ki_pfad_entscheidung_t06.md`). „Fertig“ heißt nicht „profitabel“:
Ein ehrliches „kein Vorteil“ ist ein gültiges Ergebnis.
