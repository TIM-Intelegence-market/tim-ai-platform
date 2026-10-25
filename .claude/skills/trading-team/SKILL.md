---
name: trading-team
description: Papier-Trading-Team aus drei Bots für Krypto - Scanner (Binance-Kursausschläge mit Volumen), Buzz-Tracker (CoinGecko-Trends und Krypto-Schlagzeilen, Score 0-10) und Papier-Bot (fiktive 1.000 USD, 1 % Risiko, Stop und Ziel, Gebühren) - plus ehrlicher Bericht. Nur öffentliche Daten, kein Echtgeld, keine Orders. Verwenden bei "Trading-Team", "Scanner-Bot", "Buzz-Tracker", "Papier-Trading-Bot", "fake money bot", "Team laufen lassen", "ehrlicher Bericht über trades.csv".
---

# Trading-Team (nur Papier)

Umsetzung der Anleitung „Build a 24/7 AI Trading Team With Claude Code“ (MSB Intel, von Uzi am
23.10.2026 geschickt) für TIM. Herkunft und Abweichungen: `HERKUNFT.md`.

**Grenzen:** Kein Echtgeld, keine Börsenkonten, keine API-Schlüssel, keine Orders. Die Skripte rufen nur
öffentliche Lese-Endpunkte auf (`api.binance.com` Marktdaten, `api.coingecko.com`, RSS von CoinDesk,
Cointelegraph, Decrypt). Ergebnisse sind Research, kein Handelssignal für TIM. Nicht an TIM-Order-Pfade
oder `~/TIM-live` anbinden.

## Die drei Bots

| Bot | Skript | Regel | Ausgabe |
|---|---|---|---|
| Scanner | `scripts/scanner.py` | Top 100 USDT-Paare nach 24h-Umsatz; letzte abgeschlossene 1h-Kerze bewegt sich > 3 % **und** ihr Umsatz ist ≥ 2x der durchschnittliche Stundenumsatz der 7 Tage davor | `scanner.csv` |
| Buzz-Tracker | `scripts/buzz.py` | CoinGecko-Trendliste (bis 6 Punkte nach Rang) + Schlagzeilen der letzten 24 h (bis 4 Punkte), Score 0-10 mit Begründung | `buzz.csv` |
| Papier-Bot | `scripts/paper_bot.py` | Kauf nur bei Scanner-Treffer nach oben **und** Buzz ≥ 7; 1 % Risiko, Stop 3 %, Ziel 2R, 24 h Zeitlimit, 0,1 % Gebühr + 0,05 % Schlupf je Seite, max. 10 Trades/Tag | `trades.csv`, `signals.csv`, `state.json` |
| Bericht | `scripts/report.py` | Trades, Trefferquote, Ergebnis nach Gebühren, größter Verlust, Erwartungswert in R, Buzz-Vergleich, strenges Urteil | Text oder `--json` |

Zusätzlich führt der Bot ein **Schatten-Buch**: Treffer mit Buzz < 7 werden nach denselben Regeln nur
mitgerechnet (ohne Kontowirkung). Nur so lässt sich die Frage der Anleitung beantworten, ob der Buzz-Score
überhaupt hilft.

## Ablauf

Ablage standardmäßig `state/trading-team/` im Arbeitsordner (per `.gitignore` ausgeschlossen), änderbar mit
`--data-dir` oder `TRADING_TEAM_DIR`. Nur Python-Standardbibliothek, ab Python 3.10.

```bash
S=.claude/skills/trading-team/scripts
python3 $S/run_team.py                 # ein Durchlauf: Scanner -> Buzz -> Papier-Bot
python3 $S/run_team.py --loop          # alle 5 Minuten, bis Strg+C
python3 $S/report.py                   # ehrlicher Bericht (nach 2-4 Wochen)
python3 $S/scanner.py --top 50 --move-pct 4   # Einzelne Bots mit eigenen Schwellen
```

In der Cloud sind Binance, CoinGecko und die Feeds gesperrt: dort nur mit `--market-snapshot` /
`--buzz-snapshot` (Format in den Docstrings von `common.SnapshotMarket` und `buzz.SnapshotBuzzSources`).
Live läuft es auf dem Mac.

## 24/7 auf dem Mac

Der Server ist raus, TIM läuft auf dem Mac. Vorlage für einen launchd-Dienst:
`references/com.tim.trading-team.plist.example`. Seit 24.10.2026 auf Uzis Wort eingerichtet: Dienst
`com.tim.trading-team`, Checkout `~/TIM-trading-team`, Daten und Logs in `~/TIM-trading-team/state/trading-team/`.
Aktualisieren: `git -C ~/TIM-trading-team pull`. Stoppen: `launchctl bootout gui/$(id -u)/com.tim.trading-team`. Der Bot lädt pro Lauf rund 100 Kerzenreihen
(öffentliche Binance-Gewichtsgrenze wird nicht annähernd erreicht).

## Bericht bewerten (Schritt „grade it honestly“)

Nach 2-4 Wochen `report.py` laufen lassen und dann mit Claude bewerten:

> Lies trades.csv und den Bericht. Gib mir einen ehrlichen Bericht: Anzahl Trades, Trefferquote, Ergebnis
> nach Gebühren, größter Verlust, und ob der Buzz-Score geholfen hat. Würde das realistisch mit echten
> Orders Geld verdienen? Nichts beschönigen.

Weiterführend: `backtest-expert` und `edge-strategy-reviewer` für die Prüfung, `signal-postmortem` für
einzelne Signale, `drawdown-circuit-breaker` für Verlustgrenzen.

## Tests

```bash
python3 -m pytest .claude/skills/trading-team/scripts/tests -q
```

20 Tests, offline. `tests/test_safety.py` prüft statisch, dass kein Order-, Schlüssel- oder Testnet-Code und
nur die erlaubten öffentlichen Hosts vorkommen. Die Tests laufen nicht in der TIM-Suite (`pytest tests/`).
