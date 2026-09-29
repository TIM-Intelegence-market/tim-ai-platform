"""Monitoring Agent V1: one read-only health report from existing TIM signals.

Contract (Constitution Band 5, Master Prompt 09), declared in ``SPEC``:
- Mission: bundle health signals that already exist into one report with a
  status per source (GREEN / YELLOW / RED / UNKNOWN) and its provenance.
- Reads: ``agent_infra.health.ToolHealthRegistry`` probes, the orchestrator's
  ``state.json`` and, when a manifest is given, the bugfixer readiness gate
  (``evaluate_readiness``). All of them are read-only.
- Never: restarts, repairs, releases, database access or trading. A GREEN
  report is not a release; readiness decisions stay with ``evaluate_readiness``.
- Replay: ``assess`` is a pure function of the collected snapshot; age checks
  use the snapshot's ``captured_at``, never the render time.

A missing or unreadable source is UNKNOWN, never GREEN.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from src.agent_infra.profiles import COMMON_FORBIDDEN
from src.agents.contract import AgentSpec

READ_SOURCES = "read_health_sources"
BUILD_REPORT = "build_health_report"
WRITE_REPORT = "write_health_report"

SPEC = AgentSpec(
    name="monitoring-agent",
    version="1.0.0",
    mission="Bundle existing TIM health signals into one read-only report with "
            "a status and provenance per source; never restart, repair or release.",
    owner="uezeyiraydin-cell",
    allowed_actions=(READ_SOURCES, BUILD_REPORT, WRITE_REPORT),
    tools=("tool_health_registry", "orchestration_state", "readiness_gate"),
    max_input_bytes=2 * 1024 * 1024,
    timeout_seconds=120,
    forbidden_actions=(*COMMON_FORBIDDEN, "release_approval", "repair_execution"),
)

SNAPSHOT_SCHEMA = "tim.monitoring.snapshot.v1"
REPORT_SCHEMA = "tim.monitoring.report.v1"
GREEN, YELLOW, RED, UNKNOWN = "GREEN", "YELLOW", "RED", "UNKNOWN"
_SEVERITY = (RED, UNKNOWN, YELLOW, GREEN)
DEFAULT_MAX_STATE_AGE_SECONDS = 900
_STATE_BOUND = 1024 * 1024


def _worst(statuses) -> str:
    statuses = list(statuses)
    for status in _SEVERITY:
        if status in statuses:
            return status
    return UNKNOWN


def _age_seconds(captured_at: str, observed: str | None) -> float | None:
    try:
        then = datetime.fromisoformat(str(observed).replace("Z", "+00:00"))
        now = datetime.fromisoformat(captured_at)
    except ValueError:
        return None
    if then.tzinfo is None:
        return None
    return (now - then).total_seconds()


def assess_tools(source: Mapping[str, Any]) -> dict[str, Any]:
    if source.get("collected") is not True:
        return {"status": UNKNOWN, "reasons": [source.get("reason", "nicht erhoben")], "items": {}}
    items = {}
    for name, entry in sorted(source["tools"].items()):
        state = entry.get("state")
        status = {"AVAILABLE": GREEN, "DEGRADED": YELLOW, "UNAVAILABLE": YELLOW}.get(state, UNKNOWN)
        items[name] = {"status": status, "state": state, "evidence": entry.get("evidence", ""),
                       "observed_at": entry.get("observed_at")}
    reasons = [f"{name}: {item['state']}" for name, item in items.items() if item["status"] != GREEN]
    return {"status": _worst(i["status"] for i in items.values()) if items else UNKNOWN,
            "reasons": reasons or ["alle Werkzeuge verfügbar"], "items": items}


def assess_orchestration(source: Mapping[str, Any], captured_at: str, max_age: float) -> dict[str, Any]:
    try:
        return _assess_orchestration(source, captured_at, max_age)
    except (TypeError, AttributeError, KeyError):
        return {"status": UNKNOWN, "reasons": ["Zustand hat ein unerwartetes Format"],
                "path": source.get("path")}


def _assess_orchestration(source: Mapping[str, Any], captured_at: str, max_age: float) -> dict[str, Any]:
    if source.get("collected") is not True:
        return {"status": UNKNOWN, "reasons": [source.get("reason", "nicht erhoben")],
                "path": source.get("path")}
    state = source["state"]
    health = state.get("last_health") or {}
    reasons, statuses = [], []
    if health.get("live_trading") is True or (health.get("trading_actions") or 0) > 0:
        statuses.append(RED)
        reasons.append("Live-Trading oder Trading-Aktionen gemeldet")
    if state.get("status") != "RUNNING" or state.get("phase") == "SAFE_STOP":
        statuses.append(RED)
        reasons.append(f"Orchestrator {state.get('status')} in Phase {state.get('phase')}")
    if state.get("blockers"):
        statuses.append(RED)
        reasons.append("Blocker: " + ", ".join(str(b) for b in state["blockers"][:10]))
    if health.get("infrastructure_ok") is False:
        statuses.append(RED)
        reasons.append("Infrastruktur nicht in Ordnung")
    age = _age_seconds(captured_at, state.get("updated_at"))
    if age is None:
        statuses.append(UNKNOWN)
        reasons.append("Zeitstempel des Zustands unlesbar")
    elif age > max_age:
        statuses.append(YELLOW)
        reasons.append(f"Zustand ist {int(age)} s alt (Grenze {int(max_age)} s)")
    if (health.get("unknown_errors") or 0) > 0:
        statuses.append(YELLOW)
        reasons.append(f"{health['unknown_errors']} unbekannte Fehler")
    return {"status": _worst(statuses) if statuses else GREEN,
            "reasons": reasons or [f"läuft in Phase {state.get('phase')}"],
            "path": source.get("path"), "phase": state.get("phase"),
            "updated_at": state.get("updated_at"), "revision": state.get("revision")}


def assess_readiness(source: Mapping[str, Any]) -> dict[str, Any]:
    if source.get("collected") is not True:
        return {"status": UNKNOWN, "reasons": [source.get("reason", "nicht erhoben")]}
    result = source["result"]
    if result.get("live_trading") is not False or result.get("execution") is not False:
        return {"status": RED, "reasons": ["Readiness meldet Live-Trading oder Ausführung"]}
    if result.get("LIVE_DATA_READINESS") == "PASS" and not result.get("blockers"):
        return {"status": GREEN, "reasons": ["Live-Daten-Freigabe laut Gate erlaubt"],
                "checked_at": result.get("checked_at")}
    return {"status": YELLOW,
            "reasons": ["keine Live-Daten-Freigabe: " + ", ".join(result.get("blockers") or ["SAFE_STOP"])],
            "checked_at": result.get("checked_at")}


def assess(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Pure function of the snapshot: the replayable core of the agent."""
    if snapshot.get("schema") != SNAPSHOT_SCHEMA:
        raise ValueError("unknown monitoring snapshot schema")
    captured_at = snapshot["captured_at"]
    sources = snapshot["sources"]
    max_age = snapshot.get("max_state_age_seconds", DEFAULT_MAX_STATE_AGE_SECONDS)
    report = {
        "tools": assess_tools(sources["tools"]),
        "orchestration": assess_orchestration(sources["orchestration"], captured_at, max_age),
        "readiness": assess_readiness(sources["readiness"]),
    }
    return {"schema": REPORT_SCHEMA, "captured_at": captured_at,
            "overall": _worst(entry["status"] for entry in report.values()),
            "sources": report,
            "note": "Nur lesender Bericht; GREEN ist keine Freigabe."}


def _read_json(path: Path) -> Any:
    with path.open("rb") as handle:
        data = handle.read(_STATE_BOUND + 1)
    if len(data) > _STATE_BOUND:
        raise ValueError("file exceeds bound")
    return json.loads(data)


def collect_snapshot(*, orchestration_state: Path | None = None,
                     readiness_manifest: Path | None = None, repo_root: Path | None = None,
                     tool_registry: Any | None = None, probe_tools: bool = True,
                     readiness: Callable[..., Mapping[str, Any]] | None = None,
                     clock: Callable[[], str] | None = None,
                     max_state_age_seconds: int = DEFAULT_MAX_STATE_AGE_SECONDS) -> dict[str, Any]:
    SPEC.authorize(READ_SOURCES)
    captured_at = (clock or (lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat()))()

    if probe_tools:
        if tool_registry is None:
            from src.agent_infra.health import ToolHealthRegistry
            tool_registry = ToolHealthRegistry()
        tools = {"collected": True, "tools": tool_registry.refresh()}
    else:
        tools = {"collected": False, "reason": "Werkzeug-Probes abgeschaltet"}

    if orchestration_state is None:
        orchestration = {"collected": False, "reason": "kein state.json angegeben"}
    else:
        try:
            state = _read_json(orchestration_state)
            if not isinstance(state, dict):
                raise ValueError("state is not an object")
            orchestration = {"collected": True, "path": str(orchestration_state), "state": state}
        except (OSError, ValueError) as error:
            orchestration = {"collected": False, "path": str(orchestration_state),
                             "reason": f"unlesbar: {type(error).__name__}"}

    if readiness_manifest is None:
        gate = {"collected": False, "reason": "kein Readiness-Manifest angegeben"}
    else:
        if readiness is None:
            from src.bugfixer.readiness import evaluate_readiness as readiness
        # evaluate_readiness never raises for bad evidence; it returns SAFE_STOP.
        gate = {"collected": True, "result": dict(readiness(readiness_manifest, repo_root=repo_root or Path.cwd()))}

    return {"schema": SNAPSHOT_SCHEMA, "captured_at": captured_at,
            "max_state_age_seconds": max_state_age_seconds,
            "sources": {"tools": tools, "orchestration": orchestration, "readiness": gate}}


def render_report(report: Mapping[str, Any]) -> str:
    lines = ["# TIM Health Report", "", f"Gesamt: `{report['overall']}` · erhoben `{report['captured_at']}`",
             "", f"> {report['note']}", ""]
    for name, entry in report["sources"].items():
        lines.append(f"## {name}: `{entry['status']}`")
        lines.extend(f"- {reason}" for reason in entry["reasons"])
        for tool, item in entry.get("items", {}).items():
            lines.append(f"  - {tool}: {item['status']} ({item['evidence']})")
        lines.append("")
    return "\n".join(lines)
