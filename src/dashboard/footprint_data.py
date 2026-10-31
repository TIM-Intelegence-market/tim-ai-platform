"""Footprint and volume profile for the TIM chart from TIM's own aggTrades (read-only).

The runtime (main.py) refreshes ``DashboardState.footprint`` every couple of minutes
through ``refresh``: PostgreSQL aggregates the trades per 5-minute bucket, price tick
and aggressor side (``MarketRepository.agg_trade_levels``), so no raw trade reaches
the dashboard. Finished days are kept as they are; only the running day is read again.

From that store the chart builds, per view:

- volume profiles per UTC day (volume per price step, POC, value area 70 %, delta),
- footprint bars for the shown timeframe (bid x ask per price step, delta, imbalances),
- volume bubbles: large market orders (aggTrades of one taker order, same millisecond and
  side, summed; ``MarketRepository.agg_trade_bubbles``) as circles at time and price.

Display only: nothing here writes, trades or changes a plan. Only the symbol TIM
collects (BTCUSDT) has data; other coins show nothing.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from src.dashboard.chart_model import _nice_step

BUCKET_SECONDS = 300  # finest time bucket kept; footprint bars from 5m upwards
TICK_BY_SYMBOL = {"BTCUSDT": 5.0, "ETHUSDT": 0.5, "SOLUSDT": 0.05}  # finest price level kept
DAYS_KEPT = 14  # finished days plus the running day: always covers the previous full week (Mon-Sun)
RECHECK_SECONDS = 3600  # a finished day is aggregated again after this long (late inserts from catch-up or backfill)
PROFILE_BINS = 40  # price rows per day profile
FOOTPRINT_ROWS = 40  # target price rows per footprint bar (finest step sent; the chart merges rows to fit the zoom)
IMBALANCE_RATIO = 4.0  # diagonal bid/ask ratio that marks an imbalance (same as orderflow_scenario.footprint, F1)
STACK_MIN = 3  # consecutive same-side imbalances that count as stacked (orderflow_scenario.footprint, F2)
MAX_FOOTPRINT_BARS = 400  # bars carried to the browser per view
SOURCE = "TIM agg_trades (Binance Spot aggTrades, eigene Datenbank)"
VALUE_AREA_SHARE = 0.7
BUBBLE_MIN_USD = 100_000.0  # smallest market order kept as a bubble (USD notional of one taker order)
BUBBLES_PER_DAY = 2000  # largest orders kept per day (a busy day has a few thousand above the floor)
MAX_BUBBLES_VIEW = 400  # largest orders in the shown window carried to the browser


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


def _epoch_ms(value: Any) -> int:
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int(round(moment.timestamp() * 1000))


def _bubble_rows(records: Sequence[Mapping[str, Any]]) -> list[list[float]]:
    """Compact rows [time_ms, price, quantity, side] (side 1 = aggressive buyer, -1 = aggressive seller), by time."""
    rows = [[_epoch_ms(r["time"]), round(float(r["price"]), 8), round(float(r["quantity"]), 8), 1 if r["buy"] else -1] for r in records]
    return sorted(rows)


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
        bubbles = dict(current.get("bubbles") or {})
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
        if key in complete and key not in recheck and key in bubbles:
            continue
        start = _day_start(day)
        end = min(start + timedelta(days=1), now)
        if end <= start:
            continue
        try:
            records = await repository.agg_trade_levels(symbol, start, end, tick, BUCKET_SECONDS)
            large = await repository.agg_trade_bubbles(symbol, start, end, BUBBLE_MIN_USD, BUBBLES_PER_DAY)
        except Exception as exc:  # noqa: BLE001 - keep the days read so far, report the failure once
            error = exc
            break
        kept[key] = _rows(records)
        bubbles[key] = _bubble_rows(large)
        fetched[key] = len(records)
        if end == start + timedelta(days=1):
            complete[key] = int(now.timestamp())
    keys = sorted(kept)[-(days + 1):]
    store = {"symbol": symbol, "tick": tick, "bucket_seconds": BUCKET_SECONDS, "source": SOURCE,
             "updated_at": (current.get("updated_at") if error else None) or now.isoformat(),
             "days": {k: kept[k] for k in keys}, "bubbles": {k: bubbles[k] for k in keys if k in bubbles},
             "bubble_min_usd": BUBBLE_MIN_USD, "complete": {k: v for k, v in complete.items() if k in keys}}
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


def profile_from_rows(rows: Sequence[Sequence[float]], tick: float, bins: int = PROFILE_BINS) -> dict[str, Any] | None:
    """Volume profile of stored rows ``[bucket, level, bid, ask]``: rows per price step, POC, value area.

    ``poc``, ``vah`` and ``val`` are row edges (``poc`` = lower edge of the fullest row);
    ``poc_mid`` is the centre of that row, the price a level line uses.
    """
    if not rows:
        return None
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
        return None
    poc = min(sorted(volumes), key=lambda i: (-volumes[i], i))
    val_index, vah_index = _value_area(volumes, poc)
    total = sum(volumes.values())
    return {
        "step": step, "total": round(total, 4), "delta": round(sum(ask.values()) - sum(bid.values()), 4),
        "poc": round(first + poc * step, 8), "poc_mid": round(first + poc * step + step / 2, 8),
        "vah": round(first + vah_index * step + step, 8), "val": round(first + val_index * step, 8),
        "high": round(high, 8), "low": round(low, 8), "max_volume": round(max(volumes.values()), 4),
        "rows": [{"price": round(first + i * step, 8), "volume": round(volumes[i], 4), "bid": round(bid.get(i, 0.0), 4),
                  "ask": round(ask.get(i, 0.0), 4), "delta": round(ask.get(i, 0.0) - bid.get(i, 0.0), 4)} for i in sorted(volumes)],
    }


def volume_profiles(store: Mapping[str, Any] | None, now: datetime, bins: int = PROFILE_BINS) -> list[dict[str, Any]]:
    """One volume profile per day in the store: rows per price step with bid/ask/delta, POC, VAH/VAL."""
    if not store or not store.get("days"):
        return []
    today = now.astimezone(timezone.utc).date()
    tick = float(store["tick"])
    result = []
    for key in sorted(store["days"]):
        profile = profile_from_rows(store["days"][key], tick, bins)
        if profile is None:
            continue
        day = date.fromisoformat(key)
        start = _day_start(day)
        result.append({
            "day": key, "label": f"{day.day:02d}.{day.month:02d}.", "start": start.isoformat(), "end": (start + timedelta(days=1)).isoformat(),
            "running": day == today, "complete": key in (store.get("complete") or {}),
            **{k: profile[k] for k in ("step", "total", "delta", "poc", "poc_mid", "vah", "val", "max_volume", "rows")},
        })
    return result


def _imbalances(prices: Sequence[float], grouped: Mapping[float, Sequence[float]], step: float) -> list[list[Any]]:
    """Diagonal imbalances (F1): ask at a level against bid one step below, bid against ask one step above.

    The neighbour is the row one price step away, also when nothing traded there: an empty row counts
    as zero, as in orderflow_scenario.footprint and common footprint tools. Comparing with the next row
    that has trades instead would skip the gap and measure against a row two or more steps away.
    """
    found: list[list[Any]] = []
    empty = (0.0, 0.0)
    for price in prices:
        bid, ask = grouped[price]
        below = grouped.get(round(price - step, 8), empty)
        above = grouped.get(round(price + step, 8), empty)
        if price != prices[0] and ask > 0 and ask >= IMBALANCE_RATIO * below[0]:
            found.append([price, "ask"])
        if price != prices[-1] and bid > 0 and bid >= IMBALANCE_RATIO * above[1]:
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
        imbalances = _imbalances(prices, grouped, step)
        total_bid = sum(v[0] for v in grouped.values())
        total_ask = sum(v[1] for v in grouped.values())
        poc = max(prices, key=lambda p: (grouped[p][0] + grouped[p][1], -p))
        # F3 auction edges on the finest tick: both sides traded at the extreme = unfinished auction.
        top, bottom = ticks[max(ticks)], ticks[min(ticks)]
        bars.append({"time": bar_time, "levels": levels, "delta": round(total_ask - total_bid, 4), "total": round(total_bid + total_ask, 4),
                     "poc": poc, "imbalances": imbalances, "stacked": _stacks(prices, imbalances, step),
                     "unfinished_high": min(top) > 0, "unfinished_low": min(bottom) > 0})
    return {"step": step, "bars": bars, "note": None, "bar_seconds": timeframe_seconds, "span_seconds": span}


def volume_bubbles(store: Mapping[str, Any] | None, times: Sequence[int], timeframe_seconds: int) -> dict[str, Any]:
    """Large market orders in the shown window: one bubble per taker order at its time and average price.

    ``time`` is the exact moment (UTC epoch seconds, ms precision), ``bar`` the open time of the
    candle it falls into, ``side`` 1 for an aggressive buyer (green) and -1 for a seller (red).
    Only the ``MAX_BUBBLES_VIEW`` largest orders of the window are sent, oldest first.
    """
    empty = {"items": [], "min_usd": None, "max_usd": None, "note": None}
    if not store or not store.get("bubbles") or len(times) < 2:
        return empty
    first_time, last_time = times[0], times[-1] + timeframe_seconds
    found = []
    for key in sorted(store["bubbles"]):
        for time_ms, price, quantity, side in store["bubbles"][key]:
            moment = time_ms / 1000.0
            if first_time <= moment < last_time:
                found.append((price * quantity, moment, price, quantity, side))
    if not found:
        return {**empty, "note": "Keine großen Market Orders im gezeigten Fenster."}
    found = sorted(found, reverse=True)[:MAX_BUBBLES_VIEW]
    items = []
    for usd, moment, price, quantity, side in sorted(found, key=lambda item: item[1]):
        bar = times[max(0, bisect_right(times, moment) - 1)]
        items.append({"time": round(moment, 3), "bar": bar, "price": price, "quantity": quantity, "usd": round(usd, 2), "side": int(side)})
    return {"items": items, "min_usd": round(min(i["usd"] for i in items), 2), "max_usd": round(max(i["usd"] for i in items), 2),
            "floor_usd": store.get("bubble_min_usd", BUBBLE_MIN_USD), "note": None}


def bar_deltas(store: Mapping[str, Any] | None, times: Sequence[int], timeframe_seconds: int) -> dict[int, float]:
    """Taker delta (ask - bid) per shown candle from the stored buckets; candles without trades are left out."""
    if not store or not store.get("days") or len(times) < 2:
        return {}
    bucket = int(store["bucket_seconds"])
    if timeframe_seconds < bucket or timeframe_seconds % bucket:
        return {}
    first_time, last_time = times[0], times[-1] + timeframe_seconds
    result: dict[int, float] = {}
    for key in sorted(store["days"]):
        for bucket_time, _, bid, ask in store["days"][key]:
            if first_time <= bucket_time < last_time:
                bar = times[max(0, bisect_right(times, bucket_time) - 1)]
                result[bar] = result.get(bar, 0.0) + ask - bid
    return result


def cvd_lines(spot: Mapping[str, Any] | None, perp: Mapping[str, Any] | None, times: Sequence[int], timeframe_seconds: int) -> dict[str, Any]:
    """Cumulative volume delta of spot and perp over the shown candles, both from the same start.

    The lines start at the first candle that has trades in both records (perp collection may
    begin later than spot), so the two curves compare the same stretch of time.
    """
    empty = {"spot": [], "perp": [], "start": None, "note": None}
    spot_bars, perp_bars = bar_deltas(spot, times, timeframe_seconds), bar_deltas(perp, times, timeframe_seconds)
    if not spot_bars and not perp_bars:
        bucket = int((spot or perp or {}).get("bucket_seconds") or BUCKET_SECONDS)
        return {**empty, "note": f"CVD ab {bucket // 60}m." if timeframe_seconds < bucket else None}
    both = set(spot_bars) & set(perp_bars)
    start = min(both) if both else min(set(spot_bars) | set(perp_bars))
    lines: dict[str, list[list[float]]] = {}
    for name, bars in (("spot", spot_bars), ("perp", perp_bars)):
        total, points = 0.0, []
        for bar in times:
            if bar < start or (bar not in bars and not points):
                continue
            total += bars.get(bar, 0.0)
            points.append([bar, round(total, 3)])
        lines[name] = points
    note = None if both else ("CVD nur Spot: noch keine Perp-Trades im Fenster." if spot_bars else "CVD nur Perp: keine Spot-Trades im Fenster.")
    return {"spot": lines["spot"], "perp": lines["perp"], "start": start, "note": note}
