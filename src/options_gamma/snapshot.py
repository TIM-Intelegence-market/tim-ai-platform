"""Gamma snapshot for TIM's analyses from one Deribit options book summary.

Pure calculation, no network: the caller supplies the rows of Deribit's public
``get_book_summary_by_currency?kind=option`` and the index price (see
``src/dashboard/gamma_data.py`` for the fetch). Output is one JSON-ready dict:

- regime and gamma flip (the spot where estimated dealer gamma changes sign,
  the crossing nearest to the current price),
- call wall / put wall: largest call gamma at or above spot, largest put gamma
  at or below spot (a wall per side, not two walls at the ATM strike),
- open-interest walls, max pain and the expected move of the main expiry
  (the expiry with the most open interest within the next seven days),
- ``levels`` for the chart and the prep, ``analysis_input`` for the orderflow
  scenario input field ``gamma``.

Convention (an assumption, as in gex.py): dealers are long the calls and short
the puts that customers hold. Open interest does not show who is long, so every
value is an estimate. Context only: never a signal, never an order.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from src.options_gamma.gex import OptionQuote, chain_input_hash, compute_gex_profile, gex_at

SOURCE = "DERIBIT_PUBLIC_OPTIONS_BOOK_SUMMARY"
CONVENTION = "Annahme: Händler long Calls, short Puts (Open Interest zeigt nicht, wer long ist)"
STRIKE_WINDOW = 0.35  # strikes within ±35 % of spot (same window as the OpenMarket GEX layout)
FLIP_WINDOW = 0.15  # the flip is searched within ±15 % of spot
FLIP_STEPS = 300
MAIN_EXPIRY_DAYS = 7
EXPIRY_HOUR_UTC = 8  # Deribit options settle at 08:00 UTC
_MONTHS = {name: index for index, name in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), start=1)}
_NAME = re.compile(r"^(?P<cur>[A-Z]+)-(?P<day>\d{1,2})(?P<mon>[A-Z]{3})(?P<year>\d{2})-(?P<strike>\d+(?:d\d+)?)-(?P<kind>[CP])$")


def parse_instrument(name: str) -> tuple[str, datetime, float, bool]:
    """``BTC-30OCT26-80000-C`` -> (currency, expiry 08:00 UTC, strike, is_call)."""
    match = _NAME.match(name or "")
    if not match or match["mon"] not in _MONTHS:
        raise ValueError(f"unknown instrument name: {name!r}")
    expiry = datetime(2000 + int(match["year"]), _MONTHS[match["mon"]], int(match["day"]), EXPIRY_HOUR_UTC, tzinfo=timezone.utc)
    return match["cur"], expiry, float(match["strike"].replace("d", ".")), match["kind"] == "C"


def quotes_from_book_summary(rows: Sequence[Mapping[str, Any]], currency: str, as_of: datetime) -> tuple[list[OptionQuote], dict[str, int]]:
    """Live quotes with open interest and mark IV; the counts say what was left out and why."""
    skipped = {"unparsed": 0, "other_currency": 0, "expired": 0, "no_open_interest": 0, "no_iv": 0}
    quotes: list[OptionQuote] = []
    for row in rows:
        try:
            cur, expiry, strike, is_call = parse_instrument(str(row.get("instrument_name", "")))
        except ValueError:
            skipped["unparsed"] += 1
            continue
        if cur != currency:
            skipped["other_currency"] += 1
            continue
        if expiry <= as_of:
            skipped["expired"] += 1
            continue
        oi, iv = row.get("open_interest"), row.get("mark_iv")
        if not isinstance(oi, (int, float)) or isinstance(oi, bool) or not math.isfinite(oi) or oi <= 0:
            skipped["no_open_interest"] += 1
            continue
        if not isinstance(iv, (int, float)) or isinstance(iv, bool) or not math.isfinite(iv) or iv <= 0:
            skipped["no_iv"] += 1
            continue
        quotes.append(OptionQuote(strike=strike, expiry=expiry, is_call=is_call, open_interest=float(oi), implied_vol=float(iv) / 100.0))
    return quotes, skipped


def max_pain(quotes: Sequence[OptionQuote]) -> float | None:
    """Strike where option holders' payout at expiry is smallest."""
    strikes = sorted({q.strike for q in quotes})
    if not strikes:
        return None

    def payout(price: float) -> float:
        return sum(q.open_interest * (max(price - q.strike, 0.0) if q.is_call else max(q.strike - price, 0.0)) for q in quotes)

    return min(strikes, key=lambda price: (payout(price), price))


def flip_nearest(quotes: Sequence[OptionQuote], spot: float, as_of: datetime, window: float = FLIP_WINDOW, steps: int = FLIP_STEPS) -> float | None:
    """Price where total estimated GEX changes sign, nearest to ``spot`` within ±window."""
    if not quotes:
        return None
    low, high = spot * (1 - window), spot * (1 + window)
    grid = [low + (high - low) * i / steps for i in range(steps + 1)]
    values = [gex_at(quotes, price, as_of) for price in grid]
    crossings = []
    for (p0, v0), (p1, v1) in zip(zip(grid, values), zip(grid[1:], values[1:])):
        if v0 == 0:
            crossings.append(p0)
        elif (v0 < 0) != (v1 < 0):
            crossings.append(p0 + (p1 - p0) * (-v0) / (v1 - v0))
    if not crossings:
        return None
    return min(crossings, key=lambda price: (abs(price - spot), price))


def _expected_move(quotes: Sequence[OptionQuote], spot: float, as_of: datetime, expiry: datetime) -> dict[str, Any] | None:
    same = [q for q in quotes if q.expiry == expiry]
    if not same:
        return None
    atm = min(same, key=lambda q: (abs(q.strike - spot), q.strike, q.is_call))
    years = (expiry - as_of).total_seconds() / (365.0 * 24 * 3600)
    move = spot * atm.implied_vol * math.sqrt(years)
    return {"expiry": expiry.isoformat(), "atm_iv": round(atm.implied_vol, 4), "move": round(move, 2),
            "low": round(spot - move, 2), "high": round(spot + move, 2)}


def _walls(quotes: Sequence[OptionQuote], spot: float, as_of: datetime) -> dict[str, Any]:
    profile = compute_gex_profile("X", spot, as_of, quotes)
    above = [s for s in profile.strikes if s.strike >= spot and s.call_gex > 0]
    below = [s for s in profile.strikes if s.strike <= spot and s.put_gex < 0]
    call_wall = max(above, key=lambda s: (s.call_gex, -s.strike)).strike if above else None
    put_wall = min(below, key=lambda s: (s.put_gex, -s.strike)).strike if below else None
    return {"profile": profile, "call_wall": call_wall, "put_wall": put_wall}


def _oi_walls(quotes: Sequence[OptionQuote], spot: float, count: int = 3) -> dict[str, list[list[float]]]:
    calls: dict[float, float] = {}
    puts: dict[float, float] = {}
    for q in quotes:
        book = calls if q.is_call else puts
        book[q.strike] = book.get(q.strike, 0.0) + q.open_interest
    top_calls = sorted(((k, v) for k, v in calls.items() if k >= spot), key=lambda item: (-item[1], item[0]))[:count]
    top_puts = sorted(((k, v) for k, v in puts.items() if k <= spot), key=lambda item: (-item[1], -item[0]))[:count]
    return {"calls": [[k, round(v, 1)] for k, v in top_calls], "puts": [[k, round(v, 1)] for k, v in top_puts]}


def _summary(quotes: Sequence[OptionQuote], spot: float, as_of: datetime) -> dict[str, Any]:
    walls = _walls(quotes, spot, as_of)
    profile = walls["profile"]
    flip = flip_nearest(quotes, spot, as_of)
    top = sorted(profile.strikes, key=lambda s: (-abs(s.net_gex), s.strike))[:8]
    return {
        "contracts": len(quotes),
        "open_interest": round(sum(q.open_interest for q in quotes), 1),
        "net_gex_usd_per_1pct": round(profile.net_gex, 2),
        "regime": profile.regime,
        "gamma_flip": None if flip is None else round(flip, 2),
        "price_vs_flip": None if flip is None else ("ABOVE_FLIP" if spot > flip else "BELOW_FLIP" if spot < flip else "AT_FLIP"),
        "call_wall": walls["call_wall"],
        "put_wall": walls["put_wall"],
        "max_pain": max_pain(quotes),
        "oi_walls": _oi_walls(quotes, spot),
        "top_strikes": [{"strike": s.strike, "net": round(s.net_gex, 2), "call": round(s.call_gex, 2), "put": round(s.put_gex, 2)} for s in top],
    }


def build_gamma_snapshot(rows: Sequence[Mapping[str, Any]], spot: float, as_of: datetime, currency: str = "BTC",
                         strike_window: float = STRIKE_WINDOW) -> dict[str, Any]:
    """Everything TIM's analyses read about options gamma, from one book summary."""
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    if not isinstance(spot, (int, float)) or not math.isfinite(spot) or spot <= 0:
        raise ValueError("spot must be a positive number")
    quotes, skipped = quotes_from_book_summary(rows, currency, as_of)
    inside = [q for q in quotes if abs(q.strike / spot - 1) <= strike_window]
    skipped["outside_strike_window"] = len(quotes) - len(inside)
    if not inside:
        raise ValueError("no live option with open interest inside the strike window")
    total_oi = sum(q.open_interest for q in inside)
    by_expiry: dict[datetime, float] = {}
    for q in inside:
        by_expiry[q.expiry] = by_expiry.get(q.expiry, 0.0) + q.open_interest
    soon = {expiry: oi for expiry, oi in by_expiry.items() if expiry - as_of <= timedelta(days=MAIN_EXPIRY_DAYS)}
    main_expiry = max(soon, key=lambda expiry: (soon[expiry], -expiry.timestamp())) if soon else min(by_expiry)
    main_quotes = [q for q in inside if q.expiry == main_expiry]
    overall = _summary(inside, spot, as_of)
    main = _summary(main_quotes, spot, as_of)
    main["expiry"] = main_expiry.isoformat()
    main["share_of_open_interest"] = round(by_expiry[main_expiry] / total_oi, 4)
    move = _expected_move(inside, spot, as_of, main_expiry)

    levels: list[dict[str, Any]] = []

    def level(key: str, name: str, price: float | None, note: str) -> None:
        if price is not None:
            levels.append({"key": key, "name": name, "price": float(price), "note": note})

    level("flip", "Gamma Flip", overall["gamma_flip"], "darüber dämpfen Händler eher, darunter verstärken sie Bewegungen")
    level("call_wall", "Call Wall", overall["call_wall"], "größtes Call-Gamma über dem Preis")
    level("put_wall", "Put Wall", overall["put_wall"], "größtes Put-Gamma unter dem Preis")
    expiry_label = main_expiry.strftime("%d.%m.")
    level("max_pain", f"Max Pain {expiry_label}", main["max_pain"], f"Hauptverfall {expiry_label} ({main['share_of_open_interest'] * 100:.0f} % des OI)")
    if move is not None:
        level("em_high", f"EM hoch {expiry_label}", move["high"], f"erwartete Bewegung bis Verfall, ATM-IV {move['atm_iv'] * 100:.1f} %")
        level("em_low", f"EM tief {expiry_label}", move["low"], f"erwartete Bewegung bis Verfall, ATM-IV {move['atm_iv'] * 100:.1f} %")

    analysis_input = {
        "as_of": as_of.isoformat(), "source": SOURCE, "spot": spot,
        "gamma_flip": overall["gamma_flip"], "call_wall": overall["call_wall"], "put_wall": overall["put_wall"],
        "net_gex": overall["net_gex_usd_per_1pct"], "max_pain": main["max_pain"],
        "expected_move_low": None if move is None else move["low"], "expected_move_high": None if move is None else move["high"],
        "main_expiry": main_expiry.isoformat(),
    }
    return {
        "source": SOURCE,
        "currency": currency,
        "spot": spot,
        "as_of": as_of.isoformat(),
        "convention": CONVENTION,
        "strike_window": strike_window,
        "mode": "OBSERVE",
        "skipped": skipped,
        "all_expiries": overall,
        "main_expiry": main,
        "expected_move": move,
        "levels": levels,
        "analysis_input": analysis_input,
        "input_hash": chain_input_hash(currency, spot, as_of, inside, 0.0),
    }
