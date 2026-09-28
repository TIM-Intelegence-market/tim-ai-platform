"""Lightweight JSON-schema validation for the analysis output.

No third-party dependency is introduced; the validator checks the structural
contract (required keys, enum values, audit invariants) that the pipeline
promises. The reference schema is stored alongside the module.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).with_name("schemas") / "analysis_output_v1.json"

REQUIRED_ROOT = [
    "schema_version",
    "analysis_id",
    "timestamp",
    "symbol",
    "venue",
    "market_type",
    "timeframe",
    "mode",
    "data_quality",
    "market_state",
    "auction_state",
    "orderflow",
    "scenarios",
    "decision",
    "report_text",
    "audit",
]
ALLOWED_MODES = {"OBSERVE", "RESEARCH", "SIMULATE", "PAPER", "SHADOW"}
ALLOWED_QUALITY = {"PASS", "PARTIAL", "INSUFFICIENT_DATA"}
ALLOWED_DECISION = {"NO_TRADE", "TRADE_PLAN"}


def _require_keys(node: Any, keys: list[str], path: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(node, dict):
        errors.append(f"{path}: expected object")
        return errors
    for key in keys:
        if key not in node:
            errors.append(f"{path}: missing '{key}'")
    return errors


def validate_analysis(output: dict[str, Any]) -> tuple[bool, list[str]]:
    errors = _require_keys(output, REQUIRED_ROOT, "root")
    if errors:
        return False, errors

    if output.get("mode") not in ALLOWED_MODES:
        errors.append(f"root.mode={output.get('mode')} not allowed")
    if output.get("schema_version") != "1.0.0":
        errors.append(f"root.schema_version={output.get('schema_version')}")

    dq = output.get("data_quality")
    if isinstance(dq, dict):
        if dq.get("status") not in ALLOWED_QUALITY:
            errors.append(f"data_quality.status={dq.get('status')}")
        errors.extend(_require_keys(dq, ["confidence", "missing_fields", "estimated_fields", "problems"], "data_quality"))
    else:
        errors.append("data_quality: expected object")

    decision = output.get("decision")
    if isinstance(decision, dict):
        if decision.get("status") not in ALLOWED_DECISION:
            errors.append(f"decision.status={decision.get('status')}")
        if decision.get("status") == "NO_TRADE" and decision.get("trade_plan") is not None:
            errors.append("decision: NO_TRADE must have trade_plan == null")
        if decision.get("status") == "TRADE_PLAN" and decision.get("trade_plan") is None:
            errors.append("decision: TRADE_PLAN requires trade_plan")
    else:
        errors.append("decision: expected object")

    audit = output.get("audit")
    if isinstance(audit, dict):
        if audit.get("live_execution") is not False:
            errors.append("audit.live_execution must be false")
        errors.extend(_require_keys(audit, ["mode", "kill_switch_enabled", "inputs"], "audit"))
    else:
        errors.append("audit: expected object")

    return not errors, errors


def load_reference_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))