# Datenlücken holt TIM selbst nach (Issue #82)

Stand 07.11.2026. Gilt für die Runtime (`main.py`), auf dem Mac (`~/TIM-live`) und auf tim-core-01.

## Was sich ändert

Bisher hat die Runtime nach einem Ausfall keinen Live-Trade angenommen, bevor die ganze Lücke nachgeholt war.
Der Nachhol-Versuch hatte 300 s und schaffte etwa 25 Trades/s. Bei langen Ausfällen wuchs die Lücke schneller,
als sie sich füllte, und jeder längere Ausfall brauchte einen manuellen Cutover (`scripts/apply_live_cutover.py`).

Jetzt gilt:

1. **Live zuerst.** Nach einem Reconnect holt die Runtime die Lücke höchstens `TIM_GAP_INLINE_SECONDS` (Standard 60 s)
   direkt nach. Ist sie dann noch nicht zu, bleibt sie mit genauen Trade-IDs als `OPEN` im Lücken-Register
   (`ingestion_gap_incidents`), und Live-Trades fließen sofort weiter. Metrik: `gap_deferred_to_background_total`.
2. **Nachholer im Hintergrund** (`src/data_ingestion/gap_filler.py`, Task `tim-gap-filler` in der Runtime):
   nimmt die offenen Lücken, die neueste zuerst, und holt sie über die öffentliche Binance-REST-Schnittstelle
   (ohne Schlüssel) nach. Eine Lücke wird erst `RESOLVED`, wenn jede ID ihres Bereichs gespeichert ist.
3. **Schnell schreiben.** Hinter dem Live-Zeiger schreibt der Nachholer eine Seite (1.000 Trades) in einer
   Transaktion (`DurableIngestionStore.ingest_historical_batch`). Gemessen auf PostgreSQL 16: rund 11.000 Trades/s
   statt 25. Die Binance-Abfrage (eine Seite je 0,2 s) begrenzt auf etwa 5.000 Trades/s; 3 Mio. Trades dauern
   damit rechnerisch rund 10 Minuten.
4. **Kerzen nachbauen.** Nachgeholte Trades kommen als `DEFERRED` in die Outbox und stehen so nie vor der Live-Arbeit.
   Nach jeder Runde baut der Nachholer die geschlossenen 1m-Kerzen dieser Minuten aus den Rohdaten neu
   (`deferred_candles.rebuild_deferred_candles`, höchstens 500 Minuten je Runde). Minuten, die eine offene Lücke
   noch berührt oder in denen Live-Arbeit liegt, wartet er ab. Der Neubau liest nur `DEFERRED`-Zeilen ab der kleinsten
   Trade-ID, die der Nachholer selbst geschrieben hat (`rebuild_from_trade_id` im Bericht). Die Millionen alter
   `DEFERRED`-Zeilen früherer Cutover bleiben beim Offline-Werkzeug `scripts/rebuild_deferred_candles.py`; sie alle zu
   lesen dauerte am 07.11. über 10 Minuten. Der Neubau läuft jede Runde nur, solange er etwas baut oder neue Trades
   geschrieben wurden, sonst höchstens alle 30 Minuten. Scheitert er, steht der Fehler als `candle_error` im Bericht,
   und das Nachholen der Lücken läuft trotzdem weiter.
5. **Anzeige.** Control Center, Betrieb → Eigene Marktdaten → Kachel „Datenlücken (Nachholer)“ (liest
   `data/operational/gap_filler.json`). Grün: keine Lücke oder die Lücken werden kleiner. Gelb: seit über 6 h kein
   Fortschritt. Rot: Fehler im Nachholer.

## Grenzen

- Lücken ohne ID-Bereich und Lücken über 20 Mio. Trades (etwa eine Woche) nimmt der Nachholer nicht selbst.
  Das sind alte Belegbereiche, die bleiben offen und erscheinen als `too_large_gaps` im Bericht.
- Liefert Binance für einen Bereich nichts, wartet der Nachholer bei dieser Lücke immer länger (bis 6 h) und
  versucht es dann erneut.
- Neu gebaut werden nur die 1m-Kerzen. 5m/15m/1h-Kerzen der nachgeholten Zeit baut die Runtime nicht rückwirkend.
- Kein Handel, keine Schlüssel: Modus OBSERVE, `trading_actions` 0.

## Schalter

| Variable | Standard | Wirkung |
|---|---|---|
| `TIM_GAP_BACKGROUND_FILL` | `true` | `false` stellt das alte Verhalten her: kein Live-Trade, bis die Lücke zu ist; kein Nachholer. |
| `TIM_GAP_INLINE_SECONDS` | `60` | Zeit für das direkte Nachholen vor dem ersten Live-Trade (5–110 s). |

Der manuelle Cutover (`scripts/apply_live_cutover.py`) bleibt als Notweg erhalten, ebenso `scripts/tim_catchup.py --open-gaps`.

## Tests

`tests/test_gap_filler.py`: Aufschieben mit Zeitbudget, Nachholer-Regeln, und mit PostgreSQL
(`TIM_DURABLE_TEST_DATABASE_URL`) der nachgestellte Ausfall: 40.000 fehlende Trades, Live nach Sekunden wieder da,
Lücke danach zu, Zeiger unverändert, Kerzen neu gebaut. Dazu eine Messung des Batch-Schreibens (100.000 Trades).
