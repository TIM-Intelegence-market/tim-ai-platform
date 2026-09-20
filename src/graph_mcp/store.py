"""Local SQLite graph store (STEP 6): deterministic, transactional,
portable, backupable. This file IS the only writable surface of Graph MCP."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from src.graph_mcp import SCHEMA_VERSION
from src.graph_mcp.schema import edge_set_hash, node_set_hash, utc_now

DDL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    source TEXT NOT NULL,
    path TEXT NOT NULL DEFAULT '',
    metadata TEXT NOT NULL DEFAULT '{}',
    content_hash TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    schema_version TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS nodes_type_idx ON nodes (type);
CREATE INDEX IF NOT EXISTS nodes_name_idx ON nodes (name);
CREATE INDEX IF NOT EXISTS nodes_path_idx ON nodes (path);
CREATE TABLE IF NOT EXISTS edges (
    src TEXT NOT NULL,
    dst TEXT NOT NULL,
    type TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    evidence TEXT NOT NULL DEFAULT '[]',
    content_hash TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (src, dst, type)
);
CREATE INDEX IF NOT EXISTS edges_dst_idx ON edges (dst, type);
CREATE TABLE IF NOT EXISTS file_state (
    path TEXT NOT NULL,
    source TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    indexed_at TEXT NOT NULL,
    PRIMARY KEY (path, source)
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class GraphStoreError(RuntimeError):
    pass


class GraphStore:
    """Own graph database only — never a TIM database."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if self.path.name.endswith((".sqlite", ".db")) is False:
            raise GraphStoreError("graph store must be a local sqlite file")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.connection = sqlite3.connect(str(self.path), timeout=30)
            self.connection.row_factory = sqlite3.Row
            self.connection.executescript(DDL)
        except sqlite3.DatabaseError as error:
            raise GraphStoreError(f"graph store unusable: {error}") from error

    # -- writing (own index only) ------------------------------------

    def begin(self) -> None:
        self.connection.execute("BEGIN IMMEDIATE")

    def commit(self) -> None:
        self.connection.commit()

    def rollback(self) -> None:
        self.connection.rollback()

    def apply(self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]],
              source_prefix: str = "") -> dict[str, int]:
        """Diff-based slice replace owned by `source_prefix`: only nodes that
        are genuinely gone are deleted; unchanged content counts as neither
        added nor updated (idempotency, STEP 29)."""
        if not source_prefix:
            raise GraphStoreError("apply requires an indexer-owned source prefix")
        counters = {"nodes_added": 0, "nodes_updated": 0, "nodes_removed": 0,
                    "edges_added": 0, "edges_removed": 0}
        incoming_ids = {node["id"] for node in nodes}
        incoming_edges = {(edge["from"], edge["to"], edge["type"]) for edge in edges}
        with self.connection:
            for row in self.connection.execute(
                    "SELECT id FROM nodes WHERE source LIKE ?", (source_prefix + "%",)):
                if row["id"] not in incoming_ids:
                    self.connection.execute("DELETE FROM nodes WHERE id=?", (row["id"],))
                    counters["nodes_removed"] += 1
            for node in nodes:
                existing = self.connection.execute(
                    "SELECT content_hash FROM nodes WHERE id=?", (node["id"],)).fetchone()
                if existing is None:
                    counters["nodes_added"] += 1
                elif existing["content_hash"] != node["content_hash"]:
                    counters["nodes_updated"] += 1
                else:
                    continue  # unchanged: leave the stored record untouched
                self.connection.execute(
                    "INSERT OR REPLACE INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
                    (node["id"], node["type"], node["name"], node["source"],
                     node["path"], json.dumps(node["metadata"], sort_keys=True),
                     node["content_hash"], node["observed_at"], node["schema_version"]))
            for edge in edges:
                existing = self.connection.execute(
                    "SELECT 1 FROM edges WHERE src=? AND dst=? AND type=?",
                    (edge["from"], edge["to"], edge["type"])).fetchone()
                if existing is None:
                    counters["edges_added"] += 1
                self.connection.execute(
                    "INSERT OR REPLACE INTO edges VALUES (?,?,?,?,?,?,?,?)",
                    (edge["from"], edge["to"], edge["type"],
                     json.dumps(edge["metadata"], sort_keys=True),
                     json.dumps(edge["evidence"], sort_keys=True),
                     _edge_hash(edge), SCHEMA_VERSION, source_prefix))
            for row in self.connection.execute(
                    "SELECT src,dst,type FROM edges WHERE source=?",
                    (source_prefix,)).fetchall():
                if (row["src"], row["dst"], row["type"]) not in incoming_edges:
                    self.connection.execute(
                        "DELETE FROM edges WHERE src=? AND dst=? AND type=?",
                        (row["src"], row["dst"], row["type"]))
                    counters["edges_removed"] += 1
            self._set_meta("last_apply", utc_now())
        return counters

    def record_file_state(self, path: str, sha256: str, indexed_at: str,
                          source: str = "code") -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO file_state VALUES (?,?,?,?)",
                (path, source, sha256, indexed_at))

    def file_state(self, path: str, source: str = "code") -> str | None:
        row = self.connection.execute(
            "SELECT sha256 FROM file_state WHERE path=? AND source=?",
            (path, source)).fetchone()
        return row["sha256"] if row else None

    def file_states(self, source: str) -> dict[str, str]:
        return {row["path"]: row["sha256"] for row in self.connection.execute(
            "SELECT path, sha256 FROM file_state WHERE source=?", (source,))}

    def forget_stale(self, source: str, keep: dict[str, str]) -> int:
        """STEP 27: file-state rows for deleted files are retired."""
        with self.connection:
            placeholders = ",".join("?" * len(keep)) if keep else "NULL"
            cursor = self.connection.execute(
                f"DELETE FROM file_state WHERE source=? AND path NOT IN ({placeholders})",
                (source, *keep.keys()))
            return cursor.rowcount or 0

    def forget_file_state(self, path: str) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM file_state WHERE path=?", (path,))

    def retire_source(self, source_prefix: str) -> int:
        """STEP 27: deleted sources are retired, never silently kept."""
        with self.connection:
            cursor = self.connection.execute(
                "DELETE FROM nodes WHERE source LIKE ?", (source_prefix + "%",))
            removed = cursor.rowcount or 0
            self.connection.execute(
                "DELETE FROM edges WHERE src NOT IN (SELECT id FROM nodes) "
                "OR dst NOT IN (SELECT id FROM nodes)")
        return removed

    # -- reading -------------------------------------------------------

    def node(self, node_id: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        return _node_record(row) if row else None

    def nodes(self, node_type: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
        query = "SELECT * FROM nodes" + (" WHERE type=?" if node_type else "")
        params = (node_type,) if node_type else ()
        return [_node_record(row) for row in
                self.connection.execute(query + " ORDER BY id LIMIT ?", (*params, limit))]

    def search_nodes(self, needle: str, node_type: str | None, mode: str,
                     limit: int) -> list[dict[str, Any]]:
        """Bounded SQL-side search (STEP 16): filtering happens in SQLite,
        never by scanning a fixed prefix of the table into memory. All
        external input stays data — values bind through `?` parameters, so
        SQL-looking text can only ever be search text. (LIKE wildcard
        characters typed by a user keep their wildcard meaning; there is no
        injection surface either way.) Deterministic order: id."""
        pattern = f"%{needle}%"
        clauses: list[str] = []
        params: list[Any] = []
        if mode == "id":
            clauses.append("id LIKE ?")
            params.append(pattern)
        elif mode == "path":
            clauses.append("path LIKE ?")
            params.append(pattern)
        elif mode == "metadata":
            clauses.append("metadata LIKE ?")
            params.append(pattern)
        else:
            clauses.append("(name LIKE ? OR path LIKE ? OR id LIKE ?)")
            params.extend([pattern, pattern, pattern])
        if node_type:
            clauses.append("type = ?")
            params.append(node_type)
        query = ("SELECT * FROM nodes WHERE " + " AND ".join(clauses)
                 + " ORDER BY id LIMIT ?")
        params.append(limit)
        return [_node_record(row) for row in self.connection.execute(query, params)]

    def edges_from(self, node_id: str, edge_types: tuple[str, ...] | None = None) -> list[dict]:
        return self._edges("src", node_id, edge_types)

    def edges_to(self, node_id: str, edge_types: tuple[str, ...] | None = None) -> list[dict]:
        return self._edges("dst", node_id, edge_types)

    def _edges(self, column: str, node_id: str, edge_types) -> list[dict[str, Any]]:
        query = f"SELECT * FROM edges WHERE {column}=?"
        params: list[Any] = [node_id]
        if edge_types:
            query += f" AND type IN ({','.join('?' * len(edge_types))})"
            params.extend(edge_types)
        return [_edge_record(row) for row in
                self.connection.execute(query + " ORDER BY type,dst,src", params)]

    def stats(self) -> dict[str, Any]:
        nodes = self.connection.execute(
            "SELECT type, count(*) AS n FROM nodes GROUP BY type ORDER BY type").fetchall()
        edges = self.connection.execute(
            "SELECT type, count(*) AS n FROM edges GROUP BY type ORDER BY type").fetchall()
        return {
            "nodes_total": sum(row["n"] for row in nodes),
            "edges_total": sum(row["n"] for row in edges),
            "nodes_by_type": {row["type"]: row["n"] for row in nodes},
            "edges_by_type": {row["type"]: row["n"] for row in edges},
            "schema_version": SCHEMA_VERSION,
        }

    def set_hashes(self) -> dict[str, str]:
        """STEP 28 material: deterministic fingerprints of the whole graph."""
        nodes = [dict(row) for row in self.connection.execute("SELECT * FROM nodes")]
        edges = [{"from": row["src"], "to": row["dst"], "type": row["type"],
                  "metadata": row["metadata"]}
                 for row in self.connection.execute("SELECT * FROM edges")]
        return {
            "node_set_hash": node_set_hash(nodes),
            "edge_set_hash": edge_set_hash(edges),
        }

    def close(self) -> None:
        self.connection.close()

    def _set_meta(self, key: str, value: str) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO meta VALUES (?,?)", (key, value))


def _node_record(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"], "type": row["type"], "name": row["name"],
        "source": row["source"], "path": row["path"],
        "metadata": json.loads(row["metadata"]), "content_hash": row["content_hash"],
        "observed_at": row["observed_at"], "schema_version": row["schema_version"],
    }


def _edge_record(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "from": row["src"], "to": row["dst"], "type": row["type"],
        "metadata": json.loads(row["metadata"]), "evidence": json.loads(row["evidence"]),
        "schema_version": row["schema_version"] if "schema_version" in row.keys()
                          else SCHEMA_VERSION,
    }


def _edge_hash(edge: dict[str, Any]) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(
        {"from": edge["from"], "to": edge["to"], "type": edge["type"],
         "metadata": edge["metadata"], "evidence": sorted(edge["evidence"])},
        sort_keys=True, default=str).encode()).hexdigest()
