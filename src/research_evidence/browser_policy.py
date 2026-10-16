"""Opt-in, budgeted browser-use policy for research evidence collection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from src.research_evidence.url_policy import UrlPolicy, check_url

_TRUTHY = {"1", "true", "yes", "on"}


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in _TRUTHY if value is not None else False


@dataclass(frozen=True)
class BrowserPolicy:
    enabled: bool = False
    url_policy: UrlPolicy = field(default_factory=UrlPolicy)
    max_navigations: int = 10
    max_seconds: float = 60.0
    max_download_bytes: int = 0
    kill_switch: bool = False

    @classmethod
    def from_env(cls, env: dict) -> "BrowserPolicy":
        enabled = (
            env.get("TIM_BROWSER_USE_ENABLED") == "1"
            and not _truthy(env.get("CI"))
            and env.get("TIM_ENV") != "production"
        )
        return cls(enabled=enabled)


def _verdict(result: object) -> tuple[bool, str]:
    if isinstance(result, bool):
        return result, "ok" if result else "url_denied"
    if isinstance(result, tuple) and result:
        allowed = bool(result[0])
        reason = str(result[1]) if len(result) > 1 else ("ok" if allowed else "url_denied")
        return allowed, reason
    allowed = bool(getattr(result, "allowed", getattr(result, "ok", False)))
    reason = getattr(result, "reason", None)
    return allowed, str(reason) if reason else ("ok" if allowed else "url_denied")


class BrowserBudget:
    def __init__(self, policy: BrowserPolicy, clock: Callable[[], float]) -> None:
        self._policy = policy
        self._clock = clock
        self._started_at: float | None = None
        self._navigations = 0
        self._audit: list[dict] = []

    def start(self) -> None:
        if not self._policy.enabled:
            raise PermissionError("browser use is disabled")
        if self._policy.kill_switch:
            raise PermissionError("browser kill switch is set")
        self._started_at = self._clock()

    def _running(self) -> bool:
        return self._started_at is not None and not self._policy.kill_switch

    def _expired(self) -> bool:
        return self._clock() - self._started_at > self._policy.max_seconds

    def navigate(self, url: str) -> bool:
        if not self._running():
            allowed, reason = False, "not_running"
        elif self._expired():
            allowed, reason = False, "time_limit"
        elif self._navigations >= self._policy.max_navigations:
            allowed, reason = False, "navigation_limit"
        else:
            allowed, reason = _verdict(check_url(url, self._policy.url_policy))
            if allowed:
                self._navigations += 1
        self._audit.append(
            {"action": "navigate", "url": url, "allowed": allowed, "reason": reason}
        )
        return allowed

    def download(self, size: int) -> bool:
        if not self._running():
            allowed, reason = False, "not_running"
        elif self._expired():
            allowed, reason = False, "time_limit"
        elif size > self._policy.max_download_bytes:
            allowed, reason = False, "download_too_large"
        else:
            allowed, reason = True, "ok"
        self._audit.append(
            {"action": "download", "size": size, "allowed": allowed, "reason": reason}
        )
        return allowed

    def audit(self) -> list[dict]:
        return [dict(entry) for entry in self._audit]
