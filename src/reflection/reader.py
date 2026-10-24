"""Loads validated orderflow observations for a reflection window.

Two sources: a JSON export (tests, offline review) or the database through a
connection that PostgreSQL itself keeps read-only. Only complete validations
whose outcome was known by the end of the window are returned (no look-ahead).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Mapping

from src.database.safety import guard_database_connection
from src.orderflow.validation import SIDEWAYS_THRESHOLD_PERCENT, VALIDATION_VERSION

OUTCOMES = ("PRICE_INCREASED", "PRICE_DECREASED", "PRICE_SIDEWAYS")

# The only statement the database path runs. Kept as one constant so a test
# can prove it is a single SELECT.
SELECT_CASES = (
    "SELECT o.observation_id, o.kind, o.symbol, o.observed_at, o.rule_version, "
    "v.validation_version, v.outcome, v.complete, v.horizons, v.validated_through "
    "FROM orderflow_observations o JOIN orderflow_validations v USING (observation_id) "
    "WHERE o.observed_at >= $1 AND o.observed_at < $2 AND v.complete AND v.validated_through <= $2 "
    "ORDER BY o.observed_at, o.observation_id"
)
READ_ONLY_SETTINGS = {"default_transaction_read_only": "on"}


@dataclass(frozen=True, slots=True)
class ReflectionCase:
    observation_id: str
    kind: str
    symbol: str
    observed_at: datetime
    rule_version: str
    validation_version: str
    outcome: str
    horizon_changes: tuple[tuple[int, Decimal], ...]
    validated_through: datetime

    def outcome_at(self, minutes: int) -> str | None:
        """Outcome class at one horizon, using the live sideways threshold."""
        for horizon, change in self.horizon_changes:
            if horizon == minutes:
                if change > SIDEWAYS_THRESHOLD_PERCENT:
                    return "PRICE_INCREASED"
                if change < -SIDEWAYS_THRESHOLD_PERCENT:
                    return "PRICE_DECREASED"
                return "PRICE_SIDEWAYS"
        return None


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp without timezone: {value}")
    return parsed.astimezone(timezone.utc)


def _horizons(raw: Any) -> tuple[tuple[int, Decimal], ...]:
    items = json.loads(raw) if isinstance(raw, str) else (raw or [])
    return tuple(sorted((int(item["minutes"]), Decimal(str(item["price_change_percent"]))) for item in items))


def _case(row: Mapping[str, Any]) -> ReflectionCase | None:
    if not row.get("complete") or row.get("outcome") not in OUTCOMES:
        return None
    if row.get("validation_version") != VALIDATION_VERSION:
        return None
    return ReflectionCase(
        observation_id=str(row["observation_id"]),
        kind=str(row["kind"]),
        symbol=str(row["symbol"]),
        observed_at=_utc(row["observed_at"]),
        rule_version=str(row["rule_version"]),
        validation_version=str(row["validation_version"]),
        outcome=str(row["outcome"]),
        horizon_changes=_horizons(row.get("horizons")),
        validated_through=_utc(row["validated_through"]),
    )


def select_window(rows: Iterable[Mapping[str, Any]], start: datetime, end: datetime) -> list[ReflectionCase]:
    """Cases observed in [start, end) whose outcome was known by ``end``."""
    start, end = _utc(start), _utc(end)
    if end <= start:
        raise ValueError("window end must be after start")
    cases = []
    for row in rows:
        case = _case(row)
        if case is None or not start <= case.observed_at < end or case.validated_through > end:
            continue
        cases.append(case)
    return sorted(cases, key=lambda item: (item.observed_at, item.observation_id))


def rows_from_export(path: Path) -> list[dict[str, Any]]:
    """Join an export ``{"observations": [...], "validations": [...]}`` by observation id."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    observations = {str(item["observation_id"]): item for item in data.get("observations", [])}
    rows = []
    for validation in data.get("validations", []):
        observation = observations.get(str(validation.get("observation_id")))
        if observation is None:
            continue
        rows.append({
            "observation_id": observation["observation_id"],
            "kind": observation["kind"],
            "symbol": observation["symbol"],
            "observed_at": observation["observed_at"],
            "rule_version": observation["rule_version"],
            "validation_version": validation.get("validation_version"),
            "outcome": validation.get("outcome"),
            "complete": validation.get("complete"),
            "horizons": validation.get("horizons"),
            "validated_through": validation["validated_through"],
        })
    return rows


def load_export(path: Path, start: datetime, end: datetime) -> list[ReflectionCase]:
    return select_window(rows_from_export(path), start, end)


async def load_database(
    url: str,
    start: datetime,
    end: datetime,
    *,
    connect: Callable[..., Awaitable[Any]] | None = None,
) -> list[ReflectionCase]:
    """Read one window with a session PostgreSQL itself keeps read-only."""
    guard_database_connection(url)
    if connect is None:
        import asyncpg

        connect = asyncpg.connect
    connection = await connect(url, server_settings=dict(READ_ONLY_SETTINGS), command_timeout=60)
    try:
        rows = await connection.fetch(SELECT_CASES, _utc(start), _utc(end))
    finally:
        await connection.close()
    return select_window([dict(row) for row in rows], start, end)
