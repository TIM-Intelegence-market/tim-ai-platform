"""Leverage scenarios at equal risk per trade (Phase 5).

Linear USDT perp, isolated margin. A long liquidates when the loss eats the initial margin down to the maintenance
margin: distance to liquidation ~= 1/leverage - mmr (fees and funding ignored, so the real distance is a little
smaller). Position size comes from risk and stop distance, never from leverage; leverage only sets the margin and
with it the liquidation distance. If the liquidation sits at or inside the stop, the stop never fires and the trade
loses the whole margin first: the scenario is rejected.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from src.research_lab.bitunix.contract import BTCUSDT, FEE_TAKER, Contract
from src.research_lab.of2.config import DEFAULT_CONFIG as _OF2

# Same slippage as the OF2 spec (protocol 4.4): 0,03 % on a normal fill, 0,05 % when the stop fills.
SLIPPAGE = _OF2.slippage
STOP_SLIPPAGE = _OF2.stop_slippage

LEVERAGES = (1, 2, 5, 10, 25, 50, 100, 200)


@dataclass(frozen=True)
class Scenario:
    leverage: int
    allowed_by_contract: bool
    notional: float
    initial_margin: float
    margin_use: float  # share of equity
    mmr: float
    liq_distance: float  # fraction of entry
    stop_distance: float
    liq_before_stop: bool
    cost_per_trade: float  # USDT for a trade that ends at the stop: taker both sides, entry slippage, stop slippage
    cost_in_r: float
    loss_at_stop: float  # USDT incl. costs
    funding_per_8h: float  # USDT at the given funding rate
    verdict: str

    def as_dict(self) -> dict:
        return asdict(self)


def liquidation_distance(leverage: float, mmr: float) -> float:
    return 1.0 / leverage - mmr


def scenario(
    *,
    equity: float,
    risk_fraction: float,
    stop_distance: float,
    leverage: int,
    contract: Contract = BTCUSDT,
    fee: float = FEE_TAKER,
    slippage: float = SLIPPAGE,
    stop_slippage: float = STOP_SLIPPAGE,
    funding_rate: float = 0.0001,
    safety: float = 1.5,
) -> Scenario:
    """Size the trade by risk, then check what the leverage does to margin and liquidation.

    ``safety``: the liquidation must lie at least ``safety`` x the stop distance away (gap and wick buffer).
    """
    if equity <= 0 or risk_fraction <= 0 or stop_distance <= 0:
        raise ValueError("equity, risk_fraction and stop_distance must be > 0")
    stop_costs = 2 * fee + slippage + stop_slippage  # worst normal case: the trade ends at the stop
    risk_usd = equity * risk_fraction
    # Loss at the stop = notional * (stop + costs of a stopped trade) = risk_usd.
    notional = risk_usd / (stop_distance + stop_costs)
    tier = contract.tier_for(notional)
    margin = notional / leverage
    liq = liquidation_distance(leverage, tier.mmr)
    cost = notional * stop_costs
    liq_before_stop = liq <= stop_distance
    allowed = contract.leverage_allowed(leverage, notional)
    if not allowed:
        verdict = "NOT AVAILABLE"
    elif liq_before_stop:
        verdict = "NOT APPROVED (liquidation before stop)"
    elif liq < safety * stop_distance:
        verdict = "NOT APPROVED (liquidation too close to stop)"
    elif margin > equity:
        verdict = "NOT APPROVED (margin above equity)"
    else:
        verdict = "OK"
    return Scenario(
        leverage=leverage,
        allowed_by_contract=allowed,
        notional=round(notional, 2),
        initial_margin=round(margin, 2),
        margin_use=round(margin / equity, 4),
        mmr=tier.mmr,
        liq_distance=round(liq, 5),
        stop_distance=stop_distance,
        liq_before_stop=liq_before_stop,
        cost_per_trade=round(cost, 4),
        cost_in_r=round(cost / risk_usd, 4),
        loss_at_stop=round(notional * (stop_distance + stop_costs), 4),
        funding_per_8h=round(notional * funding_rate, 4),
        verdict=verdict,
    )


def max_safe_leverage(stop_distance: float, mmr: float, safety: float = 1.5) -> float:
    """Highest leverage whose liquidation lies ``safety`` x beyond the stop: 1/L - mmr >= safety*stop."""
    return 1.0 / (safety * stop_distance + mmr)


def table(*, equity: float, risk_fraction: float, stop_distance: float, **kw) -> list[Scenario]:
    return [scenario(equity=equity, risk_fraction=risk_fraction, stop_distance=stop_distance, leverage=lev, **kw)
            for lev in LEVERAGES]
