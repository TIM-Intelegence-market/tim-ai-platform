# TIM Live Execution Risk Register

## Search method

Static searches covered order creation/submission/execution, market and limit
orders, cancellation, positions, leverage, margin, transfers, wallets,
authenticated/private requests, API keys/secrets, Binance order paths and
common SDK variants. Imports, settings and reachable calls from `main.py` were
also traced.

## Result

```text
NO_LIVE_EXECUTION_PATH_FOUND
```

This result applies to the inspected repository. It is not a mathematical
guarantee about external services, unpublished code or future changes.

## Candidate register

| ID | Candidate | Path/symbol | Reachability and trigger | Secrets/endpoint | Existing protection | Risk | Confidence |
|---|---|---|---|---|---|---|---|
| EX-001 | Public market stream | `src/data_ingestion/binance_ws.py:BinanceTradeStream` | Reachable from `main.py`; starts in normal runtime | No secret; `wss://stream.binance.com:9443/ws/...@aggTrade` | Public event type validation; no request method for orders | INFORMATIONAL | HIGH |
| EX-002 | Paper outcome journal | `src/paper/automation.py:PaperAutomation.evaluate_case` | Not wired into `main.py`; requires `enabled=True`, closed case and delay | None | `test_only=False` raises; default disabled; no exchange interface | LOW | HIGH |
| EX-003 | Execution-event detection | `src/acceptance/monitor.py`, `src/operational/research_health.py` | Monitoring only | None | Treats execution-like events as violations | INFORMATIONAL | HIGH |
| EX-004 | Dashboard test fixture containing `TRADE_EXECUTED` | `tests/test_dashboard.py`, `tests/test_acceptance.py` | Test-only synthetic event | None | Explicitly rejected/hidden | LOW | HIGH |
| EX-005 | `Setup` data class | `src/models/market_data.py:Setup` | No runtime producer or consumer that executes it; disabled default | None | `enabled=False`; no entry/exit/order fields | INFORMATIONAL | HIGH |
| EX-006 | Optional local LLM | `src/llm/ollama_client.py`; `main.py:explain` | Only if `TIM_ENABLE_OLLAMA=true`; explanation logging | Local Ollama URL; no exchange credential | prompt/output policy and no execution caller | LOW | MEDIUM |

## Call-path analysis

The only exchange-facing reachable path is:

```text
TIMApplication.run
→ BinanceTradeStream.run
→ websockets.connect(public aggTrade URL)
→ parse_message
→ TIMApplication.on_trade
```

The handler persists and analyzes received events. It exposes no method for
HTTP signing, private REST calls, order submission, cancellation, leverage,
margin, transfer, account or wallet actions.

## Secrets and endpoints

- `config/settings.py` defines a PostgreSQL URL, public WebSocket URL and local
  Ollama URL.
- No exchange API-key or secret setting was found.
- No signed-request helper, exchange REST client or private endpoint was found.
- The database default contains a local development password; it is unrelated
  to exchange execution and should still be treated as configuration hygiene.

## Bypass analysis

No existing live adapter exists to bypass. Future risk would arise if a new
dependency or HTTP wrapper introduced private calls outside a protected path.
Documentation and `OBSERVE` labels alone would not prevent that. A future
implementation must therefore add:

1. protected-path registry;
2. fail-closed mode authority;
3. independent risk authorization;
4. global kill switch;
5. credential isolation;
6. append-only correlated audit events;
7. tests that prohibit direct Strategy → Exchange calls.

These are architecture recommendations only and are not implemented here.

## Risk conclusion

Largest current live-execution risk class: **LOW** (TEST_ONLY paper journal and
optional explanation path). There is no HIGH or CRITICAL execution candidate
in the inspected code.

