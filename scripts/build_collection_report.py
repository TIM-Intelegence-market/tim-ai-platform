from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.collection_reporting import CollectionReportBuilder, CollectionReportError


def main() -> int:
    parser = argparse.ArgumentParser(description="Build deterministic, observe-only TIM collection reports")
    parser.add_argument("facts", type=Path, help="Read-only JSON facts captured by a separately validated collector")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        facts = json.loads(args.facts.read_text(encoding="utf-8"))
        result = CollectionReportBuilder().write(args.root, facts)
    except (OSError, ValueError, CollectionReportError) as exc:
        print(json.dumps({"status": "SAFE_STOP", "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 2
    print(json.dumps({
        "status": "PASS" if result["tim_autonomous_collection_ready"] else "PARTIAL",
        "collection_id": result["collection_id"],
        "decision_status": result["decision_status"],
        "management_traffic_light": result["management_traffic_light"],
        "result_hash": result["result_hash"],
        "report_dir": result["report_dir"],
        "resumed": result["resumed"],
        "trading_actions": result["trading_actions"],
    }, indent=2, sort_keys=True))
    return 0 if result["tim_autonomous_collection_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
