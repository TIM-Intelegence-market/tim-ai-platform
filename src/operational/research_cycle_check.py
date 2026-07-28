from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from config.settings import settings
from src.operational.logging import StructuredLog
from src.operational.research_health import ResearchHealthChecker


class ResearchCycleChecker:
    """Validator-facing summary of the canonical research health check."""

    def __init__(
        self,
        root: Path | None = None,
        ollama_url: str | None = None,
        validator_cycle: int | None = None,
    ) -> None:
        self.root = (root or Path(__file__).resolve().parents[2]).resolve()
        self.validator_cycle = validator_cycle
        self.health_checker = ResearchHealthChecker(
            self.root, ollama_url or settings.ollama_url
        )
        self.latest_path = self.root / "data/operational/research_cycle_latest.json"
        self.log = StructuredLog(self.root / "data/operational/events.jsonl")

    def _current_cycle(self) -> int:
        if self.validator_cycle is not None:
            return self.validator_cycle
        try:
            state = json.loads(
                (self.root / "data/operational/state.json").read_text(encoding="utf-8")
            )
            return int(state.get("cycles", 0))
        except (OSError, ValueError, TypeError):
            return 0

    @staticmethod
    def _overall_status(level: str) -> str:
        return {"GREEN": "HEALTHY", "YELLOW": "DEGRADED", "RED": "CRITICAL"}.get(
            level, "CRITICAL"
        )

    def _write_atomic(self, value: dict[str, Any]) -> None:
        self.latest_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.latest_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, self.latest_path)

    def run_full_check(self, *, persist: bool = True) -> dict[str, Any]:
        health = self.health_checker.check()
        checks = health.get("checks", {})
        failed = [name for name, passed in checks.items() if not passed]
        warnings = list(health.get("warnings", []))
        critical = list(health.get("critical", []))
        summary = {
            "check_timestamp": health.get("checked_at"),
            "validator_cycle": self._current_cycle(),
            "overall_status": self._overall_status(str(health.get("level", "RED"))),
            "checks_total": len(checks),
            "checks_pass": sum(bool(value) for value in checks.values()),
            "checks_warn": len(warnings),
            "checks_fail": len(critical),
            "failed_checks": failed,
            "details": {
                name: {"status": "PASS" if passed else "FAIL"}
                for name, passed in checks.items()
            },
            "health": health,
            "mode": "OBSERVE",
        }
        if persist:
            self._write_atomic(summary)
            self.log.write(
                "RESEARCH_CYCLE_CHECK",
                severity=(
                    "ERROR"
                    if summary["overall_status"] == "CRITICAL"
                    else "WARNING"
                    if summary["overall_status"] == "DEGRADED"
                    else "INFO"
                ),
                validator_cycle=summary["validator_cycle"],
                overall_status=summary["overall_status"],
                checks_pass=summary["checks_pass"],
                checks_warn=summary["checks_warn"],
                checks_fail=summary["checks_fail"],
                failed_checks=failed,
            )
        return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="TIM research cycle health check")
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args()
    summary = ResearchCycleChecker().run_full_check(persist=not args.no_persist)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return {"HEALTHY": 0, "DEGRADED": 1}.get(summary["overall_status"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
