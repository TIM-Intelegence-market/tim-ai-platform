"""Audit and observability support.

Each decision must be reproducible: input hashes, data source, timestamps,
feature/ruleset/module versions, scenarios, scores, confirmations, risk
decisions, operational mode, and kill-switch status. No sensitive keys and no
unneeded personal data are ever written.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .domain import sha256_hex, utc_now
from .version import FEATURE_VERSION, MODULE_VERSION, RULESET_VERSION

SENSITIVE_KEY = ("secret", "token", "password", "api_key", "authorization", "credential")


def _redact(value: Any, key: str = "") -> Any:
    if any(part in key.lower() for part in SENSITIVE_KEY):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): _redact(item_value, key=str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item, key=key) for item in value]
    return value


class AuditBuilder:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def add_input(self, name: str, payload: Any, *, redact: bool = True) -> None:
        safe = _redact(payload) if redact else payload
        digest = sha256_hex({"input": name, "payload": safe})
        self.entries.append({"input": name, "hash": digest, "source": "deterministic"})

    def add_engine(self, engine: str, version: str, result: dict[str, Any]) -> None:
        self.entries.append({"engine": engine, "version": version, "result": result})

    def build(self, *, mode: str, kill_switch_enabled: bool, timestamp: datetime | None = None) -> dict[str, Any]:
        return {
            "mode": mode,
            "kill_switch_enabled": kill_switch_enabled,
            "feature_version": FEATURE_VERSION,
            "ruleset_version": RULESET_VERSION,
            "module_version": MODULE_VERSION,
            "model": "DETERMINISTIC_RULES",
            "timestamp": (timestamp or utc_now()).isoformat(),
            "inputs": [{"input": item["input"], "hash": item["hash"]} for item in self.entries if "input" in item],
            "engines": [{"engine": item["engine"], "version": item["version"], "result": item["result"]} for item in self.entries if "engine" in item],
            "live_execution": False,
        }


def analysis_id_for(symbol: str, venue: str, timestamp: datetime) -> str:
    return "ofsc_" + sha256_hex({"symbol": symbol, "venue": venue, "timestamp": timestamp.isoformat()})[:24]


def serialize_audit(audit: dict[str, Any]) -> str:
    return json.dumps(audit, sort_keys=True, separators=(",", ":"), ensure_ascii=False)