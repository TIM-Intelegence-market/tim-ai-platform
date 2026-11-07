"""Driver catalog: one entry per suspected BTC driver (EINFLUSS_BAROMETER.md section 5a point 1).

A new driver is a new entry here, not new code. Every entry says where the value comes from, how the
change over 13 weeks is measured, when a value counts as known (``lag_days`` after its observation date,
conservative) and whether the series is published as revised latest values only.
"""
from __future__ import annotations

from dataclasses import dataclass

LIQUIDITY_KEY = "NETLIQ"


@dataclass(frozen=True, slots=True)
class Driver:
    key: str
    label: str
    series: tuple[str, ...]  # FRED ids (or CM_* for source "coinmetrics"); NETLIQ combines WALCL - WTREGEN - RRPONTSYD
    change: str  # "bp" (rates in percent), "pct" (prices, indices), "diff" (levels)
    lag_days: int  # an observation dated d counts as known from d + lag_days 00:00 UTC
    family: str
    max_age_days: int = 14  # a known value older than this gives no state
    revised: bool = False  # True: FRED gives revised latest values, no vintages used here
    note: str = ""
    source: str = "fred"  # "fred" or "coinmetrics" (dominance substitute, see dominance.py)

    @property
    def needs_lead(self) -> bool:
        """Crypto-internal series follow the price; they only count as a driver with a measured lead (5b)."""
        return self.family == "krypto"


DRIVERS: tuple[Driver, ...] = (
    Driver("DFII10", "Realzins 10J", ("DFII10",), "bp", 1, "zinsen"),
    Driver("DGS10", "Rendite 10J", ("DGS10",), "bp", 1, "zinsen"),
    Driver("T10YIE", "Inflationserwartung 10J", ("T10YIE",), "bp", 1, "zinsen"),
    Driver("DTWEXBGS", "Dollar-Index (Fed Broad)", ("DTWEXBGS",), "pct", 8, "dollar",
           note="FRED veröffentlicht den Index mit etwa einer Woche Verzug"),
    Driver("DEXJPUS", "Yen je Dollar (USD/JPY)", ("DEXJPUS",), "pct", 8, "dollar",
           note="H.10, wöchentlich veröffentlicht"),
    Driver("SP500", "S&P 500", ("SP500",), "pct", 1, "aktien",
           note="FRED führt nur rund zehn Jahre; Lizenz S&P Dow Jones Indices"),
    Driver("NASDAQCOM", "Nasdaq Composite", ("NASDAQCOM",), "pct", 1, "aktien"),
    Driver("VIXCLS", "VIX", ("VIXCLS",), "diff", 1, "risiko"),
    Driver("BAMLH0A0HYM2", "Risikoaufschlag High Yield", ("BAMLH0A0HYM2",), "bp", 1, "risiko",
           note="ICE BofA: FRED zeigt seit 2023 nur noch drei Jahre Historie, Quelle prüfen"),
    Driver("DCOILWTICO", "Öl WTI", ("DCOILWTICO",), "pct", 1, "rohstoffe"),
    Driver(LIQUIDITY_KEY, "Netto-Liquidität Fed (Mrd. USD)", ("WALCL", "WTREGEN", "RRPONTSYD"), "diff", 1,
           "liquiditaet", note="Mittwochswerte, Veröffentlichung donnerstags"),
    Driver("M2SL", "Geldmenge M2 USA", ("M2SL",), "pct", 35, "liquiditaet", max_age_days=70, revised=True,
           note="monatlich, rund vier Wochen nach Monatsende, wird revidiert"),
    Driver("ECBASSETSW", "Bilanz EZB", ("ECBASSETSW",), "pct", 8, "liquiditaet",
           note="wöchentlich, in Euro"),
    Driver("BTCD", "BTC-Dominanz (Ersatz)", ("CM_BTC_DOMINANCE",), "diff", 1, "krypto", source="coinmetrics",
           note="Prozentpunkte; Anteil BTC an rund 830 Coin-Metrics-Assets (CapMrktEstUSD) ab 2019-06, nicht TradingView BTC.D"),
    Driver("USDTD", "USDT-Dominanz (Ersatz)", ("CM_USDT_DOMINANCE",), "diff", 1, "krypto", source="coinmetrics",
           note="Prozentpunkte; Anteil Tether am selben Korb, steigt meist bei Risiko-aus"),
)

def by_key(key: str) -> Driver:
    for driver in DRIVERS:
        if driver.key == key:
            return driver
    raise KeyError(key)


def all_series(source: str = "fred") -> tuple[str, ...]:
    """Series ids of one source; FRED is the default because ``fetch`` downloads those."""
    seen: list[str] = []
    for driver in (d for d in DRIVERS if d.source == source):
        seen.extend(s for s in driver.series if s not in seen)
    return tuple(seen)
