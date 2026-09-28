#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from datetime import datetime, timezone
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.paper.automation import PaperPolicy
from src.paper.demo_trader_v1 import DemoTrader, DemoPortfolio

def main():
    p = argparse.ArgumentParser(description="Demo-Trader Bilanz export (TEST_ONLY)")
    p.add_argument("--date", default=datetime.now(timezone.utc).date().isoformat())
    p.add_argument("--starting-balance", type=float, default=100.0)
    args = p.parse_args()
    policy = PaperPolicy(policy_id="demo_v1", enabled=True, test_only=True)
    portfolio = DemoPortfolio(starting_balance=args.starting_balance)
    trader = DemoTrader(policy, portfolio)
    # Beispiel: Falls Journal existiert, lade letzte Bilanz
    journal = Path("data/paper/demo_journal.jsonl")
    if journal.exists():
        # zähle Trades
        lines = journal.read_text().strip().splitlines() if journal.stat().st_size else []
        print(f"Journal: {len(lines)} Demo-Trades vorhanden")
    out = trader.export_bilanz(Path(f"data/paper/demo_bilanz_{args.date}.json"))
    # auch CSV
    csv = Path(f"data/paper/demo_bilanz_{args.date}.csv")
    with csv.open("w", encoding="utf-8") as f:
        f.write("trade_id,case_id,side,entry,exit,gross,net,balance\n")
        # Demo-Trades aus Journal für Export (vereinfacht)
        bal = args.starting_balance
        for t in trader.portfolio.trades:
            bal *= (1 + t.net)
            f.write(f"{t.trade_id},{t.case_id},{t.side},{t.entry_price},{t.exit_price},{t.gross},{t.net},{round(bal,2)}\n")
    print(json.dumps({"status":"OK","bilanz":str(out),"csv":str(csv),"portfolio":portfolio.to_dict()}, indent=2))

if __name__ == "__main__":
    raise SystemExit(main())
