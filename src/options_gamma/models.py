"""P1: several dealer-positioning models for gamma exposure, side by side (plan docs/research_lab/of_optionen_gamma).

Nobody knows the real dealer position on Deribit. Each model states its sign assumption openly:

- ``M0`` standard: dealers long calls, short puts (same as ``gex.py``).
- ``M1`` all short: dealers short every option (customers net buyers).
- ``M2`` all long: dealers long every option (customers net sellers).
- ``M3`` taker flow: dealer position = minus the cumulative net taker flow per contract (size from flow, not OI).
  Complete only for contracts listed after the recorder started; the caller says which contracts are complete.
- ``M4`` OI change x side: sign from the taker side of the trades that changed OI; size = OI.

Under M1 GEX is always negative and under M2 always positive: they have **no regime and no flip**. Only the magnitude
``abs_gex`` is meaningful there (``regime`` and ``gamma_flip`` are None).

Two gamma variants, reported separately:
(a) ``spot``: Black-Scholes gamma on spot with rate 0, exactly as ``gex.py``.
(b) ``forward``: Black-76 gamma on the forward ``F_T`` of each expiry, mapped to spot with dF/dS = F/S.
    With F = S both variants agree.

Unit everywhere: USD change of dealer delta per 1 % move of the underlying.
Vanna exposure: USD dealer delta per +1 vol point. Charm exposure: USD dealer delta per day of time decay.
Standard library only. No data is fetched here.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from src.options_gamma.gex import SECONDS_PER_YEAR, OptionQuote
from src.options_gamma.greeks import bs_gamma

FLIP_RANGE = 0.10   # flip search over spot * (1 +- 10 %)
FLIP_STEP = 0.0025  # 0.25 % steps
DEFAULT_SHIFTS = (-0.10, -0.05, -0.02, 0.0, 0.02, 0.05, 0.10)


class DealerModel(str, Enum):
    M0 = "M0_standard"
    M1 = "M1_all_short"
    M2 = "M2_all_long"
    M3 = "M3_taker_flow"
    M4 = "M4_oi_change_side"


SIGN_VARYING = (DealerModel.M0, DealerModel.M3, DealerModel.M4)
"""Models whose net GEX can change sign; only these carry a regime and a flip."""

QuoteKey = tuple[float, datetime, bool]
"""(strike, expiry, is_call) identifies one contract."""


def quote_key(q: OptionQuote) -> QuoteKey:
    return (q.strike, q.expiry, q.is_call)


@dataclass(frozen=True, slots=True)
class Positioning:
    """Inputs the flow-based models need. Both maps are in contracts, keyed by ``quote_key``.

    ``taker_net``: cumulative taker buys minus taker sells since listing (M3).
    ``complete``: contracts whose whole trade history since listing was recorded; M3 skips the rest and counts them.
    ``oi_side``: signed taker volume during the window in which OI changed (M4); only its sign is used.
    """
    taker_net: Mapping[QuoteKey, float] | None = None
    complete: frozenset[QuoteKey] | None = None
    oi_side: Mapping[QuoteKey, float] | None = None


@dataclass(frozen=True, slots=True)
class ModelProfile:
    model: DealerModel
    variant: str
    spot: float
    net_gex: float
    abs_gex: float
    regime: str | None
    gamma_flip: float | None
    call_wall: float | None
    put_wall: float | None
    vanna_exposure: float
    charm_exposure: float
    used: int
    skipped: int


def _years(as_of: datetime, expiry: datetime) -> float:
    return (expiry - as_of).total_seconds() / SECONDS_PER_YEAR


def _phi(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _d1_d2(underlying: float, strike: float, years: float, vol: float) -> tuple[float, float]:
    sq = vol * math.sqrt(years)
    d1 = (math.log(underlying / strike) + 0.5 * vol * vol * years) / sq
    return d1, d1 - sq


def b76_gamma(forward: float, strike: float, years: float, vol: float) -> float:
    """Black-76 gamma with respect to the forward, undiscounted (rate 0)."""
    if forward <= 0 or strike <= 0 or years <= 0 or vol <= 0:
        raise ValueError("forward, strike, years and vol must be positive")
    d1, _ = _d1_d2(forward, strike, years, vol)
    return _phi(d1) / (forward * vol * math.sqrt(years))


def vanna(underlying: float, strike: float, years: float, vol: float) -> float:
    """d(delta)/d(vol) per 1.0 of vol (100 vol points), rate 0. Same for calls and puts."""
    d1, d2 = _d1_d2(underlying, strike, years, vol)
    return -_phi(d1) * d2 / vol


def charm(underlying: float, strike: float, years: float, vol: float) -> float:
    """d(delta)/d(calendar time) per year, rate 0, no dividend. Same for calls and puts.

    Delta changes by ``charm * dt`` as time ``dt`` (in years) passes; sign convention: passage of time, not tau.
    """
    d1, d2 = _d1_d2(underlying, strike, years, vol)
    return _phi(d1) * d2 / (2.0 * years)


def _sign_and_size(model: DealerModel, q: OptionQuote, pos: Positioning) -> tuple[float, float] | None:
    """Dealer sign and contract count for one quote, or None if the model cannot say anything."""
    if model is DealerModel.M0:
        return (1.0 if q.is_call else -1.0), q.open_interest
    if model is DealerModel.M1:
        return -1.0, q.open_interest
    if model is DealerModel.M2:
        return 1.0, q.open_interest
    key = quote_key(q)
    if model is DealerModel.M3:
        if pos.taker_net is None or pos.complete is None or key not in pos.complete:
            return None
        net = pos.taker_net.get(key, 0.0)
        return (-1.0 if net > 0 else 1.0), abs(net)
    if pos.oi_side is None or key not in pos.oi_side or pos.oi_side[key] == 0:
        return None
    return (-1.0 if pos.oi_side[key] > 0 else 1.0), q.open_interest


def _quote_gamma_usd(q: OptionQuote, price: float, years: float, variant: str,
                     forwards: Mapping[datetime, float] | None, spot_ref: float) -> float:
    """Gamma of one contract times multiplier * price**2 * 1 %, before dealer sign and size."""
    if variant == "spot":
        return bs_gamma(price, q.strike, years, q.implied_vol) * q.multiplier * price * price * 0.01
    if forwards is None or q.expiry not in forwards:
        raise KeyError(f"forward missing for expiry {q.expiry.isoformat()}")
    fwd = forwards[q.expiry] * price / spot_ref  # forward moves one for one in relative terms with spot
    return b76_gamma(fwd, q.strike, years, q.implied_vol) * fwd * fwd * q.multiplier * 0.01


def _live(chain: Sequence[OptionQuote], as_of: datetime, model: DealerModel, pos: Positioning):
    live, skipped = [], 0
    for q in chain:
        years = _years(as_of, q.expiry)
        ss = _sign_and_size(model, q, pos) if years > 0 else None
        if ss is None:
            skipped += 1
            continue
        live.append((q, years, ss[0], ss[1]))
    return live, skipped


def _total(live, price: float, variant: str, forwards, spot_ref: float) -> float:
    return sum(sign * size * _quote_gamma_usd(q, price, years, variant, forwards, spot_ref)
               for q, years, sign, size in live)


def _flip(live, spot: float, variant: str, forwards) -> float | None:
    steps = round(FLIP_RANGE / FLIP_STEP)
    grid = [spot * (1.0 + FLIP_STEP * i) for i in range(-steps, steps + 1)]
    prev_s, prev_v = grid[0], _total(live, grid[0], variant, forwards, spot)
    for s in grid[1:]:
        v = _total(live, s, variant, forwards, spot)
        if prev_v == 0:
            return prev_s
        if (prev_v < 0) != (v < 0):
            return prev_s + (s - prev_s) * (-prev_v) / (v - prev_v)
        prev_s, prev_v = s, v
    return None


def model_profile(chain: Sequence[OptionQuote], spot: float, as_of: datetime, model: DealerModel, *,
                  variant: str = "spot", forwards: Mapping[datetime, float] | None = None,
                  positioning: Positioning | None = None) -> ModelProfile:
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    if spot <= 0:
        raise ValueError("spot must be positive")
    if variant not in ("spot", "forward"):
        raise ValueError("variant must be 'spot' or 'forward'")
    pos = positioning or Positioning()
    live, skipped = _live(chain, as_of, model, pos)
    per_strike: dict[float, list[float]] = {}
    vanna_x = charm_x = 0.0
    for q, years, sign, size in live:
        g = sign * size * _quote_gamma_usd(q, spot, years, variant, forwards, spot)
        bucket = per_strike.setdefault(q.strike, [0.0, 0.0])
        bucket[0 if q.is_call else 1] += g
        underlying = spot if variant == "spot" else forwards[q.expiry]  # type: ignore[index]
        vanna_x += sign * size * vanna(underlying, q.strike, years, q.implied_vol) * q.multiplier * spot * 0.01
        charm_x += sign * size * charm(underlying, q.strike, years, q.implied_vol) / 365.0 * q.multiplier * spot
    net = sum(c + p for c, p in per_strike.values())
    abs_gex = sum(abs(c) + abs(p) for c, p in per_strike.values())
    calls = [(k, c) for k, (c, _) in per_strike.items() if c != 0]
    puts = [(k, p) for k, (_, p) in per_strike.items() if p != 0]
    call_wall = max(calls, key=lambda kv: (abs(kv[1]), -kv[0]))[0] if calls else None
    put_wall = max(puts, key=lambda kv: (abs(kv[1]), kv[0]))[0] if puts else None
    varying = model in SIGN_VARYING
    regime = None
    if varying:
        regime = "POSITIVE_GAMMA" if net > 0 else "NEGATIVE_GAMMA" if net < 0 else "NEUTRAL_GAMMA"
    return ModelProfile(
        model=model, variant=variant, spot=spot, net_gex=net, abs_gex=abs_gex, regime=regime,
        gamma_flip=_flip(live, spot, variant, forwards) if (varying and live) else None,
        call_wall=call_wall, put_wall=put_wall, vanna_exposure=vanna_x, charm_exposure=charm_x,
        used=len(live), skipped=skipped,
    )


def all_models(chain: Sequence[OptionQuote], spot: float, as_of: datetime, *, variant: str = "spot",
               forwards: Mapping[datetime, float] | None = None,
               positioning: Positioning | None = None) -> dict[DealerModel, ModelProfile]:
    return {m: model_profile(chain, spot, as_of, m, variant=variant, forwards=forwards, positioning=positioning)
            for m in DealerModel}


def sensitivity(chain: Sequence[OptionQuote], spot: float, as_of: datetime, model: DealerModel, *,
                shifts: Sequence[float] = DEFAULT_SHIFTS, days_ahead: Sequence[int] = (0, 1),
                variant: str = "spot", forwards: Mapping[datetime, float] | None = None,
                positioning: Positioning | None = None) -> list[dict]:
    """Net and absolute GEX on a grid of spot moves and elapsed days (chain and OI held fixed)."""
    out = []
    for days in days_ahead:
        t = as_of + timedelta(days=days)
        for shift in shifts:
            s = spot * (1.0 + shift)
            fw = None if forwards is None else {k: v * (1.0 + shift) for k, v in forwards.items()}
            p = model_profile(chain, s, t, model, variant=variant, forwards=fw, positioning=positioning)
            out.append({"days": days, "shift": shift, "spot": s, "net_gex": p.net_gex, "abs_gex": p.abs_gex,
                        "regime": p.regime, "used": p.used})
    return out


def assumption_independent(signs: Mapping[DealerModel, float], abs_signs: Mapping[DealerModel, float]) -> bool:
    """Plan 6.2: an effect counts only if it has the same direction in M0, M3, M4 (net GEX) and the same direction
    of the |GEX| effect under M1 and M2. ``signs``/``abs_signs`` hold the estimated effect per model (sign matters)."""
    need = [signs.get(m) for m in SIGN_VARYING]
    mag = [abs_signs.get(m) for m in (DealerModel.M1, DealerModel.M2)]
    if any(v is None or v == 0 for v in need + mag):
        return False
    return len({v > 0 for v in need}) == 1 and len({v > 0 for v in mag}) == 1
