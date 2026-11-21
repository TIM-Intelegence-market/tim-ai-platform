"""Kill switch for the V2.8 paper adapter.

Engaged by hand, by a file, or automatically (daily loss, drawdown, repeated rejects, reconciliation
mismatch). While engaged, the adapter refuses every order that could open or enlarge a position and
cancels such pending orders; closing (reduce-only) and flattening stay possible. Release is manual only.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

KILL_FILE_ENV = "TIM_PAPER_KILL_FILE"


@dataclass(frozen=True, slots=True)
class KillLimits:
    max_daily_loss_fraction: Decimal = Decimal("0.03")
    max_drawdown_fraction: Decimal = Decimal("0.10")
    max_consecutive_rejects: int = 5

    def __post_init__(self) -> None:
        if not (Decimal("0") < self.max_daily_loss_fraction < Decimal("1")):
            raise ValueError("max_daily_loss_fraction must be between 0 and 1")
        if not (Decimal("0") < self.max_drawdown_fraction < Decimal("1")):
            raise ValueError("max_drawdown_fraction must be between 0 and 1")
        if self.max_consecutive_rejects < 1:
            raise ValueError("max_consecutive_rejects must be at least 1")


@dataclass(frozen=True, slots=True)
class KillEvent:
    at: datetime
    reason: str
    source: str  # MANUAL, FILE, DAILY_LOSS, DRAWDOWN, REJECTS, RECONCILIATION

    def to_dict(self) -> dict[str, str]:
        return {"at": self.at.isoformat(), "reason": self.reason, "source": self.source}


@dataclass(slots=True)
class KillSwitch:
    limits: KillLimits = field(default_factory=KillLimits)
    kill_file: Path | None = None
    events: list[KillEvent] = field(default_factory=list)
    _engaged: bool = False

    @classmethod
    def from_env(cls, limits: KillLimits | None = None, env: Mapping[str, str] | None = None) -> "KillSwitch":
        env = os.environ if env is None else env
        raw = env.get(KILL_FILE_ENV)
        return cls(limits=limits or KillLimits(), kill_file=Path(raw) if raw else None)

    @property
    def engaged(self) -> bool:
        return self._engaged

    def engage(self, at: datetime, reason: str, source: str = "MANUAL") -> None:
        if not self._engaged:
            self._engaged = True
            self.events.append(KillEvent(at, reason, source))

    def release(self, at: datetime, released_by: str) -> None:
        """Manual release only; the name is kept in the event log."""
        if not released_by.strip():
            raise ValueError("release needs a named person")
        if self.kill_file is not None and self._file_present():
            raise RuntimeError("kill file still present; remove it before release")
        if self._engaged:
            self._engaged = False
            self.events.append(KillEvent(at, f"released by {released_by}", "RELEASE"))

    def _file_present(self) -> bool:
        try:
            return self.kill_file is not None and self.kill_file.exists()
        except OSError:
            return True  # unreadable path: fail closed

    def poll_file(self, at: datetime) -> bool:
        """Engage if the kill file exists; returns True if engaged afterwards."""
        if self._file_present():
            self.engage(at, f"kill file present: {self.kill_file}", "FILE")
        return self._engaged

    def check(self, at: datetime, *, day_start_equity: Decimal, equity: Decimal, peak_equity: Decimal,
              consecutive_rejects: int) -> bool:
        """Evaluate all automatic triggers; returns True if engaged afterwards."""
        self.poll_file(at)
        if day_start_equity > 0 and (day_start_equity - equity) / day_start_equity >= self.limits.max_daily_loss_fraction:
            self.engage(at, "daily loss limit reached", "DAILY_LOSS")
        if peak_equity > 0 and (peak_equity - equity) / peak_equity >= self.limits.max_drawdown_fraction:
            self.engage(at, "drawdown limit reached", "DRAWDOWN")
        if consecutive_rejects >= self.limits.max_consecutive_rejects:
            self.engage(at, f"{consecutive_rejects} rejects in a row", "REJECTS")
        return self._engaged
