# T12: Kapazität, Runtimepriorität und Lebenszyklus der `ingestion_outbox`

Stand 22.10.2026, nur aus Repo und Belegen; keine Abfrage auf der Produktionsdatenbank. Zone A/B; die Migration
(Abschnitt 5) ist Zone C und läuft nicht während der Kampagne.

## 1. Vorhandene Messwerte

| Messung | Wert | Quelle |
|---|---|---|
| Server-DB 20.10. 11:29 UTC | 23.360.663 COMPLETED, 2.857.192 DEFERRED, keine anderen Status | `docs/V2_CURRENT_READINESS_2026-10-20_1322.md` [V] |
| Mac-DB 20.10. abends | ca. 31,5 Mio. COMPLETED-Zeilen | Projektnotiz (Thread „Worker-Issues für V2“) [N] |
| Wachstum | eine Outbox-Zeile je aggTrade je Worker; Worker: CANDLE_V1, FEATURE_V1, OBSERVATION_V1, RESEARCH_TRIGGER_V1 | `schema.sql:189` [V] |
| Statusabfragen | zählten bis #350 alle Zeilen (13–28 s); seit f469ad6 nur aktive Status (`status=ANY(…)`) | `durable.py:381`, PR #350 [V] |
| Index | `ingestion_outbox_claim_idx` ist ein Teilindex auf PENDING/RETRY/PROCESSING; COMPLETED/DEFERRED sind nicht indexiert | `schema.sql:202` [V] |
| Fremdschlüssel | `(symbol, aggregate_trade_id) → agg_trades ON DELETE RESTRICT`: Trades können nicht gelöscht werden, solange eine Outbox-Zeile sie referenziert. Umgekehrt blockiert nichts das Löschen von Outbox-Zeilen. | `schema.sql:200` [V] |
| Löschpfad | Es gibt keinen: kein `DELETE`, keine Archivierung in `src/` oder `scripts/` (nur im Benchmark) | grep [V] |

Hochrechnung (grobe Größenordnung, keine Messung): BTCUSDT Spot liefert in ruhigen Phasen ~20–60 aggTrades/s, also
2–5 Mio. je Tag und Worker. Bei zwei aktiven Workern wachsen die Zeilen um 4–10 Mio. je Tag; mit ~300 Byte je Zeile
plus Indizes 1,5–3 GB je Tag. Nach 34 Tagen Kampagne sind 150–350 Mio. zusätzliche Zeilen möglich. Das ist der
Grund, warum T12 vor Ende der Kampagne entworfen, aber erst danach umgesetzt wird. **Zu prüfen:** tatsächliche
Rate aus den Tagesbelegen (Zähler je Tag), sobald die ersten fünf Tage vorliegen.

## 2. Was während der Kampagne erlaubt ist

- Nur lesen aus vorhandenen Artefakten (Tagesbelege, `server_health.json`, Watchdog-Status).
- Keine `count(*)` über die ganze Tabelle, kein `VACUUM FULL`, kein Indexbau, kein `DELETE`, kein Reload.
- Bei Platzmangel: zuerst Worker und CI pausieren (LIVE_MAC.md), dann Uzi informieren. Nicht die Runtime ändern.

## 3. Retention: Was eine Zeile noch leistet

| Status | Zweck der Zeile nach Abschluss | Aufbewahrung (Vorschlag) |
|---|---|---|
| COMPLETED | `output_hash` ist Replay-/Audit-Beleg, dass Worker W den Trade T verarbeitet hat | 7 Tage in der Tabelle; danach Archiv (Parquet/CSV.gz je Tag mit `outbox_id, worker_name, idempotency_key, aggregate_trade_id, output_hash, completed_at, worker_version`) und `DELETE` nur, wenn das Archiv des Tages per Zeilenzahl und Hash verifiziert ist |
| DEFERRED | historische zurückgestellte Arbeit (Kerzen-Nachbau), noch nicht abgearbeitet | unbegrenzt, bis `rebuild_deferred_candles` sie abschließt; nie löschen |
| PENDING/RETRY/PROCESSING | aktive Arbeit | nie löschen |
| QUARANTINED | Fehlerfälle, Beweismaterial | unbegrenzt bis zur Disposition |

Wiederanlauf: Der Cursor hängt an `agg_trades`, nicht an COMPLETED-Zeilen; Idempotenz wird über
`UNIQUE(worker_name, idempotency_key)` erreicht. Nach dem Löschen alter COMPLETED-Zeilen könnte ein Replay eines
alten Trades ihn ein zweites Mal verarbeiten. Deshalb: Archivierung **vor** Löschung, und das Replay-Werkzeug prüft
zuerst das Archiv. Das ist in der Testkopie nachzuweisen (Abschnitt 5).

## 4. Runtimepriorität

Vorlage `ops/launchd/com.tim.runtime.plist`: `ProcessType=Background`, `Nice` nicht gesetzt. Der Worker
(`com.tim.local-qwen-worker`) und der Coverage-Worker (`Nice 20`) laufen ebenfalls als Background. Welche Plist
tatsächlich geladen ist, kann nur `launchctl print gui/$(id -u)/com.tim.runtime` auf dem Mac zeigen (nur lesend,
erlaubt). Änderung erst nach gemessener Konkurrenz: Load-Werte aus `server_health.json` über zwei Wochen; liegt die
Runtime-Frische unter Last der anderen Dienste, bekommt die Runtime `ProcessType=Interactive`, Worker und CI-Runner
`Background` plus `Nice`. Das ist ein Reload und damit Zone C.

## 5. Migrationsplan nach dem 23.11. (Reihenfolge, je Schritt Rückweg)

1. Lesend messen: Zeilen je Status und Tag (eine Abfrage mit `completed_at::date`, nachts), Tabellen- und Indexgröße.
2. Archivjob in Testkopie: Tagesdatei schreiben, Zeilenzahl und SHA-256 gegen die Tabelle prüfen, Replay aus Archiv testen.
3. Löschjob in Testkopie: `DELETE … WHERE status='COMPLETED' AND completed_at < now() - interval '7 days'` in
   Blöcken von 50.000 mit Pause; Locks und Laufzeit messen; `VACUUM (ANALYZE)` danach, kein `VACUUM FULL`.
4. Teilindex auf `(worker_name, completed_at) WHERE status='COMPLETED'` nur, wenn der Archivjob ihn braucht;
   `CREATE INDEX CONCURRENTLY`.
5. Rückweg: Archivdatei zurückspielen (`COPY`), Fremdschlüssel bleibt erfüllt, weil `agg_trades` nie gelöscht werden.
6. Erst danach auf dem Mac im Wartungsfenster (T14), Dienste einzeln, Beobachtung 48 h.

## 6. Abnahme

Begrenztes Wachstum (Tabelle bleibt unter einer vorab genannten Größe), kein Verlust aktiver oder referenzierter
Evidenz, Replay und Wiederanlauf in der Testkopie nachgewiesen, Rückweg geübt.
