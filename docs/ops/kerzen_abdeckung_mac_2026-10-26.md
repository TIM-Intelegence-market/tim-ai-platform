# Kerzen-Abdeckung seit dem Mac-Umzug (Grün-Plan M1)

Gemessen 26.10.2026, 11:02 Ortszeit, von Uzi im Terminal auf dem Mac mini (nur SELECT, Live-Datenbank `tim`,
PostgreSQL 18). Zeitraum: ab 2026-10-22 00:00 UTC bis zum Abfragezeitpunkt (10:01 UTC). Nur geschlossene Kerzen.

| Symbol | Zeitstufe | Kerzen | erste | letzte | Soll | Ergebnis |
|---|---|---|---|---|---|---|
| BTCUSDT | 1m | 6362 | 22.10. 02:00 (Ortszeit) | 26.10. 11:01 | 4 × 1440 + 602 = 6362 | lückenlos, 100 % |
| BTCUSDT | 5m | 1272 | | 26.10. 10:55 | 6362 / 5 → 1272 | passt |
| BTCUSDT | 15m | 424 | | 26.10. 10:45 | 424 | passt |
| BTCUSDT | 1h | 106 | | 26.10. 10:00 | 106 | passt |
| BTCUSDT | 4h | 26 | | 26.10. 05:00 | 26 | passt (abgeleitet, H2) |
| BTCUSDT | 1d | 4 | | 25.10. 02:00 | 4 | passt (abgeleitet, H2) |

Tageswerte der 1m-Kerzen (Gruppierung nach Ortszeit Europe/Berlin): 22.10. 1320 (Tag beginnt erst 02:00 Ortszeit,
also 22 h), 23.10. 1440, 24.10. 1440, 25.10. 1500 (25 Stunden wegen der Zeitumstellung), 26.10. 662 bis 11:01
(99,9 %). Die 91,7 % und 104,2 % sind Artefakte der Tagesgrenze, keine Lücken. Kein Tag unter 95 %.

Ergebnis: Abdeckung seit dem Mac-Umzug ≥ 95 % erfüllt; genau genommen 100 % bei 1m. Rohdatei:
`~/Documents/TIM/worktrees/s2-zaehllauf/m1_abdeckung.txt` auf dem Mac. Nächste Messung zusammen mit dem
monatlichen Doku-Check (Register A26) oder nach einem Ausfall.
