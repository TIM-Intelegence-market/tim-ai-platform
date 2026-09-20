"""TIM GRAPH MCP — deterministic, queryable relationship graph for TIM.

Machine-readable graph over code, database schema, runtime components,
missions/gates, incidents/repair recipes, agents/tools, GitHub artifacts,
decisions and Obsidian notes. Read-only towards TIM; the only writable
surface is this package's own local SQLite index (default .runtime/graph/).

Obsidian stays the human-readable knowledge base; Graphify stays the
visualization layer. This package is the canonical structured interface.
"""

SCHEMA_VERSION = "1.0.0"
SERVER_NAME = "tim-graph-mcp"
