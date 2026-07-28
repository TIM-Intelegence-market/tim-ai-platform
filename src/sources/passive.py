from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.knowledge.goathub import GoatHubKnowledge, KnowledgeDocument
from src.news.intelligence import NewsIntelligence, NewsItem


@dataclass(frozen=True, slots=True)
class SourcePolicy:
    allowed_news_hosts: tuple[str, ...] = ()
    allowed_knowledge_roots: tuple[Path, ...] = ()
    maximum_file_bytes: int = 2_000_000
    retention_days: int = 90

    def __post_init__(self) -> None:
        if self.maximum_file_bytes <= 0 or self.retention_days < 1:
            raise ValueError("Invalid passive source policy")


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    snapshot_id: str
    source_type: str
    source_path: str
    captured_at: datetime
    content_hash: str
    item_count: int
    provenance: str
    snapshot_path: str


class PassiveSourceConnector:
    """Read-only local ingestion. It never downloads, edits or deletes source material."""

    def __init__(self, policy: SourcePolicy, snapshot_root: Path, news: NewsIntelligence | None = None, knowledge: GoatHubKnowledge | None = None) -> None:
        self.policy = policy
        self.snapshot_root = snapshot_root
        self.news = news or NewsIntelligence()
        self.knowledge = knowledge or GoatHubKnowledge()
        self.manifest_path = snapshot_root / "manifest.json"
        self.snapshot_root.mkdir(parents=True, exist_ok=True)
        self._manifest = self._read_json(self.manifest_path, {"snapshots": {}})

    @staticmethod
    def _read_json(path: Path, fallback: Any) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return fallback

    def _read_source(self, path: Path) -> bytes:
        resolved = path.resolve(strict=True)
        if not resolved.is_file():
            raise ValueError("Source must be a regular file")
        size = resolved.stat().st_size
        if size > self.policy.maximum_file_bytes:
            raise ValueError("Source exceeds configured size limit")
        return resolved.read_bytes()

    def ingest_news_file(self, path: Path) -> SourceSnapshot:
        raw = self._read_source(path)
        payload = json.loads(raw)
        if not isinstance(payload, list):
            raise ValueError("News source must contain a JSON list")
        accepted = 0
        for row in payload:
            host = (urlparse(str(row.get("source_url", ""))).hostname or "").lower()
            if host not in {item.lower() for item in self.policy.allowed_news_hosts}:
                raise PermissionError(f"News host is not allowlisted: {host or 'missing'}")
            item = NewsItem(source_name=str(row["source_name"]), source_url=str(row["source_url"]), published_at=datetime.fromisoformat(str(row["published_at"]).replace("Z", "+00:00")), title=str(row["title"]), summary=str(row.get("summary", "")), tags=tuple(map(str, row.get("tags", []))), provenance="ALLOWLISTED_LOCAL_NEWS_SNAPSHOT")
            accepted += int(self.news.ingest(item))
        return self._snapshot("news", path, raw, accepted, "ALLOWLISTED_LOCAL_NEWS_SNAPSHOT")

    def ingest_knowledge_file(self, path: Path) -> SourceSnapshot:
        resolved = path.resolve(strict=True)
        allowed = any(resolved == root.resolve() or root.resolve() in resolved.parents for root in self.policy.allowed_knowledge_roots)
        if not allowed:
            raise PermissionError("Knowledge path is outside configured roots")
        raw = self._read_source(resolved)
        document = KnowledgeDocument(resolved.stem, str(resolved), raw.decode("utf-8"), authorized=True, provenance="ALLOWLISTED_LOCAL_KNOWLEDGE_SNAPSHOT")
        accepted = int(self.knowledge.ingest(document))
        return self._snapshot("knowledge", resolved, raw, accepted, document.provenance)

    def _snapshot(self, source_type: str, source_path: Path, raw: bytes, item_count: int, provenance: str) -> SourceSnapshot:
        digest = hashlib.sha256(raw).hexdigest()
        snapshot_id = f"snapshot_{source_type}_{digest[:20]}"
        existing = self._manifest["snapshots"].get(snapshot_id)
        if existing:
            return SourceSnapshot(**{**existing, "captured_at": datetime.fromisoformat(existing["captured_at"])})
        captured = datetime.now(timezone.utc)
        destination = self.snapshot_root / captured.strftime("%Y/%m/%d") / f"{snapshot_id}.bin"
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        temporary.write_bytes(raw)
        os.replace(temporary, destination)
        snapshot = SourceSnapshot(snapshot_id, source_type, str(source_path.resolve()), captured, digest, item_count, provenance, str(destination.resolve()))
        serialized = asdict(snapshot);serialized["captured_at"] = captured.isoformat()
        self._manifest["snapshots"][snapshot_id] = serialized
        self._write_manifest()
        return snapshot

    def _write_manifest(self) -> None:
        temporary = self.manifest_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.manifest_path)

    def retention_candidates(self, at: datetime | None = None) -> list[Path]:
        cutoff = (at or datetime.now(timezone.utc)) - timedelta(days=self.policy.retention_days)
        candidates = []
        for row in self._manifest.get("snapshots", {}).values():
            captured = datetime.fromisoformat(row["captured_at"])
            path = Path(row["snapshot_path"])
            if captured < cutoff and path.exists() and self.snapshot_root.resolve() in path.resolve().parents:
                candidates.append(path)
        return sorted(candidates)
