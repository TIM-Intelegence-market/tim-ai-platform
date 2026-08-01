#!/usr/bin/env python3
"""Materialize the deterministic replay strata as a pending human-review sample."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path


UTC = timezone.utc


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def session(value: datetime) -> str:
    return "ASIA" if value.hour < 8 else "EUROPE" if value.hour < 16 else "US"


def atomic_write(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.template.read_text(encoding="utf-8"))
    replay = json.loads(args.replay.read_text(encoding="utf-8"))
    if replay.get("gate_status") != "PASS" or replay.get("selected_strata") != 24:
        raise RuntimeError("manual sample requires a passing 24-stratum replay")
    selected = []
    selected_times: list[datetime] = []
    for rank, item in enumerate(sorted(replay["results"], key=lambda value: (value["kind"], value["outcome"])), 1):
        observed = parse_time(item["observed_at_utc"])
        observation_id = item["observation_id"]
        selected.append(
            {
                "selection_rank": rank,
                "stratum": {"observation_kind": item["kind"], "outcome": item["outcome"]},
                "observation_id": observation_id,
                "case_id": "ofcase_" + hashlib.sha256(observation_id.encode("utf-8")).hexdigest()[:20],
                "source_window_signature": f"BINANCE_SPOT|BTCUSDT|60s|{iso(observed)}",
                "observed_at_utc": iso(observed),
                "validated_through_utc": iso(observed + timedelta(minutes=30)),
                "observation_kind": item["kind"],
                "outcome": item["outcome"],
                "utc_session": session(observed),
                "input_hash": item["input_hash_replayed"],
                "validation_hash": item["validation_hash_replayed"],
                "horizon_minutes": [5, 15, 30],
                "source_gap_overlap": False,
                "prior_selected_window_distance_minutes": (
                    None
                    if not selected_times
                    else min(
                        int(abs((observed - prior).total_seconds()) / 60)
                        for prior in selected_times
                    )
                ),
                "evidence_reference": args.replay.as_posix(),
            }
        )
        selected_times.append(observed)
    manifest["selection_execution_status"] = "EXECUTED_AUTOMATED_PENDING_HUMAN_REVIEW"
    manifest["selection_rule"]["method"] = replay["selection_rule"]
    manifest["selection_rule"]["candidate_ranking"] = "Lexicographic observation_id order; first candidate in the first 25 per stratum that passes exact replay, source-contiguity and cutoff checks."
    manifest["selection_rule"]["global_window_deduplication"] = "Not enforced for the review sample; repeated windows are explicitly disclosed and do not contribute to the independent-case gate."
    manifest["selected_cases"] = selected
    manifest["selection_shortfalls"] = []
    manifest["known_limitations"] = [
        item for item in manifest["known_limitations"]
        if item != "Selection has not been executed; selected_cases is intentionally empty."
    ]
    manifest["known_limitations"].insert(0, "Automated selection is complete, but no selected case has been accepted or labelled by a human reviewer.")
    manifest["sample_hash"] = hashlib.sha256(
        json.dumps(selected, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    atomic_write(args.output, manifest)
    print(json.dumps({"selected": len(selected), "sample_hash": manifest["sample_hash"], "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
