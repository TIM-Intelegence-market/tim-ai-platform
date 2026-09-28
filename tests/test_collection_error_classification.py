from __future__ import annotations

import pytest

from src.collection_reporting import ErrorClass, classify_error


@pytest.mark.parametrize(
    "message,category",
    [
        ("ValueError: Out-of-order trade rejected", ErrorClass.TERMINAL_BLOCKED),
        ("output hash mismatch", ErrorClass.INVARIANT_VIOLATION),
        ("keychain credential unavailable", ErrorClass.CREDENTIAL),
        ("EX_CONFIG missing environment", ErrorClass.CONFIGURATION),
        ("asyncpg database deadlock", ErrorClass.DATABASE),
        ("websocket connection refused", ErrorClass.NETWORK),
        ("invalid price", ErrorClass.DATA_QUALITY),
        ("rate limit: try again", ErrorClass.TRANSIENT),
    ],
)
def test_known_errors_have_one_policy(message: str, category: ErrorClass) -> None:
    assert classify_error(message).category is category


def test_unknown_error_is_bounded_and_fails_closed() -> None:
    policy = classify_error("something entirely new")
    assert policy.category is ErrorClass.UNKNOWN
    assert policy.retry is False
    assert policy.max_attempts == 0
    assert policy.safe_stop is True
