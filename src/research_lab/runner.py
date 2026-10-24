"""R4/R5 runner: all registered variants on training and validation data (protocol section 8, steps 1 to 3).

Holdout data is never loaded here. Each variant runs once, continuously from its
data start to the holdout boundary; a trade belongs to the period in which its
signal fired.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.research_lab.backtest.engine import Trade, run_backtest
from src.research_lab.backtest.funding import with_pre_perp_proxy
from src.research_lab.backtest.metrics import Summary, summarize
from src.research_lab.data.archive import ArchiveRef, Dataset, Market
from src.research_lab.data.parse import FundingRate, Kline
from src.research_lab.data.store import ArchiveStore, months
from src.research_lab.hypotheses.registry import VARIANTS, VariantSpec
from src.research_lab.protocol import (
    BASE_COSTS,
    HOLDOUT_START_MS,
    MAX_DRAWDOWN_LIMIT,
    MIN_TRADES_TRAIN,
    PROTOCOL_VERSION,
    STRESS_COSTS,
    VALIDATION_START_MS,
    _utc_ms,
)
from src.research_lab.stats.inference import neighbours_positive, walk_forward, walk_forward_windows, year_stability
from src.research_lab.stats.random_entry import atr_at_signal, atr_series, random_entry_pvalue
from src.research_lab.stats.snooping import REPS as SNOOPING_REPS
from src.research_lab.stats.snooping import period_report
from src.research_lab.stats.register import HypothesisRegister

# Data windows (protocol 3.1/3.2). Spot loads the partial first month 2017-08 for
# indicator warm-up. The USD-M monthly archive starts with 2020-01 (probe 2026-09-29:
# 2019-09 to 2019-12 return 404); strategies wait for their own warm-up there.
SPOT_LOAD = (2017, 8)
SPOT_SIGNALS_MS = _utc_ms(2017, 9, 1)
USDM_LOAD = (2020, 1)
USDM_SIGNALS_MS = _utc_ms(2020, 1, 1)
LAST_MONTH = (2024, 12)


@dataclass(slots=True)
class PeriodResult:
    summary: Summary
    p: float | None = None
    time_in_market: float = 0.0


@dataclass(slots=True)
class VariantResult:
    variant_id: str
    hypothesis: str
    horizon: str
    params: dict
    train: PeriodResult
    validation: PeriodResult
    stress_train: Summary
    stress_validation: Summary
    year_stable: bool = False
    neighbours_ok: bool = False
    walk_forward_mean: float | None = None
    verdict: str = ""
    reasons: list[str] = field(default_factory=list)


def signal_start(spec: VariantSpec) -> int:
    return SPOT_SIGNALS_MS if spec.market is Market.SPOT else USDM_SIGNALS_MS


def data_refs(spec: VariantSpec) -> list[ArchiveRef]:
    start = SPOT_LOAD if spec.market is Market.SPOT else USDM_LOAD
    return [ArchiveRef(spec.market, Dataset.KLINES, y, m, spec.interval) for y, m in months(start, LAST_MONTH)]


def funding_refs() -> list[ArchiveRef]:
    return [ArchiveRef(Market.USDM, Dataset.FUNDING, y, m) for y, m in months(USDM_LOAD, LAST_MONTH)]


def all_refs(specs: Sequence[VariantSpec] = VARIANTS) -> list[ArchiveRef]:
    refs = {ref.local_path: ref for spec in specs for ref in data_refs(spec)}
    refs.update({ref.local_path: ref for ref in funding_refs()})
    return list(refs.values())


def _split(trades: Sequence[Trade], start: int, end: int) -> list[Trade]:
    return [t for t in trades if start <= t.signal_time < end]


def _time_in_market(trades: Sequence[Trade], start: int, end: int, interval_ms: int) -> float:
    bars = (end - start) // interval_ms
    return sum(t.bars_held for t in trades) / bars if bars else 0.0


@dataclass(frozen=True, slots=True)
class RunConfig:
    random_runs: int = 10_000
    seed: int = 20260929
    snooping_reps: int = SNOOPING_REPS  # 0 skips the additional SPA/StepM evaluation


def evaluate_variant(spec: VariantSpec, bars: Sequence[Kline], funding: Sequence[FundingRate], config: RunConfig,
                     atr_values: Sequence[float | None] | None = None) -> tuple[VariantResult, list[Trade]]:
    start = signal_start(spec)
    bars = [b for b in bars if b.open_time < HOLDOUT_START_MS]
    engine_funding = with_pre_perp_proxy(funding, bars[0].open_time) if spec.market is Market.SPOT else list(funding)
    stress_funding = with_pre_perp_proxy(funding, bars[0].open_time, stressed=True) if spec.market is Market.SPOT else list(funding)
    base = run_backtest(bars, spec.build(funding), spec.interval_ms, costs=BASE_COSTS, funding=engine_funding,
                        start_ms=start, end_ms=HOLDOUT_START_MS, atr_at_signal=atr_at_signal)
    stress = run_backtest(bars, spec.build(funding), spec.interval_ms, costs=STRESS_COSTS, funding=stress_funding,
                          start_ms=start, end_ms=HOLDOUT_START_MS, atr_at_signal=atr_at_signal)
    atr_values = atr_series(bars) if atr_values is None else atr_values
    periods = {"train": (start, VALIDATION_START_MS), "validation": (VALIDATION_START_MS, HOLDOUT_START_MS)}
    minimum = MIN_TRADES_TRAIN[spec.horizon]
    results = {}
    for offset, (name, (lo, hi)) in enumerate(periods.items()):
        trades = _split(base.trades, lo, hi)
        summary = summarize(trades)
        need = minimum if name == "train" else minimum / 2
        p = None
        if summary.expectancy_r > 0 and summary.trades >= need:
            p = random_entry_pvalue(bars, trades, spec.interval_ms, runs=config.random_runs, seed=config.seed + offset,
                                    costs=BASE_COSTS, funding=engine_funding, start_ms=lo, end_ms=hi, atr_values=atr_values)
        results[name] = PeriodResult(summary, p, _time_in_market(trades, lo, hi, spec.interval_ms))
    result = VariantResult(
        spec.variant_id, spec.hypothesis, spec.horizon, dict(spec.params), results["train"], results["validation"],
        summarize(_split(stress.trades, *periods["train"])), summarize(_split(stress.trades, *periods["validation"])),
    )
    return result, base.trades


def decide(results: dict[str, VariantResult], trades: dict[str, list[Trade]], specs: Sequence[VariantSpec]) -> list[str]:
    """Apply section 8 steps 1-3 and 7.3. Returns the frozen candidate list."""
    by_hypothesis: dict[str, list[VariantSpec]] = {}
    for spec in specs:
        by_hypothesis.setdefault(spec.hypothesis, []).append(spec)
    walk: dict[str, float] = {}
    for hypothesis, members in by_hypothesis.items():
        start = min(signal_start(spec) for spec in members)
        windows = walk_forward_windows(start, HOLDOUT_START_MS)
        mean, _ = walk_forward({spec.variant_id: trades[spec.variant_id] for spec in members}, windows)
        walk[hypothesis] = mean
    scores: dict[str, float] = {}
    for spec in specs:
        result = results[spec.variant_id]
        result.walk_forward_mean = walk[spec.hypothesis]
        combined = summarize(_split(trades[spec.variant_id], signal_start(spec), HOLDOUT_START_MS))
        result.year_stable = year_stability(combined.expectancy_by_year)
        result.neighbours_ok = _neighbours(spec, results, by_hypothesis[spec.hypothesis])
        train, validation, minimum = result.train, result.validation, MIN_TRADES_TRAIN[spec.horizon]
        checks = [
            (train.summary.trades >= minimum, f"Training: {train.summary.trades} < {minimum} Trades"),
            (train.summary.expectancy_r > 0, "Training: Erwartungswert <= 0"),
            (train.p is not None and train.p < 0.10, "Training: p >= 0,10 gegen Zufall"),
        ]
        failed = [reason for ok, reason in checks if not ok]
        if failed:
            result.verdict, result.reasons = "failed_train", failed
            continue
        checks = [
            (validation.summary.trades >= minimum / 2, f"Validierung: weniger als {minimum / 2:.0f} Trades"),
            (validation.summary.expectancy_r > 0, "Validierung: Erwartungswert <= 0"),
            (validation.p is not None and validation.p < 0.05, "Validierung: p >= 0,05 gegen Zufall"),
            (validation.summary.profit_factor > 1.1, "Validierung: Profitfaktor <= 1,1"),
            (validation.summary.max_drawdown_pct <= MAX_DRAWDOWN_LIMIT, "Validierung: Drawdown > 20 %"),
            (result.year_stable, "Jahresstabilität verfehlt"),
            (walk[spec.hypothesis] > 0, "Walk-Forward der Hypothese <= 0"),
            (result.neighbours_ok, "Nachbarn im Raster nicht positiv"),
        ]
        failed = [reason for ok, reason in checks if not ok]
        if failed:
            result.verdict, result.reasons = "failed_validation", failed
            continue
        scores[spec.variant_id] = validation.summary.expectancy_r
    candidates: list[str] = []
    for members in by_hypothesis.values():
        ranked = sorted((s.variant_id for s in members if s.variant_id in scores), key=lambda v: (-scores[v], v))
        for rank, variant in enumerate(ranked):
            if rank < 2:
                results[variant].verdict = "candidate"
                candidates.append(variant)
            else:
                results[variant].verdict, results[variant].reasons = "not_selected", ["mehr als zwei Kandidaten je Hypothese"]
    return candidates


def _neighbours(spec: VariantSpec, results: dict[str, VariantResult], members: Sequence[VariantSpec]) -> bool:
    if not spec.grid_axes:
        return True
    categorical = {k: v for k, v in spec.params.items() if k not in spec.grid_axes}
    same = [m for m in members if {k: v for k, v in m.params.items() if k not in m.grid_axes} == categorical]
    grid = {axis: sorted({m.params[axis] for m in same}) for axis in spec.grid_axes}
    expectancy = {tuple(m.params[a] for a in spec.grid_axes): results[m.variant_id].train.summary.expectancy_r for m in same}
    return neighbours_positive(grid, expectancy, tuple(spec.params[a] for a in spec.grid_axes))


def snooping(trades: dict[str, list[Trade]], specs: Sequence[VariantSpec], config: RunConfig) -> dict:
    """Additional SPA/StepM evaluation per period (report only, never a verdict).

    Training uses the window all variants share (from the latest data start).
    """
    if config.snooping_reps < 1 or not specs:
        return {}
    shared = {spec.variant_id: trades[spec.variant_id] for spec in specs}
    windows = {"train": (max(signal_start(spec) for spec in specs), VALIDATION_START_MS),
               "validation": (VALIDATION_START_MS, HOLDOUT_START_MS)}
    out = {}
    for offset, (name, (lo, hi)) in enumerate(windows.items()):
        block = period_report(shared, lo, hi, seed=config.seed + 100 + offset, reps=config.snooping_reps)
        if block is not None:
            out[name] = block
    return out


def buy_and_hold(bars: Sequence[Kline], start: int, end: int) -> float | None:
    inside = [b for b in bars if start <= b.open_time < end]
    return inside[-1].close / inside[0].open - 1 if inside else None


def run(store: ArchiveStore, *, specs: Sequence[VariantSpec] = VARIANTS, config: RunConfig = RunConfig(),
        progress: Callable[[str], None] = print) -> tuple[dict[str, VariantResult], list[str], dict]:
    funding = store.load_funding(funding_refs())
    results: dict[str, VariantResult] = {}
    trades: dict[str, list[Trade]] = {}
    cache: dict[tuple, tuple[list[Kline], list]] = {}
    context: dict = {"dataset_hashes": {}, "buy_and_hold": {}}
    for spec in specs:
        key = (spec.market, spec.interval)
        if key not in cache:
            refs = data_refs(spec)
            bars = [b for b in store.load_klines(refs) if b.open_time < HOLDOUT_START_MS]
            cache[key] = (bars, atr_series(bars))
            context["dataset_hashes"][f"{spec.market.value}/{spec.interval}"] = store.dataset_hash(refs)
            if spec.market is Market.SPOT:
                context["buy_and_hold"] = {
                    "train": buy_and_hold(bars, SPOT_SIGNALS_MS, VALIDATION_START_MS),
                    "validation": buy_and_hold(bars, VALIDATION_START_MS, HOLDOUT_START_MS),
                }
        bars, atr_values = cache[key]
        progress(f"{spec.variant_id}: {len(bars)} Kerzen")
        results[spec.variant_id], trades[spec.variant_id] = evaluate_variant(spec, bars, funding, config, atr_values)
    context["dataset_hashes"]["funding"] = store.dataset_hash(funding_refs())
    candidates = decide(results, trades, specs)
    context["snooping"] = snooping(trades, specs, config)
    return results, candidates, context


def ensure_registered(register: HypothesisRegister, specs: Sequence[VariantSpec] = VARIANTS) -> None:
    known = register.variants()
    for spec in specs:
        if spec.variant_id not in known:
            register.register(spec.variant_id, spec.hypothesis, {k: v for k, v in spec.params.items()})


def commit_statuses(register: HypothesisRegister, results: dict[str, VariantResult]) -> None:
    for variant_id, result in results.items():
        register.set_status(variant_id, result.verdict, "; ".join(result.reasons))


def _fmt(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "–"
    if value == float("inf"):
        return "∞"
    return f"{value:.{digits}f}".replace(".", ",")


def snooping_lines(blocks: dict) -> list[str]:
    if not blocks:
        return []
    first = next(iter(blocks.values()))
    lines = ["", "## Zusatz: Glückstest über alle Varianten (SPA/StepM)", "",
             f"{first['note']}. Frage: Schlägt die beste Variante 0 R pro Tag, oder ist sie nur die glücklichste? "
             f"Stationärer Bootstrap, Blocklänge {_fmt(first['block_days'], 0)} Tage, {first['reps']} Ziehungen, studentisiert.", "",
             "| Abschnitt | Tage | Varianten | beste Variante | E[R]/Tag | SPA p (unten/konsistent/oben) | StepM überlegen (α = 5 %) |",
             "|---|---|---|---|---|---|---|"]
    for name, b in blocks.items():
        p = b["spa_p"]
        lines.append(f"| {name} {b['start']}–{b['end']} | {b['days']} | {b['variants']} | {b['best']} | {_fmt(b['best_mean_r_per_day'], 4)} "
                     f"| {_fmt(p['lower'], 4)}/{_fmt(p['consistent'], 4)}/{_fmt(p['upper'], 4)} "
                     f"| {', '.join(b['stepm_superior']) or 'keine'} |")
    return lines


def write_report(out_dir: Path, results: dict[str, VariantResult], candidates: list[str], context: dict,
                 config: RunConfig, register_m: int, commit: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "protocol": PROTOCOL_VERSION, "commit": commit, "created": stamp, "random_runs": config.random_runs,
        "seed": config.seed, "register_m": register_m, "candidates": candidates, **context,
        "variants": {k: asdict(v) for k, v in results.items()},
    }
    (out_dir / f"r4_{stamp}.json").write_text(json.dumps(payload, indent=2, default=str, ensure_ascii=False) + "\n")
    lines = [
        f"# Research Lab R4/R5 – Training und Validierung ({stamp})",
        "",
        f"Protokoll {PROTOCOL_VERSION}, Commit `{commit}`, {config.random_runs} Zufallsläufe, Seed {config.seed}, "
        f"Register m = {register_m}. Holdout nicht geladen.",
        "",
        f"**Kandidaten für den Holdout:** {', '.join(candidates) if candidates else 'keine – kein Vorteil in Training/Validierung gefunden'}",
        "",
        "| Variante | Trades T/V | E[R] T | E[R] V | E[R] Stress T/V | p T | p V | PF V | DD V | Urteil |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results.values():
        lines.append(
            f"| {r.variant_id} | {r.train.summary.trades}/{r.validation.summary.trades} | {_fmt(r.train.summary.expectancy_r)} "
            f"| {_fmt(r.validation.summary.expectancy_r)} | {_fmt(r.stress_train.expectancy_r)}/{_fmt(r.stress_validation.expectancy_r)} "
            f"| {_fmt(r.train.p, 4)} | {_fmt(r.validation.p, 4)} | {_fmt(r.validation.summary.profit_factor, 2)} "
            f"| {_fmt(r.validation.summary.max_drawdown_pct * 100, 1)} % | {r.verdict} |"
        )
    lines += ["", "## Gründe", ""]
    lines += [f"- **{r.variant_id}:** {'; '.join(r.reasons)}" for r in results.values() if r.reasons]
    bh = context.get("buy_and_hold") or {}
    if bh:
        lines += ["", f"Kaufen und Halten Spot (Vergleich, kein Kriterium): Training {_fmt((bh.get('train') or 0) * 100, 1)} %, "
                      f"Validierung {_fmt((bh.get('validation') or 0) * 100, 1)} %."]
    lines += snooping_lines(context.get("snooping") or {})
    lines += ["", "Datensatz-Hashes:", ""] + [f"- {k}: `{v}`" for k, v in context.get("dataset_hashes", {}).items()]
    path = out_dir / f"r4_{stamp}.md"
    path.write_text("\n".join(lines) + "\n")
    return path
