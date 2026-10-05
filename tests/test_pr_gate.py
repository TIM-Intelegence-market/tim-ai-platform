import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts import pr_gate
from scripts.pr_gate import Entry, GateError, evaluate, main, parse_raw

POLICY_PATH = Path(__file__).resolve().parents[1] / ".github" / "pr-gate-policy.json"
POLICY = json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def entry(path, status="M", old="100644", new="100644"):
    return Entry(old, new, status, path)


def test_parse_raw_reads_nul_separated_records():
    raw = ":100644 100644 a b M\0src/a.py\0:000000 100644 0 b A\0tests/test_a.py\0"
    assert parse_raw(raw) == [entry("src/a.py"), entry("tests/test_a.py", "A", "000000", "100644")]


@pytest.mark.parametrize("raw", ["garbage\0x\0", ":100644 100644 a M\0src/a.py\0", ":100644 100644 a b M\0"])
def test_parse_raw_rejects_malformed_output(raw):
    with pytest.raises(GateError):
        parse_raw(raw)


def test_ordinary_source_and_test_changes_pass():
    assert evaluate([entry("src/agents/review.py"), entry("tests/test_review.py", "A", "000000")], POLICY) == []


@pytest.mark.parametrize("path", [
    ".github/workflows/tim-full-suite.yml", ".github/pr-gate-policy.json", ".claude/settings.json",
    "scripts/pr_gate.py", "CLAUDE.md", "claude.md", "AGENTS.md", "CI.md", "tests/conftest.py",
    "src/database/safety.py", "requirements.txt", "docker-compose.yml", "pytest.ini", "config/x.toml",
    "src/sub/conftest.py", "SRC/../.github/x", "src/.git/config", "src/.github/x.yml",
    "README.md", "main.py", ".GITHUB/workflows/x.yml", "Scripts/x.py",
])
def test_protected_or_outside_paths_are_rejected(path):
    assert evaluate([entry(path)], POLICY)


@pytest.mark.parametrize("entry_", [
    entry("src/link.py", "A", "000000", "120000"),
    entry("src/sub", "A", "000000", "160000"),
    entry("src/tool.sh", "A", "000000", "100755"),
    entry("src/a.py", "M", "100644", "100755"),
    entry("src/a.py", "T", "100644", "120000"),
    entry("src/a.py", "R", "100644", "100644"),
    entry("src/a.py", "M", "120000", "120000"),
    entry("src/a\\b.py"), entry("src/a\nb.py"), entry("/src/a.py"), entry("src//a.py"),
])
def test_modes_symlinks_and_odd_paths_are_rejected(entry_):
    assert evaluate([entry_], POLICY)


def test_deleting_tests_empty_diffs_and_too_many_files_are_rejected():
    assert evaluate([entry("tests/test_a.py", "D", "100644", "000000")], POLICY)
    assert evaluate([], POLICY) == ["diff is empty"]
    many = [entry(f"src/f{i}.py") for i in range(POLICY["max_files"] + 1)]
    assert any("limit" in violation for violation in evaluate(many, POLICY))


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "platform-main")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("def test_a():\n    pass\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "base")
    git(tmp_path, "checkout", "-qb", "claude/issue-7-fix")
    return tmp_path


def run_gate(repo, branch="claude/issue-7-fix"):
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "work")
    return main(["--repository", str(repo), "--policy", str(POLICY_PATH), "--base", "platform-main",
                 "--head", "HEAD", "--branch", branch])


def test_gate_passes_a_clean_real_diff(repo, capsys):
    (repo / "src" / "a.py").write_text("x = 2\n")
    assert run_gate(repo) == 0
    assert "passed" in capsys.readouterr().out


def test_gate_rejects_workflow_edit_that_would_fake_ci(repo, capsys):
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "tim-full-suite.yml").write_text("run: 'true'\n")
    assert run_gate(repo) == 1
    assert "protected path" in capsys.readouterr().err


def test_gate_rejects_symlink_and_forged_marker_body_is_irrelevant(repo, capsys):
    (repo / "src" / "b.py").symlink_to("/etc/passwd")
    assert run_gate(repo) == 1
    assert "mode" in capsys.readouterr().err


def test_gate_rejects_conftest_and_test_deletion(repo):
    (repo / "tests" / "conftest.py").write_text("")
    (repo / "tests" / "test_a.py").unlink()
    assert run_gate(repo) == 1


def test_gate_rejects_rename_of_protected_file_into_src(repo):
    (repo / "scripts").mkdir()
    (repo / "scripts" / "x.py").write_text("y = 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "scripts on base-side branch")
    git(repo, "checkout", "-q", "platform-main")
    git(repo, "merge", "-q", "--ff-only", "claude/issue-7-fix")
    git(repo, "checkout", "-qb", "claude/issue-8-move")
    git(repo, "mv", "scripts/x.py", "src/x.py")
    assert run_gate(repo, "claude/issue-8-move") == 1


def test_gate_is_not_applicable_to_other_branches(repo, capsys):
    (repo / ".github").mkdir()
    (repo / ".github" / "x.yml").write_text("a: b\n")
    assert run_gate(repo, "feature/human-change") == 0
    assert "not applicable" in capsys.readouterr().out


def test_gate_fails_closed_on_unknown_revision_and_bad_policy(repo, tmp_path, capsys):
    assert main(["--repository", str(repo), "--policy", str(POLICY_PATH), "--base", "nope",
                 "--head", "HEAD", "--branch", "claude/issue-7-fix"]) == 1
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    assert main(["--repository", str(repo), "--policy", str(bad), "--base", "platform-main",
                 "--head", "HEAD", "--branch", "claude/issue-7-fix"]) == 1
    assert "failed closed" in capsys.readouterr().err


def test_oversized_file_is_rejected_in_unit_and_real_diff(repo, capsys):
    limit = POLICY["max_file_bytes"]
    assert evaluate([Entry("000000", "100644", "A", "docs/big.bin", size=limit + 1)], POLICY)
    assert evaluate([Entry("000000", "100644", "A", "docs/ok.bin", size=limit)], POLICY) == []
    (repo / "docs").mkdir()
    (repo / "docs" / "ok.bin").write_bytes(b"\0" * limit)
    assert run_gate(repo) == 0
    (repo / "docs" / "big.bin").write_bytes(b"\0" * (limit + 1))
    assert run_gate(repo) == 1
    assert "exceeds the limit" in capsys.readouterr().err


def test_policy_without_size_limit_fails_closed(tmp_path):
    without = {key: value for key, value in POLICY.items() if key != "max_file_bytes"}
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(without))
    with pytest.raises(GateError):
        pr_gate.load_policy(path)


def test_workflow_reruns_on_edited_and_keeps_read_only_permissions():
    text = (POLICY_PATH.parent / "workflows" / "pr-gate.yml").read_text(encoding="utf-8")
    types_line = next(line for line in text.splitlines() if line.strip().startswith("types:"))
    assert "edited" in types_line and "pull_request_target" in text
    assert "permissions:\n  contents: read\n" in text


def test_existing_tests_are_protected_only_new_test_files_may_be_added():
    assert evaluate([Entry("000000", "100644", "A", "tests/test_new.py")], POLICY) == []
    assert any("protected" in v for v in evaluate([entry("tests/test_existing.py")], POLICY))
    assert evaluate([entry("tests/test_existing.py", "D", "100644", "000000")], POLICY)
    assert evaluate([entry("src/agents/review.py")], POLICY) == []  # source changes stay allowed


def test_policy_without_add_only_prefixes_fails_closed(tmp_path):
    without = {key: value for key, value in POLICY.items() if key != "add_only_prefixes"}
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(without))
    with pytest.raises(GateError):
        pr_gate.load_policy(path)


# --- new test helper files: conftest, plugins, configuration, shadowing modules ---------------------------

HELPER_PATHS = [
    "tests/conftest.py", "tests/sub/conftest.py", "tests/helpers.py", "tests/__init__.py", "tests/sub/__init__.py",
    "tests/json.py", "tests/pytest.py", "tests/pytest.ini", "tests/tox.ini", "tests/pyproject.toml",
    "tests/setup.cfg", "tests/.coveragerc", "tests/plugin.pth", "tests/data/fixture.json", "tests/test_Upper.py",
    "tests/test_x.PY", "tests/test_x.py.bak", "tests/Sub/test_ok.py", "tests/sub dir/test_ok.py",
    "tests/test_ok.pyc", "tests/sitecustomize.py", "tests/usercustomize.py", "tests/noxfile.py",
    "src/sitecustomize.py", "src/usercustomize.py", "src/conftest.py", "src/mod.pth", "src/native.so",
    "tests/test_.py", "tests/_hidden/test_ok.py", "tests/test-dash.py",
]


@pytest.mark.parametrize("path", HELPER_PATHS)
def test_new_helper_plugin_and_config_files_are_rejected(path):
    assert evaluate([Entry("000000", "100644", "A", path)], POLICY)


@pytest.mark.parametrize("path", ["tests/test_new.py", "tests/sub/test_new_2.py", "tests/a/b/test_deep_9.py",
                                  "src/agents/new_module.py", "docs/note.md"])
def test_plain_new_test_modules_and_sources_stay_allowed(path):
    assert evaluate([Entry("000000", "100644", "A", path)], POLICY) == []


def test_real_git_diffs_with_hostile_test_helpers_are_rejected(repo, capsys):
    (repo / "tests" / "sub").mkdir()
    for name in ("conftest.py", "helpers.py", "json.py", "__init__.py", "plugin.pth", "pytest.ini"):
        (repo / "tests" / name).write_text("x = 1\n")
    (repo / "tests" / "sub" / "conftest.py").write_text("x = 1\n")
    (repo / "tests" / "test_good.py").write_text("def test_good():\n    pass\n")
    assert run_gate(repo) == 1
    err = capsys.readouterr().err
    for name in ("tests/conftest.py", "tests/helpers.py", "tests/json.py", "tests/__init__.py", "tests/plugin.pth",
                 "tests/pytest.ini", "tests/sub/conftest.py"):
        assert name in err
    assert "tests/test_good.py" not in err


def test_real_git_diff_with_only_new_test_modules_and_source_passes(repo):
    (repo / "tests" / "sub").mkdir()
    (repo / "tests" / "sub" / "test_more.py").write_text("def test_more():\n    pass\n")
    (repo / "tests" / "test_new.py").write_text("def test_new():\n    pass\n")
    (repo / "src" / "b.py").write_text("y = 2\n")
    assert run_gate(repo) == 0


def test_real_git_diff_that_edits_an_existing_helper_or_test_is_rejected(repo, capsys):
    (repo / "tests" / "test_a.py").write_text("def test_a():\n    assert True\n")  # weakened existing test
    assert run_gate(repo) == 1
    assert "existing files here are protected" in capsys.readouterr().err


@pytest.mark.parametrize("missing", ["new_file_patterns", "deny_suffixes"])
def test_policy_without_the_new_keys_fails_closed(tmp_path, missing):
    without = {key: value for key, value in POLICY.items() if key != missing}
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(without))
    with pytest.raises(GateError):
        pr_gate.load_policy(path)


def test_policy_with_a_broken_new_file_pattern_fails_closed(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({**POLICY, "new_file_patterns": {"tests/": "("}}))
    with pytest.raises(GateError):
        pr_gate.load_policy(path)
