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
