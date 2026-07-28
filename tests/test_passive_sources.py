import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.sources.passive import PassiveSourceConnector, SourcePolicy


def test_allowlisted_news_snapshot_and_deduplication(tmp_path: Path) -> None:
    source = tmp_path / "news.json"
    source.write_text(json.dumps([{"source_name": "Authorized", "source_url": "https://news.example/item", "published_at": "2026-07-19T10:00:00+00:00", "title": "BTC context", "summary": "Evidence", "tags": ["btcusdt"]}]))
    connector = PassiveSourceConnector(SourcePolicy(allowed_news_hosts=("news.example",)), tmp_path / "snapshots")
    first = connector.ingest_news_file(source)
    second = connector.ingest_news_file(source)
    assert first.snapshot_id == second.snapshot_id
    assert first.item_count == 1
    assert Path(first.snapshot_path).read_bytes() == source.read_bytes()
    assert len(connector.news.items) == 1


def test_news_host_must_be_allowlisted(tmp_path: Path) -> None:
    source = tmp_path / "news.json"
    source.write_text(json.dumps([{"source_name": "Unknown", "source_url": "https://blocked.example/item", "published_at": "2026-07-19T10:00:00+00:00", "title": "Context"}]))
    connector = PassiveSourceConnector(SourcePolicy(allowed_news_hosts=("news.example",)), tmp_path / "snapshots")
    with pytest.raises(PermissionError):
        connector.ingest_news_file(source)


def test_knowledge_requires_allowlisted_root_and_preserves_source(tmp_path: Path) -> None:
    allowed = tmp_path / "authorized";allowed.mkdir()
    source = allowed / "notes.md";source.write_text("Absorption requires repeated evidence.")
    connector = PassiveSourceConnector(SourcePolicy(allowed_knowledge_roots=(allowed,)), tmp_path / "snapshots")
    snapshot = connector.ingest_knowledge_file(source)
    assert snapshot.provenance == "ALLOWLISTED_LOCAL_KNOWLEDGE_SNAPSHOT"
    assert connector.knowledge.search("absorption evidence")
    outside = tmp_path / "outside.md";outside.write_text("Not authorized")
    with pytest.raises(PermissionError):
        connector.ingest_knowledge_file(outside)


def test_retention_is_dry_run_only(tmp_path: Path) -> None:
    source = tmp_path / "news.json"
    source.write_text("[]")
    connector = PassiveSourceConnector(SourcePolicy(allowed_news_hosts=("news.example",), retention_days=1), tmp_path / "snapshots")
    snapshot = connector.ingest_news_file(source)
    manifest = json.loads(connector.manifest_path.read_text())
    manifest["snapshots"][snapshot.snapshot_id]["captured_at"] = "2026-01-01T00:00:00+00:00"
    connector.manifest_path.write_text(json.dumps(manifest))
    connector = PassiveSourceConnector(connector.policy, connector.snapshot_root)
    candidates = connector.retention_candidates(datetime(2026, 1, 3, tzinfo=timezone.utc))
    assert candidates == [Path(snapshot.snapshot_path)]
    assert Path(snapshot.snapshot_path).exists()
