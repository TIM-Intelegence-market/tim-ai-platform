"""Export US-CPI and FOMC release instants for the chart's macro calendar (display only).

Reads stored research bundles (no network) and writes the JSON file that
``src.dashboard.macro_calendar`` reads (``data/macro/calendar.json`` or ``TIM_MACRO_CALENDAR``):

    python -m src.research_lab.external.macro_calendar_export --cpi-bundle ID --fomc-bundle ID

Only documented release instants are exported (CPI events with status OK and a scheduled time,
FOMC statements with a release time read from the page). The dashboard never imports this module.
"""
from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

SCHEMA = "tim_macro_calendar/1"  # same value as src.dashboard.macro_calendar.SCHEMA (checked by a test)
DEFAULT_OUT = Path("data/macro/calendar.json")


def cpi_rows(store: Any, bundle_id: str) -> list[dict[str, Any]]:
    from src.research_lab.external.events import EventStatus, release_events
    from src.research_lab.external.live import RESEARCH_2017_2024, load_research_ingest
    from src.research_lab.external.pit import PointInTimeStore
    from src.research_lab.external.realcheck import FINAL_REPLAY_AT

    _, ingest = load_research_ingest(store, bundle_id, RESEARCH_2017_2024)
    return [{"kind": "CPI", "time": e.event_time.isoformat(), "label": "US-CPI", "source": f"ALFRED CPIAUCSL, bundle {bundle_id[:12]}"}
            for e in release_events(PointInTimeStore(ingest), until=FINAL_REPLAY_AT)
            if e.status is EventStatus.OK and e.event_time is not None]


def fomc_rows(events: Sequence[Any]) -> list[dict[str, Any]]:
    return [{"kind": "FOMC", "time": e.event_time.isoformat(), "label": "FOMC", "source": f"federalreserve.gov {e.event_id}"}
            for e in events if e.event_time is not None]


def export(cpi_bundle: str | None, fomc_bundle: str | None, root: str) -> dict[str, Any]:
    from src.research_lab.external.store import RawPayloadStore

    store = RawPayloadStore(root)
    events: list[dict[str, Any]] = []
    if cpi_bundle:
        events += cpi_rows(store, cpi_bundle)
    if fomc_bundle:
        from src.research_lab.external.fomc_live import RESEARCH_2017_2024, load_fomc_ingest

        _, ingest = load_fomc_ingest(store, fomc_bundle, RESEARCH_2017_2024)
        events += fomc_rows(ingest.events)
    events.sort(key=lambda e: (e["time"], e["kind"]))
    return {"schema": SCHEMA, "events": events}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cpi-bundle")
    parser.add_argument("--fomc-bundle")
    parser.add_argument("--root", default="data/research_lab/external")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    if not (args.cpi_bundle or args.fomc_bundle):
        parser.error("--cpi-bundle or --fomc-bundle is required")
    payload = export(args.cpi_bundle, args.fomc_bundle, args.root)
    out = args.out or Path(os.environ.get("TIM_MACRO_CALENDAR") or DEFAULT_OUT)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1) + "\n")
    print(f"{len(payload['events'])} Termine geschrieben: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
