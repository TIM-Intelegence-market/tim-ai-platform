# TIM in 10 Minuten

Stand 22.10.2026. Für jede Person oder jeden Agenten, die oder der neu dazukommt. Alles Ältere ist Geschichte und
liegt in `docs/`; was hier steht, gilt.

## Was TIM ist

TIM beobachtet den Bitcoin-Spotmarkt (Binance, BTCUSDT) aus öffentlichen aggTrades, baut daraus 1-Minuten-Kerzen und
Orderflow-Metriken, beschreibt feste Schwellenkombinationen als „Beobachtungen“ (acht Arten, Regelversion 1.0.0) und
prüft später, wie der Preis 5, 15 und 30 Minuten danach stand. TIM handelt nicht. Es gibt kein Echtgeld, keine Order,
keinen Zugang zu einer Börse mit Schreibrechten. Ziel bis Ende 2026: die **V2-Trading-Version** = Paper Trading und
Shadow Trading, beide ohne echte Order (`docs/TIM_GESAMTPLAN.md`, Abschnitt 0).

## Wo es läuft

Auf einem Mac mini bei Uzi, aus dem Ordner `~/TIM-live` auf dem eingefrorenen Commit `f469ad6`. Seit 20.10.2026 20:34 UTC
läuft dort die **V2-Qualifizierungskampagne**: 34 Tage ohne Codeänderung, Ziel 95 % Minuten-Abdeckung und 1.000
gültige Fälle, Ende frühestens 23.11.2026 20:34 UTC. **Bis dahin ändert niemand etwas in `~/TIM-live`, lädt keine
Dienste neu und startet den Mac nicht neu.** Der Server tim-core-01 ist seit 20.10. nicht Teil des Betriebs.

Dienste (launchd): `com.tim.runtime` (Ingestion, Beobachtungen, Dashboard auf http://127.0.0.1:8765),
`com.tim.watchdog`, `com.tim.server-health`, `com.tim.history-recovery`, `com.tim.qualification-daily`.
Datenbank: PostgreSQL 18 auf dem Mac, 127.0.0.1:5432. Backups täglich 03:15 Ortszeit auf dieselbe Platte (offen: T02).

## Datenfluss in einem Satz

Binance-WebSocket → `DurableIngress` (aggTrades mit Cursor und Outbox in PostgreSQL) → `CandleAggregator`
(1-Minuten-Kerzen) → `OrderflowMetricsService` (60-s-Fenster) → `OrderflowObservationEngine` (Beobachtungen) →
`ResearchCaseEngine` (30-Minuten-Fälle) → `OrderflowValidationEngine` (Ergebnis 5/15/30 min) → Dashboard und
Tagesbelege. Alles in `main.py`, rund 11.000 Zeilen Live-Code (`docs/PAKETINVENTAR.md`).

## Wer entscheidet

- **Uzi** (Inhaber): Ziel, Freigaben, Merges auf `platform-main`. Schreibt Deutsch, will Ergebnisse statt Rückfragen,
  aber kein Echtgeld und keine Zugangsdaten in Dateien.
- **Chris** (Mitentwickler, Admin): Integrität, Code, Router und Tailnet.
- Agenten (Claude-Threads, Codex, Qwen-Worker) arbeiten per PR gegen `platform-main`; Regeln in `CI.md` und `CLAUDE.md`.

## Was gerade gilt (die drei nächsten Abnahmen)

1. Kampagne durchhalten und belegen: Tagesbelege, Coverage, Lücken (T09, `docs/v2_completion/kampagnenbelege_inter_rater_t09.md`).
2. Nachweisen, ob die Orderflow-Regeln überhaupt etwas vorhersagen: Studie S2 auf Archivdaten, getrennte Laborumgebung
   (`docs/research_lab/studien/S2_ORDERFLOW_REGELN_PRAEREGISTRIERUNG.md`). Paper Trading erst danach.
3. Zweite Sicherung außerhalb des Mac und ein geübter Restore (`docs/ops/restore_und_rollout_t02_t14.md`).

Der verbindliche Arbeitsplan dafür ist der „gemeinsame Verbesserungsplan“ (T01–T14); der Stand je Paket steht in
`docs/SYSTEMSTAND.md` und im Thread „22.10. Strenge Professoren-Prüfung von TIM“.

## Wie man prüft

```sh
python -m pytest tests/ -q -m "not local_env"        # volle Suite, Python 3.13, ~5 900 Tests, ~8 min
python -m pytest tests/test_research_lab_*.py -q     # Forschungsprotokoll 1.1
python scripts/v2_readiness_audit.py --no-write      # Readiness nur lesend (auf dem Mac)
```

Forschung: `docs/research_lab/PROTOKOLL.md` (Version 1.1) ist vor den Tests festgeschrieben; der Holdout ab 2025 ist
gesperrt. Ergebnis bisher: 48 Varianten, kein Vorteil in Training/Validierung (`docs/research_lab/reports/`).

## Was TIM nicht ist

Kein Handelsbot, kein Signaldienst, keine KI, die Marktfragen beantwortet (der RAG-Baustein ist ein Experiment,
`docs/v2_completion/ki_pfad_entscheidung_t06.md`). „Fertig“ heißt nicht „profitabel“: Ein ehrliches „kein Vorteil“
ist ein gültiges Ergebnis.
