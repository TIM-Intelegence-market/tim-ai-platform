"""Command-line entry point for the Orderflow Scenario and Trade Decision Manager.

Reads structured JSON or a parsed screenshot payload from stdin/--input and
prints the machine-readable AnalysisOutput. In all modes there is no order,
account, or exchange interaction.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .adapters import GenericOrderflowAdapter, MMTScreenshotAdapter, MMTStructuredDataAdapter
from .engines.pipeline import Pipeline, PipelineInputs
from .config import default_config
from .domain import MarketContext
from .schema_validation import validate_analysis


def _market_context(data: dict[str, Any], observed) -> MarketContext:
    return MarketContext(
        symbol=str(data["symbol"]),
        venue=str(data.get("venue", "UNKNOWN")),
        market_type=str(data.get("market_type", "FUTURES")),
        timeframe=str(data.get("timeframe", "4H")),
        timestamp=observed,
    )


def _pipeline_inputs(adapter, data: dict[str, Any]) -> PipelineInputs:
    from decimal import Decimal

    adapted = adapter.adapt(data)
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
    last = candles[-1].close if candles else None
    levels = None
    if adapted.levels:
        from .engines.scenario_generator import LevelSet

        levels = LevelSet(range_high=adapted.levels.get("range_high"), range_low=adapted.levels.get("range_low"), value_area_high=adapted.levels.get("value_area_high"), value_area_low=adapted.levels.get("value_area_low"), last_price=adapted.price_now or Decimal(str(last)) if last is not None else None)

    return PipelineInputs(
        market_context=_market_context(adapted, adapted.observed_at),
        candles=tuple(candles),
        trades=(),
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
        spot_futures_separated=True,
        source_name=adapters_name(adapted),
    )


def adapters_name(adapted) -> str:
    return adapted.symbol if hasattr(adapted, "symbol") else "UNKNOWN"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ofsc", description="Orderflow Scenario and Trade Decision Manager (observation-only).")
    parser.add_argument("--input", default=None, help="path to JSON input; defaults to stdin")
    parser.add_argument("--provider", choices=["generic", "mmt-structured", "mmt-screenshot"], default="generic")
    parser.add_argument("--validate", action="store_true", help="also print schema validation status")
    args = parser.parse_args(argv)

    try:
        if args.input:
            payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
        else:
            payload = json.load(sys.stdin)

        if args.provider == "mmt-screenshot":
            adapter = MMTScreenshotAdapter()
            adapt_input = payload.get("screenshot", payload)
        elif args.provider == "mmt-structured":
            adapter = MMTStructuredDataAdapter()
            adapt_input = payload
        else:
            adapter = GenericOrderflowAdapter()
            adapt_input = payload

        pipeline_inputs = _pipeline_inputs(adapter, adapt_input)
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
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())