import hashlib

import pytest

from src.research_evidence.model import Evidence, make_evidence


BASE = {
    "source_uri": "https://example.test/source",
    "source_type": "web",
    "provider": "test-provider",
    "extraction_method": "manual",
    "title": "Example",
    "content": "evidence text",
    "retrieved_at": "2026-01-01T12:00:00+00:00",
}


def test_round_trip() -> None:
    evidence = make_evidence(**BASE, metadata={"pages": 2}, warnings=("note",), parent_ids=("p1",))
    assert Evidence.from_dict(evidence.to_dict()) == evidence


def test_id_is_deterministic() -> None:
    first = make_evidence(**BASE)
    second = make_evidence(**BASE)
    assert first.evidence_id == second.evidence_id
    expected_hash = "sha256:" + hashlib.sha256(BASE["content"].encode()).hexdigest()
    assert first.content_hash == expected_hash


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_type", "rss"),
        ("freshness", "expired"),
        ("metadata", {"nested": {"value": 1}}),
        ("warnings", ["warning"]),
    ],
)
def test_rejects_invalid_values(field: str, value: object) -> None:
    values = dict(BASE)
    values[field] = value
    if field == "warnings":
        with pytest.raises(ValueError):
            make_evidence(**values)
    else:
        with pytest.raises(ValueError):
            make_evidence(**values)


def test_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError):
        make_evidence(**{**BASE, "retrieved_at": "2026-01-01T12:00:00"})


def test_rejects_tampered_content() -> None:
    evidence = make_evidence(**BASE).to_dict()
    evidence["content"] = "tampered"
    with pytest.raises(ValueError):
        Evidence.from_dict(evidence)


def test_rejects_missing_or_unknown_keys() -> None:
    data = make_evidence(**BASE).to_dict()
    data.pop("title")
    with pytest.raises(ValueError):
        Evidence.from_dict(data)
    data = make_evidence(**BASE).to_dict()
    data["extra"] = True
    with pytest.raises(ValueError):
        Evidence.from_dict(data)
