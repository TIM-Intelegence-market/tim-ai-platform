#!/usr/bin/env python3
"""Study S1: BTC range in the CPI release hour (docs/research_lab/studien/S1_CPI_VOLATILITAET.md).

  python scripts/research_lab_cpi_volatility.py --bundle ID [--btc-root DIR] [--fetch-btc] [--write-report]

Reads a stored ALFRED research bundle (``research_lab_alfred_ingest.py fetch --window research``)
and the research lab's BTCUSDT spot 1h klines 2017-08..2024-12. No FRED key and no network are
needed unless ``--fetch-btc`` downloads the public, checksum-verified Binance archive. Holdout
(2025+) stays locked.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.research_lab.external.align import BtcSeries  # noqa: E402
from src.research_lab.external.events import release_events  # noqa: E402
from src.research_lab.external.live import RESEARCH_2017_2024, load_research_ingest  # noqa: E402
from src.research_lab.external.pit import PointInTimeStore  # noqa: E402
from src.research_lab.external.realcheck import FINAL_REPLAY_AT, load_btc  # noqa: E402
from src.research_lab.external.store import DEFAULT_ROOT, RawPayloadStore  # noqa: E402
from src.research_lab.studies.cpi_volatility import render_markdown, run_study  # noqa: E402

REPORT_STEM = Path("docs/research_lab/reports/s1_cpi_volatility")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bundle", required=True, help="bundle id printed by research_lab_alfred_ingest.py fetch")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="raw payload store (default data/research_lab/external)")
    parser.add_argument("--btc-root", default="data/research_lab")
    parser.add_argument("--fetch-btc", action="store_true")
    parser.add_argument("--write-report", action="store_true", help=f"write {REPORT_STEM}.md and .json")
    args = parser.parse_args(argv)

    _bundle, ingest = load_research_ingest(RawPayloadStore(args.root), args.bundle, RESEARCH_2017_2024)
    events = release_events(PointInTimeStore(ingest), until=FINAL_REPLAY_AT)
    klines = load_btc(Path(args.btc_root), fetch=args.fetch_btc)
    btc = BtcSeries.build(klines, "1h", replay_at=FINAL_REPLAY_AT, invalid_candles="exclude")
    result = run_study(events, btc)
    provenance = {"bundle_id": args.bundle, "payload_sha256": ingest.payload_hashes, "replay_at": FINAL_REPLAY_AT.isoformat()}
    summary = {name: {k: v for k, v in window.items() if k != "rows"} for name, window in result["windows"].items()}
    print(json.dumps({"primary_verdict": result["primary_verdict"], "events_eligible": result["events_eligible"], "windows": summary}, indent=2, default=str))
    if args.write_report:
        REPORT_STEM.parent.mkdir(parents=True, exist_ok=True)
        flat = {"bundle_id": args.bundle, "replay_at": provenance["replay_at"], **{f"sha256 {k}": v for k, v in sorted(ingest.payload_hashes.items())}}
        REPORT_STEM.with_suffix(".md").write_text(render_markdown(result, flat))
        REPORT_STEM.with_suffix(".json").write_text(json.dumps({"provenance": provenance, "result": result}, indent=2, sort_keys=True, default=str) + "\n")
        print(f"wrote {REPORT_STEM}.md and {REPORT_STEM}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
