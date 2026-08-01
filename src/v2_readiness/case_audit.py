from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Iterable


UTC = timezone.utc
REQUIRED_HORIZONS = frozenset({5, 15, 30})


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class ValidatedCaseRecord:
    observation_id: str
    observed_at: datetime
    validated_through: datetime
    kind: str
    outcome: str
    input_hash: str
    horizon_minutes: tuple[int, ...]
    source_gap_overlap: bool
    case_present: bool
    case_closed: bool
    case_outcome_matches: bool
    provenance_complete: bool

    @property
    def horizon_complete(self) -> bool:
        return REQUIRED_HORIZONS.issubset(self.horizon_minutes)

    @property
    def quality_eligible(self) -> bool:
        return all(
            (
                self.horizon_complete,
                not self.source_gap_overlap,
                self.case_present,
                self.case_closed,
                self.case_outcome_matches,
                self.provenance_complete,
            )
        )


def _greedy_non_overlapping(
    timestamps: Iterable[datetime],
    *,
    separation: timedelta,
) -> list[datetime]:
    selected: list[datetime] = []
    next_allowed: datetime | None = None
    for timestamp in sorted(set(timestamps)):
        value = timestamp.astimezone(UTC)
        if next_allowed is None or value >= next_allowed:
            selected.append(value)
            next_allowed = value + separation
    return selected


def audit_validated_cases(
    records: Iterable[ValidatedCaseRecord],
    *,
    required_independent_cases: int = 1000,
    independence_separation: timedelta = timedelta(minutes=30),
) -> dict[str, object]:
    values = list(records)
    ids = [item.observation_id for item in values]
    id_counts = Counter(ids)
    duplicate_ids = sorted(key for key, count in id_counts.items() if count > 1)
    unique_records = {item.observation_id: item for item in values}
    unique_values = list(unique_records.values())
    quality = [item for item in unique_values if item.quality_eligible]
    independent = _greedy_non_overlapping(
        (item.observed_at for item in quality), separation=independence_separation
    )
    kind_distribution = Counter(item.kind for item in unique_values)
    outcome_distribution = Counter(item.outcome for item in unique_values)
    quality_kind_distribution = Counter(item.kind for item in quality)
    quality_outcome_distribution = Counter(item.outcome for item in quality)
    window_multiplicity = Counter(
        Counter(item.observed_at.astimezone(UTC) for item in unique_values).values()
    )
    gate_pass = len(independent) >= required_independent_cases and not duplicate_ids
    payload: dict[str, object] = {
        "schema_version": "1.0.0",
        "audit_method": "STRICT_30M_NON_OVERLAPPING_QUALITY_SCREEN_V1",
        "required_independent_cases": required_independent_cases,
        "raw_complete_validation_rows": len(values),
        "unique_observation_ids": len(unique_values),
        "duplicate_observation_id_count": len(duplicate_ids),
        "duplicate_observation_ids": duplicate_ids,
        "unique_underlying_observation_times": len(
            {item.observed_at.astimezone(UTC) for item in unique_values}
        ),
        "unique_input_hashes": len({item.input_hash for item in unique_values}),
        "quality_eligible_labels": len(quality),
        "quality_eligible_underlying_windows": len(
            {item.observed_at.astimezone(UTC) for item in quality}
        ),
        "strict_independent_30m_windows": len(independent),
        "strict_independent_window_starts": [_iso(item) for item in independent],
        "horizon_incomplete": sum(not item.horizon_complete for item in unique_values),
        "source_gap_overlap": sum(item.source_gap_overlap for item in unique_values),
        "case_missing": sum(not item.case_present for item in unique_values),
        "case_not_closed": sum(not item.case_closed for item in unique_values),
        "case_outcome_mismatch": sum(
            not item.case_outcome_matches for item in unique_values
        ),
        "provenance_incomplete": sum(
            not item.provenance_complete for item in unique_values
        ),
        "kind_distribution": dict(sorted(kind_distribution.items())),
        "outcome_distribution": dict(sorted(outcome_distribution.items())),
        "quality_kind_distribution": dict(sorted(quality_kind_distribution.items())),
        "quality_outcome_distribution": dict(
            sorted(quality_outcome_distribution.items())
        ),
        "underlying_window_label_multiplicity": {
            str(key): value for key, value in sorted(window_multiplicity.items())
        },
        "negative_or_control_sampling": "ABSENT",
        "reviewer_fields": "ABSENT_FROM_SCHEMA",
        "inter_rater_evidence": "ABSENT",
        "selection_bias_status": "OPEN_RISK_DETECTOR_FIRED_CASES_ONLY",
        "statistical_independence_status": (
            "PASS" if len(independent) >= required_independent_cases else "FAIL"
        ),
        "gate_status": "PASS" if gate_pass else "FAIL",
    }
    payload["audit_hash"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload
