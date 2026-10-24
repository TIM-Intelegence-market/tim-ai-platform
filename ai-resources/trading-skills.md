# Trading-Skills aus claude-trading-skills

Stand 22.10.2026. Quelle: <https://github.com/tradermonty/claude-trading-skills>, Commit `cb0f3aa`
(19.10.2026), MIT-Lizenz, Copyright (c) 2026 TraderMonty. Die Sammlung hat rund 75 Skills; viele sind auf
US-Aktien, Dividenden und den kostenpflichtigen Datendienst FMP zugeschnitten. Übernommen wurden nur die zehn,
die zu TIM passen: BTC/Krypto, nur Papier, kein Echtgeld, Fokus auf Risiko, Journal und Research.

Ablage: `.claude/skills/<name>/`, Dateien unverändert, dazu je Skill `LICENSE` (MIT-Text) und `HERKUNFT.md`
(Prüfung, Abhängigkeiten, TIM-Hinweise).

## Übernommen

| Skill | Wofür in TIM | Netz / Schlüssel |
|---|---|---|
| `crypto-regime-analyzer` | Krypto-Marktregime 0-100 als Lagebild | CoinGecko + Binance-Funding, öffentlich, ohne Schlüssel; Offline-Modus möglich |
| `position-sizer` | Positionsgröße aus Risiko, Stop, ATR oder Kelly | keins |
| `futures-position-sizer` | Kontraktgröße (nur CME-Futures, z. B. CME-Bitcoin) | keins |
| `drawdown-circuit-breaker` | Tages-/Wochen-/Monatsverlust-Sperre, Verlustserie | keins |
| `pre-trade-discipline-gate` | Checkliste vor jedem Papier-Einstieg | keins |
| `trader-memory-core` | Thesen-Journal (Idee bis Postmortem) | keins (FMP optional, nicht einrichten) |
| `signal-postmortem` | Signale nachträglich bewerten | keins (FMP optional, nicht einrichten) |
| `backtest-expert` | Backtest-Bewertung, Overfitting-Check | keins |
| `edge-strategy-reviewer` | Strategie-Entwürfe kritisch prüfen | keins |
| `trade-hypothesis-ideator` | Prüfbare Hypothesen für das Research Lab | keins |

Typischer Ablauf: Regime prüfen (`crypto-regime-analyzer`) → Schutzschalter (`drawdown-circuit-breaker`) →
Größe (`position-sizer`) → Checkliste (`pre-trade-discipline-gate`) → Journal (`trader-memory-core`) →
Nachbetrachtung (`signal-postmortem`). Research-Seite: `trade-hypothesis-ideator` → `edge-strategy-reviewer`
→ `backtest-expert`.

## Ergänzt: `trading-team` (23.10.2026)

Eigener Skill nach der Anleitung „Build a 24/7 AI Trading Team With Claude Code“ (MSB Intel), in TIM neu
geschrieben: Scanner (Binance-Stundenausschlag + Volumen), Buzz-Tracker (CoinGecko-Trends + RSS-Schlagzeilen),
Papier-Bot (fiktive 1.000 USD, 1 % Risiko, Stop/Ziel, Gebühren, max. 10 Trades/Tag) mit Schatten-Buch und
ehrlichem Bericht. Echtgeld-Teile, X-API und Cloud-Server weggelassen. Details:
`.claude/skills/trading-team/SKILL.md` und `HERKUNFT.md`.

## Bewusst weggelassen

- US-Aktien-Screener und -Analysen (CANSLIM, VCP, PEAD, Stockbee, Finviz, Value/Dividende, Kanchi, Sektoren,
  Marktbreite, IBD, FTD, Bubble/Top-Detektor u. a.): passen nicht zu BTC, brauchen meist FMP.
- `portfolio-manager` (Alpaca-Broker), `mt5-robot-tester`, `options-strategy-advisor`: Broker- oder
  Ausführungsnähe, nicht Teil von TIM V2.
- Edge-Pipeline (`edge-candidate-agent`, `edge-pipeline-orchestrator`, `edge-signal-aggregator`,
  `edge-strategy-designer` u. a.): eng an US-Aktiendaten gekoppelt; nur der Reviewer ist allgemein nutzbar.
- `technical-analyst`: braucht Chart-Bilder, TIM hat dafür eigene Analysen.
- `manifoldbt-backtester`: braucht eine fremde Rust-Engine; TIM hat das Research Lab.

## Grenzen

- Nur Analyse, Papier und Journal. Keiner der Skills führt Orders aus oder spricht einen Broker an
  (statisch geprüft, siehe `HERKUNFT.md`). Nicht an TIM-Order-Pfade anbinden.
- Testlauf 22.10.2026 (Cloud, eigenes venv, Python 3.13): 1.156 von 1.161 mitgelieferten Tests bestanden.
  Die 5 Fehlschläge hängen an Upstream-Dateien, die bewusst nicht übernommen wurden: eine Doku-Datei
  (`edge-strategy-reviewer`, nur Abgleichstest) und der Skill `edge-candidate-agent` (optionaler
  Strategie-Export von `trade-hypothesis-ideator`, in TIM nicht nutzbar). Die Tests liegen unter
  `scripts/tests/` und laufen nicht in der TIM-Suite.
- Lokaler Zustand (`state/`, `reports/`) ist per `.gitignore` aus dem Repo ausgeschlossen.
- Die SKILL.md-Texte sprechen von „stock“, „shares“ und NYSE-Handelstagen. Für 24/7-Krypto heißt das:
  Kalender-Freigaben im Schutzschalter sind konservativ, Stückzahlen ggf. mit `--fractional`.
- V2-Kampagne: bis 23.11.2026 nichts davon in `~/TIM-live` einspielen.
