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
from src.dashboard.chart_history import TIMEFRAMES as CHART_TIMEFRAMES, DEFAULT_TIMEFRAME

CHART_VISIBLE = 120  # candles drawn per chart
VALUE_AREA_SHARE = 0.70
PROFILE_TARGET_BINS = 60
PIVOT_WINDOW = 2  # same pivot width as orderflow_scenario.engines.market_state
ENTRY_REASONS = {
    "LIMIT_RETEST": "Retest Ausbruchskante",
    "RECLAIM": "Rückeroberung Range-Low",
    "FAILED_RETEST": "gescheiterter Retest",
    "PULLBACK": "Rücksetzer zum POC",
    "ENTRY_ZONE": "Zone",
}
NY_OPEN_LOCAL = (9, 30)  # New York stock market open, America/New_York
NY_OPEN_BLOCK = (timedelta(minutes=15), timedelta(minutes=30))  # before / after the open
TIMEFRAME_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800, "1M": 2678400}


def analytical_series(series: Mapping[str, Sequence[Mapping[str, Any]]], now: datetime) -> dict[str, list[dict[str, Any]]]:
    """Closed analysis intervals; aggregate only complete, contiguous source bars.

    Weeks start Monday UTC; months use calendar boundaries, never 30-day bars.
    Legacy small candles may supply data but are not active analysis timeframes.
    """
    result = {tf: [c for c in clean_candles(rows, tf) if c["close_time"] <= now and c.get("closed", True)] for tf, rows in series.items()}
    for tf in CHART_TIMEFRAMES:
        if result.get(tf):
            continue
        source = "15m" if tf == "30m" else "1h"
        groups: dict[datetime, list[dict]] = {}
        for c in result.get(source, []):
            t = c["open_time"].astimezone(timezone.utc)
            if tf == "30m":
                start = t.replace(minute=t.minute // 30 * 30, second=0, microsecond=0)
            elif tf == "4h":
                start = t.replace(hour=t.hour // 4 * 4, minute=0, second=0, microsecond=0)
            else:
                start = t.replace(hour=0, minute=0, second=0, microsecond=0)
                if tf == "1w":
                    start -= timedelta(days=start.weekday())
                elif tf == "1M":
                    start = start.replace(day=1)
            groups.setdefault(start, []).append(c)
        built = []
        for start, rows in sorted(groups.items()):
            end = (start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)) if tf == "1M" else start + timedelta(seconds=TIMEFRAME_SECONDS[tf])
            expected = int((end - start).total_seconds() / TIMEFRAME_SECONDS[source])
            if end > now or len(rows) != expected or any(c["open_time"] != start + timedelta(seconds=i * TIMEFRAME_SECONDS[source]) for i, c in enumerate(rows)):
                continue
            built.append({**rows[0], "timeframe": tf, "open_time": start, "close_time": end,
                          "high": max(c["high"] for c in rows), "low": min(c["low"] for c in rows),
                          "close": rows[-1]["close"], "volume": sum(c["volume"] for c in rows)})
        result[tf] = built
    return result


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
            "closed": item.get("closed", True),
            "provenance": item.get("provenance", "TIM_RUNTIME_CANDLES"),
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


def structure_events(candles: Sequence[Mapping[str, Any]], timeframe: str, width: int = PIVOT_WINDOW) -> list[dict[str, Any]]:
    """Causal swing breaks. Opposite close to established structure = MSS.

    Mechanical price-only interpretation, not an orderflow-confirmed entry.
    Use the latest confirmed swing on each side, once only; wicks do not count.
    """
    confirmed: dict[int, list[dict]] = {}
    for s in swing_points(candles, width):
        confirmed.setdefault(s["index"] + width + 1, []).append(s)
    active, history, broken = {}, {"HIGH": [], "LOW": []}, set()
    trend, events = None, []
    for i, candle in enumerate(candles):
        for s in confirmed.get(i, []):
            active[s["kind"]] = s
            history[s["kind"]].append(s["price"])
        if trend is None and all(len(v) >= 2 for v in history.values()):
            h, l = history["HIGH"], history["LOW"]
            if h[-1] > h[-2] and l[-1] > l[-2]:
                trend = "UP"
            elif h[-1] < h[-2] and l[-1] < l[-2]:
                trend = "DOWN"
        for side, direction in (("HIGH", "UP"), ("LOW", "DOWN")):
            s = active.get(side)
            if not s or (side, s["index"]) in broken:
                continue
            if not (candle["close"] > s["price"] if direction == "UP" else candle["close"] < s["price"]):
                continue
            events.append({"kind": "MSS" if trend is not None and trend != direction else "BOS",
                           "direction": direction, "timeframe": timeframe, "level": s["price"],
                           "swing_time": candles[s["index"]]["open_time"].isoformat(),
                           "break_time": candle["open_time"].isoformat(), "break_index": i})
            broken.add((side, s["index"]))
            trend = direction
    return events


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


def _fmt(value: float) -> str:
    """German price format: 83.650 for BTC, 1,2345 below 1000."""
    if value >= 1000:
        return f"{value:,.0f}".replace(",", ".")
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def ny_open_windows(start: datetime, end: datetime) -> list[dict[str, Any]]:
    """NY-open block windows (15 min before to 30 min after 9:30 New York time) touching [start, end]."""
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("America/New_York")
    windows = []
    day = start.astimezone(zone).date() - timedelta(days=1)
    while day <= end.astimezone(zone).date() + timedelta(days=1):
        if day.weekday() < 5:
            opened = datetime(day.year, day.month, day.day, *NY_OPEN_LOCAL, tzinfo=zone).astimezone(timezone.utc)
            begin, finish = opened - NY_OPEN_BLOCK[0], opened + NY_OPEN_BLOCK[1]
            if finish >= start and begin <= end:
                windows.append({"label": "NY-Eröffnung", "open": opened.isoformat(), "start": begin.isoformat(), "end": finish.isoformat()})
        day += timedelta(days=1)
    return windows


def _dec(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _flt(value: Any) -> float | None:
    return None if value is None else float(value)


def run_scenarios(candles: Sequence[Mapping[str, Any]], timeframe: str, profile: Mapping[str, Any] | None, now: datetime | None = None) -> dict[str, Any]:
    """Run TIM's orderflow pipeline (OBSERVE, no orders) and add preview stops/targets."""
    from src.orderflow_scenario.domain import ConfirmationState, MarketContext
    from src.orderflow_scenario.engines.pipeline import Pipeline, PipelineInputs
    from src.orderflow_scenario.engines.scenario_generator import LevelSet
    from src.orderflow_scenario.engines.trade_plan import GRADE_RULESET_VERSION, TradePlanBuilder, TradePlanInputs, grade_scenario

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
        grade = None
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
                # Grade the scenario as it is. The preview plan above was built with a forced
                # CONFIRMED state, so plan.grade would be two points too good.
                graded, reasons = grade_scenario(scenario, plan.expected_reward_risk)
                grade = {
                    "setup_grade": graded.value, "grade_reasons": list(reasons), "grade_ruleset_version": GRADE_RULESET_VERSION,
                    "graded_state": scenario.state.value, "note": "Heuristische Regelqualität, kein empirischer Edge-Nachweis",
                }
        entry_model = str(scenario.trade_template.get("entry_model", ""))
        trigger = _flt(scenario.trigger_level)
        invalid = None
        if trigger is not None and scenario.direction.value in {"LONG", "SHORT"}:
            side = "<" if scenario.direction.value == "LONG" else ">"
            invalid = {"level": trigger, "side": side, "text": f"Ungültig {scenario.scenario_id}: {timeframe}-Schluss {side} {_fmt(trigger)}"}
        plan_text = None
        if scenario.entry_zone_low is not None and scenario.entry_zone_high is not None:
            low, high = sorted((float(scenario.entry_zone_low), float(scenario.entry_zone_high)))
            plan_text = f"PLAN {scenario.scenario_id} {scenario.direction.value}  Limit {_fmt(low)}–{_fmt(high)} ({ENTRY_REASONS.get(entry_model, entry_model.replace('_', ' ').lower())})"
        if preview:
            entry, stop = preview["entry"], preview["stop"]
            gap = abs(entry - stop) / entry * 100 if entry else 0.0
            where = "unter" if stop < entry else "über"
            gap_text = f"{gap:.1f}".replace(".", ",")
            preview["stop_text"] = f"Stop {scenario.scenario_id} {_fmt(stop)} ({gap_text} % {where} Einstieg)"
        scenarios.append({
            "id": scenario.scenario_id,
            "entry_model": entry_model,
            "plan_text": plan_text,
            "invalidation_level": invalid,
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
            "grade": grade,
        })
    return {
        "analysis_id": analysis.analysis_id,
        "market": {"symbol": context.symbol, "venue": context.venue, "market_type": context.market_type},
        "market_state": analysis.market_state.primary.value,
        "auction_state": analysis.auction_state.primary.value,
        "data_quality": {"status": analysis.data_quality.status, "confidence": _flt(analysis.data_quality.confidence), "missing": list(analysis.data_quality.missing_fields), "problems": list(analysis.data_quality.problems)},
        "decision": {"status": analysis.decision.status.value, "reasons": list(analysis.decision.reason_codes)},
        "scenarios": scenarios,
    }


def profile_source(series: Mapping[str, Sequence[Mapping[str, Any]]], candles: Sequence[Mapping[str, Any]], timeframe: str) -> tuple[list[dict[str, Any]], str]:
    """Finest timeframe whose candles cover the whole chart window (falls back to the chart's own)."""
    start, end = candles[0]["open_time"], candles[-1]["open_time"]
    for tf in [tf for tf in TIMEFRAME_SECONDS if TIMEFRAME_SECONDS[tf] < TIMEFRAME_SECONDS[timeframe]]:
        finish = candles[-1]["close_time"]
        finer = [c for c in clean_candles(series.get(tf) or [], tf) if start <= c["open_time"] < finish]
        if (finer and finer[0]["open_time"] == start
                and abs((finer[-1]["close_time"] - finish).total_seconds()) < 1
                and all((b["open_time"] - a["open_time"]).total_seconds() == TIMEFRAME_SECONDS[tf] for a, b in zip(finer, finer[1:]))):
            return finer, tf
    return list(candles), timeframe


def _risk_note() -> dict[str, Any]:
    from src.orderflow_scenario.config import MAX_LEVERAGE, default_config

    tier = next((t for t in default_config().risk_tiers if t.name == "STANDARD"), None)
    risk = float(tier.account_risk_fraction) * 100 if tier else 0.5
    return {"account_risk_percent": risk, "max_leverage": float(MAX_LEVERAGE),
            "text": f"{str(round(risk, 2)).replace('.', ',')} % Kontorisiko · max. {int(MAX_LEVERAGE)}x · Vorschau nach TIM-Regeln · keine Anlageberatung"}


def build_chart_model(series: Mapping[str, Sequence[Mapping[str, Any]]], timeframe: str = DEFAULT_TIMEFRAME, now: datetime | None = None, visible: int = CHART_VISIBLE, profile: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Everything the chart page draws, as plain JSON-ready data.

    ``series`` maps timeframe -> candle dicts as kept by the runtime. ``profile``
    may carry an external volume profile (poc/vah/val); otherwise it is
    estimated from 1m candles of the visible window.
    """
    timeframe = timeframe if timeframe in CHART_TIMEFRAMES else DEFAULT_TIMEFRAME
    now = now or datetime.now(timezone.utc)
    series = analytical_series(series, now)
    candles = clean_candles(series.get(timeframe) or [], timeframe)[-visible:]
    available = [tf for tf in CHART_TIMEFRAMES if clean_candles(series.get(tf) or [], tf)]
    model: dict[str, Any] = {
        "timeframe": timeframe, "timeframes": list(CHART_TIMEFRAMES), "available_timeframes": available,
        "generated_at": now.isoformat(), "provenance": "PUBLIC_MARKET_DATA (Binance Spot; Chart-Kontext, keine wissenschaftliche Rekonstruktion)",
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
    for tf in (timeframe,):
        tf_candles = clean_candles(series.get(tf) or [], tf)
        bos.extend(e for e in structure_events(tf_candles[-CHART_CANDLE_LIMIT:], tf)
                   if e["break_time"] >= candles[0]["open_time"].isoformat())
    model["bos"] = bos

    from src.dashboard.session_map import build_session_map
    prep = build_session_map(series, now)
    model["reference_levels"] = prep.get("levels", [])
    model["notes"].extend(prep.get("notes", []))
    model["notes"].append("MSS: Schlusskurs gegen die etablierte Swing-Richtung; mechanische Preisstruktur, keine Orderflow-Bestätigung. Poor High/Low und Profile sind Kerzen-Näherungen.")

    first, now_or_last = candles[0]["open_time"], max(now, last["close_time"])
    model["events"] = ny_open_windows(first, last["close_time"]) if timeframe in ("30m", "1h") else []
    upcoming = [w for w in ny_open_windows(now, now + timedelta(days=4)) if datetime.fromisoformat(w["end"]) >= now]
    model["next_block"] = upcoming[0] if upcoming else None
    model["risk"] = _risk_note()

    if len(candles) >= 5:
        try:
            model["analysis"] = run_scenarios(candles, timeframe, model["profile"], now)
        except Exception as exc:  # noqa: BLE001 - the chart must still render
            model["notes"].append(f"Szenario-Analyse nicht verfügbar: {type(exc).__name__}")
    return model
