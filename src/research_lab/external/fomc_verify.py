"""Real-data verification of the FOMC statement events against one stored download.

Pure functions over a stored bundle and its parse result (plus, optionally, the FRED
target-range series for a cross-check): no network, no clock. The report says what
the stored pages show, which statements are not ``OK`` and why, and whether replays
of the same download are deterministic and free of lookahead.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from src.research_lab.data.parse import Kline
from src.research_lab.external.alfred import RawBundle
from src.research_lab.external.fomc import FomcIngest, PolicyStatementEvent, StatementStatus, parse_fomc_bundle, run_fomc_replay
from src.research_lab.external.records import iso
from src.research_lab.external.replay import ReplayConfig

RESEARCH_YEARS = range(2017, 2025)
FINAL_REPLAY_AT = datetime.fromisoformat("2024-12-31T23:59:59+00:00")
AS_OF_CUTS = (datetime.fromisoformat("2019-12-31T00:00:00+00:00"), datetime.fromisoformat("2020-03-16T00:00:00+00:00"), datetime.fromisoformat("2022-06-30T00:00:00+00:00"))
# FRED target range series, used only as a cross-check of the parsed ranges (never as an input).
FRED_UPPER, FRED_LOWER = "DFEDTARU", "DFEDTARL"


def summary(bundle: RawBundle, ingest: FomcIngest) -> dict[str, Any]:
    events = ingest.events
    research = [e for e in events if e.release_date.year in RESEARCH_YEARS]
    times = Counter(f"{e.release_time_local} {e.release_zone_label}" for e in research if e.release_time_local)
    return {
        "state": ingest.state.value,
        "years": list(ingest.years),
        "coverage_end": iso(ingest.coverage_end),
        "statements_total": len(events),
        "statements_per_year": {str(year): sum(1 for e in events if e.release_date.year == year) for year in ingest.years},
        "status_counts": dict(sorted(Counter(e.status.value for e in research).items())),
        "release_times": dict(sorted(times.items())),
        "weekend_releases": [e.event_id for e in research if e.release_date.weekday() >= 5],
        "not_2pm_releases": [e.event_id for e in research if e.release_time_local and e.release_time_local != "2:00 p.m."],
        "not_ok": [
            {"event_id": e.event_id, "status": e.status.value, "detail": next((i.issue.detail for i in ingest.issues if i.issue.record_id == e.event_id), None)}
            for e in research
            if e.status is not StatementStatus.OK
        ],
        "decisions": [
            {
                "event_id": e.event_id,
                "event_time": iso(e.event_time),
                "range": _range(e.target_low, e.target_high),
                "previous": _range(e.previous_low, e.previous_high),
                "decision": e.decision.value,
                "change_bp": e.change_bp,
            }
            for e in events
        ],
        "redirected": sorted(name for name, request in bundle.requests.items() if "final_url" in request),
        "payload_count": len(bundle.payloads),
        "issues": [item.to_dict() for item in ingest.issues],
    }


def _range(low: Decimal | None, high: Decimal | None) -> str | None:
    return None if low is None or high is None else f"{low} to {high}"


def fred_values(payload: bytes) -> dict[date, Decimal]:
    """Daily values of one FRED observations response; '.' (no value) is left out."""
    values = {}
    for row in json.loads(payload)["observations"]:
        try:
            values[date.fromisoformat(row["date"])] = Decimal(row["value"])
        except (InvalidOperation, KeyError, ValueError):
            continue
    return values


def fred_cross_check(events: tuple[PolicyStatementEvent, ...], upper: dict[date, Decimal], lower: dict[date, Decimal]) -> list[dict[str, Any]]:
    """For each OK statement: does FRED show its range on the release day or the day after?"""
    results = []
    for event in events:
        if event.status is not StatementStatus.OK or event.target_low is None or event.target_high is None:
            continue
        found = "MISMATCH"
        for label, day in (("SAME_DAY", event.release_date), ("NEXT_DAY", event.release_date + timedelta(days=1))):
            if day not in upper or day not in lower:
                continue
            if (lower[day], upper[day]) == (event.target_low, event.target_high):
                found = f"MATCH_{label}"
                break
        if found == "MISMATCH" and event.release_date not in upper and event.release_date + timedelta(days=1) not in upper:
            found = "NO_FRED_VALUE"
        results.append({"event_id": event.event_id, "decision": event.decision.value, "range": _range(event.target_low, event.target_high), "result": found})
    return results


def as_of(ingest: FomcIngest, cut: datetime) -> FomcIngest:
    """The download as it would have looked at ``cut``: later statements and findings removed."""
    return replace(
        ingest,
        events=tuple(e for e in ingest.events if e.available_at <= cut),
        issues=tuple(i for i in ingest.issues if i.available_at is None or i.available_at <= cut),
        coverage_end=min(ingest.coverage_end, cut),
    )


def replay_checks(bundle: RawBundle, ingest: FomcIngest, klines: list[Kline]) -> dict[str, Any]:
    config = ReplayConfig(replay_at=FINAL_REPLAY_AT, interval="1h", invalid_candles="exclude")
    first = run_fomc_replay(ingest, klines, config)
    again = run_fomc_replay(parse_fomc_bundle(bundle), klines, config)
    reordered = RawBundle(bundle.source, bundle.source_identifier, dict(reversed(list(bundle.payloads.items()))), bundle.ingested_at, dict(reversed(list(bundle.requests.items()))))
    other = run_fomc_replay(parse_fomc_bundle(reordered), klines, config)
    leaks = [
        row["event"]["event_id"]
        for row in first["events"]
        if row["event"]["available_at"] > iso(FINAL_REPLAY_AT) or (row["event"]["event_time"] and row["event"]["event_time"] != row["event"]["available_at"])
    ]
    cuts = {}
    for cut in AS_OF_CUTS:
        cut_config = ReplayConfig(replay_at=cut, interval="1h", invalid_candles="exclude")
        cuts[iso(cut)] = run_fomc_replay(ingest, klines, cut_config)["content_hash"] == run_fomc_replay(as_of(ingest, cut), klines, cut_config)["content_hash"]
    checks = {
        "repeat_identical": (first["dataset_id"], first["content_hash"], first["output_hash"]) == (again["dataset_id"], again["content_hash"], again["output_hash"]),
        "order_independent": (first["dataset_id"], first["content_hash"]) == (other["dataset_id"], other["content_hash"]),
        "no_lookahead": not leaks,
        "as_of_unchanged": all(cuts.values()),
    }
    windows = Counter(row["btc"]["status"] for row in first["events"])
    return {
        **checks,
        "all_checks_pass": all(checks.values()),
        "leaks": leaks,
        "as_of_cuts": cuts,
        "dataset_id": first["dataset_id"],
        "content_hash": first["content_hash"],
        "output_hash": first["output_hash"],
        "btc_candles": first["inputs"]["btc_candles"] if "inputs" in first else 0,
        "btc_excluded": len(first.get("inputs", {}).get("btc_excluded", [])),
        "alignment_status": dict(sorted(windows.items())),
    }


def render_markdown(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        "# FOMC statements V1.2: real-data verification",
        "",
        f"Bundle `{report['bundle_id']}`, downloaded {report['ingested_at']} from www.federalreserve.gov. "
        "Generated by `scripts/research_lab_fomc_ingest.py report`; numbers come from the stored pages, not from this text.",
        "",
        f"- State: **{s['state']}**, lists {s['years'][0]}-{s['years'][-1]} (2016 only as look-back), coverage end {s['coverage_end']}",
        f"- Statements: {s['statements_total']} in total; per year: " + ", ".join(f"{y}: {n}" for y, n in s["statements_per_year"].items()),
        "- Status 2017-2024: " + ", ".join(f"{k} {v}" for k, v in s["status_counts"].items()),
        "- Release times 2017-2024: " + ", ".join(f"{k} ({v})" for k, v in s["release_times"].items()),
        f"- Weekend releases: {', '.join(s['weekend_releases']) or 'none'}",
        f"- Releases not at 2:00 p.m.: {', '.join(s['not_2pm_releases']) or 'none'}",
        f"- Pages reached through a same-host redirect: {len(s['redirected'])}",
        "",
        "## Statements that are not OK",
        "",
    ]
    lines += [f"- `{item['event_id']}`: {item['status']} ({item['detail']})" for item in s["not_ok"]] or ["None."]
    lines += ["", "## Decisions", "", "| Statement | Event time (UTC) | Range after | Range before | Decision | Change (bp) |", "| --- | --- | --- | --- | --- | --- |"]
    lines += [f"| `{d['event_id']}` | {d['event_time'] or '-'} | {d['range'] or '-'} | {d['previous'] or '-'} | {d['decision']} | {d['change_bp'] if d['change_bp'] is not None else '-'} |" for d in s["decisions"]]
    cross = report.get("fred_cross_check")
    lines += ["", "## Cross-check against FRED (DFEDTARL/DFEDTARU)", ""]
    if cross is None:
        lines.append("Not run (needs a FRED key). The parsed ranges are not cross-checked in this report.")
    else:
        counts = Counter(item["result"] for item in cross)
        lines.append("Results: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
        lines += [f"- `{item['event_id']}` {item['range']}: {item['result']}" for item in cross if not item["result"].startswith("MATCH")]
    replay = report.get("replay")
    lines += ["", "## Replay checks", ""]
    if replay is None:
        lines.append("Not run.")
    else:
        for key in ("repeat_identical", "order_independent", "no_lookahead", "as_of_unchanged"):
            lines.append(f"- {key}: {'PASS' if replay[key] else 'FAIL'}")
        lines.append(f"- BTC 1h candles {replay['btc_candles']}, excluded {replay['btc_excluded']}; alignment " + ", ".join(f"{k} {v}" for k, v in replay["alignment_status"].items()))
        lines.append(f"- dataset_id `{replay['dataset_id']}`")
    lines.append("")
    return "\n".join(lines)


__all__ = ["FRED_LOWER", "FRED_UPPER", "as_of", "fred_cross_check", "fred_values", "render_markdown", "replay_checks", "summary"]
