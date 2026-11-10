"""The OFX search loop (P1-P3): engine configurations on training 2020-2023, many filters per run, sieve,
then neighbours and the random comparator for the survivors. Resumable, stops on a STOP file.

Files in ``out``:
* ``state.json``        configurations tried so far (the Bonferroni count) and the seed
* ``konfigurationen.jsonl``  one line per configuration: values, trades, filters tried, best filters
* ``kandidaten.jsonl``  every filter that passed the basic sieve, with neighbours and random p
* ``STOP``              create it to end the loop after the current configuration
"""
from __future__ import annotations

import functools
import hashlib
import json
import random
import time
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from pathlib import Path

from src.research_lab.of2.backtest import Trade
from src.research_lab.of2.config import Config
from src.research_lab.of2.engine import _ms, section_trades
from src.research_lab.ofx.sieve import (
    DEFAULT_RULES,
    Rules,
    apply_filter,
    basic_pass,
    metrics,
    neighbours_pass,
)
from src.research_lab.ofx.space import (
    BASE_CONFIG,
    TradeFilter,
    base_values,
    engine_config,
    neighbours,
    sample_engine,
    sample_filter,
)
from src.research_lab.ofx.trend import Trend

EngineRun = Callable[[dict], list[Trade]]
RandomP = Callable[[Sequence[Trade], Config], float]
LEAD_DAYS = 25


def training_bounds(cfg: Config = BASE_CONFIG) -> tuple[date, date]:
    return date.fromisoformat(cfg.first_day), date.fromisoformat(cfg.training_end)


def values_key(values: dict) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()[:16]


def store_engine_run(root: str, workers: int) -> EngineRun:
    """Engine run on the S8 store (training only; the plain store refuses every holdout day)."""
    from src.research_lab.of2.__main__ import _store_loader_for
    from src.research_lab.of2.parallel import run_days_parallel

    def run(values: dict) -> list[Trade]:
        cfg = engine_config(values)
        first, last = training_bounds(cfg)
        lead = first - timedelta(days=LEAD_DAYS)
        days = [lead + timedelta(days=i) for i in range((last - lead).days + 1)]
        from src.research_lab.orderflow_ml.store import MinuteBarStore
        present = MinuteBarStore(root).present_days()
        days = [d for d in days if d >= min(present)] if present else days
        trades, _ = run_days_parallel(functools.partial(_store_loader_for, root), days, cfg, workers=workers)
        inside, _ = section_trades(trades, _ms(first), _ms(last) + 86_400_000)
        return inside
    return run


def store_random_p(root: str, workers: int, draws: int = 1000) -> RandomP:
    from src.research_lab.of2.__main__ import _store_loader_for
    from src.research_lab.of2.compare import (
        p_value,
        random_signals,
        run_random_parallel,
        strategy_means,
    )

    def rp(trades: Sequence[Trade], cfg: Config, allowed: Callable[[int, int], bool] | None = None) -> float:
        first, last = training_bounds(cfg)
        pseudo = random_signals(trades, first, last, cfg, draws, cfg.seed, allowed)
        rand = run_random_parallel(functools.partial(_store_loader_for, root), first, last, pseudo, cfg, workers=workers)
        real = sum(t.net_r for t in trades) / len(trades)
        return p_value(real, list(strategy_means(rand).values()))
    return rp


def _append(path: Path, row: dict) -> None:
    with path.open("a") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def run_loop(out: Path, run_engine: EngineRun, random_p: RandomP, *, configs: int, filters_per_config: int = 300,
             seed: int = 2026_11_10, rules: Rules = DEFAULT_RULES, max_stage2: int = 3, log: Callable[[str], None] = print,
             trend: Trend | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    state_path = out / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {"configs_tried": 0, "seed": seed, "kandidaten": 0}
    if state["seed"] != seed:
        raise SystemExit("seed differs from the running search; use a new output directory")
    cache: dict[str, list[Trade]] = {}

    def trades_for(values: dict) -> list[Trade]:
        key = values_key(values)
        if key not in cache:
            if len(cache) > 64:
                cache.clear()
            cache[key] = run_engine(values)
        return cache[key]

    for _ in range(configs):
        if (out / "STOP").exists():
            log("STOP-Datei gefunden, Ende")
            break
        k = state["configs_tried"]
        rng = random.Random(f"{seed}-{k}")
        values = base_values() if k == 0 else sample_engine(rng)
        t0 = time.time()
        trades = trades_for(values)
        state["configs_tried"] = k + 1
        filters = [TradeFilter()] + [sample_filter(rng, trend=trend is not None) for _ in range(filters_per_config - 1)]
        rows = []
        for f in filters:
            m = metrics(apply_filter(trades, f, trend))
            ok, why = basic_pass(m, state["configs_tried"], rules)
            rows.append((ok, m, f, why))
        best = sorted(rows, key=lambda r: r[1]["t"], reverse=True)[:5]
        passed = [r for r in rows if r[0]]
        _append(out / "konfigurationen.jsonl", {
            "nr": k, "werte": values, "schluessel": values_key(values), "trades_of": sum(1 for t in trades if t.signal.confirmed),
            "filter": len(filters), "bestanden": len(passed), "sek": round(time.time() - t0, 1),
            "beste": [{"filter": r[2].key(), **{x: r[1][x] for x in ("n", "mean", "t", "sum", "max_dd")}, "gruende": r[3]}
                      for r in best]})
        for ok, m, f, _ in sorted(passed, key=lambda r: r[1]["t"], reverse=True)[:max_stage2]:
            means = [metrics(apply_filter(trades_for(v), f, trend))["mean"] for v in neighbours(values)]
            stable = neighbours_pass(m["mean"], means, rules)
            p = None
            if stable:
                kept, cfg = apply_filter(trades, f, trend), engine_config(values)
                rules_d = [(frame, mode) for frame, mode in f.trends if mode is not None]
                if rules_d and trend is not None:
                    # random entries obey the same direction rule (else the market's drift would count as edge)
                    def allowed(ms: int, direction: int, tr: Trend = trend, rs: list = rules_d) -> bool:
                        return all(tr.allows(ms, direction, frame, mode) for frame, mode in rs)
                    p = random_p(kept, cfg, allowed=allowed)  # type: ignore[call-arg]
                else:
                    p = random_p(kept, cfg)
            status = "KANDIDAT" if stable and p is not None and p <= rules.random_p else "SIEB_2_NICHT"
            state["kandidaten"] += status == "KANDIDAT"
            _append(out / "kandidaten.jsonl", {"nr": k, "werte": values, "filter": f.key(), "metriken": m,
                                               "nachbarn_mittel": means, "nachbarn_ok": stable, "zufall_p": p,
                                               "configs_tried": state["configs_tried"], "status": status})
            log(f"Konfiguration {k}: {status} n={m['n']} mittel={m['mean']} t={m['t']} p={p}")
        tmp = out / "state.json.tmp"
        tmp.write_text(json.dumps(state, indent=1))
        tmp.replace(state_path)
        log(f"Konfiguration {k}: {len(trades)} Trades, {len(passed)}/{len(filters)} Filter im Sieb, {time.time() - t0:.1f}s")
    return state
