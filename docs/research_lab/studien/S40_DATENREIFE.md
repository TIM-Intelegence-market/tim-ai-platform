# S40 – Datenreife (Paket 1)

Stand: 24.11.2026. Nur gelesen, kein Ergebnis einer Studie. Erzeugt mit
`python -m src.research_lab.studies.s40_daten bericht --ziel ~/Documents/TIM/s40-data`
auf dem Mac (Klon `~/Documents/TIM/worktrees/s40`, Code fb75842). Die volle Datei
`datenreife.json` (Werte je Monat, ca. 50 KB) liegt auf dem Mac und ist nicht im Repo.

## Ladelauf

- Start 23.11.2026 21:18 Ortszeit. Deribit fertig 23.11. 23:14 Ortszeit, Binance 24.11. 04:48 Ortszeit.
- Beide Läufe meldeten "fertig" und beendeten sich selbst; kein Neustart, kein fehlgeschlagener Tag im Log.
- Zeitraum bis 31.12.2024. Dateien ab 2025 wurden nicht geladen (Holdout-Sperre).
- Umfang auf der Platte: 481 MB.

## Bericht

Grenzen: Lücken bis 10 Minuten (`GAP_MS`), Lückenanteil je Monat unter 2 % (`MAX_GAP_SHARE`);
Deribit: ein Monat ist gültig, wenn jeder Tag geladen ist und die Mindestzahl an Trades hat.

| Quelle | gültige Monate | Anteil Training | Anteil Validierung | prüfbar |
|---|---|---|---|---|
| BTCUSDT (Binance-Perp) | 60 / 60 | 100 % | 100 % | ja |
| ETHUSDT (Binance-Perp) | 60 / 60 | 100 % | 100 % | ja |
| SOLUSDT (Binance-Perp) | 52 / 52 (ab 2020-09, Listung) | 100 % | 100 % | ja |
| Deribit BTC-Optionen | 60 / 60 | 100 % | 100 % | ja |
| Funding | vollständig | – | – | – |

## Folgen für die Präregistrierung

- Kein Markt fällt unter die 70-%-Regel; alle zwölf Tests T1–T12 bleiben prüfbar.
- Startmonat Optionsflow: **2020-01** (erster gültiger Deribit-Monat), in `s40.py` als
  `OPTIONS_START_MONTH = "2020-01"` eingetragen.
- SOL beginnt durch die Listung erst im September 2020; das z-Fenster (720 h) und der
  Warm-up von 21 Tagen gelten ab dort, wie im Code vorgesehen.
