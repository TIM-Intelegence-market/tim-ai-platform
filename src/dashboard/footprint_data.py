"""Footprint and volume profile for the TIM chart from TIM's own aggTrades (read-only).

The runtime (main.py) refreshes ``DashboardState.footprint`` every couple of minutes
through ``refresh``: PostgreSQL aggregates the trades per 5-minute bucket, price tick
and aggressor side (``MarketRepository.agg_trade_levels``), so no raw trade reaches
the dashboard. Finished days are kept as they are; only the running day is read again.

From that store the chart builds, per view:

- volume profiles per UTC day (volume per price step, POC, value area 70 %, delta),
- footprint bars for the shown timeframe (bid x ask per price step, delta, imbalances).

Display only: nothing here writes, trades or changes a plan. Only the symbol TIM
collects (BTCUSDT) has data; other coins show nothing.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from src.dashboard.chart_model import _nice_step

BUCKET_SECONDS = 300  # finest time bucket kept; footprint bars from 5m upwards
TICK_BY_SYMBOL = {"BTCUSDT": 5.0, "ETHUSDT": 0.5, "SOLUSDT": 0.05}  # finest price level kept
DAYS_KEPT = 7  # finished days plus the running day
RECHECK_SECONDS = 3600  # a finished day is aggregated again after this long (late inserts from catch-up or backfill)
PROFILE_BINS = 40  # price rows per day profile
FOOTPRINT_ROWS = 40  # target price rows per footprint bar (finest step sent; the chart merges rows to fit the zoom)
IMBALANCE_RATIO = 4.0  # diagonal bid/ask ratio that marks an imbalance (same as orderflow_scenario.footprint, F1)
STACK_MIN = 3  # consecutive same-side imbalances that count as stacked (orderflow_scenario.footprint, F2)
MAX_FOOTPRINT_BARS = 400  # bars carried to the browser per view
SOURCE = "TIM agg_trades (Binance Spot aggTrades, eigene Datenbank)"
VALUE_AREA_SHARE = 0.7


def tick_for(symbol: str, price: float | None = None) -> float:
    if symbol in TICK_BY_SYMBOL:
        return TICK_BY_SYMBOL[symbol]
    return _nice_step(max(price or 1.0, 1e-9) * 0.0001, 1)


def _day_start(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def _epoch(value: Any) -> int:
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int(moment.timestamp())


def _rows(records: Sequence[Mapping[str, Any]]) -> list[list[float]]:
    """Compact rows [bucket_epoch, level, bid, ask] for the state."""
    return [[_epoch(r["bucket"]), float(r["level"]), float(r["bid"]), float(r["ask"])] for r in records]


async def refresh(repository: Any, state: Any, symbol: str, now: datetime | None = None, days: int = DAYS_KEPT) -> dict[str, Any]:
    """Fill ``state.footprint`` for the last ``days`` days plus today; returns what was fetched.

    Finished days already in the store are not read again. The caller holds no
    lock: the store is replaced under ``state.lock`` once the rows are there.
    """
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(timezone.utc).date()
    tick = tick_for(symbol)
    with state.lock:
        current = dict(state.footprint) if state.footprint and state.footprint.get("symbol") == symbol and state.footprint.get("tick") == tick else {}
        kept = dict(current.get("days") or {})
        # Day -> epoch of the last read that covered the whole day. A finished day is read again once an hour
        # (one per pass, oldest first), so trades a catch-up or backfill inserts later still reach the profile.
        complete = dict(current.get("complete") or {})
    fetched: dict[str, int] = {}
    wanted = [today - timedelta(days=offset) for offset in range(days, -1, -1)]
    stale = sorted((k for k, read_at in complete.items() if now.timestamp() - read_at >= RECHECK_SECONDS), key=lambda k: complete[k])
    recheck = stale[:1]
    error: Exception | None = None
    for day in wanted:
        key = day.isoformat()
        if key in complete and key not in recheck:
            continue
        start = _day_start(day)
        end = min(start + timedelta(days=1), now)
        if end <= start:
            continue
        try:
            records = await repository.agg_trade_levels(symbol, start, end, tick, BUCKET_SECONDS)
        except Exception as exc:  # noqa: BLE001 - keep the days read so far, report the failure once
            error = exc
            break
        kept[key] = _rows(records)
        fetched[key] = len(records)
        if end == start + timedelta(days=1):
            complete[key] = int(now.timestamp())
    keys = sorted(kept)[-(days + 1):]
    store = {"symbol": symbol, "tick": tick, "bucket_seconds": BUCKET_SECONDS, "source": SOURCE,
             "updated_at": (current.get("updated_at") if error else None) or now.isoformat(),
             "days": {k: kept[k] for k in keys}, "complete": {k: v for k, v in complete.items() if k in keys}}
    with state.lock:
        state.footprint = store
    if error is not None:
        raise error
    return fetched


def _value_area(volumes: Mapping[int, float], poc: int) -> tuple[int, int]:
    """Lowest and highest row index of the value area around ``poc`` (share of total volume)."""
    total = sum(volumes.values())
    lowest, highest = min(volumes), max(volumes)
    above, below, inside = poc + 1, poc - 1, volumes[poc]
    while inside < total * VALUE_AREA_SHARE and (above <= highest or below >= lowest):  # empty rows inside the range are crossed
        up, down = volumes.get(above, 0.0), volumes.get(below, 0.0)
        if (up >= down and above <= highest) or below < lowest:
            inside += up
            above += 1
        else:
            inside += down
            below -= 1
    return below + 1, above - 1


def volume_profiles(store: Mapping[str, Any] | None, now: datetime, bins: int = PROFILE_BINS) -> list[dict[str, Any]]:
    """One volume profile per day in the store: rows per price step with bid/ask/delta, POC, VAH/VAL."""
    if not store or not store.get("days"):
        return []
    today = now.astimezone(timezone.utc).date()
    tick = float(store["tick"])
    result = []
    for key in sorted(store["days"]):
        rows = store["days"][key]
        if not rows:
            continue
        low, high = min(r[1] for r in rows), max(r[1] for r in rows) + tick
        step = max(tick, _nice_step(max(high - low, tick), bins))
        step = math.ceil(step / tick) * tick  # a whole number of ticks, so levels fall on row edges
        first = math.floor(low / step) * step
        bid: dict[int, float] = {}
        ask: dict[int, float] = {}
        for _, level, b, a in rows:
            index = int((level - first) // step)
            bid[index] = bid.get(index, 0.0) + b
            ask[index] = ask.get(index, 0.0) + a
        volumes = {i: bid.get(i, 0.0) + ask.get(i, 0.0) for i in set(bid) | set(ask)}
        if not volumes:
            continue
        poc = min(sorted(volumes), key=lambda i: (-volumes[i], i))
        val_index, vah_index = _value_area(volumes, poc)
        total = sum(volumes.values())
        day = date.fromisoformat(key)
        start = _day_start(day)
        result.append({
            "day": key, "label": f"{day.day:02d}.{day.month:02d}.", "start": start.isoformat(), "end": (start + timedelta(days=1)).isoformat(),
            "running": day == today, "step": step, "total": round(total, 4), "delta": round(sum(ask.values()) - sum(bid.values()), 4),
            "poc": round(first + poc * step, 8), "vah": round(first + vah_index * step + step, 8), "val": round(first + val_index * step, 8),
            "max_volume": round(max(volumes.values()), 4),
            "rows": [{"price": round(first + i * step, 8), "volume": round(volumes[i], 4), "bid": round(bid.get(i, 0.0), 4),
                      "ask": round(ask.get(i, 0.0), 4), "delta": round(ask.get(i, 0.0) - bid.get(i, 0.0), 4)} for i in sorted(volumes)],
        })
    return result


def _imbalances(prices: Sequence[float], grouped: Mapping[float, Sequence[float]]) -> list[list[Any]]:
    """Diagonal imbalances (F1): ask at a level against bid one level below, bid against ask one level above.

    A zero on the opposite side counts, as in orderflow_scenario.footprint and common footprint tools.
    """
    found: list[list[Any]] = []
    for index, price in enumerate(prices):
        bid, ask = grouped[price]
        if index > 0 and ask > 0 and ask >= IMBALANCE_RATIO * grouped[prices[index - 1]][0]:
            found.append([price, "ask"])
        if index + 1 < len(prices) and bid > 0 and bid >= IMBALANCE_RATIO * grouped[prices[index + 1]][1]:
            found.append([price, "bid"])
    return found


def _stacks(prices: Sequence[float], imbalances: Sequence[Sequence[Any]], step: float) -> list[list[Any]]:
    """Runs of at least ``STACK_MIN`` neighbouring same-side imbalances (F2) as [low, high, side]."""
    stacks: list[list[Any]] = []
    for side in ("ask", "bid"):
        marked = {price for price, kind in imbalances if kind == side}
        run: list[float] = []
        for price in list(prices) + [math.inf]:
            if price in marked and (not run or abs(price - run[-1] - step) < step * 1e-6):
                run.append(price)
                continue
            if len(run) >= STACK_MIN:
                stacks.append([run[0], run[-1], side])
            run = [price] if price in marked else []
    return sorted(stacks)


def footprint_bars(store: Mapping[str, Any] | None, times: Sequence[int], timeframe_seconds: int,
                   candles: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Footprint per shown candle: bid x ask per price step, delta, total, POC, imbalances,
    stacked imbalances and unfinished auctions at the candle's high and low.

    ``times`` are the candle open times (UTC epoch seconds) of the view. Bars coarser
    than the stored bucket are sums of buckets; finer views get no footprint. The
    price step per view keeps about ``FOOTPRINT_ROWS`` rows per bar.
    """
    empty = {"step": None, "bars": [], "note": None}
    if not store or not store.get("days"):
        return {**empty, "note": "Keine Trades gespeichert."}
    bucket = int(store["bucket_seconds"])
    if timeframe_seconds < bucket or timeframe_seconds % bucket:
        return {**empty, "note": f"Footprint ab {bucket // 60}m."}
    if len(times) < 2:
        return empty
    tick = float(store["tick"])
    span = max(times[-1] - times[0] + timeframe_seconds, 1)
    shown = times[-MAX_FOOTPRINT_BARS:]
    first_time, last_time = shown[0], shown[-1] + timeframe_seconds
    by_bar: dict[int, dict[float, list[float]]] = {}
    for key in sorted(store["days"]):
        for bucket_time, level, bid, ask in store["days"][key]:
            if bucket_time < first_time or bucket_time >= last_time:
                continue
            bar_time = first_time + (bucket_time - first_time) // timeframe_seconds * timeframe_seconds
            entry = by_bar.setdefault(bar_time, {}).setdefault(level, [0.0, 0.0])
            entry[0] += bid
            entry[1] += ask
    if not by_bar:
        return {**empty, "note": "Keine Trades im gezeigten Fenster."}
    ranges = sorted(max(levels) - min(levels) + tick for levels in by_bar.values())
    median_range = ranges[len(ranges) // 2]
    step = max(tick, _nice_step(median_range, FOOTPRINT_ROWS))
    step = math.ceil(step / tick) * tick
    bars = []
    for bar_time in sorted(by_bar):
        ticks = by_bar[bar_time]
        grouped: dict[float, list[float]] = {}
        for level, (bid, ask) in ticks.items():
            price = math.floor(level / step) * step
            cell = grouped.setdefault(round(price, 8), [0.0, 0.0])
            cell[0] += bid
            cell[1] += ask
        prices = sorted(grouped)
        levels = [[p, round(grouped[p][0], 4), round(grouped[p][1], 4)] for p in prices]
        imbalances = _imbalances(prices, grouped)
        total_bid = sum(v[0] for v in grouped.values())
        total_ask = sum(v[1] for v in grouped.values())
        poc = max(prices, key=lambda p: (grouped[p][0] + grouped[p][1], -p))
        # F3 auction edges on the finest tick: both sides traded at the extreme = unfinished auction.
        top, bottom = ticks[max(ticks)], ticks[min(ticks)]
        bars.append({"time": bar_time, "levels": levels, "delta": round(total_ask - total_bid, 4), "total": round(total_bid + total_ask, 4),
                     "poc": poc, "imbalances": imbalances, "stacked": _stacks(prices, imbalances, step),
                     "unfinished_high": min(top) > 0, "unfinished_low": min(bottom) > 0})
    return {"step": step, "bars": bars, "note": None, "bar_seconds": timeframe_seconds, "span_seconds": span}
