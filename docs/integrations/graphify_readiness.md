# Graphify Readiness

Date: 2026-07-29

Repository: `uezeyiraydin-cell/tim-ai-platform`

Evaluated branch: `codex/github-foundation`

Evaluated commit: `925ad91e6b920edb5d7fcb372ed1bb39fa43bda4`

## Result

**READY FOR CONTROLLED LOCAL INDEXING**

The private GitHub repository is reachable with authenticated read access, the
local checkout tracks the same remote branch and commit, and the worktree was
clean before integration artifacts were added.

The GitHub default branch is `main`, but it contains only the initial
placeholder commit. It is not the authoritative TIM state. Every Graphify run
in this review used the checked-out `codex/github-foundation` branch.

## Repository checks

| Requirement | Result | Evidence / limitation |
|---|---|---|
| Git repository | PASS | Standalone TIM repository |
| Commit history | PASS | History present; evaluated immutable commit recorded above |
| GitHub remote | PASS | `origin` points to the private TIM repository |
| Remote reachability | PASS | GitHub API and remote branch query succeeded |
| Local/remote equality | PASS | Foundation branch commit matched before indexing |
| Default branch | EXISTS, NOT AUTHORITATIVE | `main` is the placeholder |
| Working tree at start | PASS | Clean |
| README | PASS | `README.md` present |
| Documentation | PASS | `docs/` present |
| Schemas/source/tests/config | PASS | All present |
| Master prompts | PASS | Present and read-only |
| Large tracked files | PASS | No tracked file at least 5 MiB before graph output |
| Sensitive tracked filenames | PASS | No tracked `.env`, key, wallet, secret, backup, or raw-data path |

## Graphify runtime

The official PyPI package `graphifyy 0.9.29` was installed with `uv` in an
isolated user tool environment. Graphify's open-source local mode requires no
Graphify account or OAuth connection. Source parsing, graph generation, and
queries run on the local machine.

Optional extras used:

- `sql` for SQL AST parsing;
- `ollama` for controlled local semantic-extraction tests;
- `mcp` for the local read-only MCP validation.

The `mcp` extra resolved to incompatible `mcp 2.0.0`; Graphify imports
`mcp.types.AnyUrl`, which that release no longer exports. The isolated tool
environment was pinned to `mcp 1.29.0`, after which the MCP server started and
responded successfully. No TIM dependency was changed.

## Index boundaries

`.graphifyignore` uses a fail-closed allowlist. Full-content candidates are:

- `docs/`
- `schemas/`
- `src/`
- `tests/`
- `config/` (the actual repository path corresponding to requested `configs/`)
- `TIM_MASTER_PROMPTS/`

Artifacts, future `research/`, and future `datasets/` are content-excluded. A
sanitized `graphify-metadata/catalog.json` represents only group-level counts,
status, and relationships. Data, environment files, credentials, private
material, backups, raw data, databases, logs, keys, wallets, and common large
binary types are explicitly excluded.

## Readiness limitations

- GitHub `main` must not be used for indexing until an explicitly approved
  integration decision makes an authoritative commit the default.
- Metadata-only JSON is present in the extraction manifest but produces no AST
  entity nodes in Graphify 0.9.29.
- Full Markdown indexing requires a semantic backend that returns Graphify's
  required JSON reliably. The available local models did not pass this gate.
- No TIM Manager workspace/client connection is configured.
