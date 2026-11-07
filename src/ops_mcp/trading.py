"""Read-only trading sources for the tim-ops MCP server (KI1 package 1).

Plan journals, the live trader's public status file, the KI1 shadow log and a market snapshot.
Nothing here writes a file, sends an order or reaches an exchange. Paths come from the environment
(TIM_OPS_JOURNAL_DIR, TIM_OPS_LIVE_STATUS, TIM_OPS_KI_LOG); a missing setting is reported, not guessed.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.graph_mcp.redaction import redact_text
from src.ops_mcp.readers import SourceError, bounded

JOURNALS = {"15m": "tim_plan_journal_short.json", "1h": "tim_plan_journal_mid.json",
            "1d": "tim_plan_journal_long.json", "30m": "tim_plan_journal.json",
            "struct": "tim_plan_journal_struct.json", "level": "tim_plan_journal_level.json",
            "vp": "tim_plan_journal_vp.json"}
ENTRY_FIELDS = ("id", "timeframe", "direction", "created_at", "entry", "stop", "targets", "setup_grade",
                "scenario_type", "market_state", "status", "filled_at", "closed_at", "exit_reason",
                "gross_r", "net_r", "plan_text", "excluded")
MAX_STATUS_BYTES = 256_000


def _regular(path: Path, what: str) -> Path:
    if path.is_symlink():
        raise SourceError(f"{what} symlinks are forbidden")
    if not path.is_file():
        raise SourceError(f"{what} not found")
    return path


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    return value


class TradingReader:
    def __init__(self, journal_dir: Path | None, live_status: Path | None, ki_log: Path | None,
                 market=None) -> None:
        self.journal_dir = Path(journal_dir) if journal_dir else None
        self.live_status_path = Path(live_status) if live_status else None
        self.ki_log = Path(ki_log) if ki_log else None
        self.market = market

    def _view(self, name: str) -> dict[str, Any]:
        from src.dashboard import plan_journal
        return plan_journal.load_view(_regular(self.journal_dir / JOURNALS[name], "journal"))

    def plan_journal(self, name: str, limit: int | None) -> dict[str, Any]:
        if self.journal_dir is None:
            return {"status": "not_configured", "hint": "set TIM_OPS_JOURNAL_DIR"}
        from src.dashboard import plan_journal
        view = self._view(name)
        entries = list(view.get("entries") or [])[-bounded(limit):]
        return {"journal": name, "integrity": view.get("integrity", "OK"), "blocked": bool(view.get("blocked")),
                "summary": plan_journal.summary(view),
                "entries": [_clean({k: e[k] for k in ENTRY_FIELDS if k in e}) for e in entries]}

    def live_status(self) -> dict[str, Any]:
        if self.live_status_path is None:
            return {"status": "not_configured", "hint": "set TIM_OPS_LIVE_STATUS"}
        path = _regular(self.live_status_path, "live status")
        if path.stat().st_size > MAX_STATUS_BYTES:
            raise SourceError("live status file too large")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            raise SourceError("live status unreadable") from None
        age = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
        return {"age_seconds": round(age), "status": _clean(data)}

    def ki_filter(self, limit: int | None) -> dict[str, Any]:
        if self.ki_log is None or self.journal_dir is None:
            return {"status": "not_configured", "hint": "set TIM_OPS_KI_LOG and TIM_OPS_JOURNAL_DIR"}
        from src.research_lab.ki_filter.decide import LogError, read_log
        from src.research_lab.ki_filter.evaluate import evaluate
        if not self.ki_log.exists():
            return {"status": "no_decisions_yet"}
        try:
            records = read_log(_regular(self.ki_log, "ki filter log"))
        except LogError as error:
            raise SourceError(str(error)) from None
        views = {tf: self._view(tf) for tf in ("15m", "1h", "1d") if (self.journal_dir / JOURNALS[tf]).exists()}
        return {"evaluation": evaluate(records, views),
                "last": [_clean({k: v for k, v in r.items() if k not in ("hash", "prev_hash")})
                         for r in records[-bounded(limit):]]}

    def market_snapshot(self, symbol: str, timeframe: str, candles: int) -> dict[str, Any]:
        if self.market is None or not self.market.configured:
            return {"status": "not_configured", "hint": "set TIM_OPS_COVERAGE_DSN"}
        from src.research_lab.ki_filter.context import market_context
        from src.research_lab.ki_filter.market import MarketError
        now = datetime.now(timezone.utc)
        try:
            rows = self.market.candles(symbol, timeframe, now, candles)
        except MarketError as error:
            raise SourceError(str(error)) from None
        return market_context(rows, now, timeframe)
