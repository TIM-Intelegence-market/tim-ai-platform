"""Real-data regression fixture: a small ALFRED download kept byte for byte.

The fixture is not an edited extract of the large research download. It is its own
real API response for a narrow research window (three CPI periods around the
February 2020 annual revision, vintages up to 2020-12-31), fetched through the same
holdout-safe path (``live.ingest_live``) and copied unchanged. ``provenance.json``
records the bundle id, retrieval time, requests (without key) and the SHA-256 of
every payload; ``load_fixture`` refuses files whose hash no longer matches, so CI
tests run on exactly what the API returned.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path

from src.research_lab.external.alfred import RawBundle
from src.research_lab.external.live import ResearchWindow, check_window
from src.research_lab.external.records import iso
from src.research_lab.external.store import _bundle_id

FIXTURE_2019_2020 = ResearchWindow("fixture-2019-2020", date(2019, 11, 1), date(2020, 1, 31), date(2020, 12, 31))
FIXTURE_DIR = Path("tests/fixtures/research_lab/alfred_cpiaucsl_fixture_2019_2020")
PROVENANCE = "provenance.json"


def write_fixture(bundle: RawBundle, bundle_id: str, target: Path) -> Path:
    check_window(bundle, FIXTURE_2019_2020)
    target.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name, payload in sorted(bundle.payloads.items()):
        (target / f"{name}.json").write_bytes(payload)
        hashes[name] = hashlib.sha256(payload).hexdigest()
    provenance = {
        "description": "Real ALFRED/FRED API responses for CPIAUCSL, unmodified (see src/research_lab/external/fixture_window.py)",
        "source": bundle.source,
        "source_identifier": bundle.source_identifier,
        "bundle_id": bundle_id,
        "retrieved_at": bundle.ingested_at.isoformat(),
        "window": FIXTURE_2019_2020.to_dict(),
        "requests": bundle.requests,
        "payload_sha256": hashes,
    }
    (target / PROVENANCE).write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    return target


def load_fixture(directory: Path = FIXTURE_DIR) -> tuple[RawBundle, dict]:
    """Read the fixture and prove every payload is byte-identical to what was downloaded."""
    provenance = json.loads((directory / PROVENANCE).read_text())
    payloads = {}
    for name, sha in provenance["payload_sha256"].items():
        payload = (directory / f"{name}.json").read_bytes()
        if hashlib.sha256(payload).hexdigest() != sha:
            raise ValueError(f"fixture payload {name} differs from the recorded download")
        payloads[name] = payload
    bundle = RawBundle(
        provenance["source"],
        provenance["source_identifier"],
        payloads,
        datetime.fromisoformat(provenance["retrieved_at"]),
        provenance["requests"],
    )
    # The bundle id is the store's hash over source, retrieval time, payload hashes and requests: editing
    # a payload and its recorded hash together still contradicts the id of the original download.
    entry = {
        "source": bundle.source,
        "source_identifier": bundle.source_identifier,
        "ingested_at": iso(bundle.ingested_at),
        "payloads": dict(sorted(provenance["payload_sha256"].items())),
        "requests": bundle.requests,
    }
    if _bundle_id(entry) != provenance["bundle_id"]:
        raise ValueError("fixture does not match the bundle id of the recorded download")
    check_window(bundle, FIXTURE_2019_2020)
    return bundle, provenance


__all__ = ["FIXTURE_2019_2020", "FIXTURE_DIR", "load_fixture", "write_fixture"]
