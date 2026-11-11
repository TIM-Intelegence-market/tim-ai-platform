"""Bitunix research CLI (no API key, no orders).

    python -m src.research_lab.bitunix leverage --equity 1000 --risk 0.0025 --stop 0.013
    python -m src.research_lab.bitunix target --win-rate 0.39 --win-r 2.4 --trades-per-day 0.2
    python -m src.research_lab.bitunix record --root ~/TIM-research/bitunix [--symbols BTCUSDT] [--seconds 600]
    python -m src.research_lab.bitunix report --trades docs/research_lab/reports/bitunix/of2_training_of_trades_aa853e1.json --out <file>
    python -m src.research_lab.bitunix gate
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from src.research_lab.bitunix import gate, leverage, recorder, target


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m src.research_lab.bitunix")
    sub = p.add_subparsers(dest="cmd", required=True)
    lv = sub.add_parser("leverage")
    lv.add_argument("--equity", type=float, required=True)
    lv.add_argument("--risk", type=float, default=0.0025)
    lv.add_argument("--stop", type=float, required=True, help="stop distance as fraction of entry")
    tg = sub.add_parser("target")
    tg.add_argument("--win-rate", type=float, required=True)
    tg.add_argument("--win-r", type=float, required=True)
    tg.add_argument("--trades-per-day", type=float, required=True)
    tg.add_argument("--risk", type=float, default=0.0025)
    tg.add_argument("--equity", type=float, action="append")
    rc = sub.add_parser("record")
    rc.add_argument("--root", type=Path, required=True)
    rc.add_argument("--symbols", default="BTCUSDT")
    rc.add_argument("--seconds", type=float)
    rp = sub.add_parser("report")
    rp.add_argument("--trades", type=Path, required=True)
    rp.add_argument("--out", type=Path, required=True)
    sub.add_parser("gate")
    a = p.parse_args(argv)
    if a.cmd == "leverage":
        rows = [s.as_dict() for s in leverage.table(equity=a.equity, risk_fraction=a.risk, stop_distance=a.stop)]
        print(json.dumps(rows, indent=1))
    elif a.cmd == "target":
        edge = target.Edge(win_rate=a.win_rate, win_r=a.win_r, trades_per_day=a.trades_per_day)
        out = {"expectancy_r": edge.expectancy_r, "sd_r": edge.sd_r, "breakeven_win_rate": edge.breakeven_win_rate(),
               "required_equity": target.required_equity(50.0, edge, a.risk), "sims": []}
        for eq in a.equity or [500, 1000, 2500, 5000, 10000, 25000]:
            out["sims"].append(target.simulate(equity=eq, edge=edge, risk_fraction=a.risk).as_dict())
        print(json.dumps(out, indent=1))
    elif a.cmd == "report":
        rep = target.build_report(json.loads(a.trades.read_text()))
        a.out.write_text(json.dumps(rep, indent=1, ensure_ascii=False) + "\n")
        print(rep["verdict"])
    elif a.cmd == "record":
        try:
            counts = asyncio.run(recorder.record(a.root.expanduser(), a.symbols.split(","), stop_after=a.seconds))
        except recorder.StorageError as exc:
            print(json.dumps({"state": "failed", "error": str(exc)}), flush=True)
            return 2
        print(json.dumps(counts))
    else:
        ok, why = gate.authorization_status()
        print(json.dumps({"authorized": ok, "reason": why}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
