# 4h- und Tageskerzen (Paket H2)

Stand 25.10.2026, aus `docs/audits/GRUEN_PLAN_11_SICHTEN.md`. Auftrag Uzi (25.10.): Für die höheren Zeitebenen braucht TIM
eigene Forschungsdaten.

## Was neu ist

TIM speichert jetzt **4h- und 1d-Kerzen** in der Tabelle `candles`, abgeleitet aus den vorhandenen 1h-Kerzen
(`src/data_ingestion/derived_candles.py`). Ein eigener Durchlauf in der Runtime (`tim-derived-candles`, alle 5 Minuten)
liest die 1h-Kerzen seit dem letzten abgeleiteten Bucket und schreibt jeden vollständigen 4h- und Tagesbucket.

| | 1m, 5m, 15m, 1h | 4h, 1d |
|---|---|---|
| Quelle | Live-Aggregation aus aggTrades (`CandleAggregator`) | Ableitung aus persistierten 1h-Kerzen |
| Wann | je Trade | alle 5 Minuten, nur geschlossene Buckets |
| Bei Lücken | Lückenbehandlung über `history-recovery` | Bucket wird **ausgelassen**, nicht genähert |
| Ausrichtung | `bucket_start` | 4h: 00/04/08/12/16/20 UTC, 1d: 00:00 UTC |
| API | `/api/state` | `/api/candles-derived?tf=4h` und `?tf=1d` (letzte 300) |

## Warum abgeleitet statt live aggregiert

Die Live-Aggregation kennt 4h und 1d bereits (`TIMEFRAME_SECONDS`), aber jede Wiederholung oder Lückenreparatur setzt
beim Anfang des größten Buckets an (`recovery.py`, `replay_start`). Mit 1d hieße das: jeder Reparaturlauf liest einen
ganzen Tag aggTrades neu. Die Ableitung aus 1h kostet pro Durchlauf ein paar Zeilen und berührt den Dateneingang nicht.

## Grenzen

- Erster Durchlauf: Rückblick 90 Tage auf die 1h-Kerzen (seit Juli reicht das für den ganzen Bestand).
- Ein Tagesbucket entsteht nur, wenn alle 24 Stunden vorhanden sind. Bei 72,4 % Oktober-Abdeckung (Messung 20.10.)
  fehlen entsprechend viele Tage. Das ist gewollt: lieber eine fehlende Zeile als eine falsche Kerze.
- Die Beobachtungs-Engine läuft **nicht** auf 4h/1d (`TIM_TIMEFRAMES` unverändert). HTF-Beobachtungen sind ein eigenes
  Paket, erst wenn Daten da sind.
- Die Chart-Seite `/chart` bezieht ihre HTF-Kerzen weiter von Binance (`chart_history.py`); die abgeleiteten Kerzen sind
  die TIM-eigene, reproduzierbare Fassung für Forschung.

## Schema

Constraint `candles_timeframe_allowed` erlaubt jetzt `1m,5m,15m,1h,4h,1d`. `schema.sql` löscht und setzt die Constraint
neu, damit `--init-schema` beim Start eine ältere Installation mitzieht; Migration `009_candles_4h_1d.sql` für den
Handbetrieb.

## Prüfen

```sh
python -m pytest tests/test_derived_candles.py -q
curl -s 'http://127.0.0.1:8765/api/candles-derived?tf=1d' | head -c 400      # auf dem Mac, nach dem Einspielen
```
