"""Black-Scholes greeks without dividends, standard library only."""

from __future__ import annotations

import math


def _check(spot: float, strike: float, years: float, vol: float) -> None:
    if spot <= 0 or strike <= 0:
        raise ValueError("spot and strike must be positive")
    if years <= 0:
        raise ValueError("time to expiry must be positive")
    if vol <= 0:
        raise ValueError("volatility must be positive")


def _d1(spot: float, strike: float, years: float, vol: float, rate: float) -> float:
    return (math.log(spot / strike) + (rate + 0.5 * vol * vol) * years) / (vol * math.sqrt(years))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_gamma(spot: float, strike: float, years: float, vol: float, rate: float = 0.0) -> float:
    """Change of delta per 1 unit move of the underlying. Same for calls and puts."""
    _check(spot, strike, years, vol)
    d1 = _d1(spot, strike, years, vol, rate)
    return _norm_pdf(d1) / (spot * vol * math.sqrt(years))


def bs_delta(spot: float, strike: float, years: float, vol: float, is_call: bool, rate: float = 0.0) -> float:
    _check(spot, strike, years, vol)
    cdf = _norm_cdf(_d1(spot, strike, years, vol, rate))
    return cdf if is_call else cdf - 1.0
