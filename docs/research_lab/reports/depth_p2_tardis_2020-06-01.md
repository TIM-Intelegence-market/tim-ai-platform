# Orderbuch-Recorder P2: Abgleich mit einem Tardis-Tag (2020-06-01)

STATUS: bestanden mit Vorbehalt (Zeitversatz zwischen Buch- und Trade-Strom, siehe unten).
Plan: `../ORDERBUCH_RECORDER_BAUPLAN.md`, Paket P2. Datum 12.11.2026, Code `src/research_lab/depth/tardis.py`.

## Was geprüft wurde

Der Buchnachbau von TIM (`LocalBook`, derselbe wie im Recorder) liest einen ganzen Tag Binance USDⓈ-M BTCUSDT
aus den kostenlosen Tardis-Dateien (`incremental_book_L2`, `trades`, 1. des Monats, ohne API-Schlüssel). Jeder
Trade wird mit dem Buch unmittelbar davor verglichen: Ein Kauf per Marktorder darf nicht unter dem besten Ask
liegen, ein Verkauf nicht über dem besten Bid. Keine Signale, keine Merkmale, kein Studienwert.

Nutzungsbedingungen (docs.tardis.dev/legal/terms-of-service, Stand 28.10.2026): interne Forschung erlaubt, auch
für Probedaten; Rohdaten dürfen nicht weitergegeben werden (Klausel 9.2), abgeleitete Kennzahlen in Berichten schon
(9.3). Rohdaten liegen deshalb nicht im Repo.

## Ergebnis

| Größe | Wert |
|---|---|
| Dateigröße gepackt | Buch 408 MB, Trades 12 MB |
| Buchzeilen (Stufen-Änderungen) | 62.152.139 |
| Trades | 922.467 |
| Snapshot-Neustarts im Tag | 1 (nur der Anfang, keine Lücke) |
| Stufen im Buch, höchstens | 10.193 |
| Sekunden mit Buch | 86.395 von 86.400 |
| Sekunden mit gekreuztem Buch | **0** |
| Rechenzeit (Python, eine CPU) | 6 min |

Gekreuzte Zustände gibt es nur zwischen den Zeilen einer Nachricht (501.785 Zeilen), nie an einer Sekundengrenze:
Tardis zerlegt eine Binance-Nachricht in einzelne Stufen-Zeilen.

**Tickgröße:** Im Juni 2020 lag der Spread in 83 % der Sekunden bei **0,01 USDT**. Der Tick war damals also 0,01,
heute ist er 0,1. Der Abgleich nimmt den Tick deshalb als Parameter (`--tick`).

**Trades gegen Buch** (Abweichung = wie weit der Trade auf der falschen Seite des besten Preises liegt):

| Reihenfolge | genau passend | ≤ 0,10 USDT | ≤ 1 USDT |
|---|---:|---:|---:|
| nach Empfangszeit (`local_timestamp`) | 90,2 % | 94,2 % | 98,5 % |
| nach Börsenzeit (`timestamp`) | 87,2 % | 92,7 % | 98,2 % |

## Einordnung

- Das Buch selbst ist in sich stimmig: ein Snapshot, danach lückenlos, an keiner Sekundengrenze gekreuzt.
- Die Abweichungen der Trades kommen aus dem Zeitversatz zweier getrennter Ströme (Buch und Trades). Ein Trade
  kann vor oder nach der Buchänderung ankommen, die ihn abbildet. Das ist kein Fehler im Nachbau, setzt aber eine
  Grenze: Merkmale aus Buch und Trades lassen sich nur auf etwa 100 ms genau gemeinsam auswerten.
- Folge für eine Studie: Signale aus dem Buch auf vollen Sekunden bilden, Ergebnis an der Mitte messen, Einstieg
  frühestens eine Sekunde später (so war S32-Entwurf 0.1 bereits angelegt).
- Datenmenge und Rechenzeit sind tragbar: 55 Tage (Training und Validierung) ≈ 22 GB gepackt, ≈ 6 h Rechenzeit.
- Offen für P3: Größe der eigenen Live-Aufzeichnung (rohes JSON statt CSV, 2026 vermutlich mehr Verkehr als 2020).

NEXT_ACTION: P3 (72-h-Probelauf des Recorders) braucht Uzis Freigabe und eine Maschine.
