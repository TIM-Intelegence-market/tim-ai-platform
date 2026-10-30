"""Gamma and gamma-exposure (GEX) research layer.

OBSERVE only: pure calculations on a supplied options-chain snapshot. There is
no network access, no order, no hedge and no account path in this package.
"""

from src.options_gamma.greeks import bs_delta, bs_gamma
from src.options_gamma.gex import GexProfile, OptionQuote, StrikeExposure, compute_gex_profile, gex_at, load_chain_snapshot
from src.options_gamma.observations import GexObservation, GexObservationEngine
from src.options_gamma.snapshot import build_gamma_snapshot, parse_instrument

__all__ = [
    "GexObservation",
    "GexObservationEngine",
    "GexProfile",
    "OptionQuote",
    "StrikeExposure",
    "bs_delta",
    "bs_gamma",
    "build_gamma_snapshot",
    "compute_gex_profile",
    "gex_at",
    "load_chain_snapshot",
    "parse_instrument",
]
