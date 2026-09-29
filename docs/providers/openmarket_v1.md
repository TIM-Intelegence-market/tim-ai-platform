# OpenMarket v1 – Provider-Modell für TIM

Stand 2026-09-29. Scope: `ORDERFLOW_RESEARCH_PROVIDER`. Die Live-Ingestion über Binance bleibt unverändert.

## Quellenlage

| Quelle | Status |
|---|---|
| Offizielle OpenMarket-Doku, vom Owner außerhalb der Cloud-Umgebung geprüft (29.09.) | Grundlage aller Angaben unter „Belegt“ |
| Direkter Zugriff aus der Claude-Cloud-Umgebung | `CLAUDE_DIRECT_DOC_ACCESS=BLOCKED` (Egress-Proxy sperrt `openmarket.xyz`) |
| Echte API-Antwort | Noch keine. Die Belege liefert `scripts/openmarket_api_proof.py` auf dem Zielhost. |

## Belegt (offizielle Doku, vom Owner geprüft)

| Punkt | Status | Umsetzung |
|---|---|---|
| Basis-URL | VERIFIED | `https://api.openmarket.xyz` (Default); `TIM_OPENMARKET_BASE_URL` überschreibt, nur `https` |
| Endpunkt und Auth | VERIFIED | `GET /v1/points`, Header `X-OpenMarket-Key` |
| Query-Parameter (Candles) | VERIFIED | `type`, `exchange`, `rawSymbol`, `interval`, `from` (Unix-Sekunden, inklusiv), `period` (Sekunden). Die Tests prüfen den exakten Wire-String. |
| Intervalle | VERIFIED | `MINUTE, FIVE_MINUTES, FIFTEEN_MINUTES, THIRTY_MINUTES, HOUR, FOUR_HOURS, DAY, WEEK` |
| REST-Hülle | VERIFIED_FROM_DOCS | `series[] → id → points[] → Point`; primärer, strikter Pfad (siehe unten) |
| REST-Zeitstempel | VERIFIED_FROM_DOCS | `{"s"}` oder `{"s","ns"}` |
| Ort der Seite bei `TRADE_AGG` (REST) | VERIFIED_FROM_DOCS | `series[].id.side` = `BUY` \| `SELL` |
| Candle-Felder | VERIFIED | `open high low close volume timestamp firstTimestamp lastTimestamp` |
| Rate-Limit | VERIFIED | gewichtsbasiert; `X-RateLimit-Limit/-Remaining/-Used/-Reset`, `Retry-After` |
| Fehler | VERIFIED | `400 INVALID_PARAMS \| INVALID_EXCHANGE \| INVALID_SYMBOL \| INVALID_TIMEFRAME`, `401 INVALID_API_KEY`, `403` (Tier/Tiefe/Aggregation/Punktzahl), `429`, `500 INTERNAL_ERROR`, `504 TIMEOUT` |
| WebSocket | VERIFIED (nur Audit) | `public/authenticate`, `public/subscribe`, `TRADE` mit `trade.id` (Exchange-Trade-ID), Zeitstempel `{"seconds","nanoseconds"}`; `TRADE_AGG`: `series.side` = Aggressor-Seite des Batches |

Dokumentierte REST-Antwort (`TRADE_SIDE_AGNOSTIC_AGG`, gekürzt):

```json
{"series": [{"id": {"type": "TRADE_SIDE_AGNOSTIC_AGG", "exchange": "BINANCE_FUTURES", "rawSymbol": "BTCUSDT",
                    "normalizedSymbol": "BTC-USDT", "category": "PERPETUAL", "interval": "HOUR", "coin": "BTC"},
             "points": [{"Point": {"open": 66499.9, "high": 66639.0, "low": 66400.0, "close": 66467.8, "volume": 2852.833,
                                   "timestamp": {"s": 1774800000},
                                   "firstTimestamp": {"s": 1774800003, "ns": 234000000},
                                   "lastTimestamp": {"s": 1774803599, "ns": 649000000}}}]}]}
```

### Strikter dokumentierter Pfad

- `series` muss eine Liste sein. Side-agnostic: höchstens eine Serie, weil genau ein Instrument angefragt wird.
- Jede Serie hat `id` (Objekt) und `points` (Liste). `id.type/exchange/rawSymbol/interval` müssen der Anfrage entsprechen (`check:series_id`).
- `TRADE_AGG`: `id.side` ∈ {BUY, SELL}, keine Seite doppelt. Side-agnostic: kein `id.side`.
- Jeder Punkt ist `{"Point": {...}}`; Zeitstempel ausschließlich im REST-Schema `{s[,ns]}`.
- Jede strukturelle Abweichung → `SCHEMA_MISMATCH`. Punkte mit ungültigen Werten → `missing_fields`, nie ersetzt.

REST- und WebSocket-Zeitstempel sind zwei getrennte Schemas. Gemischte Schlüssel (`s`+`nanoseconds`, `seconds`+`ns`, zusätzliche Schlüssel) werden abgelehnt. Auf dem REST-Pfad wird ein WebSocket-Zeitstempel abgelehnt.

Die strukturelle Erkennung aus dem ersten Entwurf bleibt nur als Fallback für Antworten ohne `series`-Hülle. Ihr Ergebnis trägt `check:documented_envelope=FAIL` und zählt im Proof nie als Beleg.

## Weiterhin nicht belegt

| Punkt | Umgang im Code | Klärung |
|---|---|---|
| REST `TRADE_AGG`: BUY/SELL = Aggressor-Seite? | Nur für WebSocket dokumentiert, wird nicht auf REST übertragen. `net_delta`/`aggressive_*` bleiben leer (`REST_SIDE_AGGRESSOR_SEMANTICS=UNPROVEN`), außer `side_is_aggressor=True` | REST-Doku oder echter Proof |
| `timestamp` = Beginn des Intervalls | wird geprüft, nicht angenommen: Fenster `[from, from+period)`, Intervall-Raster, `first/lastTimestamp` in `[timestamp, timestamp+Intervall)` → `check:time_semantics` (im Beispiel der Doku erfüllt) | echter Proof |
| Volumen-Einheit (Base/Quote) | unverändert übernommen (`units=as_reported_by_provider`) | Doku |
| Schemas von `VOLUME_PROFILE_AGG`, `OPEN_INTEREST_AGG`, `FUNDING_RATE_AGG`, `LIQUIDATION_AGG`, `TPO_AGG` | nicht implementiert | Doku, dann v1.1 |
| echte Authentifizierung und echte Daten | nicht bewiesen (Cloud-Egress gesperrt, kein Key) | `scripts/openmarket_api_proof.py` auf dem Zielhost |

## Architektur

```
OpenMarket REST
  → src/market_data/providers/openmarket/client.py   (Auth, Timeout, begrenzte Retries, 429/Retry-After, Health)
  → .../schemas.py                                   (exakte Decimals, UTC-ns, Validierung)
  → .../mapper.py                                    (Dedup je Datentyp, TIM-Candles, Provenienz)
  → src/orderflow_scenario/adapters/openmarket.py    (AdapterInput, wie generic/MMT)
  → python -m src.orderflow_scenario.cli --provider openmarket …
```

- Es gab vorher keine Provider-Abstraktion für externe APIs. Die Adapter-Schicht von `orderflow_scenario` ist die bestehende Konvention und wird weiterverwendet.
- Die Secrets folgen dem Modell von `config/secrets.py` (`SecretValue`, 0600-Prüfung).

## Konfiguration und Secret

| Variable | Bedeutung |
|---|---|
| `TIM_OPENMARKET_SECRET_PROVIDER` | `keychain`, `file` oder `env`. Nicht gesetzt → `NO_SECRET`, es gibt keinen Request. |
| `TIM_OPENMARKET_KEYCHAIN_SERVICE` / `_ACCOUNT` | Standard `com.tim.openmarket` / `tim` |
| `TIM_OPENMARKET_SECRET_FILE` | Standard `~/Library/Application Support/TIM/openmarket-api-key`; Modus 0600, gleicher Eigentümer |
| `TIM_OPENMARKET_API_KEY` | nur bei `env` |

Key ablegen: `python scripts/openmarket_store_key.py --from-clipboard` (liest die Zwischenablage per `pbpaste` ohne Terminal-Zeilenlimit und leert sie danach) oder ohne Option per verdeckter Eingabe. Das Skript fragt den Key verdeckt ab (kein Echo, keine Zwischenablage-Datei, keine Shell-History) und prüft die Form. Mehrzeiliger Text, Leerzeichen, Nicht-ASCII-Zeichen oder ein zu kurzer Wert (z. B. nur der Key-Name) werden abgelehnt, die bestehende Datei bleibt dann unverändert. Gültige Keys (8–4096 Zeichen; OpenMarket-Keys können lange Tokens sein) schreibt es atomar mit Modus 0600 und zeigt nur Länge und `****last4` zum Abgleich mit dem Dashboard. Ist die Key-Datei fehlerhaft, nennt der Resolver den Grund nur über Zählwerte (Länge, Zeilenumbrüche, Leerzeichen, Nicht-ASCII), der Inhalt erscheint nie.
| `TIM_OPENMARKET_BASE_URL` | optional; überschreibt den dokumentierten Default `https://api.openmarket.xyz` (nur `https`) |

**Schutz des Keys:**
- Der Key steht nur im Request-Header, nie in der URL.
- Bis zum Transport bleibt er ein `SecretValue`, auch in den Stack-Frames. Tracebacks mit lokalen Variablen zeigen nur `@REDACTED@`.
- Keys, die nicht aus druckbarem ASCII ohne Leerzeichen bestehen, werden vor dem Request abgelehnt.
- `repr`/`str` liefern `@REDACTED@`.
- Fehlermeldungen enthalten keine Response-Bodies, nur dokumentierte Codes.

## Fehler und Fail-Safe

| Lage | Klasse | TIM-Reaktion |
|---|---|---|
| kein Key / ungültige Override-URL | `NO_SECRET` / `NOT_CONFIGURED` | kein Request; CLI endet mit Exit 3, keine Analyse |
| Key ungültig oder abgelaufen | `INVALID_SECRET` (401) | Abbruch ohne Retry, `authenticated=false` |
| Typ, Tier oder Tiefe nicht erlaubt | `FORBIDDEN` (403) | Abbruch; per-Side-Anfrage → nur als fehlend markiert |
| Rate-Limit | `RATE_LIMITED` (429) | `Retry-After` beachten (Obergrenze 30 s), sonst sofortiger Abbruch; Zustand in `rate_limit_state` |
| API nicht erreichbar | `DNS_FAILURE`, `TLS_FAILURE`, `NETWORK_FAILURE`, `TIMEOUT` | begrenzte Retries (Standard 2, max. 5) mit Backoff, dann Abbruch |
| 5xx / 504 | `API_FAILURE` / `TIMEOUT` | wie oben |
| ungültige oder abweichende Antwort | `SCHEMA_MISMATCH` | Abbruch; einzelne ungültige Punkte → `missing_fields`, nie ersetzt |
| Teilantwort (Lücken, nur eine Seite) | – | nur vorhandene Punkte; BUY/SELL nur über gepaarte Intervalle; `total_volume … complete=false` |
| veraltete oder laufende Daten | – | das laufende Intervall wird ausgeschlossen (`excluded:open_interval_candles`); Zeitstempel und Anfragezeit in der Provenienz |

Grundsatz: fail closed. Marktdaten werden nie erfunden oder ergänzt.

## Deduplizierung

| Datentyp | Schlüssel |
|---|---|
| Candle | `openmarket, exchange, rawSymbol, interval, type, side, timestamp_ns` |
| Profil (später) | `openmarket, exchange, rawSymbol, interval, timestamp, price_level` |
| Trade (später, WS) | `openmarket, exchange, rawSymbol, trade.id` |

- Identische Duplikate (Retry, Überlappung) werden zusammengefasst.
- Widersprüchliche Duplikate werden verworfen und gemeldet.
- Die Ausgabe ist nach Zeit sortiert.

## MMT → OpenMarket (Feldmatrix `AdapterInput`)

| Feld | OpenMarket v1 | Herleitung / Anmerkung |
|---|---|---|
| symbol, venue, market_type | DIRECT | `rawSymbol`, `exchange`; `market_type` wird im Request explizit angegeben |
| timeframe | DIRECT | Intervall → `1m 5m 15m 30m 1H 4H 1D 1W` |
| candles OHLCV | DIRECT | `TRADE_SIDE_AGNOSTIC_AGG`; Float erst an der Grenze zum TIM-`Candle`-Modell |
| candles.trade_count | NOT_AVAILABLE | 0, markiert als fehlend |
| total_volume | DERIVED | Σ `volume` der Candles (Decimal); `derived:total_volume` |
| aggressive_buy/sell_volume | DERIVED (gesperrt) | Σ BUY bzw. SELL `TRADE_AGG` über gepaarte Intervalle; nur mit `side_is_aggressor=True` |
| net_delta | DERIVED (gesperrt) | `buy_volume − sell_volume`; nur mit bestätigter Aggressor-Semantik; `derived:net_delta` |
| price_now, price_timestamp | NOT_REQUIRED | das CLI nimmt den letzten Close (bestehendes Verhalten) |
| levels (Value Area) | UNKNOWN | `VOLUME_PROFILE_AGG`/`TPO_AGG`, Schema unbelegt |
| open_interest_with_price | UNKNOWN | `OPEN_INTEREST_AGG`, Schema unbelegt |
| delta_divergence, volume_bubbles | NOT_AVAILABLE | MMT-Screenshot-Interpretation, kein API-Feld |
| trades (roh) | NOT_REQUIRED (v1) | WS `TRADE` dokumentiert, außerhalb des Scopes |

Die MMT-Adapter (`mmt-structured`, `mmt-screenshot`) bleiben als manueller Rückfallpfad bestehen. Standard-Provider des CLI bleibt `generic`.

## WebSocket-Capability-Audit (nicht implementiert)

`TRADE` liefert Einzeltrades mit Exchange-Trade-ID und Nanosekunden-Zeitstempel. Vor einer Nutzung für die Live-Ingestion ist zu beweisen:
- gleiche ID-Semantik wie die Binance-aggTrade-ID;
- Monotonie und Lückenprüfbarkeit;
- Vollständigkeit;
- Verhalten bei Disconnect und Reconnect (Duplikate), ggf. historisches Nachladen roher Trades.

Betriebsdetails:
- Heartbeat: Ping etwa alle 30 s, Disconnect nach etwa 60 s ohne Ping.
- Reconnect mit exponentiellem Backoff, danach Re-Auth und Re-Subscribe.

Das gehört in eine eigene Mission. `binance_ws.py`, Catch-up, Durable-Ingestion und Gap-Recovery sind unverändert.

## Nachweis auf dem Zielhost

```
TIM_OPENMARKET_SECRET_PROVIDER=file \
  python scripts/openmarket_api_proof.py --exchange BINANCE_FUTURES --raw-symbol BTCUSDT --per-side
```

- `FINAL=PASS` nur bei: `HTTP_STATUS=200`, `DOCUMENTED_ENVELOPE=PASS`, `REST_TIMESTAMP_SCHEMA=PASS`, `SERIES_ID=PASS`, `WINDOW_SEMANTICS=PASS`, `NORMALIZATION=PASS`; mit `--per-side` zusätzlich `SIDE_LOCATION=PASS`.
- `AUTH` und `TLS` werden nur dann `PASS`, sonst `UNPROVEN` (ein Proxy oder Gateway kann jede andere Antwort liefern).
- `ENVELOPE_SHAPE` (Schlüsselnamen und Typen) ist nur Diagnose, kein Kriterium.
- `REST_SIDE_AGGRESSOR_SEMANTICS` bleibt `UNPROVEN`; der Proof beweist sie nicht.
- Ausgegeben werden nur Statusfelder, nie der Key oder ein Response-Body.

## Rollback

- Kein Schema und keine Laufzeitkomponente geändert.
- Das CLI schreibt für `--provider openmarket` zusätzlich `adapter_evidence={missing_fields, notes}` nach stderr. Die Provenienz geht also nicht verloren, und das Ausgabeschema der Analyse bleibt unverändert.
- `--provider openmarket` einfach nicht verwenden, die MMT- und generic-Pfade bleiben unverändert.
- Code-Rollback: den PR revertieren.
