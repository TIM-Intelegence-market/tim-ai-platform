# TIM-IM V1 Compatibility Matrix

| Component | Verified version/state | Status | Notes |
|---|---|---|---|
| macOS | 26.5.1, build 25F80 | verified | Final local release host |
| Python | 3.14.6 | verified | Primary `.venv` |
| pytest | 8.4.2 | verified | 237-test full regression |
| pytest-asyncio | 0.26.0 | verified with debt | 145 deprecation warnings |
| jsonschema | 4.26.0 | verified | Available in `.venv-research` |
| SQLite / FTS5 | Python runtime build | verified | Isolated TIM-IM index |
| Git | standalone local repository | verified | `main`; annotated release tag |
| Snapshot schema | 1.1 | verified | Historical schema 1.0 validated |
| Local MCP stdio | six read tools | verified | No exposed mutation tool |
| Claude/OpenCode clients | example configuration only | not tested | No actual client connection |
| ChatGPT Workspace Agent | published but unbound | not integrated | External integration |
| Linux | not tested | unknown | No release claim |
| Windows | not tested | unknown | CRLF policy exists for cmd/bat only |
| Remote CI | not configured | not tested | Local verification is authoritative |
