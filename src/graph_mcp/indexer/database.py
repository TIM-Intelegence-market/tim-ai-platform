"""Database graph indexer (STEP 8): tables/columns/keys from schema.sql,
READS/WRITES edges from SQL strings in code — always with evidence."""
from __future__ import annotations

import re
from pathlib import Path

from src.graph_mcp.indexer import IndexResult
from src.graph_mcp.schema import Edge, EdgeType, Node, NodeType, stable_id, utc_now

_CREATE_TABLE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z_][a-z0-9_]*)\s*\((.*?)\n\);",
    re.IGNORECASE | re.DOTALL)
_COLUMN = re.compile(r"^\s*([a-z_][a-z0-9_]*)\s+([A-Za-z]+(?:\s*\([^)]*\))?)")
_REFERENCE = re.compile(r"REFERENCES\s+([a-z_][a-z0-9_]*)", re.IGNORECASE)
_SQL_TABLE = re.compile(
    r"""(?ix)\b(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+([a-z_][a-z0-9_]*)""")
_WRITE_HINTS = re.compile(r"""(?ix)\b(INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|
    CREATE\s+TABLE|DROP\s+TABLE|ALTER\s+TABLE|UPSERT)\b""")

DATABASE_ID = "database:tim"


class DatabaseIndexer:
    source = "database"

    def __init__(self, root: Path, schema_path: str = "src/database/schema.sql",
                 database_name: str = "tim") -> None:
        self.root = root.resolve()
        self.schema_file = self.root / schema_path
        self.database_name = database_name

    def tables(self) -> dict[str, dict]:
        """Parse CREATE TABLE blocks (unit-testable without a store)."""
        tables: dict[str, dict] = {}
        if not self.schema_file.is_file():
            return tables
        for match in _CREATE_TABLE.finditer(self.schema_file.read_text(encoding="utf-8")):
            name, body = match.group(1), match.group(2)
            columns, references = [], []
            for line in body.splitlines():
                line = line.strip().rstrip(",")
                if not line or line.startswith(("--", "PRIMARY", "UNIQUE", "CHECK",
                                                "CONSTRAINT", "FOREIGN")):
                    continue
                column = _COLUMN.match(line)
                if column:
                    columns.append({"name": column.group(1), "type": column.group(2)})
                reference = _REFERENCE.search(line)
                if reference:
                    references.append(reference.group(1))
            tables[name] = {"columns": columns, "references": sorted(set(references))}
        return tables

    def index(self) -> IndexResult:
        result = IndexResult(source=self.source)
        observed = utc_now()
        src = self.source
        result.nodes.append(Node(DATABASE_ID, NodeType.DATABASE, self.database_name,
                                 src, str(self.schema_file.relative_to(self.root)),
                                 {}).record(observed))
        tables = self.tables()
        table_names = set(tables)
        for name, spec in sorted(tables.items()):
            table_id = stable_id("table", self.database_name, name)
            result.nodes.append(Node(table_id, NodeType.TABLE, name, src,
                                     "src/database/schema.sql",
                                     {"columns": len(spec["columns"])}).record(observed))
            result.edges.append(Edge(DATABASE_ID, table_id, EdgeType.CONTAINS).record())
            for column in spec["columns"]:
                column_id = stable_id("column", self.database_name, name, column["name"])
                result.nodes.append(Node(column_id, NodeType.COLUMN, column["name"], src,
                                         "src/database/schema.sql",
                                         {"sql_type": column["type"]}).record(observed))
                result.edges.append(Edge(table_id, column_id, EdgeType.CONTAINS).record())
            for reference in spec["references"]:
                if reference in table_names and reference != name:
                    result.edges.append(Edge(
                        table_id, stable_id("table", self.database_name, reference),
                        EdgeType.REFERENCES,
                        {"resolution_method": "schema_sql_fk"},
                        evidence=["src/database/schema.sql"]).record())
        self._code_access(result, table_names, observed)
        result.metrics.update({"TABLES": len(tables), "NODES_ADDED": len(result.nodes),
                               "EDGES_ADDED": len(result.edges)})
        return result

    def _code_access(self, result: IndexResult, table_names: set[str], observed: str) -> None:
        """MODULE READS/WRITES TABLE with file:line evidence (STEP 8)."""
        from src.graph_mcp.indexer.code import iter_python_files
        for path in iter_python_files(self.root):
            relative = path.relative_to(self.root).as_posix()
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            module_id = None
            for lineno, line in enumerate(lines, start=1):
                for match in _SQL_TABLE.finditer(line):
                    table = match.group(1)
                    if table not in table_names:
                        continue
                    if module_id is None:
                        module = path.relative_to(self.root).with_suffix("")
                        module_id = stable_id("module", ".".join(module.parts))
                    edge_type = (EdgeType.WRITES if _WRITE_HINTS.search(line)
                                 else EdgeType.READS)
                    result.edges.append(Edge(
                        module_id, stable_id("table", self.database_name, table),
                        edge_type,
                        {"resolution_method": "sql_string_match", "confidence": 0.9},
                        evidence=[f"{relative}:L{lineno}"]).record())
