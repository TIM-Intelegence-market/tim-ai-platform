#!/usr/bin/env python3
"""TIM_OPENMARKET_API_PROOF: minimal, read-only, authenticated OpenMarket read.

Resolves the key through TIM's secret model, performs ``GET /v1/points``
(TRADE_SIDE_AGNOSTIC_AGG, one closed 5-minute window; with ``--per-side`` also
TRADE_AGG), checks status, rate-limit headers and the documented REST contract,
and normalizes the result into TIM's AdapterInput. Prints only safe evidence:
never the key, the auth header, the environment or a response body.

FINAL=PASS requires all of: HTTP_STATUS=200, DOCUMENTED_ENVELOPE=PASS,
REST_TIMESTAMP_SCHEMA=PASS, SERIES_ID=PASS, WINDOW_SEMANTICS=PASS,
NORMALIZATION=PASS, and with --per-side also SIDE_LOCATION=PASS.
ENVELOPE_SHAPE (key names and types only) is a diagnostic, not a gate.

Configuration (on the target host):
  TIM_OPENMARKET_SECRET_PROVIDER=keychain|file|env
  TIM_OPENMARKET_BASE_URL=https://...   optional override of https://api.openmarket.xyz
usage: python scripts/openmarket_api_proof.py [--exchange BINANCE_FUTURES] [--raw-symbol BTCUSDT] [--per-side]
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.market_data.providers.openmarket.client import DEFAULT_BASE_URL, OpenMarketClient  # noqa: E402
from src.market_data.providers.openmarket.errors import OpenMarketError, OpenMarketErrorKind  # noqa: E402
from src.orderflow_scenario.adapters.openmarket import OpenMarketAdapter  # noqa: E402

GATES = ("DOCUMENTED_ENVELOPE", "REST_TIMESTAMP_SCHEMA", "SERIES_ID", "WINDOW_SEMANTICS", "NORMALIZATION")


def envelope_shape(payload, depth: int = 0) -> str:
    """Diagnostic only: key names and value types, never values."""
    if depth > 4:
        return "..."
    if isinstance(payload, dict):
        return "{" + ",".join(f"{key}:{envelope_shape(value, depth + 1)}" for key, value in sorted(payload.items())[:12]) + "}"
    if isinstance(payload, list):
        return f"list[{len(payload)}]" + (f"<{envelope_shape(payload[0], depth + 1)}>" if payload else "")
    return type(payload).__name__


def note_value(notes: set[str], key: str) -> str:
    return next((note.split("=", 1)[1] for note in notes if note.startswith(key + "=")), "UNPROVEN")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--exchange", default="BINANCE_FUTURES")
    parser.add_argument("--raw-symbol", default="BTCUSDT")
    parser.add_argument("--market-type", default="FUTURES", choices=["SPOT", "FUTURES"])
    parser.add_argument("--per-side", action="store_true", help="also request TRADE_AGG and check series[].id.side")
    args = parser.parse_args()

    evidence: dict[str, object] = {"SECRET_DISCLOSED": "NO", "HOST": socket.gethostname()}
    evidence["PROXY_ENV_SET"] = "YES" if any(os.environ.get(name) for name in ("HTTPS_PROXY", "https_proxy")) else "NO"
    client = OpenMarketClient(max_retries=1)
    try:
        client.secrets.api_key()
        evidence["SECRET_CONFIGURED"] = "YES"
    except OpenMarketError as error:
        evidence["SECRET_CONFIGURED"] = "NO"
        # Fixed texts only (auth.py); never the value. Fix with scripts/openmarket_store_key.py.
        evidence["SECRET_ERROR"] = str(error)
    evidence["BASE_URL"] = "DOCUMENTED_DEFAULT" if client.base_url == DEFAULT_BASE_URL else "OVERRIDE"
    final, reason = "FAIL", ""
    if evidence["SECRET_CONFIGURED"] == "NO":
        final, reason = "INCONCLUSIVE", "OPENMARKET_SECRET_NOT_AVAILABLE"
    else:
        host = urlsplit(client.base_url).hostname or ""
        try:
            socket.getaddrinfo(host, 443)
            evidence["DNS"] = "PASS"
        except OSError:
            evidence["DNS"] = "FAIL"
        start = (int(time.time()) // 60) * 60 - 600  # minute grid, fully in the past
        request = {
            "exchange": args.exchange, "raw_symbol": args.raw_symbol, "interval": "MINUTE",
            "from": start, "period": 300, "market_type": args.market_type,
        }
        responses = []
        original = client.get_points

        def capture(params):
            response = original(params)
            responses.append(response)
            return response

        client.get_points = capture
        started = time.perf_counter()
        try:
            adapted = OpenMarketAdapter(client, include_per_side=args.per_side).adapt(request)
        except OpenMarketError as error:
            # Only a 200 with the documented payload proves TLS to OpenMarket and an
            # accepted key; a proxy or gateway can answer anything else.
            evidence["TLS"] = "FAIL" if error.kind is OpenMarketErrorKind.TLS_FAILURE else "UNPROVEN"
            evidence["AUTH"] = "FAIL" if client.authenticated is False else "UNPROVEN"
            evidence["HTTP_STATUS"] = error.http_status
            evidence["ERROR_KIND"] = error.kind.value
            evidence["PROVIDER_CODE"] = error.provider_code
            reason = error.kind.value
        else:
            notes = set(adapted.extra_notes)
            problems = [m for m in adapted.missing_fields if m.startswith(("candle_rejected", "candle_conflict", "per_side_"))]
            evidence["HTTP_STATUS"] = responses[0].status
            evidence["DOCUMENTED_ENVELOPE"] = note_value(notes, "check:documented_envelope")
            evidence["REST_TIMESTAMP_SCHEMA"] = note_value(notes, "check:rest_timestamp_schema")
            evidence["SERIES_ID"] = note_value(notes, "check:series_id")
            evidence["WINDOW_SEMANTICS"] = note_value(notes, "check:time_semantics")
            evidence["NORMALIZATION"] = "FAIL" if problems else ("PASS" if adapted.candles else "UNPROVEN")
            if args.per_side:
                evidence["SIDE_LOCATION"] = note_value(notes, "check:side_location")
                evidence["PER_SIDE_AVAILABLE"] = "NO" if any(m.startswith("aggressive_volume:TRADE_AGG_unavailable") for m in adapted.missing_fields) else "YES"
            evidence["REST_SIDE_AGGRESSOR_SEMANTICS"] = "UNPROVEN"
            evidence["REJECTED_OR_CONFLICTING_POINTS"] = len(problems)
            evidence["RECORDS_NORMALIZED"] = len(adapted.candles)
            evidence["LATENCY_MS"] = round(responses[0].latency_seconds * 1000, 1)
            evidence["RESPONSE_BYTES"] = responses[0].response_bytes
            evidence["ADAPT_TOTAL_MS"] = round((time.perf_counter() - started) * 1000, 1)
            evidence["ENVELOPE_SHAPE"] = envelope_shape(responses[0].payload)  # diagnostic, not a gate
            gates = list(GATES) + (["SIDE_LOCATION"] if args.per_side else [])
            failed = [gate for gate in gates if evidence.get(gate) != "PASS"]
            all_ok = evidence["HTTP_STATUS"] == 200 and not failed
            evidence["TLS"] = evidence["AUTH"] = "PASS" if all_ok else "UNPROVEN"
            if all_ok:
                final, reason = "PASS", ""
            elif not adapted.candles and not problems:
                final, reason = "INCONCLUSIVE", "NO_CLOSED_CANDLES_IN_WINDOW"
            else:
                final, reason = "FAIL", "GATES_NOT_PASSED:" + ",".join(failed)
        finally:
            client.close()
        limits = client.rate_limit
        evidence.update(RATE_LIMIT_LIMIT=limits.limit, RATE_LIMIT_REMAINING=limits.remaining, RATE_LIMIT_USED=limits.used)
    evidence["UTC_TIMESTAMP"] = datetime.now(timezone.utc).isoformat()
    print("TIM_OPENMARKET_API_PROOF\n")
    for key, value in evidence.items():
        print(f"{key}={value}")
    print(f"\nFINAL={final}" + (f"\nREASON={reason}" if reason else ""))
    return 0 if final == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
