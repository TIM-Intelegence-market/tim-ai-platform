import pytest

from scripts import run_full_test_suite
from scripts.run_full_test_suite import (
    isolated_child_environment,
    isolated_database_url,
    pytest_warning_count,
    resolve_test_database_url,
)


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


def test_explicit_isolated_url_is_resolved_without_eager_secret_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "postgresql://role:fixture-only@127.0.0.1:5432/tim_test"
    assert resolve_test_database_url({"TIM_DURABLE_TEST_DATABASE_URL": url}, "tim_v2_isolated") == url


def test_explicit_url_is_rejected_without_isolated_schema() -> None:
    url = "postgresql://role:fixture-only@127.0.0.1:5432/tim_test"
    with pytest.raises(ValueError, match="only with --isolated-schema"):
        resolve_test_database_url({"TIM_DURABLE_TEST_DATABASE_URL": url}, None)


def test_explicit_isolated_url_must_be_loopback() -> None:
    url = "postgresql://role:fixture-only@192.0.2.5:5432/tim"
    with pytest.raises(ValueError, match="loopback"):
        resolve_test_database_url({"TIM_DURABLE_TEST_DATABASE_URL": url}, "tim_v2_isolated")


def test_missing_explicit_test_url_never_falls_back_to_runtime() -> None:
    with pytest.raises(ValueError, match="runtime database fallback is forbidden"):
        resolve_test_database_url({}, "tim_v2_isolated")


def test_child_test_environment_sets_all_and_only_explicit_test_gates() -> None:
    base = {"PATH": "/usr/bin", "TIM_DATABASE_SECRET_PROVIDER": "keychain"}
    url = "postgresql://role:fixture-only@127.0.0.1:5432/tim_test"
    child = isolated_child_environment(base, url)
    assert child["TIM_DURABLE_TEST_DATABASE_URL"] == url
    assert child["TIM_DATABASE_SECRET_PROVIDER"] == "url-env"
    assert child["TIM_RUNTIME_ENV"] == "test"
    assert child["TIM_ALLOW_DATABASE_URL_ENV_FOR_TESTS"] == "true"
    assert base == {"PATH": "/usr/bin", "TIM_DATABASE_SECRET_PROVIDER": "keychain"}
