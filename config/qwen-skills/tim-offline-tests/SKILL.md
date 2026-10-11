---
name: tim-offline-tests
description: How TIM unit tests must look so they pass in the local sandbox and in CI.
metadata:
  tim-applies-to: "tests/**"
---

# Offline, deterministic tests

The tests run inside a sandbox with no network, a throwaway HOME and no credentials.
A test that needs any of these fails there.

- Use `tmp_path` for files and `monkeypatch` for environment variables and attributes.
- Replace network, GitHub, exchange, Ollama and subprocess calls with fakes:
  `monkeypatch.setattr(module, "urlopen", fake_urlopen)`.
- No `time.sleep`, no wall-clock assertions. Pass a clock or a fixed timestamp instead.
- No randomness without a fixed seed.
- One behaviour per test function. Name it after the behaviour:
  `test_rejects_path_outside_allowlist`.
- Assert the exact value, not only that something is truthy.
- Import the code under test the way existing tests in the same folder do
  (`from src.local_first import patch_executor`).
- Never weaken a safety check so a test passes. If the test and the safety rule disagree,
  the test is wrong.
