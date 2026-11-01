"""MCP epic, package M4 (rest): the issue pipeline's Codex analysis and tim-ops.
The pipeline itself is protected, so this package only documents the current
state. The test keeps that section true: it names every registered server and
matches how the pipeline actually starts Codex."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "GITHUB_ISSUE_PIPELINE.md"
PIPELINE = ROOT / "scripts" / "github_issue_pipeline.py"
HEADING = "## MCP context for the Codex analysis"


def _section() -> str:
    text = DOC.read_text(encoding="utf-8")
    assert HEADING in text, "pipeline doc lacks the MCP context section"
    body = text.split(HEADING, 1)[1]
    return body.split("\n## ", 1)[0]


def test_section_names_every_registered_server():
    servers = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    section = _section()
    for name in servers:
        assert f"`{name}`" in section


def test_section_matches_how_the_pipeline_starts_codex():
    source = PIPELINE.read_text(encoding="utf-8")
    assert re.search(r'"codex", "exec".*"--sandbox", "read-only"', source, flags=re.S)
    section = _section()
    assert "codex exec" in section and "--sandbox read-only" in section
    assert "~/.codex/config.toml" in section
    # The analysis is posted as an issue comment; the leak risk must stay documented.
    assert "issue comment" in section and "public" in section
    # The prompt does not mention the servers yet; the doc must not claim otherwise.
    prompt = source.split("def analysis_prompt", 1)[1].split("\ndef ", 1)[0]
    if "tim-ops" not in prompt:
        assert "does not mention" in section
