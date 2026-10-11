---
name: tim-safety-boundaries
description: Hard limits for every TIM code change made by a local model.
metadata:
  tim-applies-to: "always"
---

# Safety boundaries

TIM observes markets; it never trades with real money. These limits hold for every change:

- No order placement, position sizing, live trading or execution switches.
  `TIM_LIVE_TRADING` and `TIM_EXECUTION_ENABLED` stay `0`.
- No production databases, queues or outboxes; no deleting or resetting stored data.
- No secrets, tokens or credentials in code, tests or output.
- No `shell=True`, no `os.system`, no disabled TLS verification.
- Only touch the allowed paths of the task. If the fix needs another file, say so in the
  summary instead of working around it.
- When unsure, make the smaller change and let the tests decide.
