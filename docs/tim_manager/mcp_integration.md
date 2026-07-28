# MCP Integration

Start the read-only server:

```bash
/Users/tim/Documents/TIM/tim/.venv/bin/python -m src.tim_manager.cli serve-mcp
```

Example command configuration for Claude Desktop, Claude Code or OpenCode:

```json
{
  "mcpServers": {
    "tim-manager": {
      "command": "/Users/tim/Documents/TIM/tim/.venv/bin/python",
      "args": ["-m", "src.tim_manager.cli", "serve-mcp"],
      "cwd": "/Users/tim/Documents/TIM/tim"
    }
  }
}
```

No global application configuration is modified automatically. The exposed
tool surface contains only status, module, risk, source-health, search and
query operations; it exposes no mutation method. This is not an absolute
filesystem-read-only guarantee: `tim_search` opens the isolated TIM-IM SQLite
index with the normal manager-store connection, so a missing index could be
initialized inside the TIM-IM write allowlist. Protected TIM-V1 paths remain
outside that allowlist.

## Verified integration boundary

- Local stdio MCP server: implemented and locally protocol-tested.
- Claude Desktop / Claude Code / OpenCode: example configuration only.
- Actual Claude or OpenCode client connection: not configured and not tested.
- ChatGPT Workspace Agent: not connected to this MCP server or the TIM-IM
  artifact store. A separately published agent is not proof of data binding.
