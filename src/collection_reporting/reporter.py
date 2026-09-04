from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


_COLLECTION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ACTIVE_STATUSES = ("PENDING", "RETRY", "PROCESSING", "QUARANTINED")


class CollectionReportError(RuntimeError):
    """Raised when a report cannot be produced without weakening safety."""


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(value if isinstance(value, bytes) else _canonical(value)).hexdigest()


def _utc(value: Any, name: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise CollectionReportError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise CollectionReportError(f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _count(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise CollectionReportError(f"{name} must be a non-negative integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise CollectionReportError(f"{name} must be a non-negative integer") from exc
    if result < 0 or result != value:
        raise CollectionReportError(f"{name} must be a non-negative integer")
    return result


class CollectionReportBuilder:
    """Build deterministic, observe-only collection evidence from supplied facts.

    The builder does not connect to a market source or database, repair gaps, or
    infer missing values.  Collection facts therefore remain independently
    auditable and the same input always produces the same result hash.
    """

    schema_version = "1.0.0"
    generator_version = "1.0.0"

    def build(self, facts: Mapping[str, Any]) -> dict[str, Any]:
        source = deepcopy(dict(facts))
        collection_id = str(source.get("collection_id", ""))
        if not _COLLECTION_ID.fullmatch(collection_id):
            raise CollectionReportError("collection_id contains unsafe characters")

        started_at = _utc(source.get("started_at"), "started_at")
        ended_at = _utc(source.get("ended_at"), "ended_at")
        if ended_at < started_at:
            raise CollectionReportError("ended_at cannot precede started_at")

        mode = str(source.get("mode", ""))
        trading_actions = _count(source.get("trading_actions", 0), "trading_actions")
        if mode != "OBSERVE" or trading_actions != 0 or source.get("live_trading") is not False:
            raise CollectionReportError("observe-only facts with live_trading=false are required")

        counts = self._counts(source.get("counts"))
        status_counts = self._status_counts(source.get("status_counts"))
        gaps = self._gaps(source.get("gaps", []))
        checks = self._checks(source, counts, status_counts, gaps)
        failures = sorted(name for name, value in checks.items() if value == "FAIL")
        warnings = sorted(name for name, value in checks.items() if value == "WARN")
        quality_status = "FAIL" if failures else "WARN" if warnings else "PASS"
        decision_status = "NO_DECISION" if failures else "LIMITED" if warnings else "DECISION_READY"
        traffic_light = "RED" if failures else "YELLOW" if warnings else "GREEN"
        autonomous_ready = not failures and not warnings

        normalized = {
            "schema_version": self.schema_version,
            "generator_version": self.generator_version,
            "collection_id": collection_id,
            "started_at": started_at,
            "ended_at": ended_at,
            "mode": mode,
            "data_source": str(source.get("data_source", "")),
            "symbol": str(source.get("symbol", "")),
            "expected_period": source.get("expected_period", {}),
            "actual_period": source.get("actual_period", {}),
            "code_version": str(source.get("code_version", "")),
            "config_version": str(source.get("config_version", "")),
            "counts": counts,
            "status_counts": status_counts,
            "gaps": gaps,
            "metrics": deepcopy(source.get("metrics", {})),
            "findings": deepcopy(source.get("findings", [])),
            "limitations": sorted({str(item) for item in source.get("limitations", [])}),
            "checks": checks,
            "quality_status": quality_status,
            "management_traffic_light": traffic_light,
            "decision_status": decision_status,
            "trading_actions": trading_actions,
            "live_trading": False,
            "tim_autonomous_collection_ready": autonomous_ready,
            "safety": "Historical observations do not guarantee future results. No trading authorization is granted.",
        }
        normalized["input_hash"] = _digest(source)
        normalized["result_hash"] = _digest(normalized)
        return normalized

    def write(self, root: Path, facts: Mapping[str, Any]) -> dict[str, Any]:
        result = self.build(facts)
        target = root.resolve() / "artifacts" / "collections" / result["collection_id"]
        artifacts = self._artifact_bytes(result)
        manifest = {
            "schema_version": self.schema_version,
            "generator_version": self.generator_version,
            "collection_id": result["collection_id"],
            "mode": "OBSERVE",
            "result_hash": result["result_hash"],
            "files": [
                {"path": name, "size": len(content), "sha256": _digest(content)}
                for name, content in sorted(artifacts.items())
            ],
        }
        manifest["manifest_hash"] = _digest(manifest)
        artifacts["manifest.json"] = self._json_bytes(manifest)

        if target.exists():
            self._verify_existing(target, artifacts)
            return {**result, "report_dir": str(target), "manifest": manifest, "resumed": True}

        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{result['collection_id']}.", dir=target.parent))
        try:
            for name, content in artifacts.items():
                path = staging / name
                path.write_bytes(content)
            os.replace(staging, target)
        except Exception:
            for path in staging.glob("*"):
                path.unlink(missing_ok=True)
            staging.rmdir()
            raise
        return {**result, "report_dir": str(target), "manifest": manifest, "resumed": False}

    @staticmethod
    def _counts(value: Any) -> dict[str, int]:
        if not isinstance(value, Mapping):
            raise CollectionReportError("counts object is required")
        required = ("events_received", "events_unique", "events_processed", "duplicates", "invalid_events")
        return {name: _count(value.get(name), f"counts.{name}") for name in required}

    @staticmethod
    def _status_counts(value: Any) -> dict[str, int]:
        if not isinstance(value, Mapping):
            raise CollectionReportError("status_counts object is required")
        return {name: _count(value.get(name, 0), f"status_counts.{name}") for name in ("COMPLETED", *_ACTIVE_STATUSES)}

    @staticmethod
    def _gaps(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            raise CollectionReportError("gaps must be a list")
        result = []
        for index, gap in enumerate(value):
            if not isinstance(gap, Mapping) or not gap.get("status") or not gap.get("reason"):
                raise CollectionReportError(f"gaps[{index}] requires status and reason")
            result.append(dict(gap))
        return sorted(result, key=lambda item: _canonical(item))

    @staticmethod
    def _checks(source: Mapping[str, Any], counts: Mapping[str, int], statuses: Mapping[str, int], gaps: list[dict[str, Any]]) -> dict[str, str]:
        received = counts["events_received"]
        accounted = counts["events_unique"] + counts["duplicates"] + counts["invalid_events"]
        open_gaps = [item for item in gaps if str(item["status"]).upper() not in {"RESOLVED", "IRREPARABLE_DOCUMENTED"}]
        determinism = source.get("determinism", {})
        preflight = source.get("preflight", {})
        return {
            "counts_accounted": "PASS" if received == accounted else "FAIL",
            "all_unique_events_processed": "PASS" if counts["events_processed"] == counts["events_unique"] else "FAIL",
            "queue_drained": "PASS" if sum(statuses[name] for name in _ACTIVE_STATUSES) == 0 else "WARN",
            "no_processing_leases": "PASS" if statuses["PROCESSING"] == 0 else "FAIL",
            "no_terminal_blockers": "PASS" if statuses["QUARANTINED"] == 0 else "FAIL",
            "no_retries": "PASS" if statuses["RETRY"] == 0 else "WARN",
            "gaps_classified": "PASS" if not open_gaps else "FAIL",
            "deterministic_replay": "PASS" if determinism.get("status") == "PASS" and determinism.get("first_hash") == determinism.get("second_hash") and bool(determinism.get("first_hash")) else "FAIL",
            "database_healthy": "PASS" if preflight.get("database") == "PASS" else "FAIL",
            "single_main_process": "PASS" if preflight.get("main_processes") == 1 else "FAIL",
            "no_parallel_jobs": "PASS" if preflight.get("parallel_jobs") == 0 else "FAIL",
            "logs_healthy": "PASS" if preflight.get("logs") == "PASS" else "FAIL",
            "storage_healthy": "PASS" if preflight.get("storage") == "PASS" else "FAIL",
            "no_orphaned_leases": "PASS" if preflight.get("orphaned_leases", 0) == 0 else "FAIL",
            "collection_metrics_scoped": "PASS" if source.get("metrics_scoped") is True else "WARN",
        }

    def _artifact_bytes(self, result: Mapping[str, Any]) -> dict[str, bytes]:
        quality = {
            "collection_id": result["collection_id"],
            "quality_status": result["quality_status"],
            "checks": result["checks"],
            "input_hash": result["input_hash"],
            "result_hash": result["result_hash"],
        }
        gaps = {"collection_id": result["collection_id"], "gaps": result["gaps"]}
        return {
            "management_summary.md": self._management(result).encode(),
            "technical_report.md": self._technical(result).encode(),
            "collection_result.json": self._json_bytes(result),
            "data_quality.json": self._json_bytes(quality),
            "gaps.json": self._json_bytes(gaps),
        }

    @staticmethod
    def _management(result: Mapping[str, Any]) -> str:
        findings = result.get("findings") or ["Für diesen Lauf wurden keine belastbaren Marktbeobachtungen angegeben."]
        limitations = result.get("limitations") or ["Keine zusätzlichen Einschränkungen dokumentiert."]
        lines = [
            f"# TIM Entscheidungsträger-Bericht – {result['collection_id']}", "",
            f"**Ampel:** {result['management_traffic_light']}",
            f"**Entscheidungsstatus:** {result['decision_status']}",
            f"**Zeitraum:** {result['started_at']} bis {result['ended_at']}",
            f"**Datenquelle / Markt:** {result['data_source']} / {result['symbol']}", "",
            "## Fakten", "",
            f"- Empfangen: {result['counts']['events_received']}",
            f"- Eindeutig: {result['counts']['events_unique']}",
            f"- Verarbeitet: {result['counts']['events_processed']}",
            f"- Duplikate: {result['counts']['duplicates']}",
            f"- Ungültig: {result['counts']['invalid_events']}", "",
            "## Beobachtungen", "", *[f"- {item}" for item in findings], "",
            "## Unsicherheit und Einschränkungen", "", *[f"- {item}" for item in limitations], "",
            "## Empfehlung", "",
            "- Datenbasierte Entscheidung möglich." if result["decision_status"] == "DECISION_READY" else "- NO_DECISION: Keine operative Entscheidung treffen, bis alle Qualitätsabweichungen geklärt sind.",
            "- Diese Auswertung erteilt keine Freigabe für echtes Trading.", "",
            "Historische Daten garantieren keine zukünftigen Ergebnisse. Markt-, Liquiditäts- und Ausführungsrisiken bleiben bestehen.", "",
        ]
        return "\n".join(lines)

    @staticmethod
    def _technical(result: Mapping[str, Any]) -> str:
        lines = [
            f"# TIM Technischer Nachweis – {result['collection_id']}", "",
            f"- Schema: {result['schema_version']}",
            f"- Generator: {result['generator_version']}",
            f"- Code-Version: {result['code_version']}",
            f"- Config-Version: {result['config_version']}",
            f"- Input-Hash: `{result['input_hash']}`",
            f"- Ergebnis-Hash: `{result['result_hash']}`",
            f"- Modus: {result['mode']}",
            f"- Trading-Aktionen: {result['trading_actions']}", "",
            "## Status-Counts", "",
        ]
        lines.extend(f"- {name}: {value}" for name, value in result["status_counts"].items())
        lines.extend(["", "## Qualitäts-Gates", ""])
        lines.extend(f"- {name}: {value}" for name, value in sorted(result["checks"].items()))
        lines.extend(["", "## Bekannte Einschränkungen", ""])
        lines.extend(f"- {item}" for item in (result.get("limitations") or ["Keine angegeben."]))
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _json_bytes(value: Any) -> bytes:
        return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n").encode()

    @staticmethod
    def _verify_existing(target: Path, expected: Mapping[str, bytes]) -> None:
        actual_names = {path.name for path in target.iterdir() if path.is_file()}
        if actual_names != set(expected):
            raise CollectionReportError("existing collection artifact set differs; refusing overwrite")
        for name, content in expected.items():
            if (target / name).read_bytes() != content:
                raise CollectionReportError(f"existing artifact differs; refusing overwrite: {name}")
