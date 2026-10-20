from src.repair_gates.result import GateResult, GateStatus
from src.repair_gates.secret_scan import scan


def test_clean_diff_passes():
    result = scan("ordinary line\nsecond ordinary line")
    assert isinstance(result, GateResult)
    assert result.status is GateStatus.PASS
    assert result.gate == "secret_scan"
    assert result.reason == ""


def test_authorization_bearer_line_fails_without_exposing_value():
    value = "bear" + "er-" + "x" * 16
    line = "Authorization: " + "Bearer " + value
    result = scan(line)
    assert result.status is GateStatus.FAIL
    assert "1" in result.reason
    assert value not in result.reason
    assert value not in repr(result)


def test_password_key_value_line_fails_without_exposing_value():
    value = "pass" + "word" + "=" + "x" * 8
    result = scan(value)
    assert result.status is GateStatus.FAIL
    assert value not in result.reason
    assert value not in repr(result)


def test_postgres_uri_fails_without_exposing_credentials():
    user = "db" + "user"
    password = "p" + "w" + "x" * 8
    uri = "postgresql://" + user + ":" + password + "@localhost/db"
    result = scan(uri)
    assert result.status is GateStatus.FAIL
    assert user not in result.reason
    assert password not in result.reason
    assert uri not in repr(result)


def test_literal_hit_fails_without_exposing_literal():
    literal = "literal-" + "x" * 8
    result = scan("safe prefix " + literal, literals=(literal,))
    assert result.status is GateStatus.FAIL
    assert "1" in result.reason
    assert literal not in result.reason
    assert literal not in repr(result)


def test_non_string_input_fails():
    result = scan(None)  # type: ignore[arg-type]
    assert result.status is GateStatus.FAIL
    assert result.reason == "input must be a string"
