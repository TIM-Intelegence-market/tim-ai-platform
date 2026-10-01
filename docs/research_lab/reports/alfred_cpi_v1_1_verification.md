# ALFRED CPI – Real-Data-Verifikation (BTC Research Engine V1.1)

Erzeugt mit `scripts/research_lab_alfred_ingest.py verify` und `replay` aus einem gespeicherten
Download; Rohdaten liegen nur lokal (`data/research_lab/external/`, nicht im Repository).

| Feld | Wert |
|---|---|
| Serie | `CPIAUCSL` (research-2017-2024) |
| Bundle | `7e1c2a85a9d64fee13896935411ea85c9657580743a6390aaeee6ce5513d2476` |
| Abgerufen | 2026-10-01T20:31:02.084004+00:00 |
| Perioden (Forschung) | 2017-01-01 … 2024-11-01 (95) |
| Holdout | CLOSED (letztes Vintage 2024-12-11, letzter Termin 2024-12-11, Anfrage bis 2024-12-31) |

## Payload-Hashes (SHA-256)

| Payload | SHA-256 |
|---|---|
| observations | `d68bbbd8738f36671bdf91e2e17064468152627ec6e2c798368386b153ca73c5` |
| release_dates | `e515b7d853a41ba0908367fe9e54ecc61c7c26f44b0cf6f6db0ac2f8f96d4d8f` |
| series | `90bab80744c992336277a46b5a880937796e72b2b38ebd2c0bdf9a5476c360e0` |

## Befunde

| Beleg | Aussage |
|---|---|
| `SOURCE_VERIFIED` | Antwort-Envelope gibt die Anfrage exakt wieder: Real-Time 1776-07-04 … 2024-12-31, Beobachtungen 2016-01-01 … 2024-12-31, `output_type=1`, `count=471` = Zeilen 471, `offset=0`. |
| `SOURCE_VERIFIED` | 471 Zeilen, 107 Perioden 2016-01-01 … 2024-11-01, ohne Monatslücke (0 Lücken); 114 verschiedene Vintage-Daten 2016-02-19 … 2024-12-11. |
| `SOURCE_VERIFIED` | Werte je Periode: 1 … 7, Verteilung {'1': 11, '2': 12, '3': 12, '4': 12, '5': 12, '6': 44, '7': 4}. Im Forschungsbereich: 395 Datensätze, 300 Revisionen in 84 Perioden, höchstens 6 Werte je Periode. |
| `SOURCE_VERIFIED` | Zeilen mit offenem Ende im Download: 0; ALFRED kappt `realtime_end` auf das angefragte Ende (2024-12-31). |
| `SOURCE_VERIFIED` | Serien-Metadaten kommen mit Real-Time-Bereich in mehreren Versionen (CPIAUCSL: 6; Einheit bis 1988 „Index 1967=100“); V1 verlangte genau eine Version und war mit echten Daten `NOT_READY` (behoben). |
| `SOURCE_VERIFIED` | Release-Kalender: 929 Termine 1949-03-24 … 2024-12-11, Release-IDs [10], aufsteigend geliefert: True, Duplikate: 0, Abstände 2 … 49 Tage. |
| `SOURCE_VERIFIED` | Ungewöhnliche Abstände (außerhalb 21–42 Tage) im ganzen Kalender: 18 Terminpaare im Abstand von 2–6 Tagen (Jahre 2005–2024, alle im Februar: True); weitere: 1995-12-14→1996-02-01 (49 d), 1996-02-28→1996-03-15 (16 d), 2000-09-15→2000-09-28 (13 d), 2000-09-28→2000-10-18 (20 d), 2013-09-17→2013-10-30 (43 d). |
| `SOURCE_VERIFIED` | Reine Revisionstermine im Forschungsbereich: 2017-02-13, 2019-02-11, 2020-02-11, 2021-02-08, 2022-02-08, 2023-02-10, 2024-02-09. An ihnen beginnen nur Revisionen älterer Perioden; die Januarzahl folgt am nächsten Termin. V1 erwartete den Erstdruck am ersten Termin nach Periodenende und meldete deshalb jeden Januar als fehlend (behoben). |
| `SOURCE_VERIFIED` | Kalendertermine im Forschungsbereich: 102; ohne Erstdruck: 0; Vintages außerhalb des Kalenders: 0; Perioden ohne Erstdruck: 0; fehlende Perioden: 0. |
| `SOURCE_VERIFIED` | Erstdruck 9 … 14 Tage nach Periodenende; 95 von 95 Erstdrucken auf einem Kalendertermin. |
| `SOURCE_VERIFIED` | Datenqualität: Zustand `READY`, Befunde keine, unbrauchbare Einträge keine. |
| `RULE_VERIFIED` | Release-Zeit 08:30 New York an Stichproben belegt (BLS-Sperrfrist): 2017-02-15 (January 2017): 8:30 a.m. (EST) = ALFRED-Erstdruck; 2020-02-13 (January 2020): 8:30 a.m. (EST) = ALFRED-Erstdruck; 2022-07-13 (June 2022): 8:30 a.m. (ET) = ALFRED-Erstdruck; 2024-01-11 (December 2023): 8:30 a.m. (ET) = ALFRED-Erstdruck. |
| `RULE_VERIFIED` | BLS: revised seasonally adjusted indexes for the previous five years are made available with a date but no stated time of day (https://www.bls.gov/cpi/seasonal-adjustment/); deshalb `END_OF_VINTAGE_DAY` für reine Revisionstermine. |
| `ASSUMPTION` | 08:30 New York gilt auch für die übrigen 91 Erstdrucke; ALFRED/FRED liefert keine Uhrzeit. |
| `ASSUMPTION` | Der nächste BLS-Termin ist am Revisionstermin bereits bekannt (BLS veröffentlicht den Kalender vorab); darauf stützt sich die Erkennung reiner Revisionstermine. |
| `LIMITATION` | ALFRED-Termine sind nicht vollständig gegen das BLS-Archiv abgeglichen (4 Stichproben). |
| `LIMITATION` | `revision_number` zählt Wertänderungen (`output_type=1`), nicht jede Veröffentlichung. |

## Replay 2017–2024

| Feld | Wert |
|---|---|
| Replay-Zeit | 2024-12-31T23:59:59+00:00 (letzter Zeitpunkt vor dem Holdout) |
| BTC | 64525 Kerzen 1h Spot 2017-08 … 2024-12 (Binance-Archiv, Checksumme geprüft); ausgeschlossen (`invalid_candles=exclude`): {'OFF_GRID': 43, 'WRONG_SPAN': 14}; danach erwartet 64651, vorhanden 64467, fehlend 184 (Archivlücken und ausgeschlossene Kerzen; Fenster mit fehlenden Kerzen sind `INSUFFICIENT_DATA`) |
| Zustand | READY |
| Dataset-ID | `0ab92b1218b421798490c5319663085ba038d7e379d0d1b0aa038848682707fb` |
| Content-Hash | `45cdf4bea48a690ee9740703461cf5c80518c5a2e210ecace499d95e261a86af` |
| Output-Hash | `805841d884655be098ccd7fed5ec24addd27f3d82cabdac53e2bde7cab439ca7` |
| Ereignisse | 107 ({'OK': 107}) |
| Zeitreihenzeilen | 64467 |

| Beleg | Prüfung | Ergebnis |
|---|---|---|
| `SOURCE_VERIFIED` | Finaler Replay beantwortet (Zustand `READY`, BTC-Kerzen und Ereignisse vorhanden) | PASS |
| `SOURCE_VERIFIED` | Wiederholung: gleiche Eingaben ⇒ gleiche Dataset-ID, Content- und Output-Hash | PASS |
| `SOURCE_VERIFIED` | Zeilen- und Kalenderreihenfolge umgedreht ⇒ gleiche Dataset-ID und Content-Hash (Output-Hash enthält die Payload-Hashes) | PASS |
| `SOURCE_VERIFIED` | Kein Ereignis und kein ausgerichteter Wert nach seiner Entscheidungszeit | PASS |
| `ASSUMPTION` | Stand 2020-01-31 (Archiv rekonstruiert: spätere Zeilen und Termine entfernt, gültige Zeilen auf den Stichtag gekappt), Replay 2020-01-31T23:00:00+00:00: Content-Hash gleich dem vollen Archiv | PASS |
| `ASSUMPTION` | Stand 2020-02-12 (Archiv rekonstruiert: spätere Zeilen und Termine entfernt, gültige Zeilen auf den Stichtag gekappt), Replay 2020-02-12T23:00:00+00:00: Archiv des Tages endet 2020-02-11T13:29:59.999999+00:00 (Revisionstermin noch nicht einordenbar) ⇒ `INSUFFICIENT_DATA`, bis dahin gleich: True | PASS |
| `ASSUMPTION` | Stand 2022-06-30 (Archiv rekonstruiert: spätere Zeilen und Termine entfernt, gültige Zeilen auf den Stichtag gekappt), Replay 2022-06-30T23:00:00+00:00: Content-Hash gleich dem vollen Archiv | PASS |
