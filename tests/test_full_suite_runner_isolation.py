import pytest

from scripts.run_full_test_suite import isolated_database_url, pytest_warning_count


def test_isolated_database_url_sets_only_explicit_search_path() -> None:
    value = isolated_database_url(
        "postgresql://role:secret@127.0.0.1:5432/tim?application_name=test",
        "tim_v2_final_test",
    )
    assert "application_name=test" in value
    assert "options=-csearch_path%3Dtim_v2_final_test" in value


@pytest.mark.parametrize("schema", ["public", "Bad-Name", "x;drop schema public", "a" * 64])
def test_isolated_database_url_rejects_broad_or_unsafe_schema(schema: str) -> None:
    with pytest.raises(ValueError, match="safe lowercase"):
        isolated_database_url("postgresql://127.0.0.1/tim", schema)


def test_warning_count_uses_pytest_final_summary_not_per_file_counts() -> None:
    output = "tests/a.py: 3 warnings\ntests/b.py: 1 warning\n361 passed, 154 warnings in 34.24s\n"
    assert pytest_warning_count(output) == 154
