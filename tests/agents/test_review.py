import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.agents.contract import ReplayMismatch, RunRecord, replay, run_task
from src.agents.review import (
    INPUT_SCHEMA,
    READ_DIFF,
    SPEC,
    ReviewInputError,
    parse_unified_diff,
    render_report,
    review,
)

ROOT = Path(__file__).resolve().parents[2]


def diff(path, added=(), removed=(), *, start=10, deleted=False, new=False):
    header = [f"diff --git a/{path} b/{path}"]
    if deleted:
        header += ["deleted file mode 100644", f"--- a/{path}", "+++ /dev/null"]
    elif new:
        header += ["new file mode 100644", "--- /dev/null", f"+++ b/{path}"]
    else:
        header += [f"--- a/{path}", f"+++ b/{path}"]
    body = [f"@@ -{start},{len(removed) + 1} +{start},{len(added) + 1} @@", " context"]
    body += [f"-{line}" for line in removed] + [f"+{line}" for line in added]
    return "\n".join(header + body) + "\n"


def run(*parts):
    return review({"schema": INPUT_SCHEMA, "diff": "".join(parts)})


def rules(report):
    return [(f["rule"], f["severity"]) for f in report["findings"]]


def test_spec_can_only_read_and_report():
    assert set(SPEC.allowed_actions) == {"read_diff", "write_review_report"}
    assert "git_merge_or_push_without_authorization" in SPEC.forbidden_actions


def test_parser_tracks_new_line_numbers_and_ignores_removed_lines():
    [change] = parse_unified_diff(diff("src/a.py", added=("x = 1", "y = 2"), removed=("old",), start=20))
    assert change.added == [(21, "x = 1"), (22, "y = 2")]
    assert change.removed == ["old"]


def test_parser_handles_removed_line_that_looks_like_a_header():
    [change] = parse_unified_diff(diff("tests/test_a.py", removed=("-- comment",), added=("++x",)))
    assert change.removed == ["-- comment"] and change.added == [(11, "++x")]


def test_clean_change_with_tests_has_no_findings_and_is_not_an_approval():
    report = run(diff("src/a.py", added=("def f():", "    return 1")),
                 diff("tests/test_a.py", added=("def test_f():", "    assert f() == 1")))
    assert report["verdict"] == "NO_FINDINGS"
    assert "APPROVED" not in json.dumps(report)
    assert report["not_checked"]


@pytest.mark.parametrize("line", [
    "@pytest.mark.skip(reason='later')", "@pytest.mark.xfail", "pytest.skip('x')",
    "    self.skipTest('flaky')", "@pytest.mark.skipif(True, reason='x')",
])
def test_added_skip_or_xfail_is_reported(line):
    assert ("test-weakened", "high") in rules(run(diff("tests/test_a.py", added=(line,))))


def test_skip_inside_a_string_literal_is_not_reported():
    report = run(diff("tests/test_a.py", added=('    fixtures = ["@pytest.mark.skip", "pytest.skip(1)"]',)))
    assert report["findings"] == []


def test_removed_asserts_and_tests_are_reported():
    report = run(diff("tests/test_a.py", removed=("def test_old():", "    assert x == 1", "    assert y")))
    messages = [f["message"] for f in report["findings"]]
    assert any("Prüfungen entfernt" in m for m in messages)
    assert any("Testfunktionen entfernt" in m for m in messages)


def test_rewritten_assert_is_not_reported():
    report = run(diff("tests/test_a.py", removed=("    assert x == 1",), added=("    assert x == 2",)))
    assert report["findings"] == []


def test_deleted_test_file_is_reported():
    report = run(diff("tests/test_a.py", removed=("def test_a():", "    assert True"), deleted=True))
    assert ("test-weakened", "high") in rules(report)
    assert report["findings"][0]["file"] == "tests/test_a.py"


@pytest.mark.parametrize("line", [
    "key = 'AKIA" + "ABCDEFGHIJKLMNOP'", "-----BEGIN RSA " + "PRIVATE KEY-----",
    "token = 'ghp_" + "a" * 36 + "'", "ANTHROPIC = 'sk-ant-" + "b" * 30 + "'",
    "pass" + "word = 'hunter2hunter2'",
])
def test_secrets_are_reported_without_copying_the_value(line):
    report = run(diff("src/cfg.py", added=(line,)), diff("tests/test_cfg.py", added=("x",)))
    assert ("secret-in-diff", "critical") in rules(report)
    assert line not in json.dumps(report)


def test_password_from_environment_is_not_a_secret():
    report = run(diff("src/cfg.py", added=("password = os.environ['DB_PASSWORD']",)),
                 diff("tests/test_cfg.py", added=("x",)))
    assert report["findings"] == []


def test_sensitive_files_and_workflow_write_permissions_are_reported():
    report = run(diff(".env", added=("A=1",), new=True),
                 diff(".github/workflows/ci.yml", added=("  contents: write", "  checks: read")))
    assert ("sensitive-file", "high") in rules(report)
    escalations = [f for f in report["findings"] if f["rule"] == "workflow-permission-escalation"]
    assert len(escalations) == 1 and escalations[0]["line"] == 11


def test_source_without_tests_is_reported_as_medium():
    report = run(diff("src/a.py", added=("x = 1",)))
    assert rules(report) == [("source-without-tests", "medium")]


def test_findings_are_sorted_by_severity():
    report = run(diff("src/a.py", added=("x = 1", "sec" + "ret = 'abcdefghijkl'")))
    assert [f["severity"] for f in report["findings"]] == ["critical", "medium"]


def test_invalid_input_stops_without_report():
    with pytest.raises(ReviewInputError):
        review({"schema": "other", "diff": ""})
    with pytest.raises(ReviewInputError):
        run("diff --git broken\n")


def test_review_is_replayable_and_tamper_evident():
    record = run_task(SPEC, review, {"schema": INPUT_SCHEMA, "diff": diff("src/a.py", added=("x",))},
                      action=READ_DIFF)
    restored = RunRecord.from_dict(json.loads(json.dumps(record.to_dict())))
    assert replay(SPEC, review, restored) == record
    with pytest.raises(ReplayMismatch):
        replay(SPEC, lambda i: {**review(i), "verdict": "NO_FINDINGS"}, restored)


def test_render_report_states_limits():
    text = render_report(run(diff("src/a.py", added=("x",))))
    assert "keine Freigabe" in text and "## Nicht geprüft" in text


def test_cli_reviews_stdin_and_replays(tmp_path):
    record = tmp_path / "review.json"
    done = subprocess.run([sys.executable, "scripts/tim_review_agent.py", "--record-path", str(record)],
                          input=diff("tests/test_a.py", added=("@pytest.mark.skip",)), cwd=ROOT,
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert "test-weakened" in done.stdout
    again = subprocess.run([sys.executable, "scripts/tim_review_agent.py", "--replay", str(record)],
                           cwd=ROOT, capture_output=True, text=True)
    assert again.returncode == 0 and "Replay OK" in again.stdout
