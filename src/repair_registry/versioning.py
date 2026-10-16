import hashlib
import json

from src.bugfixer.remediation import _validate_entries


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
