import argparse
import hashlib
import json
import sys
from pathlib import Path

from src.bugfixer.remediation import _validate_entries, load_registry


class RegistryUpgradeError(ValueError):
    pass


def recipe_digest(row: dict) -> str:
    payload = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _key(version: str) -> tuple:
    return tuple(int(x) for x in version.split("."))


def latest_versions(entries: list) -> dict:
    latest: dict = {}
    for entry in entries:
        rid = entry["remediation_id"]
        version = entry["version"]
        if rid not in latest or _key(version) > _key(latest[rid]):
            latest[rid] = version
    return latest


def _digests(entries: list) -> dict:
    return {(e["remediation_id"], e["version"]): recipe_digest(e) for e in entries}


def _label(key: tuple) -> str:
    return f"{key[0]}@{key[1]}"


def check_registry_upgrade(old: list, new: list) -> dict:
    _validate_entries(old, 2)
    _validate_entries(new, 2)
    old_map = _digests(old)
    new_map = _digests(new)
    for key in new_map:
        if key in old_map and new_map[key] != old_map[key]:
            raise RegistryUpgradeError("recipe ID@version changed without version bump")
    old_latest = latest_versions(old)
    for rid, version in new_map:
        if (rid, version) in old_map or rid not in old_latest:
            continue
        if _key(version) <= _key(old_latest[rid]):
            raise RegistryUpgradeError("new version must be higher")
    added = sorted(_label(k) for k in new_map if k not in old_map)
    removed = sorted(_label(k) for k in old_map if k not in new_map)
    unchanged = sorted(_label(k) for k in new_map if k in old_map)
    return {
        "added": added,
        "removed": removed,
        "unchanged": unchanged,
        "requires_review": bool(removed),
    }


def load_checked_upgrade(old_path, new_path) -> dict:
    old = load_registry(Path(old_path))
    new = load_registry(Path(new_path))
    if old.schema_version != 2 or new.schema_version != 2:
        raise ValueError("registry upgrade check requires schema_version 2")
    report = check_registry_upgrade(list(old), list(new))
    return {"entries": list(new), "report": report}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Check a remediation registry upgrade without writing files."
    )
    parser.add_argument("--old", required=True)
    parser.add_argument("--new", required=True)
    args = parser.parse_args(argv)
    try:
        report = load_checked_upgrade(args.old, args.new)["report"]
    except OSError:
        print(json.dumps({"status": "REJECTED", "reason": "registry file could not be read"}))
        return 2
    except ValueError as exc:
        print(json.dumps({"status": "REJECTED", "reason": str(exc)}))
        return 2
    status = "REVIEW_REQUIRED" if report["requires_review"] else "OK"
    print(json.dumps({"status": status, **report}, sort_keys=True), file=sys.stdout)
    return 3 if report["requires_review"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
