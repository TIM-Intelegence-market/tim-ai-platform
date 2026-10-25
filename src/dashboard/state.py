from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from src.analytics.research import ResearchAnalyticsEngine
from src.dashboard.operations import build_operations_snapshot
from src.insights import ResearchInsightsEngine

from src.dashboard.constants import ALLOWED_TIMELINE_EVENTS, CHART_CANDLE_LIMIT, DASHBOARD_VERSION, VISIBLE_LIMIT
from src.dashboard.helpers import _parse_time

@dataclass(slots=True)
class DashboardState:
    market_status: dict[str, Any] = field(default_factory=lambda: {"status": "STARTING"})
    active_observations: list[dict] = field(default_factory=list)
    research_cases: list[dict] = field(default_factory=list)
    orderflow_observations: list[dict] = field(default_factory=list)
    orderflow_validations: list[dict] = field(default_factory=list)
    orderflow_validations_long: list[dict] = field(default_factory=list)
    derived_candles: dict[str, list[dict]] = field(default_factory=dict)
    system_health: dict[str, Any] = field(default_factory=lambda: {
        "database": "unknown",
        "stream": "unknown",
        "queue_depth": 0,
        "queue_model": "DIRECT_AWAIT_NO_APPLICATION_QUEUE",
        "ollama_enabled": False,
        "ollama_availability": "DISABLED_BY_POLICY",
    })
    memory_status: dict[str, Any] = field(default_factory=lambda: {"observations": 0})
    news: dict[str, Any] = field(default_factory=lambda: {"status": "PLACEHOLDER", "items": []})
    recent_candles: list[dict] = field(default_factory=list)
    # Per-timeframe candles for the /chart page (recent_candles mixes timeframes).
    chart_candles: dict[str, list[dict]] = field(default_factory=dict)
    validator_path: Path = field(default_factory=lambda: Path("data/operational/state.json"))
    events_path: Path = field(default_factory=lambda: Path("data/operational/events.jsonl"))
    readiness_path: Path = field(default_factory=lambda: Path("data/research/status/tim_v1_readiness.json"))
    audit_path: Path = field(default_factory=lambda: Path("data/research/audit/latest.json"))
    quality_path: Path = field(default_factory=lambda: Path("data/research/quality/latest.json"))
    core_manifest_path: Path = field(default_factory=lambda: Path("config/core_manifest.json"))
    governance_roles_path: Path = field(default_factory=lambda: Path("config/governance_roles.json"))
    completion_artifacts_path: Path = field(default_factory=lambda: Path("artifacts/v2_completion"))
    legacy_readiness_artifacts_path: Path = field(default_factory=lambda: Path("artifacts/v2_readiness"))
    operational_watchdog_path: Path = field(default_factory=lambda: Path("data/operational/watchdog_status.json"))
    rolling_liveness_path: Path = field(default_factory=lambda: Path("data/operational/rolling_liveness.json"))
    plan_journal_path: Path = field(default_factory=lambda: Path("data/journal/tim_plan_journal.json"))
    plan_journal_struct_path: Path = field(default_factory=lambda: Path("data/journal/tim_plan_journal_struct.json"))
    plan_journal_level_path: Path = field(default_factory=lambda: Path("data/journal/tim_plan_journal_level.json"))
    trader_journal_path: Path = field(default_factory=lambda: Path("data/journal/trader_journal.json"))
    qualification_root_path: Path = field(default_factory=lambda: Path("data/qualification"))
    live_cutover_path: Path = field(default_factory=lambda: Path("artifacts/operations/live_cutover.json"))
    gate_model_path: Path = field(default_factory=lambda: Path("data/research/status/current_gate_model.json"))
    phase_c_checkpoint_path: Path = field(default_factory=lambda: Path("/tmp/phase_c_checkpoint.json"))
    runtime_started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    lock: threading.Lock = field(default_factory=threading.Lock)
    _timeline_mtime_ns: Any = field(default=-1, init=False)
    _timeline_cache: list[dict[str, Any]] = field(default_factory=list, init=False)

    def _validator(self) -> dict[str, Any]:
        try:
            value = json.loads(self.validator_path.read_text())
            return {
                "status": value.get("status", "UNKNOWN"),
                "cycles": int(value.get("cycles", 0)),
                "started_at": value.get("started_at"),
                "last_cycle_at": value.get("last_cycle_at"),
                "deadline": value.get("deadline"),
                "restart_count": int(value.get("restart_count", 0)),
                "acceptance": value.get("acceptance", {"status": "monitoring"}),
                "health_monitor": value.get("health_monitor", {}),
                "latest_health": value.get("latest_health", {}),
                "research_health": value.get("latest_health", {}).get("research", {}),
            }
        except (OSError, ValueError, TypeError):
            return {"status": "UNAVAILABLE", "cycles": 0}

    def _timeline_sources(self) -> list[Path]:
        operational = self.operational_watchdog_path.parent
        return [
            self.events_path,
            operational / "watchdog.jsonl",
            operational / "backup_last_run.json",
            self.qualification_root_path / "qualification_campaign.json",
            self.qualification_root_path / "daily",
        ]

    def _timeline(self, validator: dict[str, Any]) -> list[dict[str, Any]]:
        mtimes = []
        for path in self._timeline_sources():
            try:
                mtimes.append(path.stat().st_mtime_ns)
            except OSError:
                mtimes.append(-1)
        # -1 means no source file exists (same key as before this cache held several files).
        cache_key = tuple(mtimes) if any(value != -1 for value in mtimes) else -1
        if cache_key == self._timeline_mtime_ns and self._timeline_cache:
            return list(self._timeline_cache)
        events: list[dict[str, Any]] = []
        started = validator.get("started_at")
        if started:
            events.append({"timestamp": started, "event": "RUNTIME_START", "severity": "INFO", "summary": "Persistierte TIM-Laufzeit gestartet."})
        else:
            # Without a validator state file the timeline would stay empty although this process knows when it started.
            events.append({"timestamp": self.runtime_started_at, "event": "RUNTIME_START", "severity": "INFO", "summary": "Dashboard-Prozess gestartet (kein Validator-Zustand vorhanden)."})
        try:
            lines = self.events_path.read_text().splitlines()[-250:]
        except OSError:
            lines = []
        for line in lines:
            try:
                item = json.loads(line)
            except (TypeError, ValueError):
                continue
            if not isinstance(item, dict):
                continue
            kind = str(item.get("event", ""))
            if kind not in ALLOWED_TIMELINE_EVENTS or "TRADE" in kind or "ORDER" in kind:
                continue
            summary = item.get("overall_status") or item.get("category") or item.get("status") or item.get("severity") or "Recorded"
            events.append({"timestamp": item.get("timestamp"), "event": kind, "severity": item.get("severity", "INFO"), "summary": summary})
        # The Mac runtime has no validator writing events.jsonl. Its operational
        # history lives in the watchdog log, the backup report and the campaign
        # files, so the timeline reads those (read-only) instead of staying empty.
        events.extend(self._watchdog_transitions())
        events.extend(self._backup_events())
        events.extend(self._campaign_events())
        oldest = datetime.min.replace(tzinfo=timezone.utc)
        events.sort(key=lambda item: _parse_time(item.get("timestamp")) or oldest)
        self._timeline_mtime_ns = cache_key
        self._timeline_cache = events[-50:]
        return list(self._timeline_cache)

    def _watchdog_transitions(self, tail_bytes: int = 1_048_576) -> list[dict[str, Any]]:
        """Status changes of the independent watchdog, from the tail of watchdog.jsonl."""
        path = self.operational_watchdog_path.parent / "watchdog.jsonl"
        try:
            with path.open("rb") as handle:
                handle.seek(0, 2)
                size = handle.tell()
                handle.seek(max(0, size - tail_bytes))
                raw = handle.read().decode("utf-8", errors="replace")
        except OSError:
            return []
        lines = raw.splitlines()
        if size > tail_bytes and lines:
            lines = lines[1:]  # first line may be cut in half
        events: list[dict[str, Any]] = []
        previous: str | None = None
        for line in lines:
            try:
                item = json.loads(line)
            except (TypeError, ValueError):
                continue
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "").upper()
            if not status or status == previous:
                continue
            checks = item.get("checks") if isinstance(item.get("checks"), dict) else {}
            failing = sorted(name for name, check in checks.items() if isinstance(check, dict) and str(check.get("status", "")).upper() in {"RED", "YELLOW"})
            if previous is not None:
                events.append({
                    "timestamp": item.get("timestamp"), "event": "WATCHDOG_STATUS", "severity": {"RED": "ERROR", "YELLOW": "WARNING"}.get(status, "INFO"),
                    "previous_status": previous, "new_status": status, "component_id": "watchdog",
                    "summary": ("Prüfungen: " + ", ".join(failing)) if failing else "alle Prüfungen grün",
                    "evidence_reference": "data/operational/watchdog.jsonl · " + (("Prüfungen: " + ", ".join(failing)) if failing else "alle Prüfungen grün"),
                })
            previous = status
        return events[-30:]

    def _backup_events(self) -> list[dict[str, Any]]:
        report = self._read_dict(self.operational_watchdog_path.parent / "backup_last_run.json")
        if not report.get("completed_at"):
            return []
        status = str(report.get("status") or "UNKNOWN").upper()
        size = report.get("bytes")
        detail = f"{size / 1e9:.1f} GB" if isinstance(size, (int, float)) and not isinstance(size, bool) else "Größe unbekannt"
        return [{
            "timestamp": report["completed_at"], "event": "DB_BACKUP", "severity": "INFO" if status == "PASS" else "ERROR",
            "new_status": status, "component_id": "database_backup", "summary": f"Datenbank-Backup {status} · {detail}",
            "evidence_reference": f"data/operational/backup_last_run.json · {detail}",
        }]

    def _campaign_events(self) -> list[dict[str, Any]]:
        root = self.qualification_root_path
        campaign = self._read_dict(root / "qualification_campaign.json")
        events: list[dict[str, Any]] = []
        started = campaign.get("activated_at_utc") or campaign.get("start_utc")
        if started:
            events.append({
                "timestamp": started, "event": "QUALIFICATION_START", "severity": "INFO", "component_id": "qualification",
                "new_status": str(campaign.get("campaign_status") or "UNKNOWN"),
                "summary": f"Qualifizierungskampagne {campaign.get('dataset_id') or ''} gestartet".strip(),
                "evidence_reference": "data/qualification/qualification_campaign.json",
            })
        try:
            files = sorted(item for item in (root / "daily").iterdir() if item.is_file() and item.suffix == ".json")
        except OSError:
            files = []
        for item in files[-30:]:
            manifest = self._read_dict(item)
            metrics = manifest.get("metrics") if isinstance(manifest.get("metrics"), dict) else {}
            if not manifest.get("generated_at_utc"):
                continue
            coverage = metrics.get("coverage")
            coverage_text = f"{coverage * 100:.2f} %" if isinstance(coverage, (int, float)) and not isinstance(coverage, bool) else "unbekannt"
            gaps = metrics.get("gap_count")
            summary = f"Tag {item.stem}: Abdeckung {coverage_text}, Lücken {gaps}, unabhängige Fälle {metrics.get('independent_case_count')}"
            events.append({
                "timestamp": manifest["generated_at_utc"], "event": "QUALIFICATION_DAY", "component_id": "qualification",
                "severity": "WARNING" if isinstance(gaps, int) and gaps > 0 else "INFO",
                "new_status": "RECORDED", "summary": summary,
                "evidence_reference": f"data/qualification/daily/{item.name} · {summary}",
            })
        return events

    def readiness(self)->dict[str,Any]:
        try:
            value=json.loads(self.readiness_path.read_text())
            return value if isinstance(value,dict) and value.get("mode")=="OBSERVE" else {"readiness_status":"UNAVAILABLE","criteria":{}}
        except (OSError,ValueError,TypeError):return {"readiness_status":"UNAVAILABLE","criteria":{}}

    @staticmethod
    def _read_dict(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text())
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def _gate_model(self) -> dict[str, Any]:
        """Read the operator-owned current gate model (read-only, fail-open).

        The dashboard never authors gate states. An absent or oversized file
        renders every bound gate as UNAVAILABLE instead of a substitute value.
        """
        try:
            raw = self.gate_model_path.read_text(encoding="utf-8")
            if len(raw) > 262_144:
                return {}
            model = json.loads(raw)
        except (OSError, ValueError, TypeError):
            return {}
        if not isinstance(model, dict):
            return {}
        # Live supplement: Phase C checkpoint progress (read-only, optional).
        checkpoint = self._phase_c_progress()
        if checkpoint and isinstance(model.get("bands"), dict):
            for gate in model["bands"].get("data_pipeline", []):
                if isinstance(gate, dict) and gate.get("live_checkpoint") and gate.get("id") == "PHASE_C_HISTORICAL_EXTENSION":
                    gate["checkpoint"] = checkpoint
        return model

    def _phase_c_progress(self) -> dict[str, Any]:
        try:
            info = self.phase_c_checkpoint_path.stat()
            if info.st_size > 65_536:
                return {}
            state = json.loads(self.phase_c_checkpoint_path.read_text())
        except (OSError, ValueError, TypeError):
            return {}
        if not isinstance(state, dict):
            return {}
        return {
            "trades": state.get("trades"),
            "pages": state.get("pages"),
            "last_id": state.get("last_id"),
            "checkpoint_mtime": datetime.fromtimestamp(info.st_mtime, tz=timezone.utc).isoformat(),
        }

    def record_chart_candle(self, candle: dict[str, Any], limit: int = CHART_CANDLE_LIMIT) -> None:
        """Keep the newest candles per timeframe for the chart; caller holds ``lock``."""
        timeframe = str(candle.get("timeframe") or "")
        if not timeframe:
            return
        series = self.chart_candles.setdefault(timeframe, [])
        series[:] = [item for item in series if item.get("open_time") != candle.get("open_time")]
        series.append(dict(candle))
        series.sort(key=lambda item: str(item.get("open_time")))
        del series[:-limit]

    def chart_series(self) -> dict[str, list[dict[str, Any]]]:
        with self.lock:
            series = {timeframe: [dict(item) for item in items] for timeframe, items in self.chart_candles.items()}
        if not series:
            # Older runtimes only fill recent_candles: group them by timeframe.
            with self.lock:
                for item in self.recent_candles:
                    series.setdefault(str(item.get("timeframe")), []).append(dict(item))
        from src.dashboard.chart_model import analytical_series

        enriched = analytical_series(series, datetime.now(timezone.utc))
        return {tf: [{**c, "open_time": c["open_time"].isoformat(), "close_time": c["close_time"].isoformat()} for c in rows]
                for tf, rows in enriched.items() if rows}

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            observations = [dict(item) for item in self.active_observations[-VISIBLE_LIMIT:]]
            candles = list(self.recent_candles[-VISIBLE_LIMIT:])
            cases = list(self.research_cases[-VISIBLE_LIMIT:])
            all_cases = list(self.research_cases)
            system_health = dict(self.system_health)
            market_status = dict(self.market_status)
            memory_status = dict(self.memory_status)
            news = dict(self.news)
        case_by_observation = {
            str(observation_id): case
            for case in all_cases
            for observation_id in case.get("observation_ids", [])
        }
        for observation in observations:
            related = case_by_observation.get(str(observation.get("observation_id", "")))
            if related:
                observation["research_case_id"] = related.get("case_id")
                observation["research_case_status"] = related.get("status")
        validator = self._validator()
        active = sum(str(case.get("status", "OPEN")).upper() not in {"CLOSED", "INVALIDATED"} for case in all_cases)
        closed = sum(str(case.get("status", "")).upper() == "CLOSED" for case in all_cases)
        by_status: dict[str, int] = {}
        for case in all_cases:
            key = str(case.get("status") or "OPEN").upper()
            by_status[key] = by_status.get(key, 0) + 1
        collecting = sum(by_status.get(status, 0) for status in ("OPEN", "MONITORING", "COLLECTING_EVIDENCE"))
        generated_at = datetime.now(timezone.utc)
        last_candle_at = next(
            (item.get("close_time") or item.get("open_time") for item in reversed(candles) if item.get("close_time") or item.get("open_time")),
            None,
        )
        # Raw persistence happens before candle enrichment.  A backlog in the
        # latter must not report a healthy, continuously persisted live stream
        # as stale merely because the most recently completed candle is older.
        last_data_at = system_health.get("last_raw_persisted_at") or last_candle_at
        parsed_last_data = _parse_time(last_data_at)
        data_age = int((generated_at - parsed_last_data).total_seconds()) if parsed_last_data else None
        stream_running = str(system_health.get("stream", "")).lower() == "running"
        database_connected = str(system_health.get("database", "")).lower() == "connected"
        data_fresh = data_age is not None and 0 <= data_age <= 120
        operational_health = {
            "status": "GREEN" if stream_running and database_connected and data_fresh else "YELLOW" if database_connected else "RED",
            "database": "GREEN" if database_connected else "RED",
            "stream": "GREEN" if stream_running and data_fresh else "RED",
            "dashboard": "GREEN",
            "runtime": "GREEN",
            "last_data_at": last_data_at,
            "last_candle_at": last_candle_at,
            "data_freshness_source": "DURABLE_RAW_CURSOR" if system_health.get("last_raw_persisted_at") else "COMPLETED_CANDLE",
            "data_age_seconds": data_age if data_age is not None else "MISSING:last_data_at",
            "checked_at": generated_at.isoformat(),
            "runtime_started_at": self.runtime_started_at,
            "queue_depth": int(system_health.get("queue_depth", 0)),
            "queue_model": str(system_health.get("queue_model", "DIRECT_AWAIT_NO_APPLICATION_QUEUE")),
            "ollama_enabled": bool(system_health.get("ollama_enabled", False)),
            "ollama_availability": str(system_health.get("ollama_availability", "DISABLED_BY_POLICY")),
        }
        snapshot = {
                "timestamp": generated_at.isoformat(),
                "mode": "OBSERVE",
                "provenance": "PUBLIC_MARKET_DATA_DETERMINISTIC",
                "dashboard_version": DASHBOARD_VERSION,
                "count_scope": "VISIBLE_RECENT_WINDOW",
                "visible_counts": {"candles": len(candles), "observations": len(observations), "research_cases": len(cases)},
                "case_counts": {"active": active, "closed": closed, "total": len(all_cases),
                                "by_status": dict(sorted(by_status.items())),
                                "confirmed": by_status.get("CONFIRMED", 0),
                                "collecting_evidence": collecting,
                                "open": by_status.get("OPEN", 0),
                                "monitoring": by_status.get("MONITORING", 0),
                                "ready_for_review": by_status.get("READY_FOR_REVIEW", 0),
                                "rejected": by_status.get("REJECTED", 0),
                                "quarantined": by_status.get("QUARANTINED", 0)},
                "candles": candles,
                "observations": observations,
                "active_observations": observations,
                "research_cases": cases,
                "validator": validator,
                "timeline": self._timeline(validator),
                "system_health": system_health,
                "operational_health": operational_health,
                "market_status": market_status,
                "memory_status": memory_status,
                "news": news,
                "readiness": self.readiness(),
                "research_audit": self._read_dict(self.audit_path),
                "research_quality": self._read_dict(self.quality_path),
                "core_manifest": self._read_dict(self.core_manifest_path),
                "governance_roles": self._read_dict(self.governance_roles_path),
                "live_cutover": self._read_dict(self.live_cutover_path),
                "gate_model": self._gate_model(),
                "safety": "RESEARCH ONLY — NO ORDERS OR EXECUTION",
        }
        snapshot["operations"] = build_operations_snapshot(
            snapshot,
            self.completion_artifacts_path,
            self.legacy_readiness_artifacts_path,
            self.operational_watchdog_path,
            self.rolling_liveness_path,
            self.qualification_root_path,
        )
        return snapshot

    def analytics(self) -> dict[str, Any]:
        with self.lock:
            observations = [dict(item) for item in self.active_observations]
            cases = [dict(item) for item in self.research_cases]
        events: list[dict[str, Any]] = []
        try:
            lines = self.events_path.read_text().splitlines()
        except OSError:
            lines = []
        for line in lines:
            try:
                item = json.loads(line)
                kind = str(item.get("event", "")).upper()
                if isinstance(item, dict) and "TRADE" not in kind and "ORDER" not in kind:
                    events.append(item)
            except (TypeError, ValueError):
                continue
        return ResearchAnalyticsEngine().analyze(observations, cases, events)

    def insights(self) -> dict[str, Any]:
        """Build retrospective insights from copied persisted state only."""
        with self.lock:
            observations = [dict(item) for item in self.orderflow_observations]
            validations = [dict(item) for item in self.orderflow_validations]
            cases = [dict(item) for item in self.research_cases]
        try:
            manifest = json.loads(Path("config/core_manifest.json").read_text())
        except (OSError, ValueError, TypeError) as exc:
            raise ValueError("frozen Core manifest is unavailable") from exc
        validator = self._validator()
        monitor = validator.get("health_monitor", {})
        latest = validator.get("latest_health", {})
        critical = list(monitor.get("critical", []))
        quality = {
            "coverage_percent": validator.get("acceptance", {}).get("coverage_percent"),
            "known_data_gaps": [item for item in critical if str(item).upper() == "DATA_GAP"],
            "integrity_errors": len([item for item in critical if str(item).upper() != "DATA_GAP"]),
            "replay_status": latest.get("benchmark", "UNKNOWN"),
            "source_window_complete": len(observations) < 500 and len(validations) < 500 and len(cases) < 1000,
        }
        return ResearchInsightsEngine().analyze(observations, validations, cases, manifest, quality)
