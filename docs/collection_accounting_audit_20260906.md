# Mission 04 — Collection Accounting Audit, 06.09.2026

## Ergebnis

Die Accounting-Semantik und die tatsächliche Event-Begrenzung wurden korrigiert.
Produktionsdaten, Runtime-Konfiguration, alte Reports und der gespeicherte
SAFE_STOP wurden nicht verändert. Die erneute rein lesende Abnahme bleibt
**FAIL**: Die Verarbeitung des neuen begrenzten Datensatzes ist bewiesen,
sein historischer Empfang einschließlich Duplikaten/Ablehnungen dagegen nicht.
**SAFE_TO_ENABLE_BOUNDED_LIVE_INGESTION = NO.**

Die Prüfung bestand nicht darin, frühere Events erneut zu empfangen oder zu
verarbeiten. Sie las ausschließlich bereits persistierte Daten. Null neu
empfangene Events während dieser Prüfung beweisen keine historische Collection.

## Belege

- Alter unveränderter Report: `../artifacts/collections/orchestrated-d45357132c0ef6037a77/collection_result.json`
- Unabhängiger Vergleich: `../artifacts/accounting_audit/20260906T105211Z/OLD_VS_CORRECTED.json`
- Vollständige neue Messbasis einschließlich aller 10.000 Event-IDs: `../artifacts/accounting_audit/20260906T105211Z/facts.json`
- Vorher/Nachher-Nachweise: `before.json` und `after.json` im selben Auditordner.
- Erneute begrenzte Abnahme: `../artifacts/collections/accounting-bounded-20260906T105211Z/collection_result.json`
- Auditmanifest enthält SHA-256 aller Audit-JSON-Dateien; der Vergleich enthält
  SHA-256 aller alten Reportdateien. Die alten Dateien wurden nicht überschrieben.

Der alte Report speicherte weder eine vollständige Raw-Membership-Liste noch einen
Hash aller Raw-Payloads. Der unabhängige Vergleich liest denselben persistierten
ID-Bereich mit denselben Bestandszahlen; historische Byte-Gleichheit zum alten
Snapshot wird mangels damaligem Nachweis nicht behauptet.

Alle folgenden Zeitangaben sind UTC.

## ACCOUNTING_ROOT_CAUSE

Der alte Collector hatte keinen Collection-Filter und keine LIMIT-Klausel.
`collection_id` war lediglich ein Reportname. Der Orchestrator ergänzte
„Bounded acceptance ceiling: 10000 events“ als Hinweis, übergab die Grenze
aber nicht an die Abfrage.

Die alte Gleichung lautete faktisch:

```text
2.450.342 received_total
!= 7.572.705 alle agg_trades + 1.098.705 duplicate_total + 1.044 rejected_total
Differenz: 6.222.112
```

Die zweite alte Prüfung lautete:

```text
1.350.593 CANDLE_V1 COMPLETED != 7.572.705 alle agg_trades
Differenz: ebenfalls 6.222.112
```

Der LEFT JOIN über denselben alten ID-Bereich belegt exakt:

| Bestand | Anzahl | Event-ID von/bis | ingest_timestamp von/bis |
|---|---:|---|---|
| Raw-Trades ohne CANDLE_V1-Outbox | 6.222.112 | 4020624599–4029770319 | 2026-07-22 20:13:21.856029 – 2026-08-05 23:44:00.320928 |
| Raw-Trades mit CANDLE_V1-Outbox, alle COMPLETED | 1.350.593 | 4029770320–4044244188 | 2026-09-01 16:53:35.236733 – 2026-09-02 10:42:55.033671 |

`src/database/repository.py::insert_agg_trade` kennt einen älteren Raw-Insert-Pfad
ohne Durable-Outbox. `src/data_ingestion/durable.py::ingest_trade` besitzt die
neuere atomare Raw-/Outbox-/Metrik-Transaktion. Die zeitlich ältere Population
ist mit diesem Unterschied konsistent. Aus den Bestandsdaten allein lässt sich
nicht jeder historische Aufrufer rekonstruieren. Insbesondere wird für die
6.222.112 alten Events **keine** CANDLE_V1-Verarbeitung behauptet.

## Zählerherkunft — OLD_ACCOUNTING

Für alle Zeilen gilt: Collection-ID `orchestrated-d45357132c0ef6037a77` wurde
nicht in einer Datenbankprädikate verwendet. Die Tabellen besitzen hierfür keine
historische Collection-ID oder Empfangsbaseline. „Lifetime“ bezeichnet den
gespeicherten Gesamtzähler seines jeweiligen Subsystems, nicht automatisch die
gesamte TIM-Laufzeit seit dem ersten Raw-Trade.

| Reportzähler | Quelle / Query | Filter | Zeitraum / Grenzen | Persistenz und Scope |
|---|---|---|---|---|
| events_received = 2.450.342 | Q3, `received_total` | global, kein Symbolfilter | Seit Zähleranlage; Beginn nicht gespeichert; letzte Aktualisierung 2026-09-02 10:42:54.952055 | persistiert; Durable-Ingress-Lifetime, keine Collection |
| events_unique = 7.572.705 | Q1 `count(*)` | `symbol=BTCUSDT` | ganzer Bestand; IDs 4020624599–4044244188; Trade-Zeit 2026-07-22 20:13:21.782 bis 2026-08-25 07:56:36.815 | persistierte Raw-Inventur, keine Collection |
| events_processed = 1.350.593 | Q2 `count(DISTINCT aggregate_trade_id)` | BTCUSDT, CANDLE_V1, COMPLETED | kein Zeit-/ID-Filter; letzter Abschluss 2026-09-04 13:53:23.829513 | persistierte Worker-Abschlüsse, keine Collection |
| duplicates = 1.098.705 | Q3 `duplicate_total` | global | seit Anlage, letztes Update 2026-09-02 10:42:54.949840 | persistiert; Durable-Ingress-Lifetime |
| invalid_events = 1.044 | Q3 `rejected_total` | global | seit Anlage, letztes Update 2026-09-02 10:00:27.996645 | persistiert; falsch als „invalid“ beschriftet; aktuell 1.044 Kapazitätsablehnungen |
| retries = 0 | Q4 Status RETRY | BTCUSDT, CANDLE_V1 | Bestand zum Snapshot, kein Ereigniszeitfilter | persistierter momentaner Status, kein kumulativer Retry-Versuchszähler |
| quarantines = 0 | Q4 Status QUARANTINED | BTCUSDT, CANDLE_V1 | Bestand zum Snapshot | persistierter momentaner Status, kein historischer Quarantänezähler |
| queue_before | nicht erfasst | keiner | historische Startbaseline fehlt | unbekannt; nicht nachträglich rekonstruierbar |
| queue_after | kein separates Endsample; Q4 war nur eine Inventur | BTCUSDT, CANDLE_V1 | einzelner Snapshot 2026-09-04 16:26:04.877339 | kein Baseline-Delta |
| outbox counts | Q4 | BTCUSDT, CANDLE_V1 | gesamter Worker-Bestand zum Snapshot | COMPLETED 1.350.593, alle aktiven Zustände 0 |
| queue_depth = 206.785 | Q3 `queue_depth` | global | letztes Update 2026-09-02 10:42:55.034745 | veralteter persistierter Gauge; ungeeignet für aktuelle Queue-Gates |

Die historischen Runtime-Logs liefern Idle-Zyklen, aber keine vollständige
Collection-Receipt-Liste. Keiner der alten fünf Accounting-Zähler war lediglich
runtime-only; es wurden persistierte, jedoch inkompatible Datenbasen gemischt.

### Queries

```sql
-- Q1: alte unbeschränkte Raw-Inventur
SELECT count(*) n, min(trade_time) first_at, max(trade_time) last_at,
       min(aggregate_trade_id) first_id, max(aggregate_trade_id) last_id
FROM agg_trades WHERE symbol=$1;

-- Q2: alte unbeschränkte Worker-Abschlüsse
SELECT count(DISTINCT aggregate_trade_id) FROM ingestion_outbox
WHERE worker_name='CANDLE_V1' AND symbol=$1 AND status='COMPLETED';

-- Q3: globale persistierte Metriken
SELECT metric_name,numeric_value FROM ingestion_metrics;

-- Q4: aktuelle globale Worker-Inventur für das Symbol
SELECT status,count(*) n FROM ingestion_outbox
WHERE worker_name='CANDLE_V1' AND symbol=$1 GROUP BY status;

-- Q5: neue Event-Menge wird unabhängig vom Verarbeitungserfolg gewählt
SELECT t.*,o.status,o.completed_at,o.output_hash
FROM (
  SELECT symbol,aggregate_trade_id,trade_time,ingest_timestamp
  FROM agg_trades WHERE symbol=$1
    AND aggregate_trade_id >= $2 AND aggregate_trade_id <= $3
  ORDER BY aggregate_trade_id DESC LIMIT $4
) t
LEFT JOIN ingestion_outbox o ON o.symbol=t.symbol
  AND o.aggregate_trade_id=t.aggregate_trade_id AND o.worker_name='CANDLE_V1'
ORDER BY t.aggregate_trade_id;
```

Q5 schließt fehlende Outbox-Zeilen nicht aus. Ein fehlender Worker-Abschluss
bleibt sichtbar und führt zu FAIL. Die Grenze wählt nicht nach COMPLETED aus.

## Korrekte Pipeline-Invarianten

Für eine vollständig dokumentierte Empfangs-Collection müssen disjunkte
Message-Dispositionen vorliegen:

```text
received_receipts = unique_accepted_receipts + duplicate_receipts
                   + invalid_receipts + rejected_receipts
```

Eine Message-Occurrence hat eine eigene Receipt-ID. Ein persistiertes Event hat
eine Event-ID. Dieselbe Event-ID kann mehrere empfangene Messages erklären,
aber nur einen eindeutigen Raw-Datensatz. Die Prüfung validiert Receipt-ID-
Eindeutigkeit, Collection-ID, Zeitfenster [start,end), Event-Zugehörigkeit und
vollständige Dispositionen. Bloß passende Summen reichen nicht.

TIMs bestehendes `received_total` zählt enger: erst innerhalb der erfolgreichen
Durable-Ingress-Transaktion. Für diesen Zähler gilt im beobachteten Bestand:

```text
received_total = raw_persisted_total + duplicate_total
                 + reject_reason:OUTBOX_CAPACITY
2.450.342 = 1.350.593 + 1.098.705 + 1.044   [numerisch PASS]
```

Validierungsablehnungen werden in `DurableIngress.on_trade` außerhalb dieser
Erfolgstransaktion als `reject_reason:VALIDATION`/`rejected_total` erfasst;
Parse-Fehler separat als `parse_error_total`. Deshalb ist `rejected_total`
allgemein kein Synonym für „invalid innerhalb received_total“. Die Gleichheit
oben beweist die aktuelle globale Durable-Zählerbilanz, **keinen** früheren
Collection-Vertrag und keine vollständige WebSocket-Empfangsbilanz.

„Processed“ bedeutet hier: dieselbe Event-ID besitzt einen CANDLE_V1-Outbox-
Abschluss mit `status=COMPLETED`, `completed_at` und `output_hash`. Der Worker
ruft seinen Handler auf und bestätigt anschließend den Abschluss. Das ist
weder bloß Raw-Persistierung noch eine Behauptung, dass alle Candles geschlossen,
alle nachfolgenden Worker fertig oder sämtliche Trading-Stufen finalisiert sind.

```text
all_unique_events_processed:
  Set(collection.raw_event_ids) == Set(collection.completed_CANDLE_V1_event_ids)
```

Unterschiedliche IDs mit gleicher Anzahl bestehen die Prüfung nicht.
PENDING/PROCESSING/RETRY/QUARANTINED werden separat gezählt. Ein fehlender
Abschluss wird nicht durch eine hypothetische Invalid-/Duplicate-Klassifikation
aus der eindeutigen akzeptierten Event-Menge entfernt.

## Neue Collection und Baseline

| Feld | Nachweis |
|---|---|
| collection_id | `accounting-bounded-20260906T105211Z` |
| Contract-Typ | `PERSISTED_SNAPSHOT_AUDIT`; keine neue Live-Collection |
| requested_start / requested_end | ID-Grenzen inklusiv 4020624599 / 4044244188; maximal die letzten 10.000 vorhandenen Raw-Events |
| actual_start / actual_end | IDs 4044234189 / 4044244188 |
| first event | ID 4044234189, Trade-Zeit 2026-08-25 07:51:44.198; persistiert 2026-09-02 10:15:24.464881 |
| last event | ID 4044244188, Trade-Zeit 2026-08-25 07:56:36.815; persistiert 2026-09-02 10:42:55.033671 |
| Membership | Alle 10.000 IDs gespeichert; SHA-256 `e6624e5f520ca945565b9da6a514c7b1035f7594c4a77e4e239ae9e22b2b0b66` |
| Collection-Baseline | Snapshot 2026-09-06 10:52:13.585021, Collection-ID + Membership-Hash + CANDLE_V1-Statusbestand |
| events_unique | 10.000, ausschließlich Q5-Mitgliedschaft |
| events_processed | 10.000, exakt dieselben IDs mit vollständigem CANDLE_V1-Abschlussnachweis |
| received / duplicates / invalid / rejected | **null = nicht belegt**, nicht 0; historische Receipt-Daten nicht vorhanden |
| retries / quarantines | 0 / 0, Statusbestand innerhalb Q5-Mitgliedschaft |
| outbox counts | Collection COMPLETED 10.000; PENDING/PROCESSING/RETRY/QUARANTINED jeweils 0 |
| queue_before / queue_after | separat Lifetime BTCUSDT/CANDLE_V1: jeweils COMPLETED 1.350.593, aktive Zustände 0 |

Die neue Baseline ist ein jetzt erhobener, als Audit-JSON persistierter Beleg.
Sie ist ausdrücklich kein zurückdatierter Start des alten Laufs. Alle anderen
IDs bleiben außerhalb der neuen Collection, auch wenn ihre Marktdatenzeiten im
ursprünglich beobachteten Zeitraum liegen. Das entlastet nicht die alten
6.222.112 Events ohne Worker-Nachweis.

Zwei getrennte Read-only-Transaktionen erfassten globale Durable-Counter um
10:52:13.585021 und 10:52:15.161672. Die Deltas für received, raw_persisted,
duplicate und rejected waren jeweils **0**. Subtraktion ist nur bei identischer
Collection-ID, identischem Counter-Scope und gleichem Counter-Satz zulässig;
Resets und fehlende Werte werden abgelehnt. Globale Deltas sind hier nur Kontext
und dürfen die fehlenden historischen Collection-Receipts nicht ersetzen.
Queue-Werte sind Gauges und werden getrennt als Vorher/Nachher-Inventuren gezeigt.

## OLD_ACCOUNTING vs. CORRECTED_ACCOUNTING

| Prüfung | Alter Report | Korrigierte Prüfung |
|---|---|---|
| Globale Durable-Ingress-Zählerbilanz | mit gesamtem Raw-Bestand vermischt | numerisch PASS, getrennt ausgewiesen |
| Alter voller Raw-Bestand verarbeitet | FAIL | weiterhin FAIL/kein Nachweis für 6.222.112 ältere Events |
| Historischer Collection-Empfang bilanziert | FAIL durch Scope-Mischung | FAIL wegen fehlendem Collection-Empfangsnachweis; keine erfundenen Werte |
| Neue Collection-Grenze | nicht vorhanden | PASS, 10.000 explizite Raw-IDs |
| Neue Collection vollständig Worker-verarbeitet | nicht separat geprüft | PASS, identische Event-Menge |
| Neue Collection received bilanziert | nicht vorhanden | FAIL, Receipt-Ledger/Baseline fehlen |

Alle zuvor bestandenen übrigen Gates bleiben PASS. `known_open_gaps` bleibt
wie zuvor WARN. Die erneute Abnahme hat den produktiven Orchestrator nicht
fortgesetzt und den SAFE_STOP nicht zurückgesetzt.

## Regression und Unveränderlichkeit

59 gezielte Tests bestanden (0 Fehler; eine bestehende asyncio-Deprecation-Warnung). Tests verwenden synthetische Daten und
temporäre Artefaktordner. Sie verbinden sich nicht mit der Produktionsdatenbank.
Die folgenden Fälle sind explizit abgedeckt:

1. Lifetime-Zähler kontaminieren Collection-Zähler nicht.
2. Collection A verändert B nicht; A-Receipts dürfen B nicht freigeben.
3. Baseline-Delta stimmt; Scope-Wechsel, Reset und fehlende Counter werden abgewiesen.
4. Duplicate-Accounting und eindeutige Receipt-IDs.
5. Invalid- und Kapazitäts-/Rejected-Dispositionen bleiben getrennt.
6. Vollständige Collection besteht counts_accounted.
7. Exakt verarbeitete Collection besteht all_unique_events_processed.
8. Fehlender Event, fehlende Receipt oder falsche IDs bei gleicher Anzahl führen zu FAIL.
9. Reeller Accounting-Fehler hält den Orchestrator in SAFE_STOP.
10. Collector erzwingt serverseitig Read-only und nutzt ausschließlich SELECTs.
11. SQL-Limit, ID-Grenzen, Receipt-Zeitgrenzen und Baseline-Bindung werden geprüft.
12. Fehlende historische Ingress-Daten werden nicht zu Null oder PASS umgedeutet.
13. Gespeicherte REFUSED/FAIL/PARTIAL-Receipts dürfen beim erneuten Aufruf nicht zu ALREADY_COMPLETED werden. Dieser Accounting-relevante Wiederaufnahmefehler wurde ebenfalls korrigiert; bestehende Receipts bleiben unverändert.

Der produktive Audit nutzte `default_transaction_read_only=on` sowie
`REPEATABLE READ READ ONLY`; der Serverzustand wurde abgefragt. Vorher/Nachher
waren Raw-Coverage, Outbox-Zähler/-Zeitstempel, Cursor, Gaps und Schreibstatistiken
der fünf Kerntabellen unverändert. Alte Report-Hashes und die Bytes des
Orchestratorzustands waren unverändert. Die bestehende Runtime aktualisiert
unabhängig weiterhin Event-Loop-/Reconnect-Telemetrie; solche autonomen Metriken
sind keine vom Audit vorgenommenen Produktionsänderungen.

Runtime nach der Prüfung: PID 17778, launchd runs=2, WebSocket weiterhin
`ws://127.0.0.1:1`, OBSERVE, protokollierte Trading-Aktionen 0.

## Verbleibende Freigabegrenze

Ein historischer Snapshot kann verlorene Empfangs-Multiplikitäten und den
fehlenden ursprünglichen Collection-Vertrag nicht nachträglich beweisen.
Für eine echte Ingress-Abnahme fehlt ein vollständig erfasster, eindeutig
abgegrenzter Receipt-Nachweis (oder eine bereits damals erhobene, gleichwertige
Collection-Baseline mit passenden Dispositionszählern). Die neue Accounting-
Prüfung kann solche Belege validieren, erzeugt sie aber nicht aus Raw-Zeilenzahlen.
Es wurde kein Live-Collector, keine Recovery und kein Backfill gestartet.
