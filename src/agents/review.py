"""Review Agent V1: deterministic, read-only review of a unified diff.

Contract (Constitution Band 5, Master Prompt 09), declared in ``SPEC``:
- Mission: find known risk patterns in a change and report them.
- Reads: one unified diff (``git diff`` output). Nothing else: no repository
  checkout, no network, no model.
- Writes: a review report only. The verdict is ``FINDINGS`` or
  ``NO_FINDINGS`` and never an approval; the agent cannot approve, merge or
  bypass its own rules.
- Replay: the report is a pure function of the diff.

Every report lists which rules ran and what the agent does not check, so a
clean report is never mistaken for a full review.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from src.agents.contract import AgentSpec

READ_DIFF = "read_diff"
WRITE_REPORT = "write_review_report"

SPEC = AgentSpec(
    name="review-agent",
    version="1.0.0",
    mission="Report known risk patterns in a unified diff; never approve.",
    owner="uezeyiraydin-cell",
    allowed_actions=(READ_DIFF, WRITE_REPORT),
    tools=("unified_diff",),
    max_input_bytes=16 * 1024 * 1024,
    timeout_seconds=120,
)

INPUT_SCHEMA = "tim.review.input.v1"
REPORT_SCHEMA = "tim.review.report.v1"
SEVERITY_ORDER = ("critical", "high", "medium", "low")

RULES = {
    "test-weakened": "Tests entfernt, Asserts reduziert oder skip/xfail ergänzt",
    "secret-in-diff": "Zugangsdaten oder Schlüssel in hinzugefügten Zeilen",
    "sensitive-file": "Änderung an Schlüssel-, Zertifikats- oder .env-Dateien",
    "workflow-permission-escalation": "GitHub-Workflow erhält Schreibrechte",
    "source-without-tests": "Quellcode geändert, aber kein Test im Diff",
}
NOT_CHECKED = (
    "Fachliche Korrektheit und Logikfehler",
    "Laufzeitverhalten, Tests werden nicht ausgeführt",
    "Code außerhalb des Diffs",
    "Unbekannte Muster für Zugangsdaten",
)

_STRING_LITERAL = re.compile(r"(['\"]).*?\1")
_SKIP = re.compile(r"pytest\.mark\.(skip|skipif|xfail)\b|pytest\.(skip|xfail)\(|@unittest\.skip|\.skipTest\(")
_ASSERT = re.compile(r"^\s*(assert\b|self\.assert\w*\(|pytest\.raises\()")
_TEST_DEF = re.compile(r"^\s*(async\s+)?def\s+test_\w*\(")
_SECRETS = (
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b")),
    ("API key", re.compile(r"\bsk-(ant-)?[A-Za-z0-9_-]{20,}\b")),
    ("password literal", re.compile(r"(?i)\b(password|passwd|secret|api_key|token)\s*[:=]\s*['\"][^'\"\s]{8,}['\"]")),
)
_SENSITIVE_FILE = re.compile(r"(^|/)(\.env(\.[\w-]+)?|[^/]+\.(pem|key|p12|pfx)|id_rsa|id_ed25519)$")
_WORKFLOW_WRITE = re.compile(r"^\s*(permissions\s*:\s*write-all|[\w-]+\s*:\s*write)\s*(#.*)?$")


class ReviewInputError(ValueError):
    """The diff cannot be reviewed safely; no report is produced."""


@dataclass
class FileChange:
    path: str
    old_path: str
    deleted: bool = False
    added: list[tuple[int, str]] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)


_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def parse_unified_diff(diff: str) -> list[FileChange]:
    files: list[FileChange] = []
    current: FileChange | None = None
    new_line = 0
    in_hunk = False
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            match = re.match(r"diff --git a/(.+?) b/(.+)$", line)
            if not match:
                raise ReviewInputError(f"unreadable diff header: {line[:120]}")
            current = FileChange(path=match.group(2), old_path=match.group(1))
            files.append(current)
            in_hunk = False
        elif current is None:
            continue
        elif not in_hunk and line.startswith("--- "):
            continue
        elif not in_hunk and line.startswith("+++ "):
            if line == "+++ /dev/null":
                current.deleted = True
        elif not in_hunk and line.startswith("deleted file mode"):
            current.deleted = True
        elif line.startswith("@@"):
            match = _HUNK.match(line)
            if not match:
                raise ReviewInputError(f"unreadable hunk header: {line[:120]}")
            new_line = int(match.group(1))
            in_hunk = True
        elif in_hunk and line.startswith("+"):
            current.added.append((new_line, line[1:]))
            new_line += 1
        elif in_hunk and line.startswith("-"):
            current.removed.append(line[1:])
        elif in_hunk and (line.startswith(" ") or line == ""):
            new_line += 1
        elif in_hunk and line.startswith("\\"):
            continue
        else:
            in_hunk = False
    return files


def _is_test(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return path.startswith("tests/") or "/tests/" in path or name.startswith("test_") or name.endswith("_test.py")


def _finding(path: str, line: int | None, rule: str, severity: str, message: str) -> dict[str, Any]:
    return {"file": path, "line": line, "rule": rule, "severity": severity, "message": message}


def _test_findings(change: FileChange) -> list[dict[str, Any]]:
    findings = []
    path = change.old_path if change.deleted else change.path
    if change.deleted:
        return [_finding(path, None, "test-weakened", "high", "Testdatei gelöscht.")]
    for number, text in change.added:
        # String literals are data (e.g. fixtures), not a skip that takes effect.
        if _SKIP.search(_STRING_LITERAL.sub("", text)):
            findings.append(_finding(path, number, "test-weakened", "high",
                                     "skip/xfail hinzugefügt; ein Test läuft nicht mehr voll."))
    removed_asserts = sum(bool(_ASSERT.search(text)) for text in change.removed)
    added_asserts = sum(bool(_ASSERT.search(text)) for _, text in change.added)
    if removed_asserts > added_asserts:
        findings.append(_finding(path, None, "test-weakened", "high",
                                 f"{removed_asserts} Prüfungen entfernt, nur {added_asserts} hinzugefügt."))
    removed_tests = sum(bool(_TEST_DEF.search(text)) for text in change.removed)
    added_tests = sum(bool(_TEST_DEF.search(text)) for _, text in change.added)
    if removed_tests > added_tests:
        findings.append(_finding(path, None, "test-weakened", "high",
                                 f"{removed_tests} Testfunktionen entfernt, nur {added_tests} hinzugefügt."))
    return findings


def review(task_input: Mapping[str, Any]) -> dict[str, Any]:
    """Pure function of the input: the replayable core of the agent."""
    if task_input.get("schema") != INPUT_SCHEMA or not isinstance(task_input.get("diff"), str):
        raise ReviewInputError("input must be {schema: tim.review.input.v1, diff: str}")
    changes = parse_unified_diff(task_input["diff"])
    findings: list[dict[str, Any]] = []
    for change in changes:
        path = change.path
        if _is_test(path) or _is_test(change.old_path):
            findings.extend(_test_findings(change))
        if _SENSITIVE_FILE.search(path) and not change.deleted:
            findings.append(_finding(path, None, "sensitive-file", "high",
                                     "Datei mit Schlüsseln oder Zugangsdaten geändert."))
        for number, text in change.added:
            for label, pattern in _SECRETS:
                if pattern.search(text):
                    # The value itself is never copied into the report.
                    findings.append(_finding(path, number, "secret-in-diff", "critical",
                                             f"Mögliches Geheimnis ({label}) hinzugefügt."))
                    break
            if path.startswith(".github/workflows/") and _WORKFLOW_WRITE.match(text):
                findings.append(_finding(path, number, "workflow-permission-escalation", "high",
                                         f"Schreibrecht im Workflow: {text.strip()[:80]}"))
    source = [c.path for c in changes if c.path.endswith(".py") and not c.deleted
              and c.path.startswith("src/") and c.added]
    if source and not any(_is_test(c.path) for c in changes):
        for path in source:
            findings.append(_finding(path, None, "source-without-tests", "medium",
                                     "Quellcode geändert, aber keine Testdatei im Diff."))
    findings.sort(key=lambda f: (SEVERITY_ORDER.index(f["severity"]), f["file"], f["line"] or 0, f["rule"]))
    counts = {severity: sum(f["severity"] == severity for f in findings) for severity in SEVERITY_ORDER}
    return {
        "schema": REPORT_SCHEMA,
        "verdict": "FINDINGS" if findings else "NO_FINDINGS",
        "files_reviewed": sorted({c.path for c in changes}),
        "findings": findings,
        "counts": counts,
        "rules_checked": sorted(RULES),
        "not_checked": list(NOT_CHECKED),
    }


def render_report(report: Mapping[str, Any]) -> str:
    lines = ["# TIM Review Agent", "",
             f"Ergebnis: `{report['verdict']}` · {len(report['files_reviewed'])} Dateien · "
             + ", ".join(f"{k}: {v}" for k, v in report["counts"].items()),
             "", "> Dieser Bericht ist keine Freigabe. Er meldet nur bekannte Muster.", "", "## Befunde"]
    if report["findings"]:
        for f in report["findings"]:
            where = f"{f['file']}:{f['line']}" if f["line"] else f["file"]
            lines.append(f"- **{f['severity']}** `{f['rule']}` {where}: {f['message']}")
    else:
        lines.append("- Keine Befunde zu den geprüften Regeln.")
    lines += ["", "## Geprüfte Regeln", *(f"- `{r}`: {RULES[r]}" for r in report["rules_checked"]),
              "", "## Nicht geprüft", *(f"- {item}" for item in report["not_checked"])]
    return "\n".join(lines) + "\n"
