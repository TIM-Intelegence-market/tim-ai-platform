# Security

- Default-deny write policy.
- Explicit TIM-IM write allowlist.
- TIM V1 data, historical artifacts and secrets are protected.
- Path traversal and symlink escapes are rejected.
- `.env`, credentials, private keys and wallets are excluded.
- Source contents are never executed.
- Baseline scan requires no network.
- MCP exposes no write, Git, trading or external-action tool.
