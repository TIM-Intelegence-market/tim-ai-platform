from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable


def _time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _seconds(start: Any, end: Any) -> float | None:
    left, right = _time(start), _time(end)
    return round((right - left).total_seconds(), 3) if left and right and right >= left else None


def _average(values: Iterable[float | int | None]) -> float:
    clean = [float(value) for value in values if value is not None]
    return round(sum(clean) / len(clean), 3) if clean else 0.0


def _distribution(values: Iterable[Any]) -> dict[str, int]:
    return dict(sorted(Counter(str(value) for value in values if value not in (None, "")).items()))


def _most_common(values: Iterable[Any]) -> list[str]:
    counts = Counter(str(value) for value in values if value not in (None, ""))
    highest = max(counts.values(), default=0)
    return sorted(key for key, count in counts.items() if count == highest) if highest else []


class ResearchAnalyticsEngine:
    """Pure statistics. Input is never mutated and no observations are produced."""

    schema_version = "1.0.0"

    def analyze(self, observations: list[dict[str, Any]], cases: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, Any]:
        observations = sorted((dict(item) for item in observations), key=lambda x: (str(x.get("observed_at", "")), str(x.get("observation_id", ""))))
        cases = sorted((dict(item) for item in cases), key=lambda x: (str(x.get("opened_at", "")), str(x.get("case_id", ""))))
        events = sorted((dict(item) for item in events), key=lambda x: (str(x.get("timestamp", "")), str(x.get("event", ""))))
        canonical = json.dumps({"observations": observations, "cases": cases, "events": events}, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
        by_observation: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for case in cases:
            for observation_id in case.get("observation_ids", []):
                by_observation[str(observation_id)].append(case)

        rule_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for observation in observations:
            rule_groups[(str(observation.get("rule_id") or "unassigned"), str(observation.get("rule_version") or "unknown"))].append(observation)

        rules = []
        for (rule_id, version), items in sorted(rule_groups.items()):
            ids = {str(item.get("observation_id")) for item in items}
            related = [case for case in cases if ids.intersection(str(value) for value in case.get("observation_ids", []))]
            statuses = [str(case.get("status") or "UNKNOWN").upper() for case in related]
            missing = [value for case in related for value in case.get("missing_evidence", [])]
            outcomes = [case.get("outcome") for case in related]
            timeframe_counts = []
            durations = []
            history = []
            for case in related:
                case_items = [item for item in items if str(item.get("observation_id")) in {str(value) for value in case.get("observation_ids", [])}]
                timeframe_counts.append(len({str(item.get("timeframe")) for item in case_items if item.get("timeframe")}))
                evidence_times = sorted((_time(item.get("observed_at")) for item in case_items), key=lambda x: x or datetime.min.replace(tzinfo=timezone.utc))
                valid_times = [value for value in evidence_times if value]
                durations.append((valid_times[-1] - valid_times[0]).total_seconds() if len(valid_times) > 1 else 0.0)
            for item in items:
                linked = by_observation.get(str(item.get("observation_id")), [])
                history.append({"timestamp": item.get("observed_at"), "observation_id": item.get("observation_id"), "observation_type": item.get("kind"), "timeframe": item.get("timeframe"), "case_ids": sorted(str(case.get("case_id")) for case in linked), "case_statuses": sorted({str(case.get("status")) for case in linked})})
            total = len(related)
            rate = lambda name: round(100 * statuses.count(name) / total, 3) if total else 0.0
            rules.append({
                "rule_id": rule_id, "version": version, "count": len(items),
                "first_occurrence": items[0].get("observed_at"), "last_occurrence": items[-1].get("observed_at"),
                "average_duration_seconds": _average(durations),
                "average_timeframes_per_case": _average(timeframe_counts),
                "timeframes": sorted({str(item.get("timeframe")) for item in items if item.get("timeframe")}),
                "most_common_missing_evidence": _most_common(missing), "most_common_outcomes": _most_common(outcomes),
                "status_distribution": _distribution(statuses), "invalidation_rate_percent": rate("INVALIDATED"),
                "confirmed_rate_percent": rate("CONFIRMED"), "closed_rate_percent": rate("CLOSED"),
                "average_lifetime_seconds": _average(_seconds(case.get("opened_at"), case.get("updated_at")) for case in related),
                "history": history,
            })

        clusters: dict[tuple[str, ...], dict[str, Any]] = {}
        for item in observations:
            linked = sorted(by_observation.get(str(item.get("observation_id")), []), key=lambda case: str(case.get("case_id", "")))
            case = linked[0] if linked else {}
            key = (str(item.get("kind") or "UNKNOWN"), str(item.get("rule_version") or "unknown"), str(case.get("outcome") or "UNRECORDED"), "|".join(sorted(str(x) for x in case.get("missing_evidence", []))) or "NONE", str(item.get("confidence", "UNRECORDED")), str(item.get("timeframe") or "UNKNOWN"))
            cluster = clusters.setdefault(key, {"observation_type": key[0], "rule_version": key[1], "outcome": key[2], "missing_evidence": [] if key[3] == "NONE" else key[3].split("|"), "stored_evidence_score": key[4], "timeframe": key[5], "count": 0, "observation_ids": [], "case_ids": []})
            cluster["count"] += 1
            cluster["observation_ids"].append(str(item.get("observation_id")))
            cluster["case_ids"].extend(str(value.get("case_id")) for value in linked)
        for cluster in clusters.values():
            cluster["observation_ids"] = sorted(set(cluster["observation_ids"]))
            cluster["case_ids"] = sorted(set(cluster["case_ids"]))

        cases_hour, cases_day = Counter(), Counter()
        for case in cases:
            opened = _time(case.get("opened_at"))
            if opened:
                cases_hour[opened.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:00Z")] += 1
                cases_day[opened.astimezone(timezone.utc).strftime("%Y-%m-%d")] += 1
        event_names = [str(item.get("event") or item.get("category") or "") for item in events]
        matches = lambda token: [item for item, name in zip(events, event_names) if token in name.upper()]
        result = {
            "schema_version": self.schema_version, "mode": "OBSERVE", "read_only": True,
            "dataset_hash": hashlib.sha256(canonical.encode()).hexdigest(),
            "source_counts": {"observations": len(observations), "research_cases": len(cases), "events": len(events)},
            "definitions": {"average_duration_seconds": "Average span between first and last persisted observation in each associated case.", "average_lifetime_seconds": "Average persisted updated_at minus opened_at for associated cases.", "stored_evidence_score": "Existing persisted observation confidence; never recalculated by analytics."},
            "rules": rules, "case_clusters": sorted(clusters.values(), key=lambda x: (x["observation_type"], x["rule_version"], x["outcome"], x["timeframe"], x["stored_evidence_score"])),
            "timeline": {"research_cases_per_hour": dict(sorted(cases_hour.items())), "research_cases_per_day": dict(sorted(cases_day.items())), "observation_frequency": _distribution(item.get("kind") for item in observations), "outcome_frequency": _distribution(case.get("outcome") for case in cases), "acceptance_events": matches("ACCEPTANCE"), "restart_events": matches("RESTART")},
            "data_quality": {"gap_events": len(matches("DATA_GAP")), "validator_events": len(matches("VALIDATION_CYCLE")) + len(matches("VALIDATOR_RECOVERY")), "governance_rejects": len(matches("GOVERNANCE_REJECT")), "replay_runs": len(matches("REPLAY")), "integrity_errors": len([item for item in events if "INTEGRITY" in str(item.get("event", "")).upper() and str(item.get("severity", "")).upper() in {"ERROR", "CRITICAL"}])},
        }
        return result

    @staticmethod
    def to_json(result: dict[str, Any]) -> str:
        return json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n"

    @staticmethod
    def to_csv(result: dict[str, Any]) -> str:
        output = io.StringIO(); writer = csv.writer(output, lineterminator="\n")
        writer.writerow(["section", "identifier", "metric", "value"])
        for rule in result.get("rules", []):
            identifier = f"{rule['rule_id']}@{rule['version']}"
            for key in ("count", "first_occurrence", "last_occurrence", "average_duration_seconds", "average_timeframes_per_case", "most_common_missing_evidence", "most_common_outcomes", "status_distribution", "invalidation_rate_percent", "confirmed_rate_percent", "closed_rate_percent", "average_lifetime_seconds"):
                value = rule.get(key); writer.writerow(["rule", identifier, key, json.dumps(value, sort_keys=True, ensure_ascii=False) if isinstance(value, (dict, list)) else value])
        for key, value in result.get("data_quality", {}).items(): writer.writerow(["data_quality", "all", key, value])
        for section, values in result.get("timeline", {}).items():
            if isinstance(values, dict):
                for key, value in values.items(): writer.writerow(["timeline", section, key, value])
        return output.getvalue()

    @staticmethod
    def to_markdown(result: dict[str, Any]) -> str:
        lines = ["# TIM Research Analytics", "", f"Dataset hash: `{result['dataset_hash']}`", "", "OBSERVE · READ-ONLY · deterministic statistics", "", "## Rule Analytics", "", "| Rule | Version | Count | Confirmed % | Invalidated % | Closed % |", "|---|---:|---:|---:|---:|---:|"]
        for rule in result.get("rules", []): lines.append(f"| {rule['rule_id']} | {rule['version']} | {rule['count']} | {rule['confirmed_rate_percent']} | {rule['invalidation_rate_percent']} | {rule['closed_rate_percent']} |")
        lines.extend(["", "## Data Quality Analytics", ""])
        lines.extend(f"- {key}: {value}" for key, value in result.get("data_quality", {}).items())
        return "\n".join(lines) + "\n"
