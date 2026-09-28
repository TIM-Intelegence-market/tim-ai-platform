"""Retrospective outcome frequencies for a research case.

Answers only: "Among earlier, fully validated observations of the same type
and rule version, how often did the price rise, fall or move sideways?"
Everything is past data known before ``as_of``; results are labelled
RETROSPECTIVE and carry no direction, recommendation or forecast.

Similarity is exact and transparent: same orderflow observation kind, same
rule version, same validation version (versions are never combined).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from src.insights.engine import OUTCOMES, _sample_label, _test_only
from src.orderflow.validation import VALIDATION_VERSION


LABEL = "RETROSPECTIVE"
MIN_SAMPLE = 10
NOTE = "Rückblick auf vergangene Fälle. Keine Prognose, keine Empfehlung, kein Signal."


def _time(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp without timezone: {value}")
    return parsed


def _known_at(validation: dict[str, Any]) -> datetime:
    """Latest moment any part of this validation depends on."""
    times = [_time(validation["validated_through"])]
    times.extend(_time(item["target_at"]) for item in validation.get("horizons", []))
    return max(times)


def retrospective(
    kind: str,
    rule_version: str,
    as_of: datetime,
    observations: Iterable[dict[str, Any]],
    validations: Iterable[dict[str, Any]],
    exclude_ids: Iterable[str] = (),
) -> dict[str, Any]:
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    observations = list(observations)
    excluded = {str(item) for item in exclude_ids}
    matching = {
        str(item["observation_id"])
        for item in observations
        if item.get("kind") == kind and item.get("rule_version") == rule_version and not _test_only(item)
    }
    counts = {name: 0 for name in OUTCOMES}
    for item in validations:
        oid = str(item.get("observation_id") or "")
        if oid not in matching or oid in excluded or _test_only(item):
            continue
        if not item.get("complete") or item.get("outcome") not in OUTCOMES:
            continue
        if item.get("validation_version") != VALIDATION_VERSION:
            continue
        if _time(item["observed_at"]) >= as_of or _known_at(item) > as_of:
            continue  # outcome was not yet known at as_of: no look-ahead
        counts[item["outcome"]] += 1
    n = sum(counts.values())
    sufficient = n >= MIN_SAMPLE
    return {
        "label": LABEL,
        "as_of": as_of.isoformat(),
        "observation_type": kind,
        "rule_version": rule_version,
        "validation_version": VALIDATION_VERSION,
        "sample_size": n,
        "sample_label": _sample_label(n),
        "sufficient": sufficient,
        "outcomes": counts if sufficient else None,
        "note": NOTE if sufficient else f"Zu wenige vergleichbare Fälle (n={n}, mindestens {MIN_SAMPLE}). Keine Häufigkeiten angezeigt.",
        "basis": f"Grundlage: {len(observations)} Orderflow-Beobachtungen im geladenen Verlauf, nicht die vollständige Historie.",
    }


def case_retrospective(case: dict[str, Any], observations: Iterable[dict[str, Any]], validations: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """One retrospective block per orderflow observation type in the case, as of the case opening."""
    observations, validations = list(observations), list(validations)
    rule_version = case.get("rule_versions", {}).get("orderflow")
    if not rule_version:
        return []
    as_of = _time(case["opened_at"])
    own = [str(item) for item in case.get("observation_ids", [])]
    kinds = sorted({str(item.get("kind")) for item in case.get("evidence", []) if item.get("kind")})
    return [retrospective(kind, rule_version, as_of, observations, validations, exclude_ids=own) for kind in kinds]
