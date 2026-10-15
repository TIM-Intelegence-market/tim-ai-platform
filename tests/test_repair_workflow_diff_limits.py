import subprocess

import pytest

from src.repair_workflow.diff_limits import check_diff


def diff(path, body):
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n{body}\n"


def test_accepts_clean_one_file_diff():
    result = check_diff(diff("src/app.py", "+new"), ["src/app.py"])
    assert result == {
        "ok": True,
        "files": ["src/app.py"],
        "changed_lines": 1,
        "violations": [],
    }


def test_rejects_path_outside_allowlist():
    result = check_diff(diff("src/app.py", "+new"), ["src/other.py"])
    assert result["ok"] is False
    assert "path not allowed: src/app.py" in result["violations"]


def test_rejects_too_many_files():
    text = "\n".join(diff(f"file{n}.py", "+x") for n in range(3))
    result = check_diff(text, [f"file{n}.py" for n in range(3)], max_files=2)
    assert "too many files: limit 2" in result["violations"]


def test_rejects_too_many_changed_lines():
    result = check_diff(diff("a.py", "+one\n+two"), ["a.py"], max_changed_lines=1)
    assert "too many changed lines: limit 1" in result["violations"]


def test_rejects_path_traversal():
    result = check_diff(diff("../secret", "+x"), ["../secret"])
    assert "invalid path: ../secret" in result["violations"]


def test_rejects_binary_patch():
    result = check_diff("diff --git a/a.bin b/a.bin\nGIT binary patch\n", ["a.bin"])
    assert "binary patch" in result["violations"]


def test_rejects_deleted_file():
    result = check_diff("diff --git a/a.py b/a.py\ndeleted file mode 100644\n", ["a.py"])
    assert "deleted file" in result["violations"]


def test_rejects_rename():
    result = check_diff("diff --git a/a.py b/b.py\nrename from a.py\n", ["b.py"])
    assert "rename" in result["violations"]


def test_rejects_empty_diff():
    result = check_diff("", [])
    assert result == {
        "ok": False,
        "files": [],
        "changed_lines": 0,
        "violations": ["empty diff"],
    }


def test_does_not_count_file_headers_as_changed_lines():
    result = check_diff(diff("a.py", "+x"), ["a.py"])
    assert result["changed_lines"] == 1


def test_function_context_cannot_bypass_changed_line_limit():
    text = diff("app.py", "-old\n+new").replace("@@ -1 +1 @@", "@@ -1 +1 @@ def run():")
    result = check_diff(text, ["app.py"], max_changed_lines=1)
    assert result["changed_lines"] == 2
    assert result["ok"] is False


def test_header_like_content_inside_hunk_counts_as_changes():
    result = check_diff(diff("app.py", "---old\n+++new"), ["app.py"], max_changed_lines=1)
    assert result["changed_lines"] == 2
    assert result["ok"] is False


@pytest.mark.parametrize("text", [
    "hello", " \n", "@@ -1 +1 @@\n-old\n+new\n",
    "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n",
    "diff --git a/app.py b/app.py\n@@ invalid @@\n+new\n",
])
def test_uninterpretable_diff_is_rejected(text):
    result = check_diff(text, ["app.py"])
    assert result["ok"] is False
    assert "invalid diff" in result["violations"]


def test_accepts_new_empty_file():
    text = "diff --git a/empty.py b/empty.py\nnew file mode 100644\nindex 0000000..e69de29\n"
    assert check_diff(text, ["empty.py"])["ok"] is True


@pytest.mark.parametrize("prefix", [True, False])
def test_valid_section_cannot_hide_incomplete_section(prefix):
    complete = diff("app.py", "-old\n+new")
    incomplete = "diff --git a/other.py b/other.py\n--- a/other.py\n+++ b/other.py\n"
    text = incomplete + complete if prefix else complete + incomplete
    assert check_diff(text, ["app.py", "other.py"])["ok"] is False


def test_unsupported_hunk_after_valid_diff_is_rejected():
    text = diff("app.py", "-old\n+new") + "@@ malformed @@\n+ignored\n"
    assert check_diff(text, ["app.py"])["ok"] is False


def test_real_git_diff_enforces_limit_with_function_context(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    path = tmp_path / "app.py"
    original = "def run():\n" + "    keep = 1\n" * 10 + "    return 1\n"
    path.write_text(original)
    subprocess.run(["git", "-C", str(tmp_path), "add", "app.py"], check=True)
    path.write_text(original.replace("return 1", "return 2"))
    text = subprocess.check_output(["git", "-C", str(tmp_path), "diff", "--no-ext-diff", "--no-textconv"], text=True)
    assert "@@ def run():" in text
    result = check_diff(text, ["app.py"], max_changed_lines=1)
    assert result["changed_lines"] == 2
    assert result["ok"] is False
