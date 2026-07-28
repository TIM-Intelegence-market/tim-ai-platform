# TIM-IM V1 Known Limitations

| ID | Limitation | Impact | Release disposition |
|---|---|---|---|
| KL-01 | Contradiction extraction requires explicit `tim_manager_claims` and controlled Status/Boolean rules. | Arbitrary prose conflicts are not inferred. | Intentional safety boundary. |
| KL-02 | `tim_search` does not open the isolated SQLite index with an explicit SQLite read-only URI. | A missing index can be initialized inside the TIM-IM allowlist. | Non-blocking; no protected write capability. |
| KL-03 | Several optional source groups are not configured. | Semantic completeness is not implied by required-source health. | Visible in Source Coverage. |
| KL-04 | The published Workspace Agent has no TIM-IM connector, MCP or file binding. | No remote/UI access to local TIM-IM data. | Separate integration project. |
| KL-05 | 145 pytest-asyncio deprecation warnings occur on Python 3.14. | Compatibility risk before Python 3.16. | Technical debt; no functional failure. |
| KL-06 | No Git remote is configured. | Release exists locally only. | Remote setup requires a separate authority decision. |
| KL-07 | Volatile protected runtime files continue to change under the existing TIM runtime. | Global byte immutability is not claimed for runtime state. | TIM-IM write protection remains enforced. |
