# Kerzen für DEFERRED-Zeiträume nachbauen

Stand: 2026-10-12. Paket B5 (erster Teil) aus dem TIM-Gesamtplan. OBSERVE only, keine Handelsaktion.

## Problem

Der Live-Cutover (`scripts/apply_live_cutover.py`) und die Rückstau-Regel im
`DurableIngestionStore` setzen historische `CANDLE_V1`-Einträge der Outbox auf
`DEFERRED`. Die Rohtrades liegen vollständig in `agg_trades`, aber kein Worker
hat diese Minuten je zu Kerzen gemacht. Für diese Zeiträume fehlen 1m-Kerzen,
und der Lückenbericht kann sie nicht als "erledigt" ausweisen.

## Werkzeug

```bash
# Nur ansehen: Plan je Minute, nichts wird geschrieben
.venv/bin/python scripts/rebuild_deferred_candles.py --symbol BTCUSDT

# Ausführen, älteste Minuten zuerst, höchstens 500 je Lauf
.venv/bin/python scripts/rebuild_deferred_candles.py --symbol BTCUSDT --apply --max-minutes 500
```

Bibliothek: `src/data_ingestion/deferred_candles.py`
(`inventory`, `rebuild_deferred_candles`, `candle_output_hash`).

### Was es tut

1. Sucht die Minuten mit `DEFERRED`-Einträgen für `CANDLE_V1` (älteste zuerst, begrenzt durch `--max-minutes`).
2. Prüft je Minute drei Sperren, in dieser Reihenfolge:
   - `MINUTE_NOT_CLOSED`: die Minute ist noch nicht abgeschlossen (Schließzeit plus `--safety-seconds`, Standard 120 s).
   - `ACTIVE_LIVE_WORK_IN_MINUTE`: in der Minute liegt noch aktive `CANDLE_V1`-Arbeit (PENDING, PROCESSING, RETRY, QUARANTINED). Die Minute gehört dem Live-Worker.
   - `OPEN_GAP_TOUCHES_MINUTE`: eine OPEN/CATCHING_UP-Lücke grenzt an die Trade-IDs der Minute oder überlappt ihre Zeitspanne. Fehlende Trades könnten noch in diese Minute fallen; die Kerze wäre unvollständig.
3. Baut je freier Minute in einer eigenen Transaktion die geschlossene 1m-Kerze
   aus **allen** Rohtrades der Minute (dieselbe Aggregation wie
   `scripts/finalize_closed_1m_candles.py`: kein synthetischer Wert, kein Forward-Fill)
   und setzt genau die `DEFERRED`-Einträge dieser Minute auf `COMPLETED` mit einem
   deterministischen `output_hash` (`DEFERRED_CANDLE_REBUILD_V1`, SHA-256 über Symbol,
   open_time, OHLCV und trade_count).
4. Zählt in `ingestion_metrics`: `outbox_deferred_rebuilt_total` (Einträge) und
   `candles_deferred_rebuilt_total` (Minuten).

### Was es nicht tut

- Keine Änderung an Cursor, Lückenregister, Live-Queue (`queue_depth` zählt nur aktive Einträge, DEFERRED → COMPLETED bewegt ihn nicht).
- Keine Folgestufen: `FEATURE_V1`, `OBSERVATION_V1`, `RESEARCH_TRIGGER_V1` werden für nachgebaute Minuten **nicht** eingereiht. Historische Minuten erhalten eine Kerze, keine rückdatierten Features oder Beobachtungen. `DEFERRED`-Einträge anderer Worker bleiben unberührt und werden im Bericht unter `deferred_by_worker` gezählt.
- Kein Netzzugriff. Fehlen Rohtrades, bleibt die Minute über die Lückensperre blockiert; erst `scripts/tim_catchup.py --open-gaps` oder ein promoteter Offline-Kandidat schließt die Lücke.

### Sicherheitsverhalten

- Standard ist Trockenlauf; `--apply` ist nötig, um zu schreiben.
- Jede Minute ist eine Transaktion unter demselben Advisory-Lock, den der Store beim Einreihen nimmt. Innerhalb der Transaktion werden Status, Live-Arbeit und Rohtrade-Anzahl erneut geprüft; weicht etwas vom Plan ab, wird die Minute als `CONFLICT` zurückgerollt und im nächsten Lauf erneut geplant.
- Ein Abbruch hinterlässt nur ganze Minuten; der nächste Lauf macht mit dem Rest weiter (idempotent, Test `test_rerun_after_apply_has_nothing_left_and_stays_idempotent`).
- Eine bereits vorhandene (zum Beispiel unvollständige, `closed=false`) Kerze wird durch die rohdatenbasierte ersetzt; der Bericht zählt `INSERTED`, `UPDATED`, `UNCHANGED` getrennt.

### Bericht und Rückgabewerte

JSON auf stdout; mit `--apply` zusätzlich ein Beleg unter
`data/deferred_candle_rebuild/<SYMBOL>/rebuild_<UTC>.json` (`--receipt-dir ''` schaltet ihn ab).
Exit 0: alle geplanten Minuten gebaut oder nichts zu tun. Exit 2: Minuten blockiert oder im Konflikt.
Exit 3: Fehler.

## Nachweis

- `tests/test_deferred_candle_rebuild.py`: 3 reine Tests (Schließregel, Sperrreihenfolge, Hash) und 10 Datenbanktests gegen die isolierte Test-Datenbank (`docs/ISOLATED_TEST_DATABASE.md`): Trockenlauf schreibt nichts; Nachbau erzeugt rohdatenbasierte Kerzen und schließt nur DEFERRED-Einträge; Live-Einträge, Cursor und `queue_depth` unverändert; Sperren durch Live-Arbeit, ID-nahe Lücke, zeitlich überlappende Lücke und Sicherheitsabstand; Ersetzen einer Teilkerze; fremde Worker unberührt; `--max-minutes` begrenzt älteste zuerst; Wiederholungslauf idempotent.
- CLI-Probe gegen die Test-Datenbank am 2026-10-12: Trockenlauf (2 Minuten geplant, Exit 0), `--apply` (2 Kerzen, 4 Einträge, Exit 0, Beleg geschrieben), Wiederholung (0 geplant, Exit 0).

## Bekannte Grenzen

- Die Bestandsaufnahme liest alle `DEFERRED`-Einträge des Symbols; der Teilindex der Outbox deckt nur aktive Status, auf dem Server ist das ein sequentieller Scan je Lauf. Für ein Offline-Werkzeug vertretbar; bei Millionen Einträgen einen Index auf `(worker_name, status, symbol)` erwägen.
- Minuten, deren Rohtrades ohne Outbox-Einträge in `agg_trades` liegen (promotete Offline-Kandidaten), haben ebenfalls keine Kerzen und sind **nicht** Teil dieses Werkzeugs. Das ist der zweite Teil von B5.
- Nicht gegen den Server `tim-core-01` gelaufen (war am 2026-10-12 offline). Vor dem ersten `--apply` dort: Trockenlauf lesen, `tim_catchup.py --open-gaps` vorher laufen lassen, damit möglichst wenige Minuten durch Lücken gesperrt bleiben.
