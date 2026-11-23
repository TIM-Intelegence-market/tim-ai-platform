"""P2: options-flow features Q2, Q4-Q10 of the plan (docs/research_lab/of_optionen_gamma/FORSCHUNGSPLAN.md, section 5).

Q1 (put/call), Q3 (large trades) and the block flow already live in ``features.py`` (S33 rules R2-R4) and are not
repeated here. Overlaps with S33 (Q7 ~ V1) are tested in one family with a common Holm denominator.

Observed vs. unknown: a trade shows instrument, size, price, IV and the **taker** side. Unknown: opening or closing,
the end customer, and whether a leg belongs to a hedge. Greeks below are model values (Black-Scholes on the index price,
rate 0, the trade's own IV) and carry no premium adjustment for inverse options; this is a stated simplification.

Point in time: every function only uses rows received by ``t_ms`` (``recv_ms <= t_ms``). Percentiles are taken only
over values strictly before ``t_ms``. Standard library only.
"""
from __future__ import annotations

import bisect
import itertools
import math
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from src.options_gamma.greeks import bs_delta, bs_gamma
from src.research_lab.options_flow.features import visible

YEAR_MS = 365.0 * 86_400_000
DAY_MS = 86_400_000
EXPIRY_HOUR_UTC = 8  # Deribit expiries settle at 08:00 UTC


def _taker_sign(row: Mapping[str, Any]) -> int:
    return 1 if row["side"] == "buy" else -1


def trade_greeks(row: Mapping[str, Any]) -> tuple[float, float] | None:
    """(delta, gamma) per contract from the trade's IV (Deribit gives IV in percent). None if IV or time is missing."""
    iv = row.get("iv")
    years = (row["expiry_ms"] - row["ts_ms"]) / YEAR_MS
    if not iv or iv <= 0 or years <= 0:
        return None
    s, k, vol = float(row["index_price"]), float(row["strike"]), float(iv) / 100.0
    return bs_delta(s, k, years, vol, bool(row["is_call"])), bs_gamma(s, k, years, vol)


def greek_flow(trades: Iterable[Mapping[str, Any]], t_ms: int, span_ms: int) -> dict[str, Any]:
    """Q5 delta-adjusted flow (USD delta bought by takers) and Q6 gamma-adjusted flow (USD per 1 % move).

    Positive DAF = takers added long delta. Liquidations are left out; trades without IV are counted as skipped.
    """
    daf = gaf = 0.0
    used = skipped = 0
    for r in visible(trades, t_ms, span_ms):
        if r.get("liquidation"):
            continue
        g = trade_greeks(r)
        if g is None:
            skipped += 1
            continue
        s, amount, sign = float(r["index_price"]), float(r["amount"]), _taker_sign(r)
        daf += sign * g[0] * amount * s
        gaf += sign * g[1] * amount * s * s * 0.01
        used += 1
    return {"daf_usd": daf, "gaf_usd_per_pct": gaf, "used": used, "skipped_no_iv": skipped}


def structures(trades: Iterable[Mapping[str, Any]], t_ms: int, span_ms: int) -> list[dict[str, Any]]:
    """Q4: legs with the same ``group_id`` judged together: net taker delta and gamma (USD) of the whole structure."""
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for r in visible(trades, t_ms, span_ms):
        gid = r.get("group_id")
        if gid:
            groups.setdefault(str(gid), []).append(r)
    out = []
    for gid, legs in sorted(groups.items()):
        delta = gamma = premium = 0.0
        complete = True
        for r in legs:
            g = trade_greeks(r)
            if g is None:
                complete = False
                continue
            s, amount, sign = float(r["index_price"]), float(r["amount"]), _taker_sign(r)
            delta += sign * g[0] * amount * s
            gamma += sign * g[1] * amount * s * s * 0.01
            premium += sign * float(r["premium_usd"])
        out.append({"group_id": gid, "legs": len(legs), "net_delta_usd": delta, "net_gamma_usd_per_pct": gamma,
                    "net_premium_usd": premium, "complete": complete})
    return out


def volume_to_oi(trades: Iterable[Mapping[str, Any]], summary: Sequence[Mapping[str, Any]], t_ms: int,
                 span_ms: int = DAY_MS) -> dict[str, Any]:
    """Q2: traded contracts over ``span_ms`` relative to open interest, per instrument and in total.

    High values mean new positioning **or** turnover; which of the two cannot be told from these data.
    """
    vol: dict[str, float] = {}
    for r in visible(trades, t_ms, span_ms):
        vol[str(r["instrument"])] = vol.get(str(r["instrument"]), 0.0) + float(r["amount"])
    oi = {str(r["instrument_name"]): float(r["open_interest"]) for r in summary
          if isinstance(r.get("open_interest"), (int, float)) and not isinstance(r.get("open_interest"), bool)
          and r["open_interest"] > 0}
    per = {k: v / oi[k] for k, v in vol.items() if k in oi}
    total_oi = sum(oi.values())
    return {"per_instrument": per, "total": (sum(vol.values()) / total_oi) if total_oi > 0 else None,
            "max": max(per.values()) if per else None, "without_oi": sorted(k for k in vol if k not in oi)}


def realized_vol(closes: Sequence[float], periods_per_year: float) -> float | None:
    """Annualised realised volatility from consecutive closes (log returns, mean not removed)."""
    if len(closes) < 3 or any(c <= 0 for c in closes):
        return None
    rets = [math.log(b / a) for a, b in itertools.pairwise(closes)]
    return math.sqrt(sum(x * x for x in rets) / len(rets) * periods_per_year)


def variance_premium(implied: float, realized: float) -> float:
    """Q7: implied minus realised variance, both as annual vol fractions (e.g. 0.55)."""
    return implied * implied - realized * realized


def _interp_variance(points: Sequence[tuple[float, float]], years: float) -> float | None:
    """Total-variance interpolation of ATM IV across expiries; no extrapolation."""
    pts = sorted((y, v) for y, v in points if y > 0 and v > 0)
    for (y0, v0), (y1, v1) in itertools.pairwise(pts):
        if y0 <= years <= y1:
            w0, w1 = v0 * v0 * y0, v1 * v1 * y1
            w = w0 + (w1 - w0) * (years - y0) / (y1 - y0)
            return math.sqrt(w / years) if w > 0 else None
    for y, v in pts:
        if abs(y - years) < 1e-12:
            return v
    return None


def term_structure(atm: Sequence[tuple[float, float]], short_days: float = 7, long_days: float = 30) -> float | None:
    """Q8: IV(7 d) - IV(30 d) from (years, ATM IV) pairs. Positive = inverted (short dated richer)."""
    a = _interp_variance(atm, short_days / 365.0)
    b = _interp_variance(atm, long_days / 365.0)
    return None if a is None or b is None else a - b


def risk_reversal(smile: Sequence[tuple[float, float]], target: float = 0.25) -> float | None:
    """Q9: IV(+25 delta call) - IV(-25 delta put) for one expiry from (delta, IV) points; linear in delta, no extrapolation."""
    def at(d: float) -> float | None:
        pts = sorted(smile)
        for (d0, v0), (d1, v1) in itertools.pairwise(pts):
            if d0 <= d <= d1 and d1 > d0:
                return v0 + (v1 - v0) * (d - d0) / (d1 - d0)
        return None
    call, put = at(target), at(-target)
    return None if call is None or put is None else call - put


def next_expiry(t_ms: int) -> datetime:
    t = datetime.fromtimestamp(t_ms / 1000, tz=timezone.utc)
    e = t.replace(hour=EXPIRY_HOUR_UTC, minute=0, second=0, microsecond=0)
    return e if e > t else e + timedelta(days=1)


def expiry_features(summary: Sequence[Mapping[str, Any]], spot: float, t_ms: int, *, atm_band: float = 0.02,
                    past_atm_oi: Sequence[tuple[int, float]] = ()) -> dict[str, Any]:
    """Q10 at time ``t_ms``: hours to the next 08:00 UTC, share of OI that expires within 24 h, ATM OI of that expiry,
    and its percentile **only among earlier expiries** (``past_atm_oi`` = (expiry_ms, atm_oi), anything at or after
    ``t_ms`` is ignored). Rows need ``expiry_ms``, ``strike``, ``open_interest``."""
    nxt = next_expiry(t_ms)
    nxt_ms = int(nxt.timestamp() * 1000)
    total = soon = atm = 0.0
    for r in summary:
        oi = r.get("open_interest")
        if not isinstance(oi, (int, float)) or isinstance(oi, bool) or oi <= 0:
            continue
        total += oi
        if r["expiry_ms"] - t_ms <= DAY_MS:
            soon += oi
        if r["expiry_ms"] == nxt_ms and abs(float(r["strike"]) / spot - 1.0) <= atm_band:
            atm += oi
    past = sorted(v for e, v in past_atm_oi if e < t_ms)
    pct = (bisect.bisect_right(past, atm) / len(past)) if past else None
    return {"hours_to_expiry": (nxt_ms - t_ms) / 3_600_000, "share_oi_24h": (soon / total) if total else None,
            "atm_oi_next": atm, "atm_oi_percentile": pct, "past_n": len(past)}
