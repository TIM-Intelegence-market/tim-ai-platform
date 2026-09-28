# TIM V2: Portable Path Inventory

**PROGRAM 1 — PHASE 1.1 (v1.0)**

Program: `TIM-V2-COMPLETION-PROGRAM-20260803`

## Purpose

Catalog every host-bound and user-specific absolute path in the executable
scope and classify each occurrence so portability defects are either removed
or provably safe.

## Scope searched

`src/`, `config/`, `scripts/`, `tests/`, `.github/`, `main.py`,
`docker-compose.yml`.

Patterns: `/Users/`, `/home/`, drive-letter paths, `Documents/TIM`,
`~/…` HOME references, `~/Library`, hostnames, absolute repo roots.

## Findings

| Count | Classification |
|---|---|
| 0 | MUST REPLACE (runtime code) |
| 10 | HOST CONFIG SAFE (HOME-relative credential defaults) |
| 3 | TEST FIXTURE (negative-test assertions) |

## Key result — graphify_mcp.yaml

The only host-bound runtime configuration was
`config/tim_manager/graphify_mcp.yaml`, which hardcoded:

- `/Users/tim/.local/bin/graphify-mcp`
- `/Users/tim/Documents/TIM/tim/...`

It now uses the portable placeholder `@TIM_REPO_ROOT@` and a bare executable
name resolved at runtime:

```yaml
"command": "graphify-mcp",
"arguments": ["@TIM_REPO_ROOT@/graphify-out/graph.json"],
"working_directory": "@TIM_REPO_ROOT@",
"graph_path": "@TIM_REPO_ROOT@/graphify-out/graph.json",
```

Path resolution happens in `src/tim_manager/config_paths.py`; config files
contain no Python expressions and no resolved absolute paths.

## HOST CONFIG SAFE entries (kept, provably portable)

`config/secrets.py` and `scripts/admin/*` use `~/…` only as *defaults* for
credential handoff files (`.pgpass`, Keychain alternatives, admin handoff
JSON). These are expanded at runtime against the current user's HOME, so they
are portable across machines and users and are not runtime path coupling.

## TEST FIXTURE entries (kept)

`tests/tim_manager/test_portable_paths_v2.py` intentionally asserts that
`/Users/` and `/home/` do not appear in runtime config, and that absolute
paths outside the repository are rejected.

## Conclusion

**PORTABLE — zero MUST-REPLACE occurrences remain in executable scope.**

Status: **INVENTORY COMPLETE**