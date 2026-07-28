from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import canonical_json
from .security import safe_output_path


def _write(relative: str, content: str) -> Path:
    path = safe_output_path(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def persist_scan(scan: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, str]:
    event_path = safe_output_path("artifacts/tim_manager/events/project_events.jsonl")
    event_path.parent.mkdir(parents=True, exist_ok=True)
    existing = set()
    if event_path.exists():
        for line in event_path.read_text(encoding="utf-8").splitlines():
            try:
                existing.add(json.loads(line)["event_id"])
            except (json.JSONDecodeError, KeyError):
                continue
    with event_path.open("a", encoding="utf-8") as handle:
        for event in scan["events"]:
            if event["event_id"] not in existing:
                handle.write(canonical_json(event) + "\n")
                existing.add(event["event_id"])
    scan_path = _write(f"artifacts/tim_manager/scans/{scan['scan_id']}.json", json.dumps(scan, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    current = _write("artifacts/tim_manager/snapshots/current.json", json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    versioned = _write(f"artifacts/tim_manager/snapshots/{snapshot['snapshot_id']}.json", json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    reports = generate_reports(snapshot)
    return {"scan": str(scan_path), "current_snapshot": str(current), "versioned_snapshot": str(versioned), **reports}


def generate_reports(snapshot: dict[str, Any]) -> dict[str, str]:
    sources = snapshot["source_health"]
    modules = snapshot["module_states"]
    risks = snapshot["risks"]
    contradictions = snapshot.get("contradictions", [])
    unknowns = snapshot["known_unknowns"]
    current_status = [
        "# TIM Intelligence Manager — Current Status",
        "",
        f"- Snapshot: `{snapshot['snapshot_id']}`",
        f"- Data state: `{snapshot['generated_at_utc']}`",
        f"- Repository status: `{snapshot['repository_status']}`",
        f"- Repository commit: `{snapshot['repository_commit']}`",
        f"- Authoritative Git repository: `{snapshot['authoritative_git_repository']}`",
        f"- Content manifest hash: `{snapshot['content_manifest_hash']}`",
        (
            "- Parent Git context (non-authoritative): "
            f"`{snapshot['parent_git_context'].get('git_root')}` at "
            f"`{snapshot['parent_git_context'].get('commit')}`"
        ),
        "- Global progress: not reliably computable; no weighting is configured.",
        "",
        "## Source health",
        "",
    ]
    current_status.extend(f"- `{item['source_id']}`: **{item['status'].upper()}** ({item['freshness_status']})" for item in sources)
    current_status.extend(["", "## Module states", ""])
    current_status.extend(
        f"- **{item['name']}**: `{item['status']}` — evidence: {len(item['evidence_refs'])}; failed criteria: {', '.join(item['failed_criteria']) or 'none'}"
        for item in modules
    )
    current_status.extend(["", "## Risks", ""])
    current_status.extend(f"- `{item['severity']}` {item['title']}" for item in risks)
    if not risks:
        current_status.append("- No source-derived risks in this snapshot. This is not a claim that TIM has no risks.")
    current_status.extend(["", "## Contradictions", ""])
    current_status.extend(
        (
            f"- **{item['subject']}.{item['predicate']}**: "
            f"{' vs '.join(str(claim['value']) for claim in item['claims'])} "
            f"— `{item['resolution_status']}`; evidence: "
            f"{', '.join(reference for claim in item['claims'] for reference in claim['evidence_refs'])}"
        )
        for item in contradictions
    )
    if not contradictions:
        current_status.append("- No deterministic contradiction was extracted.")
    current_status.extend(["", "## Known unknowns", ""])
    current_status.extend(f"- {item}" for item in unknowns)
    if not unknowns:
        current_status.append("- No required-source unknowns were detected; semantic completeness is not implied.")
    current_status.extend(["", "## Evidence", "", "- Canonical artifact references are stored in `artifacts/tim_manager/snapshots/current.json`."])
    current_path = _write("artifacts/tim_manager/reports/current_status.md", "\n".join(current_status) + "\n")

    changes = snapshot["recent_changes"]
    brief = [
        "# TIM Intelligence Manager — Executive Brief", "",
        f"Snapshot: `{snapshot['snapshot_id']}`", "",
        "## 1. What changed?", f"{len(changes)} source change event(s) were observed in this scan.", "",
        "## 2. What was verified?",
        f"{sum(item['status'] == 'verified' for item in modules)} module(s) meet the configured evidence-presence criteria. Test execution is reported separately.", "",
        "## 3. What is asserted but not proven?",
        "Narrative documents remain documentation-tier evidence and do not independently complete a module.", "",
        "## 4. New risks", f"{len(risks)} open source-coverage risk(s); {len(contradictions)} contradiction(s).", "",
        "## 5. Decisions pending", "No deterministic human decision record was extracted.", "",
        "## 6. Missing sources", ", ".join(item["source_id"] for item in sources if item["status"] == "missing") or "No required configured filesystem source is missing.", "",
        "## 7. Next safe step", "Review unresolved risks and run the executable validation suite before making a release claim.", "",
    ]
    brief_path = _write("artifacts/tim_manager/reports/executive_brief.md", "\n".join(brief))

    coverage = ["# TIM-IM Source Coverage", "", "| Source | Required | Status | Freshness | Errors |", "|---|---:|---|---|---|"]
    coverage.extend(f"| {item['source_id']} | {item['required']} | {item['status']} | {item['freshness_status']} | {', '.join(item['errors'])} |" for item in sources)
    coverage_path = _write("artifacts/tim_manager/reports/source_coverage.md", "\n".join(coverage) + "\n")

    risk_lines = ["# TIM-IM Risk Report", "", "Only source-derived risks are listed.", ""]
    risk_lines.extend(f"## {item['risk_id']}\n\n- Priority: {item['severity']}\n- Status: {item['status']}\n- Impact: {item['impact']}\n- Evidence: {', '.join(item['evidence_refs'])}\n" for item in risks)
    if not risks:
        risk_lines.append("No source-derived risk records were produced. Coverage limitations still apply.")
    risk_path = _write("artifacts/tim_manager/reports/risk_report.md", "\n".join(risk_lines) + "\n")
    return {"current_status": str(current_path), "executive_brief": str(brief_path), "source_coverage": str(coverage_path), "risk_report": str(risk_path)}


def load_snapshot(path: Path | None = None) -> dict[str, Any]:
    target = path or safe_output_path("artifacts/tim_manager/snapshots/current.json")
    return json.loads(target.read_text(encoding="utf-8"))


def diff_snapshots(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    old_artifacts = {item["normalized_path"]: item for item in old["artifacts"]}
    new_artifacts = {item["normalized_path"]: item for item in new["artifacts"]}
    old_state = {item["module_id"]: item["status"] for item in old["module_states"]}
    new_state = {item["module_id"]: item["status"] for item in new["module_states"]}
    module_changes = [
        {"module_id": module_id, "old": old_state.get(module_id), "new": new_state.get(module_id)}
        for module_id in sorted(set(old_state) | set(new_state))
        if old_state.get(module_id) != new_state.get(module_id)
    ]
    return {
        "old_snapshot": old["snapshot_id"], "new_snapshot": new["snapshot_id"],
        "added": sorted(set(new_artifacts) - set(old_artifacts)),
        "removed": sorted(set(old_artifacts) - set(new_artifacts)),
        "changed": sorted(path for path in set(old_artifacts) & set(new_artifacts) if old_artifacts[path]["content_hash"] != new_artifacts[path]["content_hash"]),
        "module_status_changes": module_changes,
    }
