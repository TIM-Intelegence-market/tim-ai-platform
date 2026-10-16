from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any


_SOURCE_TYPES = {"web", "pdf", "document", "derived"}
_FRESHNESS_VALUES = {"fresh", "stale", "unknown"}
_METADATA_TYPES = (str, int, float, bool)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    source_uri: str
    source_type: str
    retrieved_at: str
    provider: str
    extraction_method: str
    title: str
    content: str
    content_hash: str
    metadata: dict[str, str | int | float | bool]
    warnings: tuple[str, ...]
    freshness: str
    parent_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "evidence_id",
            "source_uri",
            "source_type",
            "retrieved_at",
            "provider",
            "extraction_method",
            "title",
            "content",
            "content_hash",
            "freshness",
        ):
            _require(isinstance(getattr(self, name), str), f"{name} must be a string")

        _require(self.source_type in _SOURCE_TYPES, "invalid source_type")
        _require(self.freshness in _FRESHNESS_VALUES, "invalid freshness")

        try:
            timestamp = self.retrieved_at
            if timestamp.endswith("Z"):
                timestamp = timestamp[:-1] + "+00:00"
            parsed = datetime.fromisoformat(timestamp)
        except (TypeError, ValueError):
            raise ValueError("retrieved_at must be ISO-8601") from None
        _require(parsed.tzinfo is not None and parsed.utcoffset() is not None,
                 "retrieved_at must include a timezone")

        expected_hash = "sha256:" + sha256(self.content.encode("utf-8")).hexdigest()
        _require(self.content_hash == expected_hash, "content_hash does not match content")

        _require(isinstance(self.metadata, dict), "metadata must be a dictionary")
        for key, value in self.metadata.items():
            _require(isinstance(key, str), "metadata keys must be strings")
            _require(type(value) in _METADATA_TYPES, "metadata values must be scalar")

        _require(isinstance(self.warnings, tuple), "warnings must be a tuple")
        _require(all(isinstance(value, str) for value in self.warnings),
                 "warnings must contain strings")
        _require(isinstance(self.parent_ids, tuple), "parent_ids must be a tuple")
        _require(all(isinstance(value, str) for value in self.parent_ids),
                 "parent_ids must contain strings")

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source_uri": self.source_uri,
            "source_type": self.source_type,
            "retrieved_at": self.retrieved_at,
            "provider": self.provider,
            "extraction_method": self.extraction_method,
            "title": self.title,
            "content": self.content,
            "content_hash": self.content_hash,
            "metadata": dict(self.metadata),
            "warnings": list(self.warnings),
            "freshness": self.freshness,
            "parent_ids": list(self.parent_ids),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Evidence":
        if not isinstance(data, dict):
            raise ValueError("data must be a dictionary")
        expected_keys = set(cls.__dataclass_fields__)
        actual_keys = set(data)
        if actual_keys != expected_keys:
            raise ValueError("data has missing or unknown keys")
        values = dict(data)
        if isinstance(values["warnings"], list):
            values["warnings"] = tuple(values["warnings"])
        if isinstance(values["parent_ids"], list):
            values["parent_ids"] = tuple(values["parent_ids"])
        return cls(**values)


def make_evidence(
    *,
    source_uri: str,
    source_type: str,
    provider: str,
    extraction_method: str,
    title: str,
    content: str,
    retrieved_at: str,
    metadata: dict[str, str | int | float | bool] | None = None,
    warnings: tuple[str, ...] = (),
    freshness: str = "unknown",
    parent_ids: tuple[str, ...] = (),
) -> Evidence:
    content_hash = "sha256:" + sha256(content.encode("utf-8")).hexdigest()
    evidence_id = "ev_" + sha256(
        f"{source_uri}\n{provider}\n{content_hash}".encode("utf-8")
    ).hexdigest()[:24]
    return Evidence(
        evidence_id=evidence_id,
        source_uri=source_uri,
        source_type=source_type,
        retrieved_at=retrieved_at,
        provider=provider,
        extraction_method=extraction_method,
        title=title,
        content=content,
        content_hash=content_hash,
        metadata={} if metadata is None else metadata,
        warnings=warnings,
        freshness=freshness,
        parent_ids=parent_ids,
    )
