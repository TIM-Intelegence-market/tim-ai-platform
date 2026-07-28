"""Immutable V2 dataset metadata contracts.

The platform stores metadata and references only. Raw data remains at its
authoritative source and is never read or copied by these types.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
import hashlib
import json
import re
from urllib.parse import urlparse


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
DATASET_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{2,63}$")
ALLOWED_MANIFEST_FIELDS = frozenset({
    "dataset_id", "version", "schema_version", "content_sha256", "source_uri",
    "source_authorized", "license_name", "sensitivity", "event_time",
    "observation_time", "publication_time", "quality", "retention_policy",
    "lineage", "supersedes", "metadata",
})


class ValidationState(StrEnum):
    VALID = "VALID"
    QUARANTINED = "QUARANTINED"


@dataclass(frozen=True)
class TimeRange:
    start: datetime
    end: datetime

    def issue(self, label: str) -> str | None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            return f"{label}_TIMEZONE_REQUIRED"
        if self.end < self.start:
            return f"{label}_ORDER_INVALID"
        return None


@dataclass(frozen=True)
class QualityMetrics:
    record_count: int
    missing_record_count: int = 0
    duplicate_record_count: int = 0
    coverage_percent: float = 100.0

    def issues(self) -> tuple[str, ...]:
        problems: list[str] = []
        if self.record_count < 0:
            problems.append("RECORD_COUNT_INVALID")
        if self.missing_record_count < 0 or self.duplicate_record_count < 0:
            problems.append("QUALITY_COUNT_INVALID")
        if not 0.0 <= self.coverage_percent <= 100.0:
            problems.append("COVERAGE_INVALID")
        return tuple(problems)


@dataclass(frozen=True)
class DatasetVersion:
    dataset_id: str
    version: str
    schema_version: str
    content_sha256: str
    source_uri: str
    source_authorized: bool
    license_name: str
    sensitivity: str
    event_time: TimeRange
    observation_time: TimeRange
    publication_time: TimeRange
    quality: QualityMetrics
    retention_policy: str
    lineage: tuple[str, ...] = ()
    supersedes: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.dataset_id}@{self.version}"

    def manifest_payload(self) -> dict[str, object]:
        payload = asdict(self)
        for name in ("event_time", "observation_time", "publication_time"):
            payload[name] = {
                key: value.isoformat() for key, value in payload[name].items()
            }
        payload["lineage"] = list(self.lineage)
        return payload

    def manifest_sha256(self) -> str:
        canonical = json.dumps(
            self.manifest_payload(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def issues(self) -> tuple[str, ...]:
        problems: list[str] = []
        if not DATASET_ID_RE.fullmatch(self.dataset_id):
            problems.append("DATASET_ID_INVALID")
        for value, label in ((self.version, "VERSION"), (self.schema_version, "SCHEMA_VERSION")):
            if not SEMVER_RE.fullmatch(value):
                problems.append(f"{label}_INVALID")
        if not SHA256_RE.fullmatch(self.content_sha256):
            problems.append("CONTENT_HASH_INVALID")
        if not self.source_uri.strip():
            problems.append("SOURCE_URI_REQUIRED")
        else:
            parsed = urlparse(self.source_uri)
            if parsed.scheme not in {"https", "s3", "urn"}:
                problems.append("SOURCE_URI_SCHEME_FORBIDDEN")
            if ".." in parsed.path.split("/"):
                problems.append("SOURCE_URI_PATH_TRAVERSAL")
        if not self.source_authorized:
            problems.append("SOURCE_UNAUTHORIZED")
        if not self.license_name.strip():
            problems.append("LICENSE_REQUIRED")
        if not self.sensitivity.strip():
            problems.append("SENSITIVITY_REQUIRED")
        if not self.retention_policy.strip():
            problems.append("RETENTION_POLICY_REQUIRED")
        for label, time_range in (
            ("EVENT", self.event_time),
            ("OBSERVATION", self.observation_time),
            ("PUBLICATION", self.publication_time),
        ):
            issue = time_range.issue(label)
            if issue:
                problems.append(issue)
        problems.extend(self.quality.issues())
        if len(set(self.lineage)) != len(self.lineage):
            problems.append("LINEAGE_DUPLICATE_REFERENCE")
        return tuple(problems)


def dataset_from_manifest_json(raw: str) -> DatasetVersion:
    """Decode one strict metadata manifest without opening its source URI."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("MANIFEST_JSON_INVALID") from exc
    if not isinstance(payload, dict):
        raise ValueError("MANIFEST_OBJECT_REQUIRED")
    unknown = set(payload) - ALLOWED_MANIFEST_FIELDS
    if unknown:
        raise ValueError(f"MANIFEST_UNKNOWN_FIELDS:{','.join(sorted(unknown))}")
    required = ALLOWED_MANIFEST_FIELDS - {"lineage", "supersedes", "metadata"}
    missing = required - set(payload)
    if missing:
        raise ValueError(f"MANIFEST_REQUIRED_FIELDS_MISSING:{','.join(sorted(missing))}")
    try:
        def time_range(value: object) -> TimeRange:
            if not isinstance(value, dict) or set(value) != {"start", "end"}:
                raise ValueError("MANIFEST_TIME_RANGE_INVALID")
            return TimeRange(datetime.fromisoformat(value["start"]), datetime.fromisoformat(value["end"]))

        quality = payload["quality"]
        if not isinstance(quality, dict) or set(quality) != {"record_count", "missing_record_count", "duplicate_record_count", "coverage_percent"}:
            raise ValueError("MANIFEST_QUALITY_INVALID")
        return DatasetVersion(
            dataset_id=payload["dataset_id"], version=payload["version"], schema_version=payload["schema_version"],
            content_sha256=payload["content_sha256"], source_uri=payload["source_uri"], source_authorized=payload["source_authorized"],
            license_name=payload["license_name"], sensitivity=payload["sensitivity"],
            event_time=time_range(payload["event_time"]), observation_time=time_range(payload["observation_time"]),
            publication_time=time_range(payload["publication_time"]), quality=QualityMetrics(**quality),
            retention_policy=payload["retention_policy"], lineage=tuple(payload.get("lineage", [])),
            supersedes=payload.get("supersedes"), metadata=payload.get("metadata", {}),
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("MANIFEST_"):
            raise
        raise ValueError("MANIFEST_FIELDS_INVALID") from exc
