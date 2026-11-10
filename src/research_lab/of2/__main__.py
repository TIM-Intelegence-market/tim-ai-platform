"""OF2 command line (paper only; the holdout is refused by the S8 store).

    python -m src.research_lab.of2 run    --bars <orderflow_ml root> --section training   --out training.json [--workers 16]
    python -m src.research_lab.of2 run    --bars <root> --section validierung --out validierung.json
    python -m src.research_lab.of2 random --bars <root> --section training --trades training.json --draws 1000 --out random_training.json [--workers 16]

``run`` streams the section's days plus ``npoc_days + ib_history`` lead days (lead days feed levels only; their
trades are dropped). ``random`` builds the random comparator from a finished run. Every file carries the
config digest; a run with another config refuses to be compared.
"""
from __future__ import annotations

import argparse
import functools
import json
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

from src.research_lab.of2.backtest import summarize
from src.research_lab.of2.compare import (
    p_value,
    random_signals,
    run_random_parallel,
    strategy_means,
)
from src.research_lab.of2.config import DEFAULT_CONFIG, VERSION, Config
from src.research_lab.of2.engine import _ms, funnel, section_trades
from src.research_lab.of2.parallel import run_days_parallel
from src.research_lab.orderflow_ml.store import MinuteBarStore

LEAD_DAYS = 25  # >= npoc_days + 1 and enough sessions for the IB history (20 sessions per name = 20 days)


def section_bounds(cfg: Config, section: str) -> tuple[date, date]:
    first, train_end, last = date.fromisoformat(cfg.first_day), date.fromisoformat(cfg.training_end), date.fromisoformat(cfg.last_day)
    if section == "training":
        return first, train_end
    if section == "validierung":
        return train_end + timedelta(days=1), last
    raise ValueError("section must be training or validierung")


def store_loader(store: MinuteBarStore):
    def load(day: date):
        return store.load(day), store.load_profile(day)
    return load


def _store_loader_for(root: str):
    """Picklable loader factory for the worker processes of ``random --workers``."""
    return store_loader(MinuteBarStore(root))


def cmd_run(args: argparse.Namespace, cfg: Config) -> dict:
    first, last = section_bounds(cfg, args.section)
    store = MinuteBarStore(args.bars)
    lead = max(first - timedelta(days=LEAD_DAYS), date.fromisoformat(cfg.first_day) - timedelta(days=LEAD_DAYS))
    days = [lead + timedelta(days=i) for i in range((last - lead).days + 1)]
    present = set(store.present_days())
    days = [d for d in days if d >= min(present)] if present else days
    trades, engine = run_days_parallel(functools.partial(_store_loader_for, args.bars), days, cfg,
                                       workers=args.workers)
    inside, open_at_end = section_trades(trades, _ms(first), _ms(last) + 86_400_000)
    return {
        "studie": "OF2", "version": VERSION, "config_digest": cfg.digest(), "config": cfg.as_dict(),
        "abschnitt": args.section, "erster_tag": first.isoformat(), "letzter_tag": last.isoformat(),
        "datensatz_hash": store.dataset_hash([d for d in days if d >= first]),
        "tage": engine.stats.tage, "tage_ohne_level": engine.stats.tage_ohne_level,
        "signale": engine.stats.signale, "verworfen": engine.stats.verworfen,
        "trichter": funnel(engine.stats.trichter, inside),
        "abgelaufen": engine.tracker.expired, "storniert": engine.tracker.cancelled, "offen_am_ende": open_at_end,
        "zusammenfassung": summarize(inside, cfg),
        "zusammenfassung_nur_of": summarize([t for t in inside if t.signal.confirmed], cfg),
        "trades": [t.as_dict() for t in inside],
    }


def cmd_random(args: argparse.Namespace, cfg: Config) -> dict:
    run = json.loads(Path(args.trades).read_text())
    if run["config_digest"] != cfg.digest():
        raise SystemExit("config digest of the run differs from this code")
    first, last = section_bounds(cfg, args.section)
    # rebuild lightweight Trade objects (only the fields the comparator needs)
    from src.research_lab.of2.backtest import Trade
    from src.research_lab.of2.models import MARKET, Signal
    real = []
    for row in run["trades"]:
        s = Signal(row["model"], row["direction"], row["signal_ms"], MARKET, None, row["signal_ms"], row["stop"], row["target"],
                   row["level"], row["level_price"], row["confirmed"], row["session"], row["regime"], tf=row.get("tf", 30))
        real.append(Trade(s, row["fill_ms"], row["entry"], row["exit_ms"], row["exit"], row["reason"], row["gross_r"],
                          row["fee_r"], row["slippage_r"], row["mfe_r"], row["mae_r"]))
    out = {"studie": "OF2", "version": VERSION, "config_digest": cfg.digest(), "abschnitt": args.section, "draws": args.draws,
           "seed": cfg.seed, "vergleiche": {}}
    for label, subset in (("OF", [t for t in real if t.signal.confirmed]), ("ALLE", real)):
        if not subset:
            out["vergleiche"][label] = {"n": 0}
            continue
        pseudo = random_signals(subset, first, last, cfg, args.draws, cfg.seed)
        rand = run_random_parallel(functools.partial(_store_loader_for, args.bars), first, last, pseudo, cfg,
                                   workers=args.workers)
        means = list(strategy_means(rand).values())
        real_mean = sum(t.net_r for t in subset) / len(subset)
        out["vergleiche"][label] = {"n": len(subset), "echt_netto_r_mittel": round(real_mean, 4),
                                    "zufall_mittel": round(sum(means) / len(means), 4) if means else None,
                                    "p": round(p_value(real_mean, means), 4), "strategien": len(means)}
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.research_lab.of2")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--bars", required=True)
    run.add_argument("--section", required=True, choices=("training", "validierung"))
    run.add_argument("--out", required=True)
    run.add_argument("--workers", type=int, default=1, help="processes, split by time (same result)")
    rnd = sub.add_parser("random")
    rnd.add_argument("--bars", required=True)
    rnd.add_argument("--section", required=True, choices=("training", "validierung"))
    rnd.add_argument("--trades", required=True)
    rnd.add_argument("--draws", type=int, default=1000)
    rnd.add_argument("--out", required=True)
    rnd.add_argument("--workers", type=int, default=1, help="processes for the random comparator (same result)")
    args = parser.parse_args(argv)
    cfg = DEFAULT_CONFIG
    result = cmd_run(args, cfg) if args.cmd == "run" else cmd_random(args, cfg)
    Path(args.out).write_text(json.dumps(result, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in result.items() if k not in ("trades", "config")}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
