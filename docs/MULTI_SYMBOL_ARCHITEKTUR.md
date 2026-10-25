# Multi-Symbol-Architektur (Entwurf + isolierter Prototyp)

Stand: 25.10.2026, Basis `platform-main` 98e8bce. Status: **Entwurf**. Der Prototyp unter
`src/multi_symbol/` ist standardmäßig **aus** und wird von der Runtime (`main.py`, `config/settings.py`)
nicht importiert; ein Test prüft das. Kein Echtgeld, keine Orders, keine Änderung an `~/TIM-live`.

## 1. Ziel und Nicht-Ziele

Ziel: TIM soll später mehrere Spot-Symbole (zuerst BTCUSDT, ETHUSDT, SOLUSDT) gleichzeitig
beobachten, mit getrennten Streams, Zuständen, Kerzen und Research-Cases und einem zentralen
Portfolio-Risikolimit für Papier-Pläne.

Nicht-Ziele dieses Pakets: Umbau von `main.py` (gehört zu den S-K-geschützten Pfaden), Änderungen an
`src/dashboard/`, Datenbank-Migrationen, Deployment, Echtgeld, Research-Lab-Freigabe für andere
Symbole (`src/research_lab/data/archive.py` ist bewusst auf BTCUSDT festgelegt).

## 2. Ist-Zustand (gemessen, nicht vermutet)

### 2.1 Verwendungen von `settings.symbol`

50 Stellen in 22 Dateien (`grep -rn "settings\.symbol"` ohne `tests/`):

| Datei | Zeilen | Rolle |
|---|---|---|
| `main.py` | 98, 227, 259, 261, 289, 291, 293–295, 303, 305, 320, 380, 517, 559, 594 | Stream, Orderflow-Fenster, Validierung, Neustart-Zustand, Recovery, Dashboard-Status, Metriken, Liveness, Historie, Cursor-Bootstrap |
| `scripts/apply_live_cutover.py` | 21, 25, 36, 46, 47, 58, 60 | Live-Cutover |
| `scripts/research_infrastructure_review.py` | 82, 83, 85, 93 | Review |
| `scripts/acceptance_check.py` | 51, 53, 63 | Abnahme |
| `scripts/drain_queue.py`, `scripts/audit_collection_accounting.py` | je 2 | Outbox, Buchhaltung |
| 16 weitere Skripte (`tim_watchdog`, `tim_server_health`, `tim_catchup`, `tim_recover_range`, `tim_history_recovery`, `tim_candle_backfill`, `backfill_gaps`, `rebuild_deferred_candles`, `classify_ingestion_gaps`, `tim_ingestion_control`, `tim_maintenance`, `tim_orchestrator`, `tim_readiness_inputs`, `tim_server_campaign`, `autonomous_collection_report`, `bench_outbox_worker`) | je 1 | Betrieb, Recovery, Reports |

Zusätzlich fest verdrahtetes `"BTCUSDT"` als Default oder Konstante, u. a.:
`src/operational/live_evidence.py:60,65`, `src/operational/watchdog.py:166`,
`src/research/trigger.py:46`, `src/research_lab/data/archive.py:15,50` (gewollt),
`src/dashboard/plan_journal.py:89` (Tick/Lot nur für BTCUSDT), `src/dashboard/chart_model.py:111`,
`src/dashboard/server.py:393`, `src/v2_readiness/*`, `src/v2_completion/*`.

### 2.2 Was schon symbolgetrennt ist

| Teil | Befund |
|---|---|
| `CandleAggregator` | Zustand ist nach `(symbol, timeframe)` geschlüsselt, Zeitordnung je Symbol. |
| Tabellen `agg_trades`, `candles`, `ingestion_cursors` | Primärschlüssel enthält `symbol`. |
| `observations`, `research_cases`, `orderflow_*`, `ingestion_gap_incidents`, `live_cutover_receipts` | Spalte `symbol` vorhanden. |
| Outbox-Identität | `outbox_identity(symbol, aggregate_trade_id, worker)`, Dedup über `UNIQUE(worker_name, idempotency_key)`. |
| `DurableIngress`, `CatchUpCoordinator` | Cursor und Catch-up laufen je `trade.symbol`. |
| `BinanceTradeStream` | Eine Instanz = ein Symbol, eigener Watchdog, Puffer, Reconnect, Recovery vor Resume. |

### 2.3 Was nicht symbolgetrennt ist (Blocker)

1. **Strikte Outbox-Ordnung ist global je Worker, nicht je Symbol (P0 für Multi-Symbol).**
   `claim_strict_prefix` und `claim(strict_order=True)` (`src/data_ingestion/durable.py:637ff., 727ff.`)
   sortieren `ORDER BY aggregate_trade_id` nur nach `worker_name`. Binance-IDs sind je Symbol
   eigene Folgen (gemessen 25.10.: BTC ≈ 4,10·10⁹, ETH ≈ 2,11·10⁹, SOL ≈ 6,8·10⁸). Mit drei
   Symbolen würde der Worker erst den ganzen SOL-Rückstand, dann ETH, dann BTC abarbeiten, und ein
   quarantänierter SOL-Kopf blockiert alle anderen Symbole. `load_batch_target_trades` wirft
   außerdem `batch targets must share symbol`, sobald ein Präfix Symbole mischt. Der Prototyp zeigt
   das im Test `test_global_strict_order_mixes_symbols_and_blocks_on_foreign_head`.
2. **In-Memory-Zustand in `main.py`**: `self.history` ist nur nach Timeframe geschlüsselt,
   `ObservationEngine`, `ResearchCaseEngine`, `MarketMemory` und `DashboardState.market_status`
   sind Einzelinstanzen. Mehrere Symbole würden sich die Historie teilen.
3. **Ein Aggregator für alles, plus `copy.deepcopy` je Trade** (`main.py:156`): Kosten wachsen
   linear mit der Symbolzahl (Messung unten).
4. **`ingestion_metrics` hat keine Symbol-Spalte**; Metriken wären nicht pro Symbol auswertbar.
5. **Plan-Journal**: Tick/Lot-Tabelle nur für BTCUSDT (`src/dashboard/plan_journal.py:89`).

### 2.4 Marktdaten BTC/ETH/SOL (Binance Spot, öffentlich, vom Mac gelesen, 25.10. 01:40 Ortszeit)

| Symbol | Tickgröße | Lot-Schritt = Min-Menge | Min-Notional | 24h-Umsatz | Spread | Tiefe ±0,1 % Bid / Ask* | aggTrades/s** |
|---|---|---|---|---|---|---|---|
| BTCUSDT | 0,01 | 0,00001 | 5 USDT | 948 Mio. USDT | 0,001 bp | ≥ 2,0 / ≥ 0,56 Mio. USDT | 4,2 |
| ETHUSDT | 0,01 | 0,0001 | 5 USDT | 470 Mio. USDT | 0,04 bp | 1,26 / 1,55 Mio. USDT | 4,4 |
| SOLUSDT | 0,01 | 0,001 | 5 USDT | 177 Mio. USDT | 0,98 bp | 1,11 / 1,61 Mio. USDT | 2,1 |

\* Aus den obersten 100 Orderbuch-Stufen; bei BTC deckt das ±0,1 % nicht ganz ab, daher Untergrenze.
\** Letzte 1000 aggTrades in der Nacht; tagsüber deutlich höher. Kein Ersatz für eine Tagesmessung.

Historie: `data.binance.vision` liefert monatliche aggTrades für alle drei Symbole (HTTP 200 für
2020-09 und 2026-09, geprüft vom Mac; aus der Cloud gesperrt). In der Mac-Datenbank liegen nach
heutigem Wissen nur BTCUSDT-Daten; ein Zählen je Symbol war ohne Datenbank-Passwort nicht möglich
(**nicht geprüft**).

Folgerung: Alle drei sind liquide genug für Papier-Beobachtung. SOL hat ~1 bp Spread, also höhere
Kosten in R bei engen Stops; die Kosten-Schwelle aus PR #408 muss je Symbol mit eigenem Spread
gerechnet werden, nicht mit BTC-Werten.

### 2.5 deepcopy-Kosten (Messung, `python -m src.multi_symbol.bench`, Cloud, Python 3.13)

| Symbole | ein gemeinsamer Aggregator | ein Aggregator je Symbol |
|---|---|---|
| 1 | 84 µs | 77 µs |
| 3 | 189 µs | 74 µs |
| 20 | 1261 µs | 73 µs |

Bei 3 Symbolen und ~11 Trades/s (Nacht) sind das ~2 ms CPU je Sekunde, also **kein Engpass**.
Trotzdem gilt: Je Symbol ein eigener Aggregator hält die Kosten konstant und isoliert Fehler;
das ist ein Strukturgrund, keine Performance-Optimierung. Der Mac-Wert aus der Vormessung
(83 µs bei 1 Symbol) passt dazu.

## 3. Entwurf

### 3.1 Konfiguration
- `TIM_MULTI_SYMBOL_ENABLED` (Default `false`) und `TIM_SYMBOLS` (Komma-Liste).
- Aus: genau `(TIM_SYMBOL,)`, `TIM_SYMBOLS` wird ignoriert. Heute bleibt also alles gleich.
- An: `TIM_SYMBOL` muss in der Liste sein und steht immer vorn (Primärsymbol für alle Einzel-Symbol-
  Verbraucher wie Skripte und Dashboard). Duplikate, ungültige Namen, mehr als 5 Symbole: Abbruch.
- Umsetzung: `src/multi_symbol/config.py` (`resolve_symbols`).

### 3.2 Streams
- Je Symbol eine Instanz des bestehenden `BinanceTradeStream` (eigener Socket). Kein kombinierter
  Stream: so bleiben Watchdog, Puffer-Limit, Reconnect-Backoff und Catch-up vor Resume je Symbol
  unabhängig, und es ändert sich kein geprüfter Code.
- Ein Supervisor (`MultiSymbolStreamSet`) startet ein Symbol nach fatalem Fehler mit Backoff neu,
  höchstens `max_restarts`-mal; danach ist nur dieses Symbol `FAILED`, die anderen laufen weiter.
- Offene Entscheidung: Soll ein `FAILED`-Symbol den Prozess beenden (launchd startet neu) oder nur
  gemeldet werden? Vorschlag: melden plus Watchdog-Gelb, kein Prozess-Exit.

### 3.3 Ordnung, Dedup, Recovery-Cursor
- Ordnung, Dedup und Lücken je Symbol: `SymbolCursorBook` (Modell) und in der Datenbank weiterhin
  `ingestion_cursors` je Symbol (schon so).
- **Pflichtänderung vor dem Einschalten**: strikte Claims je `(worker_name, symbol)`.
  Vorschlag, umgesetzt erst in einem eigenen PR mit Migration:
  - `claim_strict_prefix(worker_name, symbol=...)` mit `WHERE worker_name=$1 AND symbol=$2`.
  - Neuer Index `ingestion_outbox(worker_name, symbol, aggregate_trade_id, created_at, outbox_id)
    INCLUDE(status) WHERE status <> 'COMPLETED'` (`CREATE INDEX CONCURRENTLY`).
  - Je Symbol eine `DurableOutboxWorker`-Schleife; Quarantäne blockiert nur das eigene Symbol.
  - Mit einem Symbol ist das Verhalten identisch zu heute (gleicher Filterwert).
- Modell und Tests: `per_symbol_heads` vs. `global_order_heads` in `src/multi_symbol/ordering.py`.

### 3.4 Kerzen, Research-Cases, Historie
- Je Symbol eigener `CandleAggregator` und eigene Historie (`SymbolPartitionedCandles`);
  Kandidat-Kopie nur des eigenen Symbols, Commit erst nach erfolgreicher Anreicherung (wie heute).
- Unbekanntes Symbol: Abbruch, kein automatisches Anlegen.
- Research-Cases, Beobachtungen, Orderflow: Tabellen haben `symbol` schon. In `main.py` muss jede
  Engine je Symbol instanziiert oder nach Symbol gefiltert werden (Punkt 2.3.2). Das ist der größte
  Umbau und kommt erst nach der S-K-Studie.

### 3.5 Zentrales Portfolio-Risikolimit (nur Papier)
- `PortfolioLimits` in R: Gesamt offenes R (Vorschlag 3,0), je Symbol (1,0), Anzahl offener Pläne
  (3), gleiche Richtung über alle Symbole (2,0, weil BTC/ETH/SOL stark korrelieren).
- Entscheidung ist ein Datensatz `ALLOW`/`REJECT` mit allen Gründen, nie eine Order.
  Die Zahlen sind Hypothesen und brauchen Uzis Wort, bevor sie irgendwo wirken.

### 3.6 Backpressure
- Je Symbol eigener begrenzter Puffer (`SymbolBuffers`); voll heißt nur dieses Symbol
  `SymbolBackpressure`, nichts wird still verworfen; danach Reconnect plus Catch-up für dieses Symbol.
  Der bestehende `BinanceTradeStream` macht das schon je Instanz (`buffer_limit`).

### 3.7 Metriken
- Je Symbol: `buffer_depth`, `backpressure_total`, `stream_fatal_total`, `stream_restart_total`,
  später Outbox-Tiefe und ältester Eintrag je Symbol.
- Übergang ohne Migration: Symbol in `metadata` von `ingestion_metrics` (`SymbolMetrics.as_rows`).
  Später eigene Spalte, falls Abfragen zu langsam werden (erst messen).

### 3.8 Instrumente
- `InstrumentSpec` mit Decimal: Preis auf Tick runden, Menge abrunden (nie Risiko aufrunden),
  Min-Menge und Min-Notional prüfen; `parse_exchange_info` liest frische Werte und bricht bei
  fehlenden Filtern ab. Der feste Stand vom 25.10. ist datiert.

## 4. Prototyp in diesem PR

| Datei | Inhalt |
|---|---|
| `src/multi_symbol/config.py` | Symbol-Liste, Default aus |
| `src/multi_symbol/instruments.py` | Tick, Lot, Min-Notional, Parser |
| `src/multi_symbol/partition.py` | Aggregator und Historie je Symbol |
| `src/multi_symbol/ordering.py` | Cursor/Dedup/Lücken je Symbol, Claim-Modell |
| `src/multi_symbol/risk.py` | Portfolio-Risikolimit (Papier) |
| `src/multi_symbol/backpressure.py` | Puffer und Metriken je Symbol |
| `src/multi_symbol/streams.py` | Stream-Supervisor mit Isolation |
| `src/multi_symbol/bench.py` | deepcopy-Messung |
| `tests/test_multi_symbol_prototype.py` | 26 Tests inkl. Reconnect-/Ausfall-Isolation |

## 5. Reihenfolge bis zum Einschalten (Vorschlag)

1. Dieser PR: Entwurf + Prototyp (ohne Wirkung).
2. Eigener PR: Outbox-Claim je Symbol + Index-Migration, Tests auf echter Test-Datenbank.
3. Nach S-K-Studie: `main.py` auf `SymbolPartitionedCandles` und Engines je Symbol umstellen,
   ein Symbol bleibt Default; Shadow-Lauf mit 3 Symbolen auf dem Mac in getrennter Datenbank.
4. Skripte (22 Dateien) bekommen `--symbol` mit Default `settings.symbol`.
5. Plan-Journal: Tick/Lot und Kosten-Schwelle je Symbol.
6. Einschalten nur mit Uzis Ja.

## 6. Risiken und offene Punkte

- Reconnect-Tests sind Unit-Tests mit Fake-Streams; ein echter Mehr-Symbol-Lauf gegen Binance fehlt.
- Anzahl Datenbank-Verbindungen und Outbox-Last bei 3 Symbolen nicht gemessen.
- Kosten in R je Symbol (SOL-Spread) noch nicht in der Kosten-Schwelle.
- Datenbankbestand je Symbol auf dem Mac nicht gezählt.
