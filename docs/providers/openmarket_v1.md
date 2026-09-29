# OpenMarket v1 – Provider-Modell für TIM

Stand 2026-09-29. Scope: `ORDERFLOW_RESEARCH_PROVIDER`. Die Live-Ingestion über Binance bleibt unverändert.

## Quellenlage

| Quelle | Status |
|---|---|
| Offizielle OpenMarket-Doku, vom Owner außerhalb der Cloud-Umgebung geprüft (29.09.) | Grundlage aller Angaben unter „Belegt“ |
| Direkter Zugriff aus der Claude-Cloud-Umgebung | `CLAUDE_DIRECT_DOC_ACCESS=BLOCKED` (Egress-Proxy sperrt `openmarket.xyz`) |
| Echte API-Antwort | Noch keine. Die Belege liefert `scripts/openmarket_api_proof.py` auf dem Zielhost. |

## Belegt

- **REST:** `GET /v1/points`.
- **Auth:** Header `X-OpenMarket-Key`. Der Key ist ein serverseitiges Secret.
- **Parameter:**
  - `type`, `exchange`, `rawSymbol` (alternativ `coin`, `normalizedSymbol`);
  - `from` = Unix-Sekunden (inklusiv), `period` = Dauer in Sekunden;
  - Intervalle `MINUTE, FIVE_MINUTES, FIFTEEN_MINUTES, THIRTY_MINUTES, HOUR, FOUR_HOURS, DAY, WEEK`.
- **Datentypen:** `TRADE_SIDE_AGNOSTIC_AGG, TRADE_AGG, OPEN_INTEREST_AGG, FUNDING_RATE_AGG, LIQUIDATION_AGG, VOLUME_PROFILE_AGG, TPO_AGG, BLOCK_BOOK_SNAPSHOT_AGG, HYPERLIQUID_LIQUIDATION_AGG, HYPERLIQUID_TRIGGER_LIQUIDITY_AGG`.
- **Candle-Felder (`TRADE_SIDE_AGNOSTIC_AGG`):** `open high low close volume timestamp firstTimestamp lastTimestamp`.
- **`TRADE_AGG`:** getrennte BUY- und SELL-Serien.
- **Rate-Limit:** gewichtsbasiert. Header `X-RateLimit-Limit/-Remaining/-Used/-Reset`, dazu `Retry-After` (vor allem bei 429).
- **Fehler:**
  - `400 INVALID_PARAMS | INVALID_EXCHANGE | INVALID_SYMBOL | INVALID_TIMEFRAME`;
  - `401 INVALID_API_KEY`;
  - `403` für Typ/Tier, History-Tiefe, Aggregation oder maximale Punktzahl;
  - `429`, `500 INTERNAL_ERROR`, `504 TIMEOUT`.
- **WebSocket** (nur Audit, siehe unten): `public/authenticate`, `public/subscribe`, Typ `TRADE` mit `series.{exchange,symbol,normalizedSymbol,category,side}` und `trade.{id,price,amount,timestamp.seconds,timestamp.nanoseconds}`. `trade.id` ist die Exchange-Trade-ID.

## Nicht belegt – im Code bewusst nicht angenommen

| Punkt | Umgang im Code | Klärung |
|---|---|---|
| Basis-URL (Host) | muss als `TIM_OPENMARKET_BASE_URL` gesetzt werden, nur `https` | Doku/Konto |
| JSON-Hülle um die Punkte | Punktlisten werden an den dokumentierten Feldern erkannt, der Pfad landet in der Provenienz (`envelope_paths`). Mehrdeutig → `SCHEMA_MISMATCH` | `ENVELOPE_SHAPE` im Proof |
| Ort der BUY/SELL-Kennung bei `TRADE_AGG` | `side` oder `series.side` des nächsten umschließenden Objekts; fehlt sie → `SCHEMA_MISMATCH` | Proof mit `TRADE_AGG` |
| Zeitstempel-Kodierung der REST-Punkte | akzeptiert `{seconds,nanoseconds}`, ganzzahlige Unix-Sekunden, ISO-8601 mit Offset. Millisekunden-Größen werden als mehrdeutig abgelehnt | Proof |
| Parametername für das Intervall | `interval` (aus der Doku-Übersicht; im Proof bestätigen) | Proof |
| BUY/SELL = Aggressor-Seite? | nicht angenommen: `net_delta`/`aggressive_*` bleiben leer, außer `side_is_aggressor=True` | Doku-Definition |
| Volumen-Einheit (Base/Quote) | wird unverändert übernommen (`units=as_reported_by_provider`) | Doku |
| Schemas von `VOLUME_PROFILE_AGG`, `OPEN_INTEREST_AGG`, `FUNDING_RATE_AGG`, `LIQUIDATION_AGG`, `TPO_AGG` | nicht implementiert (keine Felddefinition belegt) | Doku, dann v1.1 |

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
| `TIM_OPENMARKET_BASE_URL` | Pflicht, `https://…` |

**Schutz des Keys:**
- Der Key steht nur im Request-Header, nie in der URL.
- `repr`/`str` liefern `@REDACTED@`.
- Fehlermeldungen enthalten keine Response-Bodies, nur dokumentierte Codes.

## Fehler und Fail-Safe

| Lage | Klasse | TIM-Reaktion |
|---|---|---|
| kein Key / keine Basis-URL | `NO_SECRET` / `NOT_CONFIGURED` | kein Request; CLI endet mit Exit 3, keine Analyse |
| Key ungültig oder abgelaufen | `INVALID_SECRET` (401) | Abbruch ohne Retry, `authenticated=false` |
| Typ, Tier oder Tiefe nicht erlaubt | `FORBIDDEN` (403) | Abbruch; per-Side-Anfrage → nur als fehlend markiert |
| Rate-Limit | `RATE_LIMITED` (429) | `Retry-After` beachten (Obergrenze 30 s), sonst sofortiger Abbruch; Zustand in `rate_limit_state` |
| API nicht erreichbar | `DNS_FAILURE`, `TLS_FAILURE`, `NETWORK_FAILURE`, `TIMEOUT` | begrenzte Retries (Standard 2, max. 5) mit Backoff, dann Abbruch |
| 5xx / 504 | `API_FAILURE` / `TIMEOUT` | wie oben |
| ungültige oder abweichende Antwort | `SCHEMA_MISMATCH` | Abbruch; einzelne ungültige Punkte → `missing_fields`, nie ersetzt |
| Teilantwort (Lücken, nur eine Seite) | – | nur vorhandene Punkte; BUY/SELL nur über gepaarte Intervalle |
| veraltete Daten | – | laufendes Intervall `closed=false`; Zeitstempel und Anfragezeit in der Provenienz |

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
TIM_OPENMARKET_SECRET_PROVIDER=file TIM_OPENMARKET_BASE_URL=https://… \
  python scripts/openmarket_api_proof.py --exchange BINANCE_FUTURES --raw-symbol BTCUSDT
```

- Ausgegeben werden nur Statusfelder. `AUTH` und `TLS` werden nur bei HTTP 200 mit gültigem Schema zu `PASS`, sonst `UNPROVEN`.
- `ENVELOPE_SHAPE` zeigt nur Schlüsselnamen und Typen. Damit werden die offenen Punkte aus „Nicht belegt“ geklärt.

## Rollback

- Kein Schema und keine Laufzeitkomponente geändert.
- `--provider openmarket` einfach nicht verwenden, die MMT- und generic-Pfade bleiben unverändert.
- Code-Rollback: den PR revertieren.
