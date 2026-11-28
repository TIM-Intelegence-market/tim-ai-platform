# Bauplan: Orderbuch-Recorder (Binance USDⓈ-M BTCUSDT)

**Status: P1 (Code, Tests) und P2 (Tardis-Abgleich, `reports/depth_p2_tardis_2020-06-01.md`) erledigt; P3 wartet auf Uzis Freigabe.** Anlass: Barti 12.11.2026, „bauen wir erstmal diesen Orderbuchrekorder und dann
machen wir die Studie“. Grundlage: `studien/S8_DEPTH_DATENVERTRAG_ENTWURF.md` (Entwurf 0.1).

## Warum

TIM speichert heute nur Trades (`agg_trades`, `venue_trades`, aggTrades-Archive). Das Orderbuch, also die wartenden
Limit-Orders, schreibt nichts dauerhaft mit:

- `orderflow_scenario` hat ein Feld für Orderbuch-Ungleichgewicht, das nur von außen gefüllt wird; OpenMarket liefert
  dafür nichts.
- Der Bitunix-Recorder (seit 12.11.2026) speichert nur die beste Stufe (`depth_book1`).
- Das Binance-Archiv `bookDepth` beginnt 2023-01 und kennt nur Bänder von ±1 bis ±5 %.

Ohne Orderbuch kann TIM Setups wie „Pfad des geringsten Widerstands“ (Range plus dünne Buchseite) weder erkennen
noch prüfen.

## Ziel und Erfolgskriterium

Das volle Orderbuch von Binance USDⓈ-M BTCUSDT wird lückenlos und nachprüfbar mitgeschrieben, sodass sich jeder
Buchzustand je Sekunde nachbauen lässt.

- Replay der Rohdaten ergibt dieselben Buchzustände wie der Live-Recorder (Prüfsumme je Sekunde).
- Probelauf 72 h: mindestens 99,5 % gültige Sekunden, längste Lücke ausgewiesen, Datenmenge je Tag gemessen.

## Bauart

- Quelle: Diff-Stream `btcusdt@depth@100ms` plus REST-Snapshot `/fapi/v1/depth` beim Start und nach jeder Lücke,
  Synchronisation nach S8-Vertrag Abschnitt 3 (für Futures mit `pu`/`u`). Dazu `btcusdt@aggTrade` für die
  Aggressor-Seite. Öffentlich, kein API-Schlüssel.
- Warum das volle Buch statt `depth20`: Historische Daten (Tardis.dev) haben dasselbe Diff-Format. Rückblick und
  Live-Erkennung nutzen dann denselben Buchnachbau.
- Ablage wie beim Bitunix-Recorder: gzip-JSONL je UTC-Tag und Lauf, Nachrichten unverändert plus Empfangszeit,
  `status.json`, markierte Lücken, Speicherfehler beenden den Lauf sichtbar. Nicht in der Runtime-Datenbank.

## Pakete

| Paket | Inhalt | Prüfung | Braucht |
|---|---|---|---|
| P1 | Recorder und Buchnachbau mit Tests (Neustart, Sequenzlücke, doppelte Nachricht, Snapshot älter als Puffer, Holdout-Sperre für Auswertung) | `pytest tests/test_research_lab_depth*.py` | Review |
| P2 | Derselbe Buchnachbau liest einen kostenlosen Tardis-Tag; jeder Trade liegt am besten Bid/Ask | Prüfskript, Bericht | AGB Tardis geprüft |
| P3 | Probelauf 72 h auf einer Maschine (Mac, tim-core-01 oder PS5) | Kriterien oben | **Uzis Freigabe** (S8-Vertrag, Abschnitt 6) |
| P4 | Dauerbetrieb mit Neustart-Automatik | Status und Lücken im Checkup | Uzi |

## Nicht-Ziele

Keine Orders, keine Anzeige im Chart, keine Änderung an `~/TIM-live` oder der Runtime-Datenbank, keine Studie in
diesem Plan. Die Studie (Orderbuch-Ungleichgewicht in einer Range) bekommt danach eine eigene Präregistrierung.

## Risiken

- Speicherbedarf unbekannt, wird in P3 gemessen; Speicherplan = Menge je Tag × Aufbewahrungstage × 1,3.
- Binance trennt spätestens nach 24 h; jede Neuverbindung erzeugt eine kurze, markierte Lücke.
- Snapshot-Abrufe kosten Request-Gewicht; nur beim Start und nach Lücken, nie periodisch.
- L2-Aggregat: keine Akteure, kein sicherer Nachweis von Spoofing oder Icebergs.

## Integritäts-Audit (Paket D)

Nur lesend und zeilenweise (konstanter Speicher, schreibt nie ins Archiv; Bericht als JSON auf stdout,
`--out` nur außerhalb von `--root`):

```
python -m src.research_lab.orderbook audit --root ~/Documents/TIM/orderbook/binance --symbol BTCUSDT \
    [--start ISO] [--end ISO] [--window-hours 72] [--pause-seconds 10] [--open-grace-seconds 120] [--out FILE]
```

- **Zeitabdeckung**: Anteil des Zeitraums mit Depth-Ereignissen; jeder Abstand > 1 s zählt ganz als Lücke.
  Pausen > `--pause-seconds` stehen mit Start, Ende, Dauer und Hinweis (`gap_row`, `restart`,
  `after_damaged_segment`) in der Liste, ab 10 min zusätzlich als Ausfall. Der Nenner steht im Bericht
  (`period`, ohne `--start/--end` erstes bis letztes Ereignis).
- **Ereignisvollständigkeit**: Update-ID-Kette wie im Buchnachbau (`pu` = vorheriges `u`, erstes Ereignis nach
  Snapshot mit `U <= lastUpdateId <= u`). Brüche einzeln gelistet; `gap`-Zeilen und Sitzungsstart setzen die
  Kette zurück (erklärt), eine Synchronisierung danach zählt als Resync.
- **Segmente**: `ok`, `damaged` (kein sauberes gzip-Ende, kaputte oder halbe Zeile, leer) oder `open`: das
  neueste Segment der neuesten Sitzung ohne gzip-Ende, zuletzt vor höchstens `--open-grace-seconds` geändert.
  Überlappende Sitzungen werden gelistet.
- **Buchgültigkeit**: Ereignisse ohne synchronisiertes Buch (vor dem ersten Snapshot, nach Bruch, `gap`-Zeile
  oder Neustart bis zum nächsten Sync) zählen als "unsynced": nicht abgedeckt in `book_coverage`, und ein
  solcher Abschnitt über 60 s beendet ein sauberes Fenster. Ereignisse ganz ohne Snapshot ergeben FAIL.
- **Abnahme "72 h durchgehend"** (Konstanten in `audit.py`, vor Blick auf die Daten festgelegt, nicht
  nachjustieren): ein 72-h-Fenster ohne Pause > 60 s, ohne unsynced-Abschnitt > 60 s, ohne Sequenzbruch, ohne
  beschädigtes Segment, unlesbare Zeile oder Überlappung, mit Abdeckung (Ereignisse *und* gültiges Buch)
  ≥ 99,9 % (höchstens 259 s Lücke). Ergebnis PASS/FAIL mit Gründen, längster sauberer Abschnitt und bestem
  Fenster. Das P3-Kriterium oben (99,5 % gültige Sekunden) ist ein eigenes Gate und steht getrennt unter
  `acceptance.p3_valid_seconds`.
- **Welches Fenster**: `period.scope` = `current` (`--current`: genau die letzten 72 h bis jetzt, Zustand des
  laufenden Recorders, ein laufender Ausfall zählt mit), `explicit` (`--start/--end`) oder `historical`
  (erstes bis letztes Ereignis: bestes *historisches* Fenster, kein Betriebszustand).
- Alle Zeiten UTC als ISO und Epoch-ms; `--start/--end` ohne Offset gelten als UTC.
