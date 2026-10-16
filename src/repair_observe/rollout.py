"""Pure helpers for the observe-only repair rollout."""

from __future__ import annotations

_TRADING_FLAGS = ("TIM_LIVE_TRADING", "TIM_EXECUTION_ENABLED")

SAFE_STOP_STEPS = (
    "set AUTO_REPAIR=false",
    "stop the repair worker",
    "preserve incident evidence",
    "escalate to the operator",
)


def _flag_disabled(value: object) -> bool:
    if type(value) is str:
        return value in ("0", "false")
    if type(value) is bool:
        return value is False
    if type(value) is int:
        return value == 0
    return False


def validate_observe_config(cfg: dict) -> dict:
    try:
        if not isinstance(cfg, dict):
            return {"ok": False, "violations": ["config must be a dict"]}

        violations: list[str] = []
        if "AUTO_REPAIR" not in cfg:
            violations.append("AUTO_REPAIR missing")
        elif cfg["AUTO_REPAIR"] is not False:
            violations.append("AUTO_REPAIR must be False")

        if "MODE" not in cfg:
            violations.append("MODE missing")
        elif type(cfg["MODE"]) is not str or cfg["MODE"] != "OBSERVE":
            violations.append("MODE must be OBSERVE")

        for flag in _TRADING_FLAGS:
            if flag in cfg and not _flag_disabled(cfg[flag]):
                violations.append(f"{flag} must be disabled")

        return {"ok": not violations, "violations": sorted(violations)}
    except Exception:
        return {"ok": False, "violations": ["config could not be validated"]}


def _non_empty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def rollout_checklist(status: dict) -> list[dict]:
    names = (
        "observe_config_valid",
        "metrics_available",
        "safe_stop_procedure_documented",
        "rollback_procedure_documented",
        "a1_decision_recorded",
    )
    if not isinstance(status, dict):
        return [{"item": name, "passed": False} for name in names]

    metrics = status.get("metrics")
    decision = status.get("a1_decision")
    checks = (
        validate_observe_config(status.get("config"))["ok"],
        isinstance(metrics, dict) and bool(metrics),
        _non_empty_str(status.get("safe_stop_doc")),
        _non_empty_str(status.get("rollback_doc")),
        type(decision) is str and decision in ("GO", "NO_GO"),
    )
    return [{"item": name, "passed": passed} for name, passed in zip(names, checks)]


def safe_stop_steps() -> tuple[str, ...]:
    return SAFE_STOP_STEPS
