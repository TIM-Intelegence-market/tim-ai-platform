"""Gamma exposure (GEX) per strike from one options-chain snapshot.

Convention (an assumption, not a fact about real positioning): dealers are
long the calls and short the puts that customers hold. Call GEX counts
positive, put GEX negative. Open interest does not reveal who is long or
short, so every number here is an estimate.

Unit: USD change of dealer delta per 1 % move of the underlying,
GEX = gamma * open_interest * multiplier * spot**2 * 0.01.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from src.options_gamma.greeks import bs_gamma

SECONDS_PER_YEAR = 365.0 * 24 * 3600
FLIP_GRID_STEPS = 400


@dataclass(frozen=True, slots=True)
class OptionQuote:
    strike: float
    expiry: datetime
    is_call: bool
    open_interest: float
    implied_vol: float
    multiplier: float = 1.0

    def __post_init__(self) -> None:
        if self.expiry.tzinfo is None:
            raise ValueError("expiry must be timezone-aware")
        if self.open_interest < 0:
            raise ValueError("open interest must not be negative")
        if self.strike <= 0 or self.implied_vol <= 0 or self.multiplier <= 0:
            raise ValueError("strike, implied_vol and multiplier must be positive")


@dataclass(frozen=True, slots=True)
class StrikeExposure:
    strike: float
    call_gex: float
    put_gex: float

    @property
    def net_gex(self) -> float:
        return self.call_gex + self.put_gex


@dataclass(frozen=True, slots=True)
class GexProfile:
    symbol: str
    spot: float
    as_of: datetime
    strikes: tuple[StrikeExposure, ...]
    net_gex: float
    call_wall: float | None
    put_wall: float | None
    gamma_flip: float | None
    skipped_expired: int
    input_hash: str

    @property
    def regime(self) -> str:
        if self.net_gex > 0:
            return "POSITIVE_GAMMA"
        if self.net_gex < 0:
            return "NEGATIVE_GAMMA"
        return "NEUTRAL_GAMMA"


def chain_input_hash(symbol: str, spot: float, as_of: datetime, chain: Sequence[OptionQuote], rate: float) -> str:
    rows = sorted(
        [q.strike, q.expiry.isoformat(), q.is_call, q.open_interest, q.implied_vol, q.multiplier] for q in chain
    )
    payload = {"symbol": symbol, "spot": spot, "as_of": as_of.isoformat(), "rate": rate, "chain": rows}
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def _years(as_of: datetime, expiry: datetime) -> float:
    return (expiry - as_of).total_seconds() / SECONDS_PER_YEAR


def _quote_gex(quote: OptionQuote, spot: float, years: float, rate: float) -> float:
    gamma = bs_gamma(spot, quote.strike, years, quote.implied_vol, rate)
    value = gamma * quote.open_interest * quote.multiplier * spot * spot * 0.01
    return value if quote.is_call else -value


def _total_gex(live: Sequence[tuple[OptionQuote, float]], spot: float, rate: float) -> float:
    return sum(_quote_gex(q, spot, years, rate) for q, years in live)


def _gamma_flip(live: Sequence[tuple[OptionQuote, float]], rate: float) -> float | None:
    """Hypothetical spot where total GEX changes sign, scanned over the strike range.

    If several crossings exist, the one with the lowest price is returned. None if no crossing.
    """
    low = min(q.strike for q, _ in live)
    high = max(q.strike for q, _ in live)
    if high <= low:
        return None
    step = (high - low) / FLIP_GRID_STEPS
    prev_s, prev_v = low, _total_gex(live, low, rate)
    for i in range(1, FLIP_GRID_STEPS + 1):
        s = low + i * step
        v = _total_gex(live, s, rate)
        if prev_v == 0:
            return prev_s
        if (prev_v < 0) != (v < 0):
            return prev_s + (s - prev_s) * (-prev_v) / (v - prev_v)
        prev_s, prev_v = s, v
    return prev_s if prev_v == 0 else None


def compute_gex_profile(
    symbol: str, spot: float, as_of: datetime, chain: Sequence[OptionQuote], rate: float = 0.0
) -> GexProfile:
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    if spot <= 0:
        raise ValueError("spot must be positive")
    live: list[tuple[OptionQuote, float]] = []
    skipped = 0
    for quote in chain:
        years = _years(as_of, quote.expiry)
        if years <= 0:
            skipped += 1
            continue
        live.append((quote, years))
    per_strike: dict[float, list[float]] = {}
    for quote, years in live:
        bucket = per_strike.setdefault(quote.strike, [0.0, 0.0])
        bucket[0 if quote.is_call else 1] += _quote_gex(quote, spot, years, rate)
    strikes = tuple(StrikeExposure(k, v[0], v[1]) for k, v in sorted(per_strike.items()))
    calls = [s for s in strikes if s.call_gex > 0]
    puts = [s for s in strikes if s.put_gex < 0]
    call_wall = max(calls, key=lambda s: (s.call_gex, -s.strike)).strike if calls else None
    put_wall = min(puts, key=lambda s: (s.put_gex, s.strike)).strike if puts else None
    return GexProfile(
        symbol=symbol,
        spot=spot,
        as_of=as_of,
        strikes=strikes,
        net_gex=sum(s.net_gex for s in strikes),
        call_wall=call_wall,
        put_wall=put_wall,
        gamma_flip=_gamma_flip(live, rate) if live else None,
        skipped_expired=skipped,
        input_hash=chain_input_hash(symbol, spot, as_of, chain, rate),
    )


def load_chain_snapshot(data: dict[str, Any]) -> tuple[str, float, datetime, list[OptionQuote]]:
    """Read a snapshot dict (see tests/fixtures/options_gamma/btc_chain_sample.json)."""
    multiplier = float(data.get("multiplier", 1.0))
    chain = []
    for row in data["chain"]:
        if row["type"] not in ("call", "put"):
            raise ValueError(f"unknown option type: {row['type']!r}")
        chain.append(
            OptionQuote(
                strike=float(row["strike"]),
                expiry=datetime.fromisoformat(row["expiry"]),
                is_call=row["type"] == "call",
                open_interest=float(row["open_interest"]),
                implied_vol=float(row["implied_vol"]),
                multiplier=multiplier,
            )
        )
    return str(data["symbol"]), float(data["spot"]), datetime.fromisoformat(data["as_of"]), chain
