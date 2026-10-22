#!/usr/bin/env python3
"""Read-only capture of real OpenMarket ``GET /v1/points`` responses per data type.

Purpose: the field formats of OPEN_INTEREST_AGG, FUNDING_RATE_AGG,
LIQUIDATION_AGG, VOLUME_PROFILE_AGG and TPO_AGG are not documented in TIM.
This script fetches one small, closed window per type and stores the raw
response bodies so that schemas and parsers can be written against real data.

Safety:
- Only ``GET /v1/points`` through TIM's ``OpenMarketClient`` (same secret model,
  timeouts and rate-limit handling as the adapter). No writes anywhere at OpenMarket.
- The key is never printed or written. Stored are: response bodies (market
  data), HTTP status, provider error code, rate-limit headers and the query
  parameters (which contain no secret).
- Error bodies are stored truncated to 4 KiB, because they name missing or
  invalid parameters.

usage:
  TIM_OPENMARKET_SECRET_PROVIDER=file python scripts/openmarket_capture_samples.py \
      --out ./openmarket-samples [--exchange BINANCE_FUTURES] [--raw-symbol BTCUSDT] \
      [--interval HOUR] [--hours 6] [--types OPEN_INTEREST_AGG,...] [--extra key=value ...]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.market_data.providers.openmarket.client import (  # noqa: E402
    HttpResult,
    OpenMarketClient,
    _PersistentHttpsTransport,
)
from src.market_data.providers.openmarket.errors import OpenMarketError  # noqa: E402
from src.market_data.providers.openmarket.schemas import INTERVAL_SECONDS  # noqa: E402

DEFAULT_TYPES = (
    "OPEN_INTEREST_AGG",
    "FUNDING_RATE_AGG",
    "LIQUIDATION_AGG",
    "VOLUME_PROFILE_AGG",
    "TPO_AGG",
    # Reference types with a known schema, for comparison.
    "TRADE_SIDE_AGNOSTIC_AGG",
    "TRADE_AGG",
)
ERROR_BODY_LIMIT = 4096


def envelope_shape(payload, depth: int = 0) -> str:
    """Key names and value types only, never values."""
    if depth > 6:
        return "..."
    if isinstance(payload, dict):
        return "{" + ",".join(f"{key}:{envelope_shape(value, depth + 1)}" for key, value in sorted(payload.items())[:20]) + "}"
    if isinstance(payload, list):
        return f"list[{len(payload)}]" + (f"<{envelope_shape(payload[0], depth + 1)}>" if payload else "")
    return type(payload).__name__


class RecordingTransport:
    """Wraps the real transport and keeps the last raw result (for error bodies)."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.last: HttpResult | None = None

    def __call__(self, method, path, headers, timeout):
        self.last = None
        self.last = self.inner(method, path, headers, timeout)
        return self.last

    def close(self) -> None:
        self.inner.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, help="directory for the captured samples")
    parser.add_argument("--exchange", default="BINANCE_FUTURES")
    parser.add_argument("--raw-symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="HOUR", choices=sorted(INTERVAL_SECONDS))
    parser.add_argument("--hours", type=int, default=6, help="window length in hours (closed intervals only)")
    parser.add_argument("--types", default=",".join(DEFAULT_TYPES))
    parser.add_argument("--extra", action="append", default=[], help="additional query parameter key=value")
    parser.add_argument("--pause", type=float, default=1.0, help="seconds between requests")
    args = parser.parse_args()

    step = INTERVAL_SECONDS[args.interval]
    period = max(step, (args.hours * 3600) // step * step)
    start = (int(time.time()) // step) * step - period  # grid aligned, fully closed
    extra = {}
    for item in args.extra:
        key, sep, value = item.partition("=")
        if not sep or not key:
            parser.error(f"--extra expects key=value, got {item!r}")
        extra[key] = value

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out).expanduser() / stamp
    out.mkdir(parents=True, exist_ok=False)

    client = OpenMarketClient(max_retries=1)
    parts = urlsplit(client.base_url)
    recorder = RecordingTransport(_PersistentHttpsTransport(parts.hostname or "", parts.port))
    client._transport = recorder

    summary = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "exchange": args.exchange, "raw_symbol": args.raw_symbol, "interval": args.interval,
        "from": start, "period": period, "extra_params": extra, "results": [],
    }
    print("TIM_OPENMARKET_CAPTURE_SAMPLES")
    try:
        for data_type in [name.strip() for name in args.types.split(",") if name.strip()]:
            params = {"type": data_type, "exchange": args.exchange, "rawSymbol": args.raw_symbol,
                      "interval": args.interval, "from": start, "period": period, **extra}
            entry: dict = {"type": data_type, "params": params}
            try:
                response = client.get_points(params)
            except OpenMarketError as error:
                entry.update(status=error.http_status, error_kind=error.kind.value, provider_code=error.provider_code)
                raw = recorder.last
                if raw is not None and raw.body:
                    path = out / f"{data_type}.error.txt"
                    path.write_bytes(raw.body[:ERROR_BODY_LIMIT])
                    entry["error_body_file"] = path.name
            else:
                raw = recorder.last
                path = out / f"{data_type}.json"
                path.write_bytes(raw.body if raw is not None else json.dumps(response.payload, default=str).encode())
                entry.update(status=response.status, bytes=response.response_bytes, sha256=response.body_sha256,
                             file=path.name, shape=envelope_shape(response.payload))
            entry["rate_limit"] = client.rate_limit.as_dict()
            summary["results"].append(entry)
            print(f"{data_type}: status={entry.get('status')} kind={entry.get('error_kind', 'OK')} "
                  f"code={entry.get('provider_code')} bytes={entry.get('bytes')}")
            time.sleep(max(0.0, args.pause))
    finally:
        client.close()
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"OUT={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
