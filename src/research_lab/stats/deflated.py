"""Deflated Sharpe Ratio: how much of a Sharpe ratio is left after many trials.

Additional evaluation only, like ``snooping.py``: it never changes a verdict. It answers
"is this Sharpe ratio larger than the best one we would expect by luck after N trials?".

Built from the papers, in plain Python like the rest of the lab:
- Bailey, D. H. and López de Prado, M. (2012). The Sharpe ratio efficient frontier.
  Journal of Risk 15(2). Probabilistic Sharpe Ratio (PSR), eq. for the standard error with
  skewness and kurtosis of the returns.
- Bailey, D. H. and López de Prado, M. (2014). The Deflated Sharpe Ratio. Journal of
  Portfolio Management 40(5). Expected maximum Sharpe ratio of N independent trials (SR0) and
  DSR = PSR(SR0).

All Sharpe ratios here are per observation (per trade or per day), never annualised, so the
caller needs no annualisation factor. ``kurtosis`` is the raw (non-excess) kurtosis, 3 for a
normal distribution, as in the papers.

Choice of the variance of the trial Sharpe ratios (``sr_variance``): the paper uses the variance
of the Sharpe ratios of all trials. TIM does not keep the Sharpe ratio of every trial (filters,
studies outside the register), so ``null_sr_variance`` gives the variance of a Sharpe estimate
under "no trial has an edge", which is about 1/(T-1). A caller that has the Sharpe ratios of the
trials passes ``trial_sr_variance(...)`` instead; the report states which one was used.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import NormalDist

EULER_GAMMA = 0.5772156649015329
NOTE = "Zusatzauswertung, keine Regel: ändert kein Urteil (wie SPA/StepM, PROTOKOLL 2026-10-23)"
_N = NormalDist()


@dataclass(frozen=True, slots=True)
class Moments:
    n: int
    mean: float
    std: float  # population standard deviation, as in the papers
    sharpe: float
    skewness: float
    kurtosis: float  # raw, 3 for a normal distribution


def moments(returns: Sequence[float]) -> Moments:
    values = [float(r) for r in returns]
    if len(values) < 3:
        raise ValueError("at least 3 returns are needed")
    if not all(math.isfinite(v) for v in values):
        raise ValueError("returns must be finite")
    mean = statistics.fmean(values)
    std = statistics.pstdev(values, mu=mean)
    if std <= 0:
        raise ValueError("returns have no variation")
    n = len(values)
    skew = sum(((v - mean) / std) ** 3 for v in values) / n
    kurt = sum(((v - mean) / std) ** 4 for v in values) / n
    return Moments(n, mean, std, mean / std, skew, kurt)


def probabilistic_sharpe(sharpe: float, n: int, skewness: float, kurtosis: float, benchmark: float = 0.0) -> float:
    """P(true Sharpe > benchmark) given the estimate from n observations (PSR)."""
    if n < 2:
        raise ValueError("n must be at least 2")
    denom = 1.0 - skewness * sharpe + (kurtosis - 1.0) / 4.0 * sharpe * sharpe
    if denom <= 0:
        raise ValueError("non-positive variance term; skewness/kurtosis do not fit this Sharpe ratio")
    return _N.cdf((sharpe - benchmark) * math.sqrt(n - 1) / math.sqrt(denom))


def expected_max_sharpe(trials: int, sr_variance: float) -> float:
    """Expected maximum of ``trials`` independent Sharpe estimates with true Sharpe 0 (SR0)."""
    if trials < 1:
        raise ValueError("trials must be at least 1")
    if sr_variance < 0:
        raise ValueError("sr_variance must not be negative")
    if trials == 1:
        return 0.0
    z1 = _N.inv_cdf(1.0 - 1.0 / trials)
    z2 = _N.inv_cdf(1.0 - 1.0 / (trials * math.e))
    return math.sqrt(sr_variance) * ((1.0 - EULER_GAMMA) * z1 + EULER_GAMMA * z2)


def null_sr_variance(n: int) -> float:
    """Variance of a Sharpe estimate from n observations when the true Sharpe is 0 (about 1/(n-1))."""
    if n < 2:
        raise ValueError("n must be at least 2")
    return 1.0 / (n - 1)


def trial_sr_variance(sharpes: Sequence[float]) -> float:
    """Sample variance of the Sharpe ratios of all trials (the paper's choice)."""
    if len(sharpes) < 2:
        raise ValueError("at least 2 trial Sharpe ratios are needed")
    return statistics.variance(sharpes)


@dataclass(frozen=True, slots=True)
class DeflatedResult:
    name: str
    trials: int
    variance_source: str
    sr_variance: float
    moments: Moments
    psr_zero: float  # P(true Sharpe > 0), no correction for trials
    sr0: float  # expected best Sharpe of `trials` trials without edge
    dsr: float  # P(true Sharpe > sr0)
    note: str = NOTE


def deflated_sharpe(returns: Sequence[float], trials: int, *, name: str = "",
                    sr_variance: float | None = None) -> DeflatedResult:
    m = moments(returns)
    source = "trials" if sr_variance is not None else "null"
    variance = sr_variance if sr_variance is not None else null_sr_variance(m.n)
    sr0 = expected_max_sharpe(trials, variance)
    return DeflatedResult(
        name=name,
        trials=trials,
        variance_source=source,
        sr_variance=variance,
        moments=m,
        psr_zero=probabilistic_sharpe(m.sharpe, m.n, m.skewness, m.kurtosis, 0.0),
        sr0=sr0,
        dsr=probabilistic_sharpe(m.sharpe, m.n, m.skewness, m.kurtosis, sr0),
    )


def register_trials(path: Path | str) -> int:
    """Number of variants in REGISTER.jsonl (kind 'register'); the hash chain is checked by HypothesisRegister."""
    from src.research_lab.stats.register import HypothesisRegister

    return HypothesisRegister(path).m


def total_trials(register: int, outside: Mapping[str, int]) -> int:
    """Register variants plus trials outside the register (filters, own families), each counted once."""
    if register < 0 or any(v < 0 for v in outside.values()):
        raise ValueError("trial counts must not be negative")
    return register + sum(outside.values())


def _load_returns(path: Path) -> dict[str, list[float]]:
    """JSON: either {"name": [r, ...], ...} or a list of trades with field "r"."""
    data = json.loads(path.read_text())
    if isinstance(data, Mapping):
        return {str(k): [float(x) for x in v] for k, v in data.items()}
    if isinstance(data, list):
        return {path.stem: [float(t["r"]) if isinstance(t, Mapping) else float(t) for t in data]}
    raise ValueError("unsupported JSON layout")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.research_lab.stats.deflated",
                                     description="Deflated Sharpe Ratio for net R per trade (Zusatzauswertung).")
    parser.add_argument("returns", type=Path, help="JSON mit Netto-R je Trade (Liste oder {Name: Liste})")
    parser.add_argument("--trials", type=int, help="Zahl aller Versuche; ohne Angabe Register + --outside")
    parser.add_argument("--register", type=Path, default=Path("docs/research_lab/REGISTER.jsonl"))
    parser.add_argument("--outside", type=int, default=0, help="Versuche außerhalb des Registers")
    args = parser.parse_args(argv)
    trials = args.trials if args.trials is not None else total_trials(register_trials(args.register), {"outside": args.outside})
    out = []
    for name, series in _load_returns(args.returns).items():
        out.append(asdict(deflated_sharpe(series, trials, name=name)))
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
