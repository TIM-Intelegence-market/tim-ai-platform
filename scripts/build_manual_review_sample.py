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
    parser.add_argument("--case-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.template.read_text(encoding="utf-8"))
    replay = json.loads(args.replay.read_text(encoding="utf-8"))
    case_audit = json.loads(args.case_audit.read_text(encoding="utf-8"))
    if replay.get("gate_status") != "PASS" or replay.get("selected_strata") != 24:
        raise RuntimeError("manual sample requires a passing 24-stratum replay")
    replay_cutoff = replay.get("cutoff_utc")
    if replay_cutoff != case_audit.get("current_cutoff_utc"):
        raise RuntimeError("replay and current case-audit cut-offs must match")
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
    if len({item["observation_id"] for item in selected}) != len(selected):
        raise RuntimeError("manual sample contains duplicate observation IDs")
    if len({item["source_window_signature"] for item in selected}) != len(selected):
        raise RuntimeError("manual sample contains duplicate source windows")
    manifest["selection_execution_status"] = "EXECUTED_AUTOMATED_PENDING_HUMAN_REVIEW"
    if "population" in manifest and "frozen_gate_population" not in manifest:
        manifest["frozen_gate_population"] = manifest.pop("population")
    current = case_audit["current_cutoff_audit"]
    manifest["selection_population"] = {
        "scope": "CURRENT_CUTOFF_REPLAY_CANDIDATE_POPULATION_NOT_FROZEN_GATE_POPULATION",
        "cutoff_utc": replay_cutoff,
        "case_gate_status": current["gate_status"],
        "raw_complete_validation_labels": current["raw_complete_validation_rows"],
        "horizon_incomplete_labels": current["horizon_incomplete"],
        "source_gap_overlap_labels": current["source_gap_overlap"],
        "strict_quality_eligible_labels": current["quality_eligible_labels"],
        "strict_unique_source_windows": current["quality_eligible_underlying_windows"],
        "strict_non_overlapping_30m_windows": current["strict_independent_30m_windows"],
        "required_independent_quality_cases": current["required_independent_cases"],
    }
    manifest["selection_rule"]["method"] = replay["selection_rule"]
    manifest["selection_rule"]["candidate_ranking"] = "Lexicographic observation_id order; first candidate in the first 25 per stratum that passes exact replay, source-contiguity and cutoff checks."
    manifest["selection_rule"]["global_window_deduplication"] = "Not enforced for the review sample; repeated windows are explicitly disclosed and do not contribute to the independent-case gate."
    manifest["selection_rule"]["eligibility_predicate"] = [
        "persisted complete validation is at or before source_cutoff_utc",
        "persisted outcome is non-null and persisted horizons include 5, 15, and 30 minutes",
        "candidate is in the first 25 lexicographic observation IDs for its observation-kind x outcome stratum",
        "raw replay input is aggregate-trade-ID contiguous across the metric and outcome interval",
        "observation input hash, validation hash, outcome, reversed-input result, and OBSERVE mode replay exactly",
        "the validation is not complete at the 29-minute pre-cutoff check",
    ]
    manifest["selected_cases"] = selected
    manifest["selected_output_checks"] = {
        "observation_ids_unique": True,
        "source_window_signatures_unique": True,
        "selected_count": len(selected),
        "scope": "CURRENT_OUTPUT_ASSERTION_NOT_INDEPENDENT_CASE_GATE",
    }
    manifest["selection_shortfalls"] = []
    manifest["source_cutoff_utc"] = replay_cutoff
    manifest["source_scope"].pop("observation_start_utc", None)
    manifest["source_scope"].pop("observation_end_utc", None)
    manifest["source_scope"].update({
        "selected_observation_start_utc": iso(min(selected_times)),
        "selected_observation_end_utc": iso(max(selected_times)),
        "selection_population_reference": args.case_audit.as_posix() + "#current_cutoff_audit",
        "validation_cutoff_rule": "replay candidate complete=true AND validated_through<=source_cutoff_utc; exact replay must also pass",
    })
    manifest["case_id_semantics"] = "DERIVED_FROM_OBSERVATION_ID_BY_BUILDER_NOT_DATABASE_CASE_PROVENANCE_PROOF"
    manifest["source_replay"] = {
        "artifact": args.replay.as_posix(),
        "artifact_sha256": hashlib.sha256(args.replay.read_bytes()).hexdigest(),
        "replay_hash": replay["replay_hash"],
        "cutoff_utc": replay_cutoff,
    }
    manifest["known_limitations"] = [
        item for item in manifest["known_limitations"]
        if item not in {
            "Selection has not been executed; selected_cases is intentionally empty.",
            "Automated selection is complete, but no selected case has been accepted or labelled by a human reviewer.",
        }
    ]
    manifest["known_limitations"].insert(0, "Automated selection is complete, but no selected case has been accepted or labelled by a human reviewer.")
    manifest["sample_hash"] = hashlib.sha256(
        json.dumps(selected, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    manifest["sample_hash_scope"] = "CANONICAL_SELECTED_CASES_ONLY_V1"
    atomic_write(args.output, manifest)
    print(json.dumps({"selected": len(selected), "sample_hash": manifest["sample_hash"], "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
