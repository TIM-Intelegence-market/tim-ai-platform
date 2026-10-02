#!/usr/bin/env python3
"""ALFRED CPI live ingest and real-data verification for the research lab (read-only).

  fetch    --window research|fixture        download, check against the window, store raw payloads
           (prints the bundle id; reuse it everywhere below, no second download)
  verify   --bundle ID                      real-data summary of a stored research bundle (JSON + Markdown)
  fixture  --bundle ID                      copy a stored fixture-window bundle byte for byte into tests/fixtures
  replay   --bundle ID [--btc-root DIR]     deterministic replay checks on real data (2017-2024)
  report   --verify JSON [--replay JSON]    write docs/research_lab/reports/alfred_cpi_v1_1_verification.{md,json}

The key comes from TIM_FRED_SECRET_PROVIDER (see scripts/fred_store_key.py) and is
needed for ``fetch`` only. Everything else reads stored bundles, never the network
(``replay --fetch-btc`` downloads the public, checksum-verified Binance archive
through the research lab's ArchiveStore, holdout-locked as always).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.research_lab.external.fixture_window import FIXTURE_2019_2020, FIXTURE_DIR, write_fixture  # noqa: E402
from src.research_lab.external.fred_secret import FredSecretResolver  # noqa: E402
from src.research_lab.external.live import (  # noqa: E402
    HOLDOUT_START,
    RESEARCH_2017_2024,
    http_fetcher,
    ingest_live,
    load_research_ingest,
)
from src.research_lab.external.realcheck import replay_checks  # noqa: E402
from src.research_lab.external.store import DEFAULT_ROOT, RawPayloadStore  # noqa: E402
from src.research_lab.external.verify import holdout_status, model_summary, raw_summary, render_markdown  # noqa: E402

WINDOWS = {"research": RESEARCH_2017_2024, "fixture": FIXTURE_2019_2020}
REPORT_DIR = Path("docs/research_lab/reports")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def cmd_fetch(args: argparse.Namespace) -> int:
    window = WINDOWS[args.window]
    store = RawPayloadStore(args.root)
    bundle_id = ingest_live(window, resolver=FredSecretResolver(), store=store, fetcher=http_fetcher(), clock=_utc_now)
    bundle = store.get(bundle_id)
    print(json.dumps({"window": window.to_dict(), "bundle_id": bundle_id, "ingested_at": bundle.ingested_at.isoformat(),
                      "payload_bytes": {name: len(payload) for name, payload in sorted(bundle.payloads.items())}}, indent=2))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    store = RawPayloadStore(args.root)
    bundle, ingest = load_research_ingest(store, args.bundle, RESEARCH_2017_2024)
    summary = {
        "bundle_id": args.bundle,
        "window": RESEARCH_2017_2024.to_dict(),
        "ingested_at": bundle.ingested_at.isoformat(),
        "requests": bundle.requests,
        "payload_sha256": ingest.payload_hashes,
        "raw": raw_summary(bundle),
        "model": model_summary(bundle, ingest, research_start=date(2017, 1, 1), research_end=date(2024, 12, 31)),
        "holdout": holdout_status(bundle, HOLDOUT_START),
    }
    summary["raw"].pop("vintage_dates_list")
    print(json.dumps(summary, indent=2, default=str))
    if args.out:
        Path(args.out).write_text(json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n")
    return 0


def cmd_fixture(args: argparse.Namespace) -> int:
    store = RawPayloadStore(args.root)
    bundle, ingest = load_research_ingest(store, args.bundle, FIXTURE_2019_2020)
    target = write_fixture(bundle, args.bundle, Path(args.out or FIXTURE_DIR))
    print(json.dumps({"fixture": str(target), "state": ingest.state.value, "records": len(ingest.records)}, indent=2))
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    store = RawPayloadStore(args.root)
    bundle, ingest = load_research_ingest(store, args.bundle, RESEARCH_2017_2024)
    result = replay_checks(bundle, ingest, btc_root=Path(args.btc_root), fetch_btc=args.fetch_btc)
    print(json.dumps(result, indent=2, default=str))
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n")
    return 0 if result["all_checks_pass"] else 1


def cmd_report(args: argparse.Namespace) -> int:
    summary = json.loads(Path(args.verify).read_text())
    replay = json.loads(Path(args.replay).read_text()) if args.replay else None
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stem = REPORT_DIR / "alfred_cpi_v1_1_verification"
    stem.with_suffix(".md").write_text(render_markdown(summary, replay))
    stem.with_suffix(".json").write_text(json.dumps({"verification": summary, "replay": replay}, indent=2, sort_keys=True, default=str) + "\n")
    print(f"wrote {stem}.md and {stem}.json")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="raw payload store (default data/research_lab/external)")
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch")
    fetch.add_argument("--window", choices=sorted(WINDOWS), required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--bundle", required=True)
    verify.add_argument("--out")
    fixture = sub.add_parser("fixture")
    fixture.add_argument("--bundle", required=True)
    fixture.add_argument("--out")
    replay = sub.add_parser("replay")
    replay.add_argument("--bundle", required=True)
    replay.add_argument("--btc-root", default="data/research_lab")
    replay.add_argument("--fetch-btc", action="store_true")
    replay.add_argument("--out")
    report = sub.add_parser("report")
    report.add_argument("--verify", required=True, help="JSON written by verify --out")
    report.add_argument("--replay", help="JSON written by replay --out")
    args = parser.parse_args(argv)
    commands = {"fetch": cmd_fetch, "verify": cmd_verify, "fixture": cmd_fixture, "replay": cmd_replay, "report": cmd_report}
    return commands[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
