from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from typing import Any, Iterable


OUTCOMES = ("PRICE_DECREASED", "PRICE_INCREASED", "PRICE_SIDEWAYS")
HORIZONS = (5, 15, 30)
HASH = re.compile(r"^[0-9a-f]{64}$")
PLACES = Decimal("0.00000001")
SESSIONS = (
    ("ASIA", 0, 8),
    ("EUROPE", 8, 16),
    ("USA", 16, 24),
)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _utc(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"timezone-aware timestamp required: {value}")
    return parsed.astimezone(timezone.utc)


def _decimal(value: Any) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"invalid decimal value: {value}") from exc
    if not number.is_finite():
        raise ValueError(f"non-finite decimal value: {value}")
    return number


def _number(value: Decimal) -> str:
    rounded = value.quantize(PLACES, rounding=ROUND_HALF_EVEN)
    return "0" if rounded == 0 else format(rounded.normalize(), "f")


def _percentile(values: list[Decimal], fraction: Decimal) -> Decimal:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile requires values")
    if len(ordered) == 1:
        return ordered[0]
    position = Decimal(len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - Decimal(lower)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _statistics(values: Iterable[Any]) -> dict[str, Any] | None:
    data = [_decimal(value) for value in values]
    if not data:
        return None
    with localcontext() as context:
        context.prec = 40
        count = Decimal(len(data))
        mean = sum(data, Decimal("0")) / count
        variance = sum(((value - mean) ** 2 for value in data), Decimal("0")) / count
        q25, median, q75 = (_percentile(data, part) for part in (Decimal("0.25"), Decimal("0.5"), Decimal("0.75")))
        return {
            "n": len(data),
            "minimum": _number(min(data)),
            "maximum": _number(max(data)),
            "mean": _number(mean),
            "median": _number(median),
            "standard_deviation": _number(variance.sqrt()),
            "percentile_25": _number(q25),
            "percentile_75": _number(q75),
            "interquartile_range": _number(q75 - q25),
        }


def _sample_label(n: int) -> str:
    if n < 10:
        return "N_LT_10"
    if n < 30:
        return "N_LT_30"
    if n < 100:
        return "N_LT_100"
    if n < 1000:
        return "N_GTE_100"
    return "N_GTE_1000"


def _test_only(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_test_only(key) or _test_only(item) for key, item in value.items())
    if isinstance(value, (list, tuple, set)):
        return any(_test_only(item) for item in value)
    return "TEST_ONLY" in str(value).upper()


def _session(hour: int) -> str:
    return next(name for name, start, end in SESSIONS if start <= hour < end)


def _evidence_signature(evidence: list[dict[str, Any]]) -> tuple[str, ...]:
    """Describe evidence clauses without per-observation values or hashes."""
    signatures = []
    for clause in evidence:
        if not isinstance(clause, dict):
            raise ValueError("evidence clauses must be objects")
        descriptor = clause.get("condition") or clause.get("metric")
        if not descriptor:
            stable = {key: value for key, value in clause.items() if key not in {"value", "current_source_hash", "previous_source_hash", "source_hash"}}
            if not stable:
                raise ValueError("evidence clause has no stable descriptor")
            descriptor = _canonical(stable)
        signatures.append(str(descriptor))
    return tuple(sorted(signatures))


class ResearchInsightsEngine:
    """Pure retrospective statistics; inputs are copied and never mutated."""

    schema_version = "1.0.0"
    configuration = {
        "timezone": "UTC",
        "rounding": "ROUND_HALF_EVEN_8_DECIMALS",
        "percentile_method": "LINEAR_INDEX_N_MINUS_1",
        "standard_deviation": "POPULATION",
        "sessions": [{"name": name, "start_hour_utc": start, "end_hour_utc": end} for name, start, end in SESSIONS],
    }

    def analyze(
        self,
        observations: list[dict[str, Any]],
        validations: list[dict[str, Any]],
        cases: list[dict[str, Any]],
        manifest: dict[str, Any],
        quality: dict[str, Any] | None = None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        if manifest.get("status") != "FROZEN" or manifest.get("operating_mode") != "OBSERVE":
            raise ValueError("frozen OBSERVE core manifest required")
        components = manifest.get("components")
        if not isinstance(components, dict):
            raise ValueError("core manifest components missing")
        required_versions = ("orderflow_metrics", "orderflow_observations", "orderflow_validation")
        if any(not components.get(key) for key in required_versions):
            raise ValueError("core manifest version metadata incomplete")

        source_observations = sorted((dict(item) for item in observations), key=lambda x: (str(x.get("observed_at", "")), str(x.get("observation_id", ""))))
        source_validations = sorted((dict(item) for item in validations), key=lambda x: (str(x.get("observed_at", "")), str(x.get("observation_id", ""))))
        source_cases = sorted((dict(item) for item in cases), key=lambda x: (str(x.get("opened_at", "")), str(x.get("case_id", ""))))
        exclusions: list[dict[str, str]] = []

        observations_by_id: dict[str, dict[str, Any]] = {}
        for item in source_observations:
            oid = str(item.get("observation_id") or "")
            if not oid or oid in observations_by_id:
                raise ValueError("invalid or duplicate observation_id")
            _utc(item.get("observed_at"))
            if not HASH.fullmatch(str(item.get("input_hash") or "")):
                raise ValueError(f"invalid observation hash: {oid}")
            if _test_only(item):
                exclusions.append({"id": oid, "reason": "TEST_ONLY"})
                continue
            observations_by_id[oid] = item

        validations_by_id: dict[str, dict[str, Any]] = {}
        for item in source_validations:
            oid = str(item.get("observation_id") or "")
            if not oid or oid in validations_by_id:
                raise ValueError("invalid or duplicate validation observation_id")
            _utc(item.get("observed_at"))
            if not HASH.fullmatch(str(item.get("validation_hash") or "")):
                raise ValueError(f"invalid validation hash: {oid}")
            if item.get("outcome") not in (*OUTCOMES, None):
                raise ValueError(f"unsupported persisted outcome: {oid}")
            if _test_only(item):
                exclusions.append({"id": oid, "reason": "TEST_ONLY"})
                continue
            validations_by_id[oid] = item

        test_case_observations = {
            str(oid)
            for case in source_cases
            if _test_only(case)
            for oid in case.get("observation_ids", [])
        }
        for oid in sorted(test_case_observations):
            observations_by_id.pop(oid, None)
            validations_by_id.pop(oid, None)
            exclusions.append({"id": oid, "reason": "TEST_ONLY_CASE"})

        version_groups: dict[tuple[str, str, str, str], list[tuple[dict[str, Any], dict[str, Any] | None]]] = defaultdict(list)
        all_pairs: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
        for oid, observation in observations_by_id.items():
            validation = validations_by_id.get(oid)
            version_key = (
                str(manifest.get("core_version")),
                str(components["orderflow_metrics"]),
                str(observation.get("rule_version") or "UNKNOWN"),
                str(validation.get("validation_version") if validation else components["orderflow_validation"]),
            )
            pair = (observation, validation)
            version_groups[version_key].append(pair)
            all_pairs.append(pair)

        outcomes: list[dict[str, Any]] = []
        followups: list[dict[str, Any]] = []
        evidence_groups: dict[tuple[str, str, tuple[str, ...]], list[str | None]] = defaultdict(list)
        temporal: dict[str, Counter[str]] = {key: Counter() for key in ("utc_hour", "weekday", "calendar_week", "month", "market_session")}
        complete_total = 0

        for versions, pairs in sorted(version_groups.items()):
            by_type: dict[str, list[tuple[dict[str, Any], dict[str, Any] | None]]] = defaultdict(list)
            for observation, validation in pairs:
                by_type[str(observation.get("kind") or "UNKNOWN")].append((observation, validation))
            for kind, items in sorted(by_type.items()):
                complete = [validation for _, validation in items if validation and validation.get("complete") is True]
                incomplete = [validation for _, validation in items if validation and validation.get("complete") is not True]
                open_count = sum(validation is None for _, validation in items)
                complete_total += len(complete)
                counts = Counter(str(item.get("outcome")) for item in complete)
                n = len(complete)
                outcomes.append({
                    "versions": {"core": versions[0], "metrics": versions[1], "rule": versions[2], "validation": versions[3]},
                    "observation_type": kind,
                    "fully_validated_cases": n,
                    "open_cases": open_count,
                    "incomplete_validations": len(incomplete),
                    "outcomes": {name: counts.get(name, 0) for name in OUTCOMES},
                    "outcome_shares_percent": {name: _number(Decimal(counts.get(name, 0)) * 100 / Decimal(n)) if n else None for name in OUTCOMES},
                    "sample_size": n,
                    "sample_label": _sample_label(n),
                })
                horizon_results = []
                for minutes in HORIZONS:
                    horizons = [h for validation in complete for h in validation.get("horizons", []) if int(h.get("minutes", -1)) == minutes]
                    horizon_results.append({
                        "minutes": minutes,
                        "price_change_percent": _statistics(h.get("price_change_percent") for h in horizons),
                        "net_delta": _statistics(h.get("net_delta") for h in horizons),
                        "sample_label": _sample_label(len(horizons)),
                    })
                followups.append({"versions": outcomes[-1]["versions"], "observation_type": kind, "horizons": horizon_results})

            for observation, validation in pairs:
                evidence = observation.get("evidence")
                if not isinstance(evidence, list) or len(evidence) < 2:
                    raise ValueError(f"invalid evidence list: {observation.get('observation_id')}")
                clauses = _evidence_signature(evidence)
                evidence_groups[(str(observation.get("kind")), str(observation.get("rule_version")), clauses)].append(validation.get("outcome") if validation and validation.get("complete") else None)
                observed = _utc(observation["observed_at"])
                temporal["utc_hour"][f"{observed.hour:02d}:00"] += 1
                temporal["weekday"][observed.strftime("%A").upper()] += 1
                temporal["calendar_week"][f"{observed.isocalendar().year}-W{observed.isocalendar().week:02d}"] += 1
                temporal["month"][observed.strftime("%Y-%m")] += 1
                temporal["market_session"][_session(observed.hour)] += 1

        combinations = []
        for (kind, rule, clauses), values in evidence_groups.items():
            counts = Counter(value for value in values if value)
            combinations.append({
                "observation_type": kind,
                "rule_version": rule,
                "evidence": list(clauses),
                "count": len(values),
                "outcomes": {name: counts.get(name, 0) for name in OUTCOMES},
                "sample_label": _sample_label(len(values)),
            })
        combinations.sort(key=lambda item: (-item["count"], item["observation_type"], item["rule_version"], _canonical(item["evidence"])))

        quality = dict(quality or {})
        gaps = quality.get("known_data_gaps", quality.get("gap_events", []))
        gap_count = len(gaps) if isinstance(gaps, list) else int(gaps or 0)
        integrity_errors = int(quality.get("integrity_errors", 0) or 0)
        replay_status = str(quality.get("replay_status", "UNKNOWN")).upper()
        coverage = quality.get("coverage_percent")
        source_complete = quality.get("source_window_complete", True) is True
        integrity_status = "PASS" if gap_count == 0 and integrity_errors == 0 and replay_status == "PASS" else "OPEN_ISSUES"
        version_consistent = len(version_groups) <= 1 and bool(version_groups)
        enough_per_type = bool(outcomes) and all(item["sample_size"] >= 100 for item in outcomes)
        eligible = complete_total >= 1000 and enough_per_type and version_consistent and integrity_status == "PASS" and coverage is not None and source_complete
        status = "ELIGIBLE" if eligible else "NOT_YET_ELIGIBLE"
        result_status = "DESCRIPTIVE" if eligible else ("EXPLORATORY_ONLY" if complete_total else "INSUFFICIENT_SAMPLE")

        dataset = {
            "observations": list(observations_by_id.values()),
            "validations": [validations_by_id[key] for key in sorted(validations_by_id)],
            "cases": [item for item in source_cases if not _test_only(item)],
            "manifest": manifest,
            "quality": quality,
            "configuration": self.configuration,
        }
        input_hash = _hash(dataset)
        timestamps = [str(item.get("validated_through") or item.get("observed_at")) for item in validations_by_id.values()]
        created = generated_at or (max(timestamps) if timestamps else "1970-01-01T00:00:00+00:00")
        _utc(created)
        result = {
            "schema_version": self.schema_version,
            "generated_at": created,
            "analysis_period": {
                "start": min((item.get("observed_at") for item in observations_by_id.values()), default=None),
                "end": max((item.get("observed_at") for item in observations_by_id.values()), default=None),
            },
            "mode": "OBSERVE",
            "read_only": True,
            "eligibility_status": status,
            "result_status": result_status,
            "eligibility": {
                "fully_validated_cases": complete_total,
                "minimum_required": 1000,
                "sufficient_per_observation_type": enough_per_type,
                "version_consistent": version_consistent,
                "integrity_status": integrity_status,
                "coverage_documented": coverage is not None,
                "source_window_complete": source_complete,
            },
            "versions": {
                "core": str(manifest.get("core_version")),
                "metrics": sorted({key[1] for key in version_groups}),
                "rules": sorted({key[2] for key in version_groups}),
                "validations": sorted({key[3] for key in version_groups}),
            },
            "configuration": self.configuration,
            "input_hash": input_hash,
            "sample_size": len(all_pairs),
            "exclusions": sorted(exclusions, key=lambda item: (item["reason"], item["id"])),
            "data_quality": {
                "coverage_percent": coverage,
                "known_data_gaps": gaps,
                "integrity_errors": integrity_errors,
                "replay_status": replay_status,
                "excluded_cases": len(exclusions),
                "integrity_status": integrity_status,
            },
            "outcome_distribution": outcomes,
            "followup_statistics": followups,
            "evidence_combinations": combinations,
            "temporal_distribution": {key: dict(sorted(value.items())) for key, value in temporal.items()},
            "warnings": self._warnings(status, complete_total, version_consistent, gap_count, integrity_errors, replay_status, coverage, source_complete),
        }
        result["output_hash"] = _hash(result)
        return result

    @staticmethod
    def _warnings(status: str, n: int, version_consistent: bool, gaps: int, integrity_errors: int, replay: str, coverage: Any, source_complete: bool) -> list[str]:
        warnings = []
        if status != "ELIGIBLE": warnings.append("NOT_YET_ELIGIBLE")
        if n < 1000: warnings.append("INSUFFICIENT_FULLY_VALIDATED_CASES")
        if not version_consistent: warnings.append("MULTIPLE_OR_MISSING_VERSION_GROUPS")
        if gaps: warnings.append("KNOWN_DATA_GAPS")
        if integrity_errors: warnings.append("OPEN_INTEGRITY_ERRORS")
        if replay != "PASS": warnings.append("REPLAY_NOT_CONFIRMED")
        if coverage is None: warnings.append("DATA_COVERAGE_NOT_DOCUMENTED")
        if not source_complete: warnings.append("PERSISTED_SOURCE_WINDOW_INCOMPLETE")
        return warnings

    @staticmethod
    def to_json(result: dict[str, Any]) -> str:
        return json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    @staticmethod
    def to_csv(result: dict[str, Any]) -> str:
        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(["metadata", "value"])
        for key in ("generated_at", "eligibility_status", "result_status", "input_hash", "output_hash", "sample_size"):
            writer.writerow([key, result.get(key)])
        writer.writerow([])
        writer.writerow(["observation_type", "rule_version", "fully_validated_cases", *OUTCOMES, "sample_label"])
        for item in result.get("outcome_distribution", []):
            writer.writerow([item["observation_type"], item["versions"]["rule"], item["fully_validated_cases"], *(item["outcomes"][name] for name in OUTCOMES), item["sample_label"]])
        return output.getvalue()

    @staticmethod
    def to_markdown(result: dict[str, Any]) -> str:
        lines = [
            "# TIM Research Insights",
            "",
            f"- Generated: {result['generated_at']}",
            f"- Eligibility: **{result['eligibility_status']}**",
            f"- Status: **{result['result_status']}**",
            f"- Input hash: `{result['input_hash']}`",
            f"- Output hash: `{result['output_hash']}`",
            f"- Sample size: {result['sample_size']}",
            "",
            "No forecasts, rankings, causal claims, or trading signals.",
            "",
            "## Outcome distributions",
            "",
            "| Observation | Rule | N complete | Increased | Decreased | Sideways | Label |",
            "|---|---:|---:|---:|---:|---:|---|",
        ]
        for item in result.get("outcome_distribution", []):
            lines.append(f"| {item['observation_type']} | {item['versions']['rule']} | {item['fully_validated_cases']} | {item['outcomes']['PRICE_INCREASED']} | {item['outcomes']['PRICE_DECREASED']} | {item['outcomes']['PRICE_SIDEWAYS']} | {item['sample_label']} |")
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in result.get("warnings", []))
        return "\n".join(lines) + "\n"
