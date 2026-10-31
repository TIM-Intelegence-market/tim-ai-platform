#!/usr/bin/env python3
"""FOMC statement ingest and real-data verification for the research lab (read-only).

  fetch    --window research|fixture        download lists and statement pages from www.federalreserve.gov,
           check against the window, store raw pages (prints the bundle id; reuse it below)
  fixture  --bundle ID                      copy a stored fixture-window bundle byte for byte into tests/fixtures
  verify   --bundle ID [--fred] [--btc-root DIR] [--fetch-btc]
           real-data summary of a stored research bundle; --fred adds the FRED target-range cross-check
           (needs the FRED key, see scripts/fred_store_key.py), BTC replay checks need the 1h spot archive
  report   --verify JSON                    write docs/research_lab/reports/fomc_v1_2_verification.{md,json}

No key is needed for federalreserve.gov. Everything except ``fetch``, ``verify --fred``
and ``--fetch-btc`` reads stored data only.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.research_lab.external.alfred import Fetcher, url_for  # noqa: E402
from src.research_lab.external.fomc_live import (  # noqa: E402
    FIXTURE_2019_2020,
    FIXTURE_DIR,
    RESEARCH_2017_2024,
    http_page_fetcher,
    ingest_fomc_live,
    load_fomc_ingest,
    write_fixture,
)
from src.research_lab.external.fomc_verify import FRED_LOWER, FRED_UPPER, fred_cross_check, fred_values, render_markdown, replay_checks, summary  # noqa: E402
from src.research_lab.external.fred_secret import FredSecretResolver  # noqa: E402
from src.research_lab.external.live import http_fetcher  # noqa: E402
from src.research_lab.external.realcheck import load_btc  # noqa: E402
from src.research_lab.external.store import DEFAULT_ROOT, RawPayloadStore  # noqa: E402

WINDOWS = {"research": RESEARCH_2017_2024, "fixture": FIXTURE_2019_2020}
REPORT = Path("docs/research_lab/reports/fomc_v1_2_verification")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def cmd_fetch(args: argparse.Namespace) -> int:
    window = WINDOWS[args.window]
    store = RawPayloadStore(args.root)
    bundle_id = ingest_fomc_live(window, store=store, fetcher=http_page_fetcher(), clock=_utc_now)
    bundle = store.get(bundle_id)
    print(json.dumps({"window": window.to_dict(), "bundle_id": bundle_id, "ingested_at": bundle.ingested_at.isoformat(), "pages": len(bundle.payloads),
                      "missing": sorted(name for name, request in bundle.requests.items() if request.get("status") != "200")}, indent=2))
    return 0


def cmd_fixture(args: argparse.Namespace) -> int:
    store = RawPayloadStore(args.root)
    bundle, ingest = load_fomc_ingest(store, args.bundle, FIXTURE_2019_2020)
    target = write_fixture(bundle, args.bundle, Path(args.out or FIXTURE_DIR))
    print(json.dumps({"fixture": str(target), "state": ingest.state.value, "statements": len(ingest.events)}, indent=2))
    return 0


def _fred(series_id: str, fetch: Fetcher) -> bytes:
    key = FredSecretResolver().api_key()
    request = {"path": "series/observations", "series_id": series_id, "observation_start": "2016-12-01", "observation_end": "2024-12-31"}
    return fetch(url_for(request, key.reveal()))


def cmd_verify(args: argparse.Namespace) -> int:
    store = RawPayloadStore(args.root)
    bundle, ingest = load_fomc_ingest(store, args.bundle, RESEARCH_2017_2024)
    report = {"bundle_id": args.bundle, "window": RESEARCH_2017_2024.to_dict(), "ingested_at": bundle.ingested_at.isoformat(),
              "payload_sha256": ingest.payload_hashes, "summary": summary(bundle, ingest), "fred_cross_check": None, "replay": None}
    if args.fred:
        fetch = http_fetcher()
        report["fred_cross_check"] = fred_cross_check(ingest.events, fred_values(_fred(FRED_UPPER, fetch)), fred_values(_fred(FRED_LOWER, fetch)))
    if args.btc_root:
        report["replay"] = replay_checks(bundle, ingest, load_btc(Path(args.btc_root), fetch=args.fetch_btc))
    print(json.dumps(report["summary"]["status_counts"], indent=2))
    out = Path(args.out or "fomc_verify.json")
    out.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    print(f"wrote {out}")
    return 0 if report["replay"] is None or report["replay"]["all_checks_pass"] else 1


def cmd_report(args: argparse.Namespace) -> int:
    report = json.loads(Path(args.verify).read_text())
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.with_suffix(".md").write_text(render_markdown(report))
    REPORT.with_suffix(".json").write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    print(f"wrote {REPORT}.md and {REPORT}.json")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="raw payload store (default data/research_lab/external)")
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch")
    fetch.add_argument("--window", choices=sorted(WINDOWS), required=True)
    fixture = sub.add_parser("fixture")
    fixture.add_argument("--bundle", required=True)
    fixture.add_argument("--out")
    verify = sub.add_parser("verify")
    verify.add_argument("--bundle", required=True)
    verify.add_argument("--fred", action="store_true")
    verify.add_argument("--btc-root")
    verify.add_argument("--fetch-btc", action="store_true")
    verify.add_argument("--out")
    report = sub.add_parser("report")
    report.add_argument("--verify", required=True, help="JSON written by verify")
    args = parser.parse_args(argv)
    commands = {"fetch": cmd_fetch, "fixture": cmd_fixture, "verify": cmd_verify, "report": cmd_report}
    return commands[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
