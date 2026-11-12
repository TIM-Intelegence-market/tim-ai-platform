"""Study S25: position size from the GARCH-4h forecast for S7b-D20-T3 (sizing study, no new entries).

Preregistration: docs/research_lab/studien/S25_GARCH_GROESSE_S7B_PRAEREGISTRIERUNG_ENTWURF.md. Pure Python (stdlib).

The S7b trades stay exactly as they are. Each trade gets a weight from the S15-4h GARCH forecast for the 4h
period that starts at the entry (known at the entry: only periods that closed by then are used):

    w = clip(ref / sigma, W_MIN, W_MAX)

``sigma`` is the square root of the forecast variance (percent), ``ref`` the median sigma of the same symbol
over the REF_DAYS before the entry (past only). The weighted trade is R' = w * R / mean(w of the section), so
both arms have the same mean size and the comparison shows only the redistribution between calm and wild
periods. Main measure: maximum drawdown in R (trades in exit order). A placebo shuffles the weights over the
trades of a section.

Commands (``python -m src.research_lab.studies.s25``):
- ``count``: outcome-blind, only the number of trades with a usable weight per section and symbol; never
  reads R.
- ``run``: refuses until the preregistration is frozen (``FROZEN``) and the trades file has the frozen hash.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import random
import statistics
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from src.research_lab.backtest.metrics import max_drawdown_r
from src.research_lab.protocol import HOLDOUT_START_MS
from src.research_lab.studies import s15

FROZEN = False  # set to True only with the freeze of version 1.0 on Uzi's word
FROZEN_TRADES_SHA256 = "fa45d740da405a2fc96737a1a61d3fde151d81f68695f1951587ae0e85b88b26"  # s7b_train_2026-10-26T1305Z_trades.json
VARIANT = "S7b-D20-T3"
REPORTED = ("S7b-D20-T4",)  # reported only, decides nothing
HORIZON = s15.S15_VARIANTS[0]  # S15-4h
DAY_MS = 86_400_000
REF_DAYS = 365
REF_MIN_DAYS = 90  # fewer days of earlier forecasts: no weight (trade left out in both arms)
W_MIN, W_MAX = 0.5, 2.0  # as src/research_lab/vol_4h.py
PLACEBO_RUNS = 2000
SEED = 20261111
MIN_VALIDATION_TRADES = 80
DD_FACTOR = 0.9
P_MAX = 0.05
SECTIONS = ("train", "validation")
SYMBOLS = {"BTCUSDT": (2020, 1), "ETHUSDT": (2020, 1), "SOLUSDT": (2020, 9)}
LAST = (2024, 12)


# ---------------------------------------------------------------- forecasts and weights


@dataclass(frozen=True, slots=True)
class SigmaSeries:
    """GARCH-4h sigma (percent) per period start, in time order, for one symbol."""
    starts: list[int]
    sigmas: list[float]

    def at(self, start: int) -> float | None:
        i = bisect.bisect_left(self.starts, start)
        return self.sigmas[i] if i < len(self.starts) and self.starts[i] == start else None

    def reference(self, before: int) -> float | None:
        """Median sigma of the periods that start in [before - REF_DAYS, before); None below REF_MIN_DAYS."""
        lo = bisect.bisect_left(self.starts, before - REF_DAYS * DAY_MS)
        hi = bisect.bisect_left(self.starts, before)
        window = self.sigmas[lo:hi]
        if len(window) < REF_MIN_DAYS * HORIZON.per_day:
            return None
        return statistics.median(window)


def sigma_series(periods: Sequence[s15.Period]) -> SigmaSeries:
    """S15-4h GARCH forecasts (expanding refit every 30 days, burn-in 365 days), holdout cut off."""
    forecasts = s15.forecasts([p for p in periods if p.start < HOLDOUT_START_MS], HORIZON, 0, HOLDOUT_START_MS)
    usable = [f for f in forecasts if f.garch > 0 and math.isfinite(f.garch)]
    return SigmaSeries([f.start for f in usable], [math.sqrt(f.garch) for f in usable])


def weight(series: SigmaSeries, entry_time: int) -> float | None:
    """Weight for a trade entering at entry_time (a 4h period start), or None without forecast or reference."""
    sigma = series.at(entry_time)
    ref = series.reference(entry_time)
    if sigma is None or ref is None or sigma <= 0:
        return None
    return min(W_MAX, max(W_MIN, ref / sigma))


# ---------------------------------------------------------------- trades


@dataclass(frozen=True, slots=True)
class WTrade:
    symbol: str
    entry_time: int
    exit_time: int
    r: float
    cost_r: float
    w: float


def select(trades: Sequence[Mapping], variant: str, section: str) -> list[Mapping]:
    out = [t for t in trades if t["variant"] == variant and t["section"] == section]
    if any(int(t["entry_time"]) >= HOLDOUT_START_MS for t in out):
        raise ValueError("trade in the holdout period; S25 never uses the holdout")
    return out


def attach(trades: Sequence[Mapping], sigmas: Mapping[str, SigmaSeries]) -> tuple[list[WTrade], int]:
    """Trades with a weight, and the number left out (no forecast or reference)."""
    out, missing = [], 0
    for t in trades:
        series = sigmas.get(t["symbol"])
        w = weight(series, int(t["entry_time"])) if series else None
        if w is None:
            missing += 1
            continue
        out.append(WTrade(t["symbol"], int(t["entry_time"]), int(t["exit_time"]), float(t["r"]),
                          float(t.get("cost_r", 0.0)), w))
    return out, missing


def count_rows(trades: Sequence[Mapping], sigmas: Mapping[str, SigmaSeries]) -> dict:
    """Outcome-blind count: reads only symbol and entry time, never R."""
    rows: dict = {}
    for variant in (VARIANT, *REPORTED):
        rows[variant] = {}
        for section in SECTIONS:
            chosen = select(trades, variant, section)
            by_symbol: dict[str, dict[str, int]] = {}
            for t in chosen:
                row = by_symbol.setdefault(t["symbol"], {"trades": 0, "with_weight": 0})
                row["trades"] += 1
                series = sigmas.get(t["symbol"])
                if series is not None and weight(series, int(t["entry_time"])) is not None:
                    row["with_weight"] += 1
            rows[variant][section] = {
                "trades": len(chosen),
                "with_weight": sum(r["with_weight"] for r in by_symbol.values()),
                "by_symbol": by_symbol,
            }
    return rows


# ---------------------------------------------------------------- measures


def _ordered(trades: Sequence[WTrade]) -> list[WTrade]:
    return sorted(trades, key=lambda t: (t.exit_time, t.entry_time, t.symbol))


def weighted(results: Sequence[float], weights: Sequence[float]) -> list[float]:
    mean_w = statistics.fmean(weights)
    return [w * r / mean_w for r, w in zip(results, weights, strict=True)]


@dataclass(frozen=True, slots=True)
class ArmResult:
    n: int
    expectancy: float
    drawdown: float
    r_per_risk: float  # expectancy / drawdown (inf without drawdown)
    worst_trade: float


def arm(results: Sequence[float]) -> ArmResult:
    dd = max_drawdown_r(results)
    e = statistics.fmean(results)
    return ArmResult(len(results), e, dd, e / dd if dd > 0 else math.inf, min(results))


def placebo_p(results: Sequence[float], weights: Sequence[float], target_dd: float,
              runs: int = PLACEBO_RUNS, seed: int = SEED) -> float:
    """Share of random weight orders whose drawdown is <= the GARCH drawdown (with the +1 correction)."""
    rng = random.Random(seed)
    pool = list(weights)
    hits = 0
    for _ in range(runs):
        rng.shuffle(pool)
        if max_drawdown_r(weighted(results, pool)) <= target_dd + 1e-12:
            hits += 1
    return (hits + 1) / (runs + 1)


def section_result(trades: Sequence[WTrade]) -> dict:
    ordered = _ordered(trades)
    plain = [t.r for t in ordered]
    weights = [t.w for t in ordered]
    garch = weighted(plain, weights)
    fixed_arm, garch_arm = arm(plain), arm(garch)
    stress_plain = [t.r - t.cost_r for t in ordered]  # fees doubled (slippage stays inside the fills), report only
    return {
        "fixed": asdict(fixed_arm),
        "garch": asdict(garch_arm),
        "placebo_p": placebo_p(plain, weights, garch_arm.drawdown),
        "stress": {"fixed": asdict(arm(stress_plain)), "garch": asdict(arm(weighted(stress_plain, weights)))},
        "weights": {
            "mean": statistics.fmean(weights),
            "at_min": sum(1 for w in weights if w <= W_MIN),
            "at_max": sum(1 for w in weights if w >= W_MAX),
            "corr_w_r": _corr(weights, plain),
        },
    }


def _corr(x: Sequence[float], y: Sequence[float]) -> float | None:
    try:
        return statistics.correlation(x, y)
    except statistics.StatisticsError:
        return None


def verdict(train: Mapping, validation: Mapping, validation_n: int) -> dict:
    if validation_n < MIN_VALIDATION_TRADES:
        return {"verdict": "KEIN URTEIL", "reason": f"{validation_n} < {MIN_VALIDATION_TRADES} Validierungs-Trades"}
    v_f, v_g = validation["fixed"], validation["garch"]
    checks = {
        "dd_10pct_lower": v_g["drawdown"] <= DD_FACTOR * v_f["drawdown"],
        "placebo": validation["placebo_p"] <= P_MAX,
        "r_per_risk_not_worse": v_g["r_per_risk"] >= v_f["r_per_risk"],
        "train_same_direction": train["garch"]["drawdown"] < train["fixed"]["drawdown"],
    }
    return {"verdict": "BESTANDEN" if all(checks.values()) else "NICHT BESTANDEN", "checks": checks}


# ---------------------------------------------------------------- CLI (Mac, lab data)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def load_sigmas(root: Path) -> tuple[dict[str, SigmaSeries], str]:
    from src.research_lab.data.archive import ArchiveRef, Dataset, Market
    from src.research_lab.data.store import ArchiveStore, months

    store = ArchiveStore(root)
    refs = {s: [ArchiveRef(Market.USDM, Dataset.KLINES, y, m, "5m", s) for y, m in months(first, LAST)]
            for s, first in SYMBOLS.items()}
    out = {}
    for symbol, symbol_refs in refs.items():
        bars = [b for b in store.load_klines(symbol_refs) if b.open_time < HOLDOUT_START_MS]
        out[symbol] = sigma_series(s15.periods(bars, HORIZON))
        del bars
    return out, store.dataset_hash([r for rs in refs.values() for r in rs])


def _header(trades_path: Path, dataset_hash: str) -> dict:
    return {"study": "S25", "commit": _commit(), "created": datetime.now(UTC).isoformat(timespec="seconds"),
            "trades_file": trades_path.name, "trades_sha256": _sha256(trades_path), "dataset_hash": dataset_hash,
            "variant": VARIANT, "reported": list(REPORTED), "ref_days": REF_DAYS, "ref_min_days": REF_MIN_DAYS,
            "w_bounds": [W_MIN, W_MAX], "frozen": FROZEN}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.research_lab.studies.s25")
    parser.add_argument("command", choices=("count", "run"))
    parser.add_argument("--trades", type=Path, required=True, help="S7b-Tradeliste (JSON)")
    parser.add_argument("--root", type=Path, default=Path("data/research_lab"), help="Labor-Datenspeicher (5m-Klines)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    trades = json.loads(args.trades.read_text())
    if args.command == "run":
        if not FROZEN:
            print("S25 ist nicht eingefroren: run ist gesperrt (erst Zähllauf, dann 1.0 auf Uzis Wort).", file=sys.stderr)
            return 2
        if _sha256(args.trades) != FROZEN_TRADES_SHA256:
            print("Tradeliste hat nicht den eingefrorenen Hash.", file=sys.stderr)
            return 2
    sigmas, dataset_hash = load_sigmas(args.root)
    payload = _header(args.trades, dataset_hash)
    if args.command == "count":
        payload["count"] = count_rows(trades, sigmas)
        payload["gate"] = {"min_validation_with_weight": MIN_VALIDATION_TRADES,
                           "passes": payload["count"][VARIANT]["validation"]["with_weight"] >= MIN_VALIDATION_TRADES}
    else:
        payload["results"] = {}
        for variant in (VARIANT, *REPORTED):
            sections = {}
            for section in SECTIONS:
                weighted_trades, missing = attach(select(trades, variant, section), sigmas)
                sections[section] = {"missing": missing, **section_result(weighted_trades)}
            n_val = sections["validation"]["garch"]["n"]
            sections["verdict"] = verdict(sections["train"], sections["validation"], n_val)
            payload["results"][variant] = sections
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%MZ")
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"s25_{args.command}_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
