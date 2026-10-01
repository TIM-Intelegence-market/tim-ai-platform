"""Local store for raw external payloads, content-addressed and verified on load.

Files live under data/research_lab/external (ignored by git, like the archive
store). Raw bytes are kept exactly as received, so every normalization can be
re-run and checked. Request parameters are recorded without credentials.

Every bundle has its own manifest entry (``bundles/<id>.json``) and every file is
written atomically (temporary file, then rename): concurrent saves never overwrite
each other and an interrupted save leaves earlier bundles intact.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from src.research_lab.external.alfred import RawBundle, reject_credentials
from src.research_lab.external.records import iso, require_utc

DEFAULT_ROOT = Path("data/research_lab/external")
BUNDLES = "bundles"


class RawPayloadStore:
    def __init__(self, root: Path | str = DEFAULT_ROOT) -> None:
        self.root = Path(root)

    def _entry_path(self, bundle_id: str) -> Path:
        return self.root / BUNDLES / f"{bundle_id}.json"

    def put(self, bundle: RawBundle) -> str:
        """Store a bundle; returns its id (hash of payload hashes and ingestion time)."""
        ingested_at = require_utc(bundle.ingested_at, "ingested_at")
        reject_credentials(bundle.requests)
        hashes = {name: hashlib.sha256(payload).hexdigest() for name, payload in sorted(bundle.payloads.items())}
        entry = {
            "source": bundle.source,
            "source_identifier": bundle.source_identifier,
            "ingested_at": iso(ingested_at),
            "payloads": hashes,
            "requests": bundle.requests,
        }
        bundle_id = _bundle_id(entry)
        for name, payload in bundle.payloads.items():
            target = self._path(hashes[name])
            if not target.exists():
                _write_atomic(target, payload)
        # The entry goes last: a bundle is only visible once all its payloads are on disk.
        _write_atomic(self._entry_path(bundle_id), (json.dumps(entry, indent=2, sort_keys=True) + "\n").encode())
        return bundle_id

    def get(self, bundle_id: str) -> RawBundle:
        path = self._entry_path(bundle_id)
        if not path.exists():
            raise KeyError(f"unknown bundle {bundle_id}")
        entry = json.loads(path.read_text())
        if _bundle_id(entry) != bundle_id:
            raise ValueError(f"manifest entry of bundle {bundle_id} changed since it was stored")
        payloads = {}
        for name, sha in entry["payloads"].items():
            payload = self._path(sha).read_bytes()
            if hashlib.sha256(payload).hexdigest() != sha:
                raise ValueError(f"payload {name} of bundle {bundle_id} changed on disk since it was stored")
            payloads[name] = payload
        return RawBundle(entry["source"], entry["source_identifier"], payloads, datetime.fromisoformat(entry["ingested_at"]), entry["requests"])

    def _path(self, sha: str) -> Path:
        return self.root / "payloads" / sha[:2] / f"{sha}.json"


def _write_atomic(target: Path, content: bytes) -> None:
    """Write via a unique temporary file in the same directory and rename: readers see all or nothing."""
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _bundle_id(entry: dict[str, Any]) -> str:
    """The id is the hash of the provenance entry, so an edited manifest entry no longer matches its id."""
    return hashlib.sha256(json.dumps(entry, sort_keys=True).encode()).hexdigest()


__all__ = ["DEFAULT_ROOT", "RawPayloadStore"]
