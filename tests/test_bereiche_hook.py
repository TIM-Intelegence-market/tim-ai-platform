"""UserPromptSubmit hook .claude/hooks/bereiche.py: memory areas by keyword (Uzi 04.11.2026)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "bereiche.py"
SETTINGS = Path(__file__).resolve().parents[1] / ".claude" / "settings.json"


def _run(prompt: str | None, folder: Path | None, raw: str | None = None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "TIM_MEMORY_DIR"}
    if folder is not None:
        env["TIM_MEMORY_DIR"] = str(folder)
    data = raw if raw is not None else json.dumps({"prompt": prompt, "hook_event_name": "UserPromptSubmit"})
    return subprocess.run([sys.executable, str(HOOK)], input=data, capture_output=True, text=True, env=env, timeout=10, check=False)


def _memory(tmp_path: Path) -> Path:
    for area in ("bereich-git-pr", "bereich-research", "bereich-chart-link", "bereich-echtgeld", "bereich-mac-server", "bereich-allgemein"):
        (tmp_path / f"{area}.md").write_text(f"---\nname: {area}\ndescription: x\n---\nInhalt {area}\n", encoding="utf-8")
    return tmp_path


def test_matching_areas_are_added_without_frontmatter(tmp_path) -> None:
    result = _run("Merge PR #97 und prüf den Chart-Link", _memory(tmp_path))
    assert result.returncode == 0 and result.stderr == ""
    out = json.loads(result.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "UserPromptSubmit"
    text = out["additionalContext"]
    assert "Inhalt bereich-git-pr" in text and "Inhalt bereich-chart-link" in text
    assert "Inhalt bereich-echtgeld" not in text and "description:" not in text


def test_short_words_match_whole_and_unrelated_prompts_add_nothing(tmp_path) -> None:
    folder = _memory(tmp_path)
    assert _run("prüf das bitte", folder).stdout == ""  # "pr" is not in "prüf"
    assert _run("go", folder).stdout == ""
    assert "bereich-research" in _run("S7b und Holdout?", folder).stdout
    assert "bereich-echtgeld" in _run("Ist bei Kraken eine Position offen?", folder).stdout


def test_never_blocks_without_memory_or_with_bad_input(tmp_path) -> None:
    for result in (_run("Merge PR", tmp_path / "missing"), _run(None, _memory(tmp_path), raw="kein json"), _run("", _memory(tmp_path))):
        assert result.returncode == 0 and result.stdout == ""


def test_context_is_capped(tmp_path) -> None:
    folder = _memory(tmp_path)
    (folder / "bereich-git-pr.md").write_text("x" * 20000, encoding="utf-8")
    text = json.loads(_run("Merge PR und Chart und Kraken", folder).stdout)["hookSpecificOutput"]["additionalContext"]
    assert len(text) <= 9000 + 200 and "bereich-git-pr" not in text


def test_hook_is_registered_and_holds_no_memory_facts() -> None:
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    command = settings["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
    assert ".claude/hooks/bereiche.py" in command
    source = HOOK.read_text(encoding="utf-8")
    for secret_like in ("warpgate port", "2222", "com.tim.live", "env_01"):
        assert secret_like not in source.lower()
