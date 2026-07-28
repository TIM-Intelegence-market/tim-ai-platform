from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import settings
from src.sources.passive import PassiveSourceConnector, SourcePolicy


def main() -> int:
    parser = argparse.ArgumentParser(description="TIM passive read-only source ingestion")
    parser.add_argument("source_type", choices=("news", "knowledge"))
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    policy = SourcePolicy(allowed_news_hosts=settings.allowed_news_hosts, allowed_knowledge_roots=settings.allowed_knowledge_roots)
    connector = PassiveSourceConnector(policy, settings.source_snapshot_root)
    snapshot = connector.ingest_news_file(args.path) if args.source_type == "news" else connector.ingest_knowledge_file(args.path)
    payload = asdict(snapshot)
    payload["captured_at"] = snapshot.captured_at.isoformat()
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
