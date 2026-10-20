from datetime import datetime
import math
import re


_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_REQUIRED_KEYS = {
    "archive_sha256",
    "restored_sha256",
    "offsite_restored_sha256",
    "backup_at",
    "restore_at",
    "offsite_restore_at",
    "offsite_encrypted",
    "timer_enabled",
    "evidence_refs",
}
_EVIDENCE_KEYS = {"backup", "restore", "offsite", "timer"}


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def evaluate_backup(receipt, *, now, max_age_seconds=86400):
    reasons = []
    try:
        if not isinstance(receipt, dict):
            return {"status": "BLOCKED", "reasons": ["receipt must be a dict"], "executed": False}
        if set(receipt) != _REQUIRED_KEYS:
            reasons.append("receipt keys must be exact")

        hashes = {}
        for key in ("archive_sha256", "restored_sha256", "offsite_restored_sha256"):
            value = receipt.get(key)
            if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
                reasons.append(f"invalid {key}")
            else:
                hashes[key] = value

        evidence = receipt.get("evidence_refs")
        if not isinstance(evidence, dict) or set(evidence) != _EVIDENCE_KEYS:
            reasons.append("evidence_refs keys must be exact")
        else:
            for key, value in evidence.items():
                if not isinstance(value, str) or not value.startswith("sha256:") or _HEX64.fullmatch(value[7:]) is None:
                    reasons.append(f"invalid evidence_refs.{key}")

        for key in ("offsite_encrypted", "timer_enabled"):
            if type(receipt.get(key)) is not bool:
                reasons.append(f"{key} must be a bool")

        timestamps = {}
        for key in ("backup_at", "restore_at", "offsite_restore_at"):
            parsed = _timestamp(receipt.get(key))
            if parsed is None:
                reasons.append(f"invalid {key}")
            else:
                timestamps[key] = parsed

        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            reasons.append("now must be timezone-aware")
            parsed_now = None
        else:
            parsed_now = now

        if isinstance(max_age_seconds, bool) or not isinstance(max_age_seconds, (int, float)):
            reasons.append("max_age_seconds must be a finite non-negative number")
            age_limit = None
        elif not math.isfinite(max_age_seconds) or max_age_seconds < 0:
            reasons.append("max_age_seconds must be a finite non-negative number")
            age_limit = None
        else:
            age_limit = max_age_seconds

        if len(hashes) == 3 and len(set(hashes.values())) != 1:
            reasons.append("hashes do not match")
            return {"status": "FAIL", "reasons": sorted(set(reasons)), "executed": False}

        if len(timestamps) == 3 and parsed_now is not None:
            if any(value > parsed_now for value in timestamps.values()):
                reasons.append("timestamp is in the future")
            if timestamps["backup_at"] > timestamps["restore_at"] or timestamps["backup_at"] > timestamps["offsite_restore_at"]:
                reasons.append("timestamps are out of order")
            if age_limit is not None and any((parsed_now - value).total_seconds() > age_limit for value in timestamps.values()):
                reasons.append("timestamp is too old")

        if receipt.get("offsite_encrypted") is not True:
            reasons.append("offsite_encrypted must be true")
        if receipt.get("timer_enabled") is not True:
            reasons.append("timer_enabled must be true")

        if reasons:
            return {"status": "BLOCKED", "reasons": sorted(set(reasons)), "executed": False}
        return {"status": "PASS", "reasons": [], "executed": False}
    except Exception:
        return {"status": "BLOCKED", "reasons": ["invalid receipt"], "executed": False}
