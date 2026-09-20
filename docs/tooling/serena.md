# Serena Integration (Semantic Code Intelligence)

Serena 2.0.0.dev0-a418894d, LSP backend, `ide-assistant` context,
21 tools (exact names from live `tools/list`): find_symbol,
find_referencing_symbols, find_declaration, find_implementations,
get_symbols_overview, get_diagnostics_for_file, replace_content,
replace_in_files, replace_symbol_body, insert_before_symbol,
insert_after_symbol, rename_symbol, safe_delete_symbol, list/read/write/
edit/rename/delete_memory, initial_instructions, onboarding.

## Role

Serena is TIM's SEMANTIC CODE layer: symbol lookup, definitions,
references, bounded code reading, precise navigation, scoped edits.
It is NOT the mission/incident graph (Graph MCP), not visualization
(Graphify), not the knowledge base (Obsidian), not a production repair
controller.

## Project topology — the nested-repo finding

Registering only the control root `~/Documents/TIM` is
**insufficient**: `tim/` is a nested repository excluded by the control
repo's ignore rules, and Serena respects them — symbol requests into
`tim/` fail with "path is ignored". Correct additive topology:

| Project | Role |
|---|---|
| `~/Documents/TIM` | control/context (read) |
| `~/Documents/TIM/tim` | canonical platform code (read source) |
| `worktrees/<mission>` | the ONLY writable scope for edits |

Registered additively in `~/.serena/serena_config.yml` (2026-09-18).

## Read/write boundary

READ_ROOT = `~/Documents/TIM/tim` (navigation only).
WRITE_ROOT = the isolated mission worktree. Workers never edit the
productive checkout; the main checkout stays read-only.

## Payload conventions

`find_symbol` -> [{name_path (nesting separator `/`), kind,
relative_path, body_location}]. `find_referencing_symbols` ->
{file: {kind: [{name_path, body_location, content_around_reference}]}}
(flatten via `src.agent_infra.serena_client.flatten_references`).
Note: `search_for_pattern` is not part of the ide-assistant toolset —
tests are found via references into `tests/`.

## Dashboard note

`web_dashboard: true` in config, tray manager present; the previously
observed empty dashboard sections (no projects/tools) predate the
project registration (config modified 2026-09-18 13:06). The config
contains a dashboard `auth_secret` — it must never appear in the graph,
docs, tests, logs or commits (scan: EXPOSED=NO).
