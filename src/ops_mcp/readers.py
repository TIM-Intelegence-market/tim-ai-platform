"""Read-only sources for the tim-ops MCP server.

The Task Engine store is opened through a ``mode=ro`` URI connection with
``PRAGMA query_only`` set, never through SqliteTaskRepository (its
constructor creates the schema and chmods the file). Free text that may
carry operator input is passed through the graph redaction patterns.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable

from src.graph_mcp.redaction import redact_text
from src.research_lab.stats.register import HypothesisRegister, RegisterError
from src.task_engine.model import TaskState
from src.task_engine.repository import (APP_ID, SCHEMA_VERSION as TASK_SCHEMA_VERSION,
                                        CorruptTaskRecord, SqliteTaskRepository)

MAX_LIMIT = 200
DEFAULT_LIMIT = 50
_TASK_TEXT = ("title", "objective", "failure_reason", "blocker_reason", "next_action")


class SourceError(Exception):
    """A configured source exists but cannot be read safely."""


def bounded(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    return max(1, min(int(limit), MAX_LIMIT))


def _clean(value: Any) -> Any:
    return redact_text(value) if isinstance(value, str) else value


class TaskReader:
    def __init__(self, path: Path | None) -> None:
        self.path = Path(path) if path else None

    def _connect(self) -> sqlite3.Connection | None:
        if self.path is None:
            return None
        if self.path.is_symlink():
            raise SourceError("task store symlinks are forbidden")
        if not self.path.is_file():
            raise SourceError("task store not found")
        connection = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True,
                                     timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        if connection.execute("PRAGMA application_id").fetchone()[0] != APP_ID:
            connection.close()
            raise SourceError("not a task engine database")
        if connection.execute("PRAGMA user_version").fetchone()[0] != TASK_SCHEMA_VERSION:
            connection.close()
            raise SourceError("unsupported task engine schema")
        return connection

    def _with(self, action: Callable[[sqlite3.Connection], dict]) -> dict:
        connection = self._connect()
        if connection is None:
            return {"status": "not_configured", "hint": "set TIM_OPS_TASK_DB"}
        try:
            return action(connection)
        except sqlite3.Error as error:
            raise SourceError(f"task store unreadable: {type(error).__name__}") from None
        finally:
            connection.close()

    @staticmethod
    def _task(row: sqlite3.Row) -> dict[str, Any]:
        try:
            task = SqliteTaskRepository._decode(row).to_dict()
        except CorruptTaskRecord as error:
            return {"task_id": row["task_id"], "error": "corrupt_record", "detail": str(error)}
        for key in _TASK_TEXT:
            task[key] = _clean(task.get(key))
        task["revision"] = row["revision"]
        return task

    def summary(self) -> dict:
        def run(db):
            rows = db.execute("SELECT state, count(*) AS n FROM tasks GROUP BY state").fetchall()
            counts = {state.value: 0 for state in TaskState}
            counts.update({row["state"]: row["n"] for row in rows})
            return {"status": "ok", "total": sum(counts.values()), "by_state": counts,
                    "open": sum(n for s, n in counts.items()
                                if s not in ("FIXED", "FAILED"))}
        return self._with(run)

    def list(self, state: str | None = None, type: str | None = None,
             limit: int | None = None) -> dict:
        limit = bounded(limit)

        def run(db):
            clauses, values = [], []
            if state:
                clauses.append("state=?")
                values.append(state)
            if type:
                clauses.append("type=?")
                values.append(type)
            where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = db.execute(f"SELECT * FROM tasks{where} ORDER BY task_id LIMIT ?",
                              (*values, limit + 1)).fetchall()
            tasks = [self._task(row) for row in rows[:limit]]
            keep = ("task_id", "parent_task_id", "type", "state", "priority", "risk",
                    "title", "attempt_count", "blocker_reason", "next_action", "error")
            return {"status": "ok", "truncated": len(rows) > limit,
                    "tasks": [{k: t[k] for k in keep if k in t} for t in tasks]}
        return self._with(run)

    def get(self, task_id: str) -> dict:
        def run(db):
            row = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                return {"status": "not_found", "task_id": task_id}
            history = [{"from": r["from_state"], "to": r["to_state"], "at": r["at"],
                        "reason": _clean(r["reason"]), "attempt_count": r["attempt_count"]}
                       for r in db.execute("SELECT * FROM task_transitions WHERE task_id=? "
                                           "ORDER BY sequence", (task_id,))]
            evidence = [{"name": r["name"], "reference": _clean(r["reference"]), "at": r["at"]}
                        for r in db.execute("SELECT * FROM task_evidence WHERE task_id=? "
                                            "ORDER BY sequence", (task_id,))]
            checkpoints = [{"step_id": r["step_id"], "at": r["at"],
                            "next_action": _clean(r["next_action"])}
                           for r in db.execute("SELECT * FROM task_checkpoints WHERE task_id=? "
                                               "ORDER BY sequence", (task_id,))]
            return {"status": "ok", "task": self._task(row), "history": history[-MAX_LIMIT:],
                    "evidence": evidence[-MAX_LIMIT:], "checkpoints": checkpoints[-MAX_LIMIT:]}
        return self._with(run)


class ResearchReader:
    """Research Lab register (hash-chained) and committed R-reports."""

    def __init__(self, root: Path) -> None:
        self.base = Path(root) / "docs/research_lab"

    def register(self) -> dict:
        path = self.base / "REGISTER.jsonl"
        if not path.is_file():
            return {"status": "not_found"}
        register = HypothesisRegister(path)
        try:
            events = register.events()
            variants = register.variants()
        except RegisterError as error:
            return {"status": "chain_broken", "detail": str(error)}
        by_status: dict[str, int] = {}
        for entry in variants.values():
            by_status[entry["status"]] = by_status.get(entry["status"], 0) + 1
        return {"status": "ok", "chain_valid": True, "events": len(events), "m": len(variants),
                "head": events[-1]["hash"] if events else None, "by_status": by_status,
                "candidates": sorted(v for v, e in variants.items()
                                     if e["status"] == "candidate")}

    def reports(self) -> dict:
        folder = self.base / "reports"
        names = sorted(p.name for p in folder.glob("*.json")) if folder.is_dir() else []
        return {"status": "ok", "reports": names}

    def report(self, name: str, limit: int | None = None) -> dict:
        folder = (self.base / "reports").resolve()
        path = (folder / name).resolve()
        if path.parent != folder or path.suffix != ".json" or not path.is_file():
            return {"status": "not_found", "name": name}
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
        summary = {k: data[k] for k in ("protocol", "commit", "created", "register_m",
                                        "candidates", "seed", "random_runs") if k in data}
        variants = []
        raw = data.get("variants")
        for variant_id, variant in sorted((raw if isinstance(raw, dict) else {}).items()):
            if not isinstance(variant, dict):
                continue
            row = {"variant": variant_id, "hypothesis": variant.get("hypothesis")}
            for period in ("train", "validation"):
                block = variant.get(period) or {}
                stats = block.get("summary") or {}
                row[period] = {"trades": stats.get("trades"),
                               "expectancy_r": stats.get("expectancy_r"),
                               "max_drawdown_pct": stats.get("max_drawdown_pct"),
                               "p": block.get("p")}
            variants.append(row)
        limit = bounded(limit)
        return {"status": "ok", "name": name, **summary,
                "truncated": len(variants) > limit, "variants": variants[:limit]}
