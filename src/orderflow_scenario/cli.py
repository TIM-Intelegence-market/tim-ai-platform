"""Command-line entry point for the Orderflow Scenario and Trade Decision Manager.

Reads structured JSON or a parsed screenshot payload from stdin/--input and
prints the machine-readable AnalysisOutput. In all modes there is no order,
account, or exchange interaction.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

from .adapters import GenericOrderflowAdapter, MMTScreenshotAdapter, MMTStructuredDataAdapter, OpenMarketAdapter
from .engines.pipeline import Pipeline, PipelineInputs
from .config import default_config
from .domain import MarketContext
from .schema_validation import validate_analysis
from src.knowledge.broncx_feed import BroncxFeedStore
from src.market_data.providers.openmarket.errors import OpenMarketError


def _market_context(data: Any, observed) -> MarketContext:
    # Adapters return an AdapterInput (attributes); mappings are still accepted.
    def value(name: str, default: str | None = None) -> Any:
        if isinstance(data, dict):
            return data[name] if default is None else data.get(name, default)
        return getattr(data, name) if default is None else getattr(data, name, default)

    return MarketContext(
        symbol=str(value("symbol")),
        venue=str(value("venue", "UNKNOWN")),
        market_type=str(value("market_type", "FUTURES")),
        timeframe=str(value("timeframe", "4H")),
        timestamp=observed,
    )


def _pipeline_inputs(adapter, data: dict[str, Any]) -> PipelineInputs:
    from decimal import Decimal

    adapted = adapter.adapt(data)
    rejected = [item for item in adapted.missing_fields if item.startswith("candles[")]
    if not adapted.candles and rejected:
        # Every supplied candle was unusable: an input error, not a market condition.
        raise ValueError(f"no usable candles in input ({len(rejected)} rejected, first: {rejected[0]})")
    candles = []
    for raw in adapted.candles:
        candles.append(
            __import__("src.models.market_data", fromlist=["Candle"]).Candle(
                symbol=raw["symbol"],
                timeframe=raw["timeframe"],
                open_time=__import__("datetime", fromlist=["datetime"]).datetime.fromisoformat(raw["open_time"]),
                close_time=__import__("datetime", fromlist=["datetime"]).datetime.fromisoformat(raw.get("close_time") or raw["open_time"]),
                open=raw["open"],
                high=raw["high"],
                low=raw["low"],
                close=raw["close"],
                volume=raw["volume"],
                trade_count=raw["trade_count"],
                closed=raw.get("closed", True),
            )
        )
    trades = []
    for raw in adapted.trades:
        trades.append(
            __import__("src.models.market_data", fromlist=["Trade"]).Trade(
                symbol=raw["symbol"],
                price=raw["price"],
                quantity=raw["quantity"],
                event_time=__import__("datetime", fromlist=["datetime"]).datetime.fromisoformat(raw["event_time"]),
                trade_id=raw.get("trade_id"),
                buyer_is_maker=raw.get("buyer_is_maker"),
            )
        )
    last = candles[-1].close if candles else None
    levels = None
    if adapted.levels:
        from .engines.scenario_generator import LevelSet

        levels = LevelSet(range_high=adapted.levels.get("range_high"), range_low=adapted.levels.get("range_low"), value_area_high=adapted.levels.get("value_area_high"), value_area_low=adapted.levels.get("value_area_low"), last_price=adapted.price_now or Decimal(str(last)) if last is not None else None)

    notes = set(getattr(adapted, "extra_notes", ()) or ())
    return PipelineInputs(
        market_context=_market_context(adapted, adapted.observed_at),
        candles=tuple(candles),
        trades=tuple(trades),
        price_now=adapted.price_now if adapted.price_now is not None else (Decimal(str(last)) if last is not None else None),
        price_timestamp=adapted.price_timestamp,
        net_delta=adapted.net_delta,
        aggressive_buy_volume=adapted.aggressive_buy_volume,
        aggressive_sell_volume=adapted.aggressive_sell_volume,
        total_volume=adapted.total_volume,
        open_interest_with_price=adapted.open_interest_with_price,
        delta_divergence=adapted.delta_divergence,
        levels=levels,
        structured=adapted.structured,
        screenshot_confidence=adapted.screenshot_confidence,
        estimated_prices=adapted.estimated_prices,
        venue_mixed=False,
        # Adapters that cannot prove these say so explicitly (OpenMarket); others keep the default.
        delta_definition_verified="verify:delta_definition=false" not in notes,
        time_unit_verified="verify:time_unit=false" not in notes,
        spot_futures_separated=True,
        source_name=adapters_name(adapted),
    )


def adapters_name(adapted) -> str:
    return adapted.symbol if hasattr(adapted, "symbol") else "UNKNOWN"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ofsc", description="Orderflow Scenario and Trade Decision Manager (observation-only).")
    parser.add_argument("--input", default=None, help="path to JSON input; defaults to stdin")
    parser.add_argument("--provider", choices=["generic", "mmt-structured", "mmt-screenshot", "openmarket"], default="generic")
    openmarket = parser.add_argument_group("openmarket", "read-only OpenMarket request (instead of --input)")
    openmarket.add_argument("--exchange", help="OpenMarket exchange, e.g. BINANCE_FUTURES")
    openmarket.add_argument("--raw-symbol", help="exchange symbol, e.g. BTCUSDT")
    openmarket.add_argument("--interval", help="MINUTE, FIVE_MINUTES, ..., FOUR_HOURS, DAY, WEEK")
    openmarket.add_argument("--from", dest="from_seconds", type=int, help="UTC epoch seconds (inclusive)")
    openmarket.add_argument("--period", type=int, help="duration in seconds")
    openmarket.add_argument("--market-type", choices=["SPOT", "FUTURES"])
    openmarket.add_argument("--no-per-side", action="store_true", help="skip the TRADE_AGG per-side request")
    parser.add_argument("--validate", action="store_true", help="also print schema validation status")
    parser.add_argument("--broncx-feed", type=Path, default=None, help="Broncx Discord feed directory (external guidance: weights scenario scores, adds level scenarios, never confirms)")
    parser.add_argument("--broncx-max-age-hours", type=float, default=24.0, help="Broncx posts older than this are shown as stale and not used")
    args = parser.parse_args(argv)

    try:
        if args.provider == "openmarket":
            payload = {
                "exchange": args.exchange, "raw_symbol": args.raw_symbol, "interval": args.interval,
                "from": args.from_seconds, "period": args.period, "market_type": args.market_type,
            }
            if any(value is None for value in payload.values()):
                raise ValueError("--provider openmarket requires --exchange --raw-symbol --interval --from --period --market-type")
        elif args.input:
            payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
        else:
            payload = json.load(sys.stdin)

        if args.provider == "openmarket":
            adapter = OpenMarketAdapter(include_per_side=not args.no_per_side)
            adapt_input = payload
        elif args.provider == "mmt-screenshot":
            adapter = MMTScreenshotAdapter()
            adapt_input = payload.get("screenshot", payload)
        elif args.provider == "mmt-structured":
            adapter = MMTStructuredDataAdapter()
            adapt_input = payload
        else:
            adapter = GenericOrderflowAdapter()
            adapt_input = payload

        pipeline_inputs = _pipeline_inputs(adapter, adapt_input)
        if args.provider == "openmarket":
            evidence = getattr(adapter, "last_input", None)
            if evidence is not None:
                sys.stderr.write(
                    "adapter_evidence="
                    + json.dumps({"missing_fields": list(evidence.missing_fields), "notes": list(evidence.extra_notes)}, sort_keys=True)
                    + "\n"
                )
        if args.broncx_feed is not None:
            if args.broncx_max_age_hours <= 0:
                raise ValueError("--broncx-max-age-hours must be positive")
            if not args.broncx_feed.expanduser().is_dir():
                raise ValueError(f"--broncx-feed directory not found: {args.broncx_feed}")
            pipeline_inputs = dataclasses.replace(
                pipeline_inputs,
                external_posts=tuple(BroncxFeedStore(args.broncx_feed.expanduser()).load()),
                external_max_age=timedelta(hours=args.broncx_max_age_hours),
            )
        analysis = Pipeline(default_config()).run(pipeline_inputs)
        output = analysis.to_dict()
        sys.stdout.write(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

        if args.validate:
            ok, errors = validate_analysis(output)
            sys.stderr.write(f"schema_validation={'PASS' if ok else 'FAIL'}\n")
            if not ok:
                for error in errors:
                    sys.stderr.write(f"  - {error}\n")
                return 2
        return 0
    except OpenMarketError as exc:
        # Classified, secret-free provider failure: fail closed, no analysis.
        sys.stderr.write(f"ERROR: {exc}\n")
        return 3
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 2
    except (TypeError, AttributeError) as exc:
        # Wrongly shaped input (e.g. a list or number where an object is expected): input error, no traceback.
        sys.stderr.write(f"ERROR: malformed input: {type(exc).__name__}: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())