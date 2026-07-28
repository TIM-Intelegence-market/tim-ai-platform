from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .config import canonical_json
from .security import assert_write_allowed


SCHEMA = """
CREATE TABLE IF NOT EXISTS artifacts (
  artifact_id TEXT PRIMARY KEY,
  normalized_path TEXT NOT NULL UNIQUE,
  source_id TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  record_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  event_id TEXT PRIMARY KEY,
  event_json TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS artifact_fts USING fts5(
  artifact_id UNINDEXED, normalized_path, classification, searchable_text
);
"""


class ManagerStore:
    def __init__(self, path: Path):
        assert_write_allowed(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.connection = sqlite3.connect(path)
        self.connection.executescript(SCHEMA)

    def close(self) -> None:
        self.connection.close()

    def artifacts(self) -> dict[str, dict[str, Any]]:
        return {
            row[0]: json.loads(row[1])
            for row in self.connection.execute("SELECT normalized_path, record_json FROM artifacts")
        }

    def event_ids(self) -> set[str]:
        return {row[0] for row in self.connection.execute("SELECT event_id FROM events")}

    def upsert_artifact(self, record: dict[str, Any], searchable_text: str = "") -> None:
        self.connection.execute(
            "INSERT INTO artifacts(artifact_id,normalized_path,source_id,content_hash,record_json) VALUES(?,?,?,?,?) "
            "ON CONFLICT(normalized_path) DO UPDATE SET artifact_id=excluded.artifact_id,source_id=excluded.source_id,"
            "content_hash=excluded.content_hash,record_json=excluded.record_json",
            (record["artifact_id"], record["normalized_path"], record["source_id"], record["content_hash"], canonical_json(record)),
        )
        self.connection.execute("DELETE FROM artifact_fts WHERE artifact_id=?", (record["artifact_id"],))
        self.connection.execute(
            "INSERT INTO artifact_fts(artifact_id,normalized_path,classification,searchable_text) VALUES(?,?,?,?)",
            (record["artifact_id"], record["normalized_path"], record["classification"], searchable_text[:100_000]),
        )

    def delete_artifact(self, normalized_path: str) -> None:
        row = self.connection.execute("SELECT artifact_id FROM artifacts WHERE normalized_path=?", (normalized_path,)).fetchone()
        if row:
            self.connection.execute("DELETE FROM artifact_fts WHERE artifact_id=?", (row[0],))
            self.connection.execute("DELETE FROM artifacts WHERE normalized_path=?", (normalized_path,))

    def add_event(self, event: dict[str, Any]) -> bool:
        cursor = self.connection.execute(
            "INSERT OR IGNORE INTO events(event_id,event_json) VALUES(?,?)",
            (event["event_id"], canonical_json(event)),
        )
        return cursor.rowcount == 1

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT a.record_json FROM artifact_fts f JOIN artifacts a ON a.artifact_id=f.artifact_id "
            "WHERE artifact_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit),
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def commit(self) -> None:
        self.connection.commit()

