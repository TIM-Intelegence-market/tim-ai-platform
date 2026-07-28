from src.database.repository import _json_object


def test_json_object_accepts_asyncpg_string_and_mapping() -> None:
    assert _json_object('{"level": 68420}') == {"level": 68420}
    assert _json_object({"kind": "BOS"}) == {"kind": "BOS"}


def test_json_object_keeps_invalid_storage_visible() -> None:
    assert _json_object("not-json") == {"_quality_error": "INVALID_JSON_OBJECT"}
    assert _json_object("[]") == {"_quality_error": "INVALID_JSON_OBJECT"}
