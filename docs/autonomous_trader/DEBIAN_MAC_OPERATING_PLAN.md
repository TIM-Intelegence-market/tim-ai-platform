# TIM Betriebsplan: Debian-Server und Mac

**Stand:** 2026-10-01
**Status:** Planungsdokument. Es autorisiert keine Implementierung, keine
Secret-Nutzung, keine privaten Exchange-Aufrufe, keine Shadow-Execution und
kein Live-Trading.
**Bezug:** [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md) (Phasen 0–10
bleiben maßgeblich), [CURRENT_STATE_ASSESSMENT.md](CURRENT_STATE_ASSESSMENT.md),
[`TIM_V2_BLOCKER_REGISTER.md`](../../TIM_V2_BLOCKER_REGISTER.md),
[`TIM_COVERAGE_ROOT_CAUSE_ANALYSIS.md`](../../TIM_COVERAGE_ROOT_CAUSE_ANALYSIS.md).

## 1. Ziel

TIM auf zwei Rechner aufteilen, damit Phase 1 (Datenstabilität) erreichbar
wird und später Backtest, Paper Trading und die Capital Ladder auf belastbarer
Evidenz aufbauen.

- **Debian-Server:** Betrieb, 24/7. Erzeugt Evidenz.
- **Mac:** Forschung. Erzeugt Hypothesen.
- **Grundregel:** Nichts wird promotet, was nicht auf dem Server im
  Paper-Modus die Gates der Roadmap bestanden hat.

## 2. Ausgangslage (belegt im Repo)

| Punkt | Wert | Quelle |
|---|---|---|
| Modus | OBSERVE-only, Core 1.0 FROZEN | `docs/TIM_V1_LIVE_STATUS.md`, `TIM_V2_BLOCKER_REGISTER.md` |
| Continuous Coverage | 60,659 % (Gate V2: ≥ 95 %, Phase 1: ≥ 99,5 %) | `TIM_COVERAGE_ROOT_CAUSE_ANALYSIS.md` |
| Fehlende 1m-Minuten | 430 von 1.093, davon 415 als Input/Persistenz-Ausfall klassifiziert | ebd. |
| Offene V2-Blocker | V2-B01 bis V2-B08, alle OPEN | `TIM_V2_BLOCKER_REGISTER.md` |
| Datenquelle | Binance Spot aggTrade (public WebSocket), Reconnect ohne Catch-up | `CURRENT_STATE_ASSESSMENT.md` |
| Fehlend für Futures | Funding, Mark Price, Orderbook, Latenz | `IMPLEMENTATION_ROADMAP.md` |
| Strategie-/Risk-/Order-Contracts | existieren nicht | ebd. |

**Einordnung:** Die Roadmap nennt „historical host-sleep gaps" als Blocker für
Phase 1. Die physische Ursache der einzelnen Lücken ist laut Root-Cause-Analyse
nicht belegt (UNKNOWN). Ein dauerhaft laufender Server beseitigt die
Sleep-Hypothese als Ursache und macht die verbleibenden Ursachen messbar.

## 3. Rollenverteilung

### Debian-Server (Betrieb)

- Collector (`main.py`, `src/data_ingestion/`) als `systemd`-Service mit
  `Restart=always` und Watchdog.
- PostgreSQL lokal auf dem Server, tägliches Backup mit Restore-Test.
- Health- und Gap-Monitoring mit Alert (Mail oder Telegram) bei Datenlücke,
  Prozessausfall oder vollem Datenträger.
- Zeitsynchronisation (`chrony`), damit Minutengrenzen und Hashes stimmen.
- Später (erst nach Freigabe der jeweiligen Phase): Paper-Engine im
  Dauerlauf, danach Shadow, danach Limited Live mit Kill-Switch,
  API-Keys ohne Withdraw-Recht und IP-Whitelist.

### Mac (Forschung)

- Codex-Tasks, Strategieentwicklung, Code-Reviews.
- Backtests und Walk-Forward auf einer Read-only-Kopie der Server-Daten
  (Replikat oder Snapshot per `rsync`/`pg_dump`), nie auf der Produktions-DB.
- Ollama/Qwen nur für qualitative Beobachtung und Reports, nicht für
  Handelsentscheidungen.
- Auswertung der Paper-Ergebnisse als Input für die Promotion Gates.

## 4. Roadmap, abgebildet auf die bestehenden Phasen

| Schritt | Roadmap-Phase | Maschine | Ergebnis / Abnahme |
|---|---|---|---|
| 1. Server-Betrieb aufsetzen | 1 Datenstabilität | Debian | Collector läuft als Service; prospektives Messfenster ist vorab definiert |
| 2. Coverage-Nachweis | 1 | Debian | ≥ 99,5 % Coverage, keine unbekannten Gaps, Provenance pro Zeile; schließt V2-B01/B02 prospektiv |
| 3. Zusatzdaten (Funding, OI, Mark Price, Orderbook) | 1 → 2 | Debian | eigener Collector je Quelle, gleiche Quality Gates |
| 4. Hypothesen-Pipeline | 2–4 | Mac | Konzepte (z. B. CVD-Divergenz, Funding/OI-Extreme, Liquidity Sweeps) als deterministische, einzeln testbare Regeln; eine Hypothese pro Codex-Task |
| 5. Harte Validierung | 5–6 | Mac | Forward-only-Backtest mit Fees, Slippage, Funding; Walk-Forward/OOS mit vorab festgelegten Splits; Korrektur für Mehrfachtests (z. B. Deflated Sharpe) |
| 6. Risk Engine | 7 | beide | Denial-/Bypass-Testsuite grün |
| 7. Paper Trading | 8 | Debian | 30–60 Tage ohne Integritätsfehler; Abweichung Paper vs. Backtest dokumentiert |
| 8. Shadow, dann Micro-Live | 9–10 | Debian | nur mit separater, ausdrücklicher Freigabe; minimales Kapital, niedriger Hebel |

## 5. Leitplanken

- **Engpass ist Edge, nicht Governance:** Governance nur so weit ausbauen, wie
  das nächste Gate es verlangt.
- **Scope:** ein Instrument, ein Timeframe, eine Strategie zuerst.
- **Hebel:** konservativ. Hohe Hebel sind mit der Capital Ladder unvereinbar.
- **Erwartung:** Die meisten Hypothesen scheitern. Erfolg heißt, sie schnell
  und sauber zu verwerfen.
- **Secrets:** keine Zugangsdaten im Repo, in Übergaben oder Commits.

## 6. Nächster konkreter Schritt

Codex-Task-Paket für Schritt 1: Debian-Server-Setup für den bestehenden
Collector (systemd-Unit, PostgreSQL, Backup, Monitoring, `chrony`), mit
Prüfbefehlen und ohne Änderung an Core-1.0-Logik. Umsetzung erst nach Go.

## 7. Offene Fragen

- Debian-Hardware, Netzwerk und Standort (Uptime, USV)?
- Bleibt Binance Spot die Primärquelle, oder kommt Bybit (wie in Bronxc) hinzu?
- Welches prospektive Messfenster soll für den Phase-1-Nachweis gelten?
