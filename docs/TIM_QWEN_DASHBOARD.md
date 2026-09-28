# TIM QWEN-DASHBOARD

The local Qwen dashboard is an observation and explicit-submission surface for
the existing `tim-local-qwen` supervisor. It never starts a second repair
worker and contains no trading, execution, production-data, or GitHub-write
control.

Use `scripts/tim-qwen status` for a JSON report or `scripts/tim-qwen dashboard`
for the loopback-only web view. `master run` sends a planning/test question to
local Ollama and writes only a local transcript under `.tim/qwen-dashboard/`.
Task submission requires `--confirm-sandbox-submit`; the submitted JSON must
already meet the existing A3 sandbox contract. The existing Qwen daemon is
controlled with `scripts/tim-qwen daemon start|stop`.
