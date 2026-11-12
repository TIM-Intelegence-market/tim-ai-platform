"""S31 command line (paper only). Count run first, evaluation second (preregistration 1.0).

    python -m src.research_lab.s31 count --bars <S8 root> --metrics <.../metrics/BTCUSDT/5m> --section training --out count.json
    python -m src.research_lab.s31 run   --bars <S8 root> --metrics <...> --section training --out run.json

``count`` writes signal and trade counts only (no R values). ``run`` writes the full result for the
orderflow rule (``of_gate``) and its price twin (all triggers). The holdout is refused by the S8 store.
"""
from __future__ import annotations

import argparse
import dataclasses
import functools
import json
from datetime import date, timedelta
from pathlib import Path

from src.research_lab.of2.__main__ import LEAD_DAYS, section_bounds, store_loader
from src.research_lab.of2.backtest import summarize
from src.research_lab.of2.config import DEFAULT_CONFIG, Config
from src.research_lab.of2.engine import Engine, _ms, section_trades
from src.research_lab.orderflow_ml.store import MinuteBarStore
from src.research_lab.s31.metrics import Metrics
from src.research_lab.s31.models import b6_divergence, b7_oi_sweep

VERSION = "1.0.0"
MODELS = ("B6", "B7")


def run_pass(bars_root: str, metrics: Metrics, cfg: Config, days: list[date]):
    store = MinuteBarStore(bars_root)
    load = store_loader(store)
    engine = Engine(cfg)
    engine.extra_15m = (functools.partial(b6_divergence, metrics), functools.partial(b7_oi_sweep, metrics))
    trades = []
    for day in days:
        trades.extend(engine.run_day(*load(day)))
    return [t for t in trades if t.signal.model in MODELS], engine


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.research_lab.s31")
    ap.add_argument("cmd", choices=("count", "run"))
    ap.add_argument("--bars", required=True)
    ap.add_argument("--metrics", required=True)
    ap.add_argument("--section", required=True, choices=("training", "validierung"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    base = DEFAULT_CONFIG
    first, last = section_bounds(base, args.section)
    lead = max(first - timedelta(days=LEAD_DAYS), date.fromisoformat(base.first_day) - timedelta(days=LEAD_DAYS))
    present = set(MinuteBarStore(args.bars).present_days())
    days = [lead + timedelta(days=i) for i in range((last - lead).days + 1)]
    days = [d for d in days if d >= min(present)]
    metrics = Metrics.load(args.metrics, first - timedelta(days=2), last)
    out = {"studie": "S31", "version": VERSION, "abschnitt": args.section, "erster_tag": first.isoformat(),
           "letzter_tag": last.isoformat(), "metrics_erster_stand": metrics.times[0] if metrics.times else None,
           "metrics_snapshots": len(metrics.times), "ergebnisse": {}}
    for label, gate in (("OF", True), ("PREIS_ZWILLING_ALLE", False)):
        cfg = dataclasses.replace(base, of_gate=gate)
        trades, engine = run_pass(args.bars, metrics, cfg, days)
        inside, open_end = section_trades(trades, _ms(first), _ms(last) + 86_400_000)
        by_model = {m: [t for t in inside if t.signal.model == m] for m in MODELS}
        block = {"config_digest": cfg.digest(), "n": {m: len(v) for m, v in by_model.items()},
                 "n_je_jahr": {m: {str(y): sum(1 for t in v if date.fromtimestamp(t.signal.signal_ms / 1000).year == y)
                                   for y in range(first.year, last.year + 1)} for m, v in by_model.items()},
                 "offen_am_ende": open_end,
                 "signale": {k: v for k, v in engine.stats.signale.items() if k[:2] in MODELS},
                 "verworfen": {k: v for k, v in engine.stats.verworfen.items() if k[:2] in MODELS}}
        if args.cmd == "run":
            block["zusammenfassung"] = {m: summarize(v, cfg) if v else {"n": 0} for m, v in by_model.items()}
            block["trades"] = [t.as_dict() for t in inside]
        out["ergebnisse"][label] = block
    Path(args.out).write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in out.items() if k != "ergebnisse"}, ensure_ascii=False))
    for label, b in out["ergebnisse"].items():
        print(label, b["n"], b["n_je_jahr"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
