"""TIM OPS MCP — read-only view of TIM's runtime state for agents.

Task Engine (SQLite, opened with mode=ro), tool health probes and the
Research Lab register/reports. No tool writes anything: there is no
code path to TIM databases in write mode, the runtime, queues, git or
orders. Sources that are not configured answer "not_configured".
"""

SCHEMA_VERSION = "1.0.0"
SERVER_NAME = "tim-ops-mcp"
