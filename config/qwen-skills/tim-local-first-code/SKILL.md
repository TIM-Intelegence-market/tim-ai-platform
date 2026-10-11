---
name: tim-local-first-code
description: Conventions of the local-first worker code (src/local_first, src/llm).
metadata:
  tim-applies-to: "src/local_first/**, src/llm/**"
---

# Local-first worker conventions

- Fail closed: on unclear input return or raise a BLOCKED result, never guess.
- Results are plain dicts or frozen dataclasses with an `as_dict()` method.
- Write state files atomically (write to a temp file, then `replace`).
- Model output is untrusted: validate type, length and allowed values before using it.
- Keep functions small and typed (`from __future__ import annotations`, type hints).
- Bounded everything: limits on file count, sizes, retries and timeouts are constants
  at the top of the module.
