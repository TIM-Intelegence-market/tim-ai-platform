"""Replay runner for V2.8 paper trading: bars + order instructions in, journal + evidence out.

Input files are JSON lines.

bars.jsonl:    {"symbol": "BTCUSDT", "opened_at": "2026-11-12T10:00:00Z", "open": "...", "high": "...",
                "low": "...", "close": "...", "funding_rate": "0.0001"}   (funding_rate optional)
orders.jsonl:  {"at": "...", "client_id": "...", "symbol": "BTCUSDT", "side": "BUY", "quantity": "0.01",
                "type": "MARKET|LIMIT|STOP", "price": "...", "reduce_only": false,
                "stop_loss": "...", "take_profit": "..."}
               {"at": "...", "action": "cancel", "client_id": "..."}
               {"at": "...", "action": "flatten", "symbol": "BTCUSDT"}
               {"at": "...", "action": "kill", "reason": "..."}

An instruction with time ``at`` is handled before every bar that opens at or after ``at``. Bars are processed in
time order across symbols. After every bar the account is reconciled.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from .adapter import AdapterConfig, FakeExecutionAdapter
from .isolation import scan
from .kill_switch import KillSwitch
from .models import Bar, OrderRequest, OrderType, Side, d
from .reconcile import reconcile


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"time without timezone: {value}")
    return parsed.astimezone(timezone.utc)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{n}: {exc}") from exc
    return rows


def bar_from_row(row: dict[str, Any]) -> Bar:
    funding = row.get("funding_rate")
    return Bar(row["symbol"], parse_time(row["opened_at"]), d(row["open"]), d(row["high"]), d(row["low"]),
               d(row["close"]), d(funding) if funding is not None else None)


def request_from_row(row: dict[str, Any]) -> OrderRequest:
    def opt(key: str) -> Decimal | None:
        return d(row[key]) if row.get(key) is not None else None

    return OrderRequest(
        client_id=str(row["client_id"]), symbol=row["symbol"], side=Side(row["side"]),
        quantity=d(row["quantity"]), order_type=OrderType(row.get("type", "MARKET")), price=opt("price"),
        reduce_only=bool(row.get("reduce_only", False)), stop_loss=opt("stop_loss"), take_profit=opt("take_profit"),
        note=str(row.get("note", "")),
    )


@dataclass(frozen=True, slots=True)
class ReplayResult:
    adapter: FakeExecutionAdapter
    journal: list[dict[str, Any]]
    reconciliation_failures: int


def replay(bars: list[Bar], instructions: list[dict[str, Any]], config: AdapterConfig | None = None,
           kill_switch: KillSwitch | None = None) -> ReplayResult:
    adapter = FakeExecutionAdapter(config, kill_switch)
    journal: list[dict[str, Any]] = []
    pending = sorted(instructions, key=lambda r: parse_time(r["at"]))
    bars = sorted(bars, key=lambda b: (b.opened_at, b.symbol))
    i = 0
    failures = 0

    def handle(row: dict[str, Any]) -> None:
        at = parse_time(row["at"])
        action = row.get("action", "order")
        if action == "cancel":
            ok = adapter.cancel(str(row["client_id"]), at)
            journal.append({"at": at.isoformat(), "event": "CANCEL", "client_id": row["client_id"], "ok": ok})
        elif action == "flatten":
            order = adapter.flatten(row["symbol"], at)
            journal.append({"at": at.isoformat(), "event": "FLATTEN", "symbol": row["symbol"],
                            "order_id": order.order_id if order else None})
        elif action == "kill":
            adapter.engage_kill(at, str(row.get("reason", "manual")))
            journal.append({"at": at.isoformat(), "event": "KILL", "reason": row.get("reason", "manual")})
        else:
            order = adapter.submit(request_from_row(row), at)
            journal.append({"at": at.isoformat(), "event": "ORDER", "client_id": order.request.client_id,
                            "order_id": order.order_id, "status": order.status.value, "reason": order.reason})

    for bar in bars:
        while i < len(pending) and parse_time(pending[i]["at"]) <= bar.opened_at:
            handle(pending[i])
            i += 1
        for fill in adapter.on_bar(bar):
            journal.append({"at": fill.filled_at.isoformat(), "event": "FILL", **fill.to_dict()})
        report = reconcile(adapter, bar.opened_at)
        if not report.ok:
            failures += 1
            journal.append({"at": bar.opened_at.isoformat(), "event": "RECONCILIATION_MISMATCH",
                            **report.to_dict()})
    for row in pending[i:]:
        handle(row)  # after the last bar: recorded, cannot fill
    return ReplayResult(adapter, journal, failures)


def write_outputs(result: ReplayResult, out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    adapter = result.adapter
    with (out_dir / "journal.jsonl").open("w", encoding="utf-8") as fh:
        for row in result.journal:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    isolation = scan()
    summary = {
        "mode": "PAPER",
        "live_execution": False,
        "initial_equity": str(adapter.config.initial_equity),
        "final_cash": str(adapter.cash),
        "final_equity": str(adapter.equity()),
        "positions": {s: {"quantity": str(p.quantity), "entry_price": str(p.entry_price)}
                      for s, p in adapter.positions.items() if p.quantity},
        "metrics": adapter.metrics.to_dict(),
        "kill_switch": {"engaged": adapter.kill.engaged, "events": [e.to_dict() for e in adapter.kill.events]},
        "reconciliation_failures": result.reconciliation_failures,
        "isolation": isolation.to_dict(),
        "limitation": "Paper simulation on supplied bars. Not an order, not a fill at an exchange, not a "
                      "profitability claim. Fees are assumptions until confirmed.",
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n",
                                          encoding="utf-8")
    return summary
