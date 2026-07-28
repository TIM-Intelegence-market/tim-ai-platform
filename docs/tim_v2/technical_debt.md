# TIM V2 Technical Debt Baseline

| ID | Debt | Priority | Target | Acceptance evidence |
|---|---|---|---|---|
| TD-01 | pytest-asyncio 0.26 emits 145 deprecations on Python 3.14 | high | V2.0 compatibility lane | warning-free supported matrix |
| TD-02 | no remote or CI is configured | medium | separate release-infrastructure task | protected remote and green CI |
| TD-03 | MCP search store is not opened by explicit SQLite read-only URI | medium | V2.1 | no initialization on read path |
| TD-04 | Workspace Agent is not connected to TIM-IM | low | optional integration | authenticated read-only end-to-end test |
| TD-05 | optional semantic source groups lack adapters | medium | V2.1–V2.3 | visible health and coverage tests |
| TD-06 | move events lack explicit `from_path` | low | V2.1 event schema | backward-compatible move provenance |
| TD-07 | local Postgres development password is static | medium | V2.0 security | external secret injection |
| TD-08 | no formal SBOM or dependency lock is versioned | medium | V2.0 | reproducible lock and SBOM |
| TD-09 | macOS is the only verified release platform | medium | V2.0 CI | Linux support decision and evidence |
| TD-10 | runtime restore drills are manual | high | V2.0 operations | automated, audited restore rehearsal |

Debt does not authorize unscoped refactoring. Each item requires a dedicated
decision, tests and release note.
