from __future__ import annotations

from pathlib import Path

from src.local_first.patch_executor import redact_code_secrets

ROOT = Path(__file__).resolve().parents[1]


def test_names_and_type_hints_stay_readable():
    for line in ("token: int", "token=claim_token+1", "token=token", "    token = self._next_token()",
                 "def check(password: str) -> bool:"):
        assert redact_code_secrets(line) == line


def test_secret_literals_and_known_tokens_are_redacted():
    assert redact_code_secrets("TOKEN = 'ghp_SUPERSECRETTOKEN'") == "TOKEN = '<REDACTED>'"
    assert redact_code_secrets('GITHUB_TOKEN = "abcdefghijkl"') == 'GITHUB_TOKEN = "<REDACTED>"'
    assert "ghp_" not in redact_code_secrets("value = ghp_" + "A" * 36)


def test_task_governance_sources_count_as_complete_context():
    # These files blocked issues #186, #188 and #189 because "token: int" looked like a secret.
    for relative in ("src/task_governance/registry.py", "src/task_governance/sync.py"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert redact_code_secrets(text) == text
    secret = (ROOT / "tests/task_governance/test_review_findings_137.py").read_text(encoding="utf-8")
    assert "SUPERSECRETTOKEN" not in redact_code_secrets(secret)


def test_constant_names_are_not_secrets_but_values_are():
    for line in ("TOKEN_VARIABLE = 'TIM_LIVE_CHECK_TOKEN'", "TOKEN_INVALID = 'token_invalid'"):
        assert redact_code_secrets(line) == line
    assert redact_code_secrets("password = 'supersecret1'") == "password = '<REDACTED>'"
