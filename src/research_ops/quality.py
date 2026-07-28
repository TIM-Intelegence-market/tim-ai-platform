from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.research_ops.audit import canonical, digest, parse_time


class ResearchQualityEngine:
    """Deterministic quality assessment; it never repairs source data."""

    schema_version = "1.0.0"
    generator_version = "1.0.0"

    def assess(self, root: Path, audit: dict[str, Any], *, as_of: datetime) -> dict[str, Any]:
        if as_of.tzinfo is None: raise ValueError("as_of must be timezone-aware")
        root = root.resolve(); issues = []; records_checked = 0; gap_events = []; timestamps: dict[str, list[datetime]] = {}
        sources = [root / "data/operational/events.jsonl", root / "data/operational/metrics.jsonl", root / "data/research/trigger_events.jsonl"]
        for path in sources:
            sequence = []
            try: lines = path.read_text().splitlines()
            except OSError:
                issues.append({"code":"MISSING_SOURCE","path":path.relative_to(root).as_posix(),"detail":"File unavailable"}); continue
            for number, line in enumerate(lines, 1):
                if not line.strip(): continue
                records_checked += 1
                try: value = json.loads(line)
                except ValueError:
                    issues.append({"code":"INVALID_SCHEMA","path":f"{path.relative_to(root)}:{number}","detail":"Invalid JSON"}); continue
                if not isinstance(value, dict):
                    issues.append({"code":"INVALID_SCHEMA","path":f"{path.relative_to(root)}:{number}","detail":"Object required"}); continue
                raw_time = next((value.get(key) for key in ("timestamp","recorded_at","triggered_at","checked_at") if value.get(key)), None)
                if raw_time is not None:
                    parsed = parse_time(raw_time)
                    if parsed is None: issues.append({"code":"INVALID_TIMESTAMP","path":f"{path.relative_to(root)}:{number}","detail":str(raw_time)})
                    else:
                        sequence.append(parsed)
                        if parsed > as_of: issues.append({"code":"FUTURE_TIMESTAMP","path":f"{path.relative_to(root)}:{number}","detail":parsed.isoformat()})
                if str(value.get("event") or value.get("category") or "").upper() == "DATA_GAP": gap_events.append({"path":path.relative_to(root).as_posix(),"line":number,"timestamp":raw_time})
                if value.get("mode") not in (None,"OBSERVE"): issues.append({"code":"MODE_VIOLATION","path":f"{path.relative_to(root)}:{number}","detail":str(value.get("mode"))})
            timestamps[path.relative_to(root).as_posix()] = sequence
        for path, sequence in timestamps.items():
            if any(current < previous for previous, current in zip(sequence, sequence[1:])):
                issues.append({"code":"TIMESTAMP_ORDER_VIOLATION","path":path,"detail":"Persisted sequence is not forward-only."})
        state = self._load(root / "data/operational/state.json", issues, root)
        health = state.get("health_monitor", {}) if isinstance(state, dict) else {}
        checks = health.get("checks", {}) if isinstance(health, dict) else {}
        if checks.get("candle_sequence_gap_free") is False and not gap_events:
            issues.append({"code":"UNDOCUMENTED_DATA_GAP","path":"data/operational/state.json","detail":"Health reports a gap without a DATA_GAP event."})
        if checks.get("provenance_deterministic") is False:
            issues.append({"code":"PROVENANCE_INCOMPLETE","path":"data/operational/state.json","detail":"Acceptance provenance check is false."})
        issues.extend({"code":item["code"],"path":item["path"],"detail":item["detail"]} for item in audit.get("issues", []))
        payload = {
            "schema_version":self.schema_version,"generator_version":self.generator_version,"generated_at":as_of.astimezone(timezone.utc).isoformat(),"generation_timestamp":as_of.astimezone(timezone.utc).isoformat(),"mode":"OBSERVE","read_only_sources":True,
            "status":"PASS" if not issues else "FAIL","records_checked":records_checked,"audit_status":audit.get("status"),"audit_hash":audit.get("audit_hash"),
            "known_data_gaps":gap_events,"issues":sorted(issues,key=lambda x:(x["path"],x["code"],x["detail"])),
            "checks":{"schema_valid":not any(x["code"]=="INVALID_SCHEMA" for x in issues),"timestamp_integrity":not any("TIMESTAMP" in x["code"] for x in issues),"forward_only":not any(x["code"]=="TIMESTAMP_ORDER_VIOLATION" for x in issues),"deterministic":audit.get("status")=="PASS","observe_only":not any(x["code"]=="MODE_VIOLATION" for x in issues),"data_gaps_documented":not any(x["code"]=="UNDOCUMENTED_DATA_GAP" for x in issues)},
        }
        payload["input_hash"] = digest({"audit_hash":audit.get("audit_hash"),"sources":{path: [value.isoformat() for value in values] for path,values in sorted(timestamps.items())},"state":state})
        payload["dataset_hash"] = audit.get("dataset_hash")
        payload["validation_status"] = payload["status"]
        payload["artifact_hash"] = digest(payload)
        payload["report_hash"] = digest(payload)
        return payload

    @staticmethod
    def _load(path:Path,issues:list[dict[str,str]],root:Path)->dict[str,Any]:
        try:
            value=json.loads(path.read_text())
            if not isinstance(value,dict):raise ValueError("Object required")
            return value
        except (OSError,ValueError) as exc:
            issues.append({"code":"INVALID_SCHEMA","path":path.relative_to(root).as_posix(),"detail":str(exc)});return {}
