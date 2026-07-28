from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SHA256 = re.compile(r"^[0-9a-f]{64}$")


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def digest(value: Any) -> str:
    return hashlib.sha256((value if isinstance(value, bytes) else canonical(value).encode())).hexdigest()


def parse_time(value: Any) -> datetime | None:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (TypeError, ValueError):
        return None


class ResearchAuditEngine:
    """Read-only validator for persisted research artifacts."""

    schema_version = "1.0.0"
    generator_version = "1.0.0"
    ignored_names = {".gitkeep", "README.md"}
    ignored_directories = {"audit"}  # prevents recursive self-auditing

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def audit(self, *, as_of: datetime) -> dict[str, Any]:
        if as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        manifest = self._json(self.root / "config/core_manifest.json")
        if manifest.get("status") != "FROZEN" or manifest.get("operating_mode") != "OBSERVE":
            raise ValueError("frozen OBSERVE manifest required")
        research_root = self.root / "data/research"
        paths = sorted(
            path for path in research_root.rglob("*")
            if path.is_file() and path.name not in self.ignored_names and not self.ignored_directories.intersection(path.relative_to(research_root).parts)
        )
        records: list[dict[str, Any]] = []
        issues: list[dict[str, str]] = []
        report_metadata: dict[Path, dict[str, Any]] = {}
        for path in paths:
            relative = path.relative_to(self.root).as_posix()
            raw = path.read_bytes()
            record = {"path": relative, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "format": path.suffix.lower().lstrip(".") or "unknown", "status": "PASS"}
            try:
                if path.name.endswith(".md.json"):
                    value = json.loads(raw)
                    report_metadata[path] = value
                    self._validate_report_metadata(path, value, manifest, issues)
                elif path.suffix == ".json":
                    value = json.loads(raw)
                    if not isinstance(value, dict): raise ValueError("JSON root must be an object")
                    self._validate_common(relative, value, as_of, issues)
                    self._validate_declared_hash(relative, value, issues)
                elif path.suffix == ".jsonl":
                    lines = raw.decode().splitlines()
                    parsed = []
                    missing_documentation: dict[tuple[str, ...], int] = {}
                    for number, line in enumerate(lines, 1):
                        if not line.strip(): continue
                        value = json.loads(line)
                        if not isinstance(value, dict): raise ValueError(f"line {number} is not an object")
                        self._validate_common(f"{relative}:{number}", value, as_of, issues)
                        if path.name == "module_a_cache.jsonl":
                            missing = sorted({"schema_version", "generator_version", "artifact_hash"} - value.keys())
                            if missing:
                                key = tuple(missing); missing_documentation[key] = missing_documentation.get(key, 0) + 1
                        parsed.append(value)
                    for missing, count in sorted(missing_documentation.items()):
                        issues.append({"code":"MISSING_DOCUMENTATION","path":relative,"detail":f"{count} record(s) missing: {', '.join(missing)}"})
                    record["records"] = len(parsed)
                elif path.suffix == ".md" and path.parent.name == "module_b_reports" and not path.with_name(path.name + ".json").exists():
                    issues.append({"code": "MISSING_METADATA", "path": relative, "detail": "Markdown research artifact has no metadata sidecar."})
            except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
                record["status"] = "FAIL"
                issues.append({"code": "INVALID_ARTIFACT", "path": relative, "detail": str(exc)})
            records.append(record)
        for path, metadata in report_metadata.items():
            target = self._resolve_declared_path(metadata.get("file"))
            if not target or target not in paths:
                issues.append({"code": "MISSING_REPORT", "path": path.relative_to(self.root).as_posix(), "detail": "Metadata target is missing."})
        issue_paths = {item["path"].split(":", 1)[0] for item in issues}
        for record in records:
            if record["path"] in issue_paths: record["status"] = "FAIL"
        payload = {
            "schema_version": self.schema_version,
            "generator_version": self.generator_version,
            "generated_at": as_of.astimezone(timezone.utc).isoformat(),
            "generation_timestamp": as_of.astimezone(timezone.utc).isoformat(),
            "mode": "OBSERVE",
            "read_only": True,
            "core_version": manifest.get("core_version"),
            "component_versions": manifest.get("components", {}),
            "artifacts_checked": len(records),
            "artifacts_passed": sum(item["status"] == "PASS" for item in records),
            "artifacts_failed": sum(item["status"] != "PASS" for item in records),
            "artifacts": records,
            "issues": sorted(issues, key=lambda item: (item["path"], item["code"], item["detail"])),
        }
        payload["dataset_hash"] = digest({"manifest": manifest, "artifacts": records})
        payload["audit_hash"] = digest(payload)
        payload["status"] = "PASS" if not issues else "FAIL"
        payload["validation_status"] = payload["status"]
        payload["artifact_hash"] = digest(payload)
        return payload

    def _validate_report_metadata(self, path: Path, value: dict[str, Any], manifest: dict[str, Any], issues: list[dict[str, str]]) -> None:
        relative = path.relative_to(self.root).as_posix()
        required = {"report_id", "file", "input_hash", "artifact_hash", "schema_version", "generator_version", "provenance", "mode", "timestamp", "word_count"}
        missing = sorted(required - value.keys())
        if missing: issues.append({"code": "MISSING_DOCUMENTATION", "path": relative, "detail": ", ".join(missing)})
        self._validate_common(relative, value, datetime.max.replace(tzinfo=timezone.utc), issues)
        target = self._resolve_declared_path(value.get("file"))
        if not target or not target.is_file(): return
        content = target.read_bytes()
        if not SHA256.fullmatch(str(value.get("input_hash", ""))): issues.append({"code": "INVALID_INPUT_HASH", "path": relative, "detail": "input_hash is not SHA-256."})
        if hashlib.sha256(content).hexdigest() != value.get("artifact_hash"): issues.append({"code": "ARTIFACT_HASH_MISMATCH", "path": relative, "detail": target.name})
        if int(value.get("word_count", -1)) != len(content.decode().split()): issues.append({"code": "WORD_COUNT_MISMATCH", "path": relative, "detail": target.name})
        if value.get("schema_version") != "1.0.0" or value.get("generator_version") != "1.0.0": issues.append({"code": "VERSION_MISMATCH", "path": relative, "detail": "Unsupported report version."})

    @staticmethod
    def _validate_common(path: str, value: dict[str, Any], as_of: datetime, issues: list[dict[str, str]]) -> None:
        if value.get("mode") not in (None, "OBSERVE"):
            issues.append({"code": "MODE_VIOLATION", "path": path, "detail": str(value.get("mode"))})
        for key in ("timestamp", "created_at", "generated_at", "triggered_at"):
            if key not in value: continue
            parsed = parse_time(value[key])
            if parsed is None: issues.append({"code": "INVALID_TIMESTAMP", "path": path, "detail": key})
            elif parsed > as_of: issues.append({"code": "FUTURE_TIMESTAMP", "path": path, "detail": key})
        provenance = value.get("provenance")
        if provenance is not None and "DETERMINISTIC" not in str(provenance):
            issues.append({"code": "INVALID_PROVENANCE", "path": path, "detail": str(provenance)})

    @staticmethod
    def _validate_declared_hash(path: str, value: dict[str, Any], issues: list[dict[str, str]]) -> None:
        if "output_hash" in value:
            copy = dict(value); declared = str(copy.pop("output_hash"))
            if not SHA256.fullmatch(declared) or digest(copy) != declared: issues.append({"code": "OUTPUT_HASH_MISMATCH", "path": path, "detail": "output_hash"})
        if "snapshot_hash" in value:
            copy = dict(value); declared = str(copy.pop("snapshot_hash"))
            if not SHA256.fullmatch(declared) or digest(copy) != declared: issues.append({"code": "SNAPSHOT_HASH_MISMATCH", "path": path, "detail": "snapshot_hash"})
        if "report_hash" in value:
            copy = dict(value); declared = str(copy.pop("report_hash"))
            if not SHA256.fullmatch(declared) or digest(copy) != declared: issues.append({"code": "REPORT_HASH_MISMATCH", "path": path, "detail": "report_hash"})

    def _resolve_declared_path(self, value: Any) -> Path | None:
        if not value: return None
        path = Path(str(value)); resolved = (path if path.is_absolute() else self.root / path).resolve()
        return resolved if resolved == self.root or self.root in resolved.parents else None

    @staticmethod
    def _json(path: Path) -> dict[str, Any]:
        value = json.loads(path.read_text())
        if not isinstance(value, dict): raise ValueError(f"JSON object required: {path}")
        return value
