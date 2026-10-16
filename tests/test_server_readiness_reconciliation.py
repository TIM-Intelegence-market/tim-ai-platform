import pytest

from src.server_readiness.reconciliation import compare_reviewed_files

A = "a" * 64
B = "b" * 64
C = "c" * 64


def test_identical_content_is_already_present():
    result = compare_reviewed_files(
        {"x/a.py": A, "x/b.py": B},
        {"x/b.py": B, "x/a.py": A},
        reviewed_paths=["x/b.py", "x/a.py"],
    )
    assert result == {
        "status": "ALREADY_PRESENT",
        "present": ["x/a.py", "x/b.py"],
        "missing": [],
        "changed": [],
        "reasons": [],
        "automatic_merge": False,
    }


def test_missing_file_requires_review():
    result = compare_reviewed_files(
        {"a.py": A, "b.py": B}, {"a.py": A}, reviewed_paths=["a.py", "b.py"]
    )
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["present"] == ["a.py"]
    assert result["missing"] == ["b.py"]
    assert result["changed"] == []
    assert result["reasons"] == ["reviewed_files_missing"]


def test_changed_file_requires_review():
    result = compare_reviewed_files(
        {"a.py": A, "b.py": B}, {"a.py": A, "b.py": C}, reviewed_paths=["b.py", "a.py"]
    )
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["present"] == ["a.py"]
    assert result["missing"] == []
    assert result["changed"] == ["b.py"]
    assert result["reasons"] == ["reviewed_files_changed"]


def test_missing_and_changed_report_both_reasons():
    result = compare_reviewed_files(
        {"a.py": A, "b.py": B}, {"a.py": C}, reviewed_paths=["a.py", "b.py"]
    )
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["missing"] == ["b.py"]
    assert result["changed"] == ["a.py"]
    assert result["reasons"] == ["reviewed_files_changed", "reviewed_files_missing"]


def test_unreviewed_changes_are_ignored():
    result = compare_reviewed_files(
        {"a.py": A, "other.py": B, "only_candidate.py": B},
        {"a.py": A, "other.py": C, "unrelated.py": C},
        reviewed_paths=["a.py"],
    )
    assert result["status"] == "ALREADY_PRESENT"
    assert result["present"] == ["a.py"]
    assert result["missing"] == []
    assert result["changed"] == []


@pytest.mark.parametrize(
    "bad",
    [
        "/abs/a.py",
        "dir\\a.py",
        "",
        "a//b.py",
        "./a.py",
        "a/../b.py",
        "a/.",
        ".git/config",
        "a/.ENV",
        "Secrets/x.py",
        "a/Credentials",
        "a/KeyChain/x",
    ],
)
def test_invalid_reviewed_path_is_blocked_without_echo(bad):
    result = compare_reviewed_files({bad: A}, {bad: A}, reviewed_paths=[bad])
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["reviewed_path_invalid"]
    assert result["present"] == [] and result["missing"] == [] and result["changed"] == []
    if bad:
        assert bad not in repr(result["reasons"])
    assert result["automatic_merge"] is False


def test_duplicate_reviewed_paths_are_blocked():
    result = compare_reviewed_files({"a.py": A}, {"a.py": A}, reviewed_paths=["a.py", "a.py"])
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["reviewed_path_duplicate"]


@pytest.mark.parametrize("paths", [[], None, "a.py", [1], [None]])
def test_invalid_reviewed_paths_shape_is_blocked(paths):
    result = compare_reviewed_files({"a.py": A}, {"a.py": A}, reviewed_paths=paths)
    assert result["status"] == "BLOCKED"
    assert result["automatic_merge"] is False


def test_non_mapping_manifests_are_blocked():
    result = compare_reviewed_files([], "x", reviewed_paths=["a.py"])
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["candidate_not_mapping", "current_not_mapping"]


def test_missing_candidate_entry_is_blocked():
    result = compare_reviewed_files({}, {"a.py": A}, reviewed_paths=["a.py"])
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["candidate_entry_missing"]
    assert result["present"] == []


@pytest.mark.parametrize("digest", ["A" * 64, "a" * 63, "a" * 65, "g" * 64, 123, None, "a" * 64 + "\n"])
def test_invalid_candidate_digest_is_blocked(digest):
    result = compare_reviewed_files({"a.py": digest}, {"a.py": A}, reviewed_paths=["a.py"])
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["candidate_digest_invalid"]


def test_invalid_current_digest_is_blocked():
    result = compare_reviewed_files({"a.py": A}, {"a.py": "zz"}, reviewed_paths=["a.py"])
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["current_digest_invalid"]


def test_automatic_merge_is_always_false():
    cases = [
        compare_reviewed_files({"a.py": A}, {"a.py": A}, reviewed_paths=["a.py"]),
        compare_reviewed_files({"a.py": A}, {}, reviewed_paths=["a.py"]),
        compare_reviewed_files({"a.py": A}, {"a.py": B}, reviewed_paths=["a.py"]),
        compare_reviewed_files({}, {}, reviewed_paths=["a.py"]),
    ]
    assert [c["automatic_merge"] for c in cases] == [False, False, False, False]
