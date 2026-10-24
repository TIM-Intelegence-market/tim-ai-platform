# TIM MCP — Client-Anbindung außerhalb des Repos

Issue #152, Paket M2. Claude Code liest die Server aus der projektbezogenen
`.mcp.json` im Repo-Root (fragt pro Checkout einmal nach Freigabe). Codex und
Claude Desktop lesen ihre eigene Konfiguration außerhalb des Repos; dafür sind
die Blöcke unten gedacht. Beide Server sind nur lesend (`docs/graph_mcp/security.md`,
`docs/ops_mcp/README.md`).

| Server | Modul | Inhalt |
|---|---|---|
| `tim-graph` | `src.graph_mcp.mcp_server` | Code-, Doku- und Wissensgraph |
| `tim-ops` | `src.ops_mcp.mcp_server` | Task Engine, Tool-Health, Research Lab |

## Vorbereitung

1. `<tim worktree>` überall durch den absoluten Pfad des Checkouts ersetzen.
   Beide Clients starten den Server aus ihrem eigenen Arbeitsverzeichnis,
   deshalb müssen `PYTHONPATH` und die `*_ROOT`-Variablen absolut sein.
2. Die venv muss existieren: `<tim worktree>/.venv/bin/python`.
3. `tim-graph` braucht einmal einen Index, sonst liefert `graph_health`
   `"status": "empty"` (siehe `docs/graph_mcp/runbook.md`, `refresh-all`).

Optionale Variablen, nur ergänzen, wenn vorhanden (keine Zugangsdaten):

- `TIM_OBSIDIAN_VAULT` bei `tim-graph`: Pfad zum Obsidian-Vault für Missions- und Notizkontext.
- `TIM_OPS_TASK_DB` bei `tim-ops`: Pfad zur Task-Engine-SQLite. Ohne sie antworten die
  Task-Werkzeuge mit `not_configured`, die übrigen Werkzeuge laufen trotzdem.

## Codex

Datei `~/.codex/config.toml`:

```toml
[mcp_servers.tim-graph]
command = "<tim worktree>/.venv/bin/python"
args = ["-m", "src.graph_mcp.mcp_server"]
env = { TIM_GRAPH_MCP_ROOT = "<tim worktree>", PYTHONPATH = "<tim worktree>" }

[mcp_servers.tim-ops]
command = "<tim worktree>/.venv/bin/python"
args = ["-m", "src.ops_mcp.mcp_server"]
env = { TIM_OPS_MCP_ROOT = "<tim worktree>", PYTHONPATH = "<tim worktree>" }
```

Prüfen: `codex mcp list` zeigt beide Server.

## Claude Desktop

Datei auf dem Mac: `~/Library/Application Support/Claude/claude_desktop_config.json`
(Einstellungen → Entwickler → Konfiguration bearbeiten). Vorhandene Einträge unter
`mcpServers` behalten und diese beiden ergänzen:

```json
{
  "mcpServers": {
    "tim-graph": {
      "command": "<tim worktree>/.venv/bin/python",
      "args": ["-m", "src.graph_mcp.mcp_server"],
      "env": {
        "TIM_GRAPH_MCP_ROOT": "<tim worktree>",
        "PYTHONPATH": "<tim worktree>"
      }
    },
    "tim-ops": {
      "command": "<tim worktree>/.venv/bin/python",
      "args": ["-m", "src.ops_mcp.mcp_server"],
      "env": {
        "TIM_OPS_MCP_ROOT": "<tim worktree>",
        "PYTHONPATH": "<tim worktree>"
      }
    }
  }
}
```

Danach Claude Desktop neu starten; die Werkzeuge erscheinen im Werkzeugmenü des Chats.

## Abnahme

- Im Repo: `tests/ops_mcp/test_client_snippets.py` prüft, dass beide Blöcke zu `.mcp.json`
  passen, keine Zugangsdaten enthalten und mit eingesetztem Pfad beide Server aus einem
  fremden Arbeitsverzeichnis starten.
- Auf dem Mac (offen, außerhalb des Repos): Blöcke eintragen, in Codex `codex mcp list`,
  in Claude Desktop je einmal `graph_health` und `ops_health` aufrufen.
