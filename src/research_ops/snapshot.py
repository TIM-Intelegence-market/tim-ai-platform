from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any

from src.research_ops.audit import digest


class MonthlyResearchSnapshot:
    """Builds a deterministic descriptive month record from supplied facts."""

    schema_version = "1.0.0"
    generator_version = "1.0.0"

    def build(self, *, month: str, as_of: datetime, manifest: dict[str, Any], counts: dict[str, int], coverage: dict[str, Any], replay: dict[str, Any], quality: dict[str, Any], insights: dict[str, Any]) -> dict[str, Any]:
        if as_of.tzinfo is None: raise ValueError("as_of must be timezone-aware")
        if len(month) != 7 or month[4] != "-": raise ValueError("month must use YYYY-MM")
        if manifest.get("status") != "FROZEN" or manifest.get("operating_mode") != "OBSERVE": raise ValueError("frozen OBSERVE manifest required")
        if any(int(value) < 0 for value in counts.values()): raise ValueError("counts cannot be negative")
        completed = as_of.astimezone(timezone.utc).strftime("%Y-%m") > month
        status = "FINAL" if completed else "IN_PROGRESS"
        open_issues = sorted({item.get("code", "UNKNOWN") for item in quality.get("issues", [])} | set(insights.get("warnings", [])))
        orderflow_total=int(counts.get("orderflow_observations",0));validated=int(counts.get("validated_cases",0));open_cases=max(0,orderflow_total-validated)
        validation_coverage=(Decimal(validated)*100/Decimal(orderflow_total)).quantize(Decimal("0.001"),rounding=ROUND_HALF_EVEN) if orderflow_total else Decimal("0")
        quality_checks=quality.get("checks",{});required_meta=("artifact_hash","generator_version","schema_version","dataset_hash","generation_timestamp","validation_status")
        hash_valid=lambda value:isinstance(value,str) and len(value)==64 and all(char in "0123456789abcdef" for char in value)
        health_checks={
            "replay": "PASS" if replay.get("status")=="PASS" else "FAIL",
            "dataset_hash": "PASS" if hash_valid(insights.get("input_hash")) else "FAIL",
            "output_hash": "PASS" if hash_valid(insights.get("output_hash")) else "FAIL",
            "schema_version": "PASS" if self.schema_version=="1.0.0" else "FAIL",
            "generator_version": "PASS" if self.generator_version=="1.0.0" else "FAIL",
            "forward_only": "PASS" if quality_checks.get("forward_only") is True else "FAIL",
            "observe_only": "PASS" if quality_checks.get("observe_only") is True and insights.get("mode")=="OBSERVE" else "FAIL",
            "data_gap_status": "PASS" if not quality.get("known_data_gaps") else "OPEN",
            "coverage_reported": "PASS" if coverage.get("coverage_percent") is not None else "FAIL",
            "validated_cases_reported": "PASS",
            "new_artifact_provenance": "PASS" if all(all(source.get(key) for key in required_meta) for source in (quality,)) else "FAIL",
        }
        health_deviations=sorted(key for key,value in health_checks.items() if value!="PASS")
        payload = {
            "schema_version":self.schema_version,"generator_version":self.generator_version,"snapshot_name":f"TIM Core 1.0 — Research Snapshot {month}","snapshot_month":month,"snapshot_status":status,"generated_at":as_of.astimezone(timezone.utc).isoformat(),"generation_timestamp":as_of.astimezone(timezone.utc).isoformat(),
            "mode":"OBSERVE","core_manifest_hash":digest(manifest),"versions":{"core":manifest.get("core_version"),**manifest.get("components",{})},"counts":dict(sorted(counts.items())),"coverage":coverage,"replay":replay,
            "research_results":{"eligibility_status":insights.get("eligibility_status"),"result_status":insights.get("result_status"),"sample_maturity":insights.get("result_status"),"observations":orderflow_total,"fully_validated_cases":validated,"open_cases":open_cases,"validation_coverage_percent":format(validation_coverage,"f"),"minimum_required":insights.get("eligibility",{}).get("minimum_required",1000),"outcome_groups":len(insights.get("outcome_distribution",[])),"dataset_hash":insights.get("input_hash")},
            "data_quality":{"status":quality.get("status"),"report_hash":quality.get("report_hash"),"known_data_gaps":quality.get("known_data_gaps",[]),"issue_count":len(quality.get("issues",[]))},
            "scientific_health":{"status":"PASS" if not health_deviations else "OPEN_ISSUES","checks":health_checks,"deviations":health_deviations,"output_hash":insights.get("output_hash")},
            "review_criteria":{"minimum_validated_cases":1000,"minimum_contiguous_coverage_percent":"95.000","validated_cases_observed":validated,"coverage_percent_observed":coverage.get("coverage_percent"),"new_data_gaps_observed":len(quality.get("known_data_gaps",[]))},
            "known_limitations":open_issues,"open_points":open_issues,
            "future_research_recommendations":["Continue unchanged Core 1.0 evidence collection.","Resolve and document integrity findings before treating insights as eligible.","Generate the final month snapshot only after the UTC month has ended."],
            "safety":"No forecasts, confidence scores, signals, orders, execution, or strategy recommendations.",
        }
        payload["dataset_hash"] = insights.get("input_hash")
        payload["validation_status"] = quality.get("status", "UNKNOWN")
        payload["artifact_hash"] = digest(payload)
        payload["snapshot_hash"] = digest(payload)
        return payload

    @staticmethod
    def to_markdown(snapshot: dict[str, Any]) -> str:
        counts = snapshot["counts"]; coverage = snapshot["coverage"]; research = snapshot["research_results"]
        lines = [
            f"# {snapshot['snapshot_name']}", "",
            f"**Status:** {snapshot['snapshot_status']}  ", f"**Generated:** {snapshot['generated_at']}  ", f"**Mode:** OBSERVE-only  ",
            f"**Snapshot hash:** `{snapshot['snapshot_hash']}`", "", "## Summary", "",
            f"- Persisted AggTrades: {counts.get('agg_trades', 0)}",
            f"- Candles: {counts.get('candles', 0)}",
            f"- Observations: {counts.get('observations', 0)}",
            f"- Orderflow observations: {counts.get('orderflow_observations', 0)}",
            f"- Fully validated cases: {research.get('fully_validated_cases', 0)}",
            f"- Open cases: {research.get('open_cases', 0)}",
            f"- Validation coverage: {research.get('validation_coverage_percent', '0')}%",
            f"- Sample maturity: {research.get('sample_maturity')}",
            f"- Research eligibility: {research.get('eligibility_status')}", "", "## Data coverage", "",
            f"- Basis: {coverage.get('basis')}", f"- Expected intervals: {coverage.get('expected_intervals')}", f"- Observed intervals: {coverage.get('observed_intervals')}", f"- Coverage: {coverage.get('coverage_percent')}%", f"- Missing intervals: {coverage.get('missing_intervals')}", "",
            "## Known limitations and open points", "",
        ]
        lines.extend(f"- {item}" for item in snapshot.get("open_points", []))
        lines.extend(["", "## Scientific health", ""])
        lines.extend(f"- {key}: {value}" for key,value in sorted(snapshot.get("scientific_health",{}).get("checks",{}).items()))
        lines.extend(["", "## Future research", ""])
        lines.extend(f"- {item}" for item in snapshot.get("future_research_recommendations", []))
        lines.extend(["", snapshot["safety"], ""])
        return "\n".join(lines)
