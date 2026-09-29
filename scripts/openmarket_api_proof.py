#!/usr/bin/env python3
"""TIM_OPENMARKET_API_PROOF: one minimal, read-only, authenticated OpenMarket read.

Resolves the key through TIM's secret model, performs a single
``GET /v1/points`` (TRADE_SIDE_AGNOSTIC_AGG, one short window), inspects status
and rate-limit headers, parses the response and normalizes it into TIM's
AdapterInput. Prints only safe evidence: never the key, the auth header, the
environment or a response body. Envelope key names (not values) are printed so
the unverified response envelope can be confirmed.

Configuration (on the target host):
  TIM_OPENMARKET_SECRET_PROVIDER=keychain|file|env
  TIM_OPENMARKET_BASE_URL=https://...        (from the OpenMarket docs)
usage: python scripts/openmarket_api_proof.py [--exchange BINANCE_FUTURES] [--raw-symbol BTCUSDT]
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

from src.market_data.providers.openmarket.client import OpenMarketClient  # noqa: E402
from src.market_data.providers.openmarket.errors import OpenMarketError, OpenMarketErrorKind  # noqa: E402
from src.orderflow_scenario.adapters.openmarket import OpenMarketAdapter  # noqa: E402

DNS_KINDS = {OpenMarketErrorKind.DNS_FAILURE}
TLS_KINDS = {OpenMarketErrorKind.TLS_FAILURE}


def envelope_shape(payload, depth: int = 0) -> str:
    if depth > 2:
        return "..."
    if isinstance(payload, dict):
        return "{" + ",".join(f"{key}:{envelope_shape(value, depth + 1)}" for key, value in sorted(payload.items())[:12]) + "}"
    if isinstance(payload, list):
        return f"list[{len(payload)}]" + (f"<{envelope_shape(payload[0], depth + 1)}>" if payload else "")
    return type(payload).__name__


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--exchange", default="BINANCE_FUTURES")
    parser.add_argument("--raw-symbol", default="BTCUSDT")
    parser.add_argument("--market-type", default="FUTURES", choices=["SPOT", "FUTURES"])
    args = parser.parse_args()

    evidence: dict[str, object] = {"SECRET_DISCLOSED": "NO", "HOST": socket.gethostname()}
    evidence["PROXY_ENV_SET"] = "YES" if any(os.environ.get(name) for name in ("HTTPS_PROXY", "https_proxy")) else "NO"
    client = OpenMarketClient(max_retries=1)
    evidence["SECRET_CONFIGURED"] = "YES" if client.secrets.configured() else "NO"
    evidence["BASE_URL_CONFIGURED"] = "YES" if client.base_url else "NO"
    final, reason = "FAIL", ""
    if evidence["SECRET_CONFIGURED"] == "NO":
        final, reason = "INCONCLUSIVE", "OPENMARKET_SECRET_NOT_AVAILABLE"
    elif not client.base_url:
        final, reason = "INCONCLUSIVE", "OPENMARKET_BASE_URL_NOT_CONFIGURED"
    else:
        host = urlsplit(client.base_url).hostname or ""
        try:
            socket.getaddrinfo(host, 443)
            evidence["DNS"] = "PASS"
        except OSError:
            evidence["DNS"] = "FAIL"
        now = int(time.time())
        request = {
            "exchange": args.exchange, "raw_symbol": args.raw_symbol, "interval": "MINUTE",
            "from": now - 600, "period": 300, "market_type": args.market_type,
        }
        captured = {}
        original = client.get_points

        def capture(params):
            response = original(params)
            captured["response"] = response
            return response

        client.get_points = capture
        started = time.perf_counter()
        try:
            adapted = OpenMarketAdapter(client, include_per_side=False).adapt(request)
        except OpenMarketError as error:
            # Only an HTTP 200 with a parsable OpenMarket payload proves TLS to the
            # provider and an accepted key; a proxy or gateway can answer anything else.
            evidence["TLS"] = "FAIL" if error.kind in TLS_KINDS else "UNPROVEN"
            evidence["AUTH"] = "FAIL" if client.authenticated is False else "UNPROVEN"
            evidence["HTTP_STATUS"] = error.http_status
            evidence["ERROR_KIND"] = error.kind.value
            evidence["PROVIDER_CODE"] = error.provider_code
            reason = error.kind.value
        else:
            response = captured["response"]
            evidence.update(
                TLS="PASS", AUTH="PASS", HTTP_STATUS=response.status, SCHEMA="PASS", NORMALIZATION="PASS",
                ENVELOPE_SHAPE=envelope_shape(response.payload),
                RECORDS_NORMALIZED=len(adapted.candles),
                LATENCY_MS=round(response.latency_seconds * 1000, 1),
                RESPONSE_BYTES=response.response_bytes,
                ADAPT_TOTAL_MS=round((time.perf_counter() - started) * 1000, 1),
                MISSING_FIELDS=",".join(adapted.missing_fields),
            )
            final = "PASS" if adapted.candles else "INCONCLUSIVE"
            reason = "" if adapted.candles else "NO_CANDLES_IN_WINDOW"
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
