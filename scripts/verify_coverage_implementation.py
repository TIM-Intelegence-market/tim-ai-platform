#!/usr/bin/env python3
"""Fail closed when a sealed TIM coverage-campaign component changes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(manifest_path: Path) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_manifest_hash = manifest.get("manifest_hash")
    unsigned = {key: value for key, value in manifest.items() if key != "manifest_hash"}
    actual_manifest_hash = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    components: dict[str, dict[str, str]] = {}
    for name, entry in manifest.get("files", {}).items():
        relative_path = entry["path"]
        expected = entry["sha256"]
        actual = sha256_file(ROOT / relative_path)
        components[name] = {
            "expected_sha256": expected,
            "actual_sha256": actual,
            "status": "PASS" if actual == expected else "FAIL",
        }
    passed = expected_manifest_hash == actual_manifest_hash and all(
        item["status"] == "PASS" for item in components.values()
    )
    return {
        "manifest": str(manifest_path),
        "manifest_hash_status": "PASS" if expected_manifest_hash == actual_manifest_hash else "FAIL",
        "components": components,
        "status": "PASS" if passed else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "artifacts/continuous_coverage/implementation_20260923T0951Z.json",
    )
    args = parser.parse_args()
    result = verify(args.manifest)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
