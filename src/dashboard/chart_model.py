"""Chart model for the TIM chart page (read-only, no orders).

Builds everything the /chart page draws from TIM's own candles:

- range high/low and last price,
- a volume profile with POC and value area (VAH/VAL), estimated from candles,
- break-of-structure (BOS) levels per timeframe from confirmed swing points,
- TIM's orderflow scenarios with entry zone, trigger and a preview stop/targets.

Stop and targets come from TIM's TradePlanBuilder rules, applied to a scenario
that is NOT confirmed. They are a preview of TIM's rules, never a trade signal.
All functions are pure; the caller passes copies of the runtime candles.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping, Sequence

from src.dashboard.constants import CHART_CANDLE_LIMIT
from src.dashboard.helpers import _number

CHART_TIMEFRAMES = ("1m", "5m", "15m", "1h")
DEFAULT_TIMEFRAME = "15m"
CHART_VISIBLE = 120  # candles drawn per chart
VALUE_AREA_SHARE = 0.70
PROFILE_TARGET_BINS = 60
PIVOT_WINDOW = 2  # same pivot width as orderflow_scenario.engines.market_state
TIMEFRAME_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}


def _time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def clean_candles(raw: Sequence[Mapping[str, Any]], timeframe: str | None = None) -> list[dict[str, Any]]:
    """Valid OHLC candles of one timeframe, sorted by open time, one per open time."""
    by_open: dict[datetime, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        if timeframe is not None and item.get("timeframe") not in (None, timeframe):
            continue
        opened = _time(item.get("open_time"))
        values = [_number(item.get(key)) for key in ("open", "high", "low", "close")]
        if opened is None or any(value is None or not math.isfinite(value) or value <= 0 for value in values):
            continue
        open_, high, low, close = values
        if low > min(open_, close) or high < max(open_, close) or low > high:
            continue
        volume = _number(item.get("volume"))
        by_open[opened] = {
            "symbol": str(item.get("symbol") or "BTCUSDT"),
            "timeframe": str(item.get("timeframe") or timeframe or "?"),
            "open_time": opened,
            "close_time": _time(item.get("close_time")) or opened,
            "open": open_, "high": high, "low": low, "close": close,
            "volume": volume if volume is not None and math.isfinite(volume) and volume > 0 else 0.0,
        }
    return [by_open[key] for key in sorted(by_open)]


def _nice_step(span: float, bins: int = PROFILE_TARGET_BINS) -> float:
    raw = max(span / bins, 1e-9)
    magnitude = 10 ** math.floor(math.log10(raw))
    for factor in (1, 2, 2.5, 5, 10):
        if raw <= factor * magnitude:
            return factor * magnitude
    return 10 * magnitude


def volume_profile(candles: Sequence[Mapping[str, Any]], share: float = VALUE_AREA_SHARE) -> dict[str, Any] | None:
    """Volume by price, POC and value area.

    Each candle's volume is spread evenly over its high-low range (no trades
    are available here), so the profile is an estimate. POC is the centre of
    the fullest bin; the value area grows from the POC towards the fuller
    neighbour until it holds ``share`` of the volume.
    """
    usable = [c for c in candles if c["volume"] > 0]
    if len(usable) < 2:
        return None
    low = min(c["low"] for c in usable)
    high = max(c["high"] for c in usable)
    step = _nice_step(max(high - low, high * 0.0005))
    base = math.floor(low / step) * step
    count = max(1, int(math.ceil((high - base) / step)) + 1)
    bins = [0.0] * count
    for candle in usable:
        lo, hi, vol = candle["low"], candle["high"], candle["volume"]
        first = min(count - 1, int((lo - base) // step))
        last = min(count - 1, int((hi - base) // step))
        if hi <= lo or first == last:
            bins[first] += vol
            continue
        for index in range(first, last + 1):
            edge_lo = max(lo, base + index * step)
            edge_hi = min(hi, base + (index + 1) * step)
            if edge_hi > edge_lo:
                bins[index] += vol * (edge_hi - edge_lo) / (hi - lo)
    total = sum(bins)
    if total <= 0:
        return None
    poc_index = max(range(count), key=lambda i: (bins[i], -abs(i - count / 2)))
    lo_i = hi_i = poc_index
    covered = bins[poc_index]
    while covered < total * share and (lo_i > 0 or hi_i < count - 1):
        below = bins[lo_i - 1] if lo_i > 0 else -1.0
        above = bins[hi_i + 1] if hi_i < count - 1 else -1.0
        if above >= below:
            hi_i += 1
            covered += bins[hi_i]
        else:
            lo_i -= 1
            covered += bins[lo_i]
    return {
        "poc": round(base + (poc_index + 0.5) * step, 8),
        "vah": round(base + (hi_i + 1) * step, 8),
        "val": round(base + lo_i * step, 8),
        "step": step,
        "bins": [{"low": round(base + i * step, 8), "high": round(base + (i + 1) * step, 8), "volume": round(v, 8)} for i, v in enumerate(bins) if v > 0],
        "total_volume": round(total, 8),
        "value_area_share": share,
    }


def swing_points(candles: Sequence[Mapping[str, Any]], width: int = PIVOT_WINDOW) -> list[dict[str, Any]]:
    result = []
    for index in range(width, len(candles) - width):
        candle = candles[index]
        neighbours = list(candles[index - width:index]) + list(candles[index + 1:index + width + 1])
        if all(candle["high"] > item["high"] for item in neighbours):
            result.append({"index": index, "price": candle["high"], "kind": "HIGH"})
        if all(candle["low"] < item["low"] for item in neighbours):
            result.append({"index": index, "price": candle["low"], "kind": "LOW"})
    return result


def break_of_structure(candles: Sequence[Mapping[str, Any]], timeframe: str, width: int = PIVOT_WINDOW) -> list[dict[str, Any]]:
    """Latest bullish and bearish BOS: first close beyond a confirmed swing high/low.

    A swing is confirmed ``width`` candles after it formed; only closes after
    that count as a break. Returns at most one event per direction.
    """
    events: dict[str, dict[str, Any]] = {}
    for swing in swing_points(candles, width):
        start = swing["index"] + width + 1
        for index in range(start, len(candles)):
            close = candles[index]["close"]
            broken = close > swing["price"] if swing["kind"] == "HIGH" else close < swing["price"]
            if broken:
                direction = "UP" if swing["kind"] == "HIGH" else "DOWN"
                event = {
                    "timeframe": timeframe,
                    "direction": direction,
                    "level": swing["price"],
                    "swing_time": candles[swing["index"]]["open_time"].isoformat(),
                    "break_time": candles[index]["open_time"].isoformat(),
                    "break_index": index,
                }
                current = events.get(direction)
                if current is None or (index, swing["index"]) > (current["break_index"], current.get("_swing", -1)):
                    events[direction] = {**event, "_swing": swing["index"]}
                break
    result = []
    for event in events.values():
        event.pop("_swing", None)
        result.append(event)
    return sorted(result, key=lambda item: item["break_index"])


def _to_model_candles(candles: Sequence[Mapping[str, Any]]):
    from src.models.market_data import Candle

    result = []
    for item in candles:
        close_time = item["close_time"]
        if close_time <= item["open_time"]:
            close_time = item["open_time"] + timedelta(seconds=TIMEFRAME_SECONDS.get(item["timeframe"], 60))
        result.append(Candle(
            symbol=item["symbol"], timeframe=item["timeframe"], open_time=item["open_time"], close_time=close_time,
            open=item["open"], high=item["high"], low=item["low"], close=item["close"],
            volume=item["volume"], trade_count=0, closed=True,
        ))
    return result


def _dec(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _flt(value: Any) -> float | None:
    return None if value is None else float(value)


def run_scenarios(candles: Sequence[Mapping[str, Any]], timeframe: str, profile: Mapping[str, Any] | None, now: datetime | None = None) -> dict[str, Any]:
    """Run TIM's orderflow pipeline (OBSERVE, no orders) and add preview stops/targets."""
    from src.orderflow_scenario.domain import ConfirmationState, MarketContext
    from src.orderflow_scenario.engines.pipeline import Pipeline, PipelineInputs
    from src.orderflow_scenario.engines.scenario_generator import LevelSet
    from src.orderflow_scenario.engines.trade_plan import TradePlanBuilder, TradePlanInputs

    now = now or datetime.now(timezone.utc)
    model_candles = _to_model_candles(candles)
    last = model_candles[-1]
    levels = LevelSet(
        range_high=Decimal(str(max(c.high for c in model_candles))),
        range_low=Decimal(str(min(c.low for c in model_candles))),
        midpoint=Decimal(str((max(c.high for c in model_candles) + min(c.low for c in model_candles)) / 2)),
        session_high=Decimal(str(max(c.high for c in model_candles[-6:]))),
        session_low=Decimal(str(min(c.low for c in model_candles[-6:]))),
        value_area_high=_dec(profile.get("vah")) if profile else None,
        value_area_low=_dec(profile.get("val")) if profile else None,
        point_of_control=_dec(profile.get("poc")) if profile else None,
        last_price=Decimal(str(last.close)),
    )
    context = MarketContext(symbol=last.symbol, venue="BINANCE", market_type="SPOT", timeframe=timeframe, timestamp=now)
    analysis = Pipeline().run(PipelineInputs(
        market_context=context, candles=model_candles, price_now=Decimal(str(last.close)), price_timestamp=last.close_time,
        levels=levels, structured=True, source_name="TIM_RUNTIME_CANDLES", observed_at=now,
    ))
    builder = TradePlanBuilder()
    scenarios = []
    for scenario in analysis.scenarios:
        preview = None
        if scenario.entry_zone_low is not None and scenario.entry_zone_high is not None:
            try:
                plan = builder.build(TradePlanInputs(
                    scenario=replace(scenario, state=ConfirmationState.CONFIRMED), market_state=analysis.market_state,
                    symbol=last.symbol, venue="BINANCE", market_type="SPOT", timeframe=timeframe,
                    last_price=Decimal(str(last.close)), timestamp=now,
                ))
            except (ValueError, ArithmeticError):
                plan = None
            if plan is not None:
                preview = {
                    "entry": _flt(plan.exact_entry), "stop": _flt(plan.stop_loss),
                    "targets": [_flt(plan.target_1), _flt(plan.target_2), _flt(plan.target_3)],
                    "reward_risk": _flt(plan.expected_reward_risk),
                    "note": "Vorschau nach TIM-Regeln, Szenario nicht bestätigt",
                }
        scenarios.append({
            "id": scenario.scenario_id,
            "type": scenario.scenario_type.value,
            "direction": scenario.direction.value,
            "state": scenario.state.value,
            "score": _flt(scenario.score),
            "score_type": scenario.score_type.value,
            "trigger": _flt(scenario.trigger_level),
            "entry_low": _flt(scenario.entry_zone_low),
            "entry_high": _flt(scenario.entry_zone_high),
            "invalidation": list(scenario.invalidation),
            "missing_confirmations": list(scenario.mandatory_confirmations),
            "preview": preview,
        })
    return {
        "analysis_id": analysis.analysis_id,
        "market_state": analysis.market_state.primary.value,
        "auction_state": analysis.auction_state.primary.value,
        "data_quality": {"status": analysis.data_quality.status, "confidence": _flt(analysis.data_quality.confidence), "missing": list(analysis.data_quality.missing_fields), "problems": list(analysis.data_quality.problems)},
        "decision": {"status": analysis.decision.status.value, "reasons": list(analysis.decision.reason_codes)},
        "scenarios": scenarios,
    }


def profile_source(series: Mapping[str, Sequence[Mapping[str, Any]]], candles: Sequence[Mapping[str, Any]], timeframe: str) -> tuple[list[dict[str, Any]], str]:
    """Finest timeframe whose candles cover the whole chart window (falls back to the chart's own)."""
    start, end = candles[0]["open_time"], candles[-1]["open_time"]
    for tf in CHART_TIMEFRAMES[:CHART_TIMEFRAMES.index(timeframe)]:
        finer = [c for c in clean_candles(series.get(tf) or [], tf) if start <= c["open_time"] <= end + timedelta(seconds=TIMEFRAME_SECONDS[timeframe])]
        if finer and (finer[0]["open_time"] - start).total_seconds() <= TIMEFRAME_SECONDS[tf]:
            return finer, tf
    return list(candles), timeframe


def build_chart_model(series: Mapping[str, Sequence[Mapping[str, Any]]], timeframe: str = DEFAULT_TIMEFRAME, now: datetime | None = None, visible: int = CHART_VISIBLE, profile: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Everything the chart page draws, as plain JSON-ready data.

    ``series`` maps timeframe -> candle dicts as kept by the runtime. ``profile``
    may carry an external volume profile (poc/vah/val); otherwise it is
    estimated from 1m candles of the visible window.
    """
    timeframe = timeframe if timeframe in CHART_TIMEFRAMES else DEFAULT_TIMEFRAME
    now = now or datetime.now(timezone.utc)
    candles = clean_candles(series.get(timeframe) or [], timeframe)[-visible:]
    available = [tf for tf in CHART_TIMEFRAMES if clean_candles(series.get(tf) or [], tf)]
    model: dict[str, Any] = {
        "timeframe": timeframe, "timeframes": list(CHART_TIMEFRAMES), "available_timeframes": available,
        "generated_at": now.isoformat(), "provenance": "PUBLIC_MARKET_DATA (Binance Spot, TIM-Runtime)",
        "read_only": True, "candles": [], "levels": {}, "profile": None, "bos": [], "analysis": None, "notes": [],
    }
    if len(candles) < 2:
        model["notes"].append("Zu wenige Kerzen für diesen Zeitrahmen.")
        return model
    model["candles"] = [{**c, "open_time": c["open_time"].isoformat(), "close_time": c["close_time"].isoformat()} for c in candles]
    last = candles[-1]
    model["levels"] = {
        "range_high": max(c["high"] for c in candles),
        "range_low": min(c["low"] for c in candles),
        "last": last["close"],
        "last_time": last["close_time"].isoformat(),
        "age_seconds": max(0, int((now - last["close_time"]).total_seconds())),
    }

    if profile and all(profile.get(key) is not None for key in ("poc", "vah", "val")):
        model["profile"] = {**dict(profile), "source": profile.get("source", "extern")}
    else:
        source_candles, source = profile_source(series, candles, timeframe)
        estimated = volume_profile(source_candles)
        if estimated:
            estimated["source"] = f"geschätzt aus {len(source_candles)} {source}-Kerzen über das Chartfenster (Volumen gleichmäßig über Hoch–Tief verteilt)"
            model["profile"] = estimated
        else:
            model["notes"].append("Kein Volumen vorhanden: VAH/VAL/POC nicht berechenbar.")

    bos: list[dict[str, Any]] = []
    for tf in CHART_TIMEFRAMES[CHART_TIMEFRAMES.index(timeframe):]:
        tf_candles = clean_candles(series.get(tf) or [], tf)
        bos.extend(break_of_structure(tf_candles[-CHART_CANDLE_LIMIT:], tf))
    model["bos"] = bos

    if len(candles) >= 5:
        try:
            model["analysis"] = run_scenarios(candles, timeframe, model["profile"], now)
        except Exception as exc:  # noqa: BLE001 - the chart must still render
            model["notes"].append(f"Szenario-Analyse nicht verfügbar: {type(exc).__name__}")
    return model
