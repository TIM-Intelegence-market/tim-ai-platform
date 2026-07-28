from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TAG = "tim-im-v1.0.0"
FROZEN_SNAPSHOT = (
    ROOT / "artifacts/tim_manager/reports/final_acceptance_snapshot_export.json"
)
FROZEN_SNAPSHOT_SHA256 = (
    "73c6481e3f33ed0ccdc8514fa81bdaf481d104f1bf0b2002da211592b82ebb7d"
)
REQUIRED_DOCS = (
    "docs/releases/tim-im-v1-release.md",
    "docs/releases/release_notes.md",
    "docs/releases/architecture_freeze.md",
    "docs/releases/known_limitations.md",
    "docs/releases/compatibility_matrix.md",
    "docs/releases/release_manifest.md",
    "docs/releases/definition_of_done.md",
    "docs/tim_v2/master_plan.md",
    "docs/tim_v2/architecture.md",
    "docs/tim_v2/roadmap.md",
    "docs/tim_v2/milestones.md",
    "docs/tim_v2/risk_register.md",
    "docs/tim_v2/decision_log.md",
    "docs/tim_v2/technical_debt.md",
    "docs/tim_v2/interfaces.md",
    "docs/tim_v2/development_guidelines.md",
)
FORBIDDEN_TRACKED_PREFIXES = (
    ".venv/",
    ".venv-research/",
    "data/",
    "output/",
    "artifacts/audits/",
    "artifacts/provenance/",
    "artifacts/tim_manager/events/",
    "artifacts/tim_manager/indexes/",
    "artifacts/tim_manager/scans/",
    "artifacts/tim_manager/snapshots/",
)


def git(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(ROOT), *arguments],
        text=True,
        capture_output=True,
        check=check,
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    tracked = git("ls-files").stdout.splitlines()
    tag_type = git("cat-file", "-t", f"refs/tags/{TAG}", check=False)
    tag_commit = git("rev-list", "-n", "1", TAG, check=False)
    head = git("rev-parse", "HEAD").stdout.strip()
    junit = ET.parse(
        ROOT / "artifacts/tim_manager/reports/mandatory_acceptance.junit.xml"
    ).getroot().find("testsuite")
    checks = {
        "repository_root": git("rev-parse", "--show-toplevel").stdout.strip()
        == str(ROOT),
        "branch_main": git("branch", "--show-current").stdout.strip() == "main",
        "clean_worktree": not git("status", "--porcelain").stdout.strip(),
        "annotated_tag": tag_type.returncode == 0 and tag_type.stdout.strip() == "tag",
        "tag_points_to_head": (
            tag_commit.returncode == 0 and tag_commit.stdout.strip() == head
        ),
        "remote_not_configured": not git("remote").stdout.strip(),
        "required_docs": all((ROOT / path).is_file() for path in REQUIRED_DOCS),
        "frozen_snapshot_hash": (
            FROZEN_SNAPSHOT.is_file()
            and sha256(FROZEN_SNAPSHOT) == FROZEN_SNAPSHOT_SHA256
        ),
        "mandatory_acceptance": (
            junit is not None
            and junit.attrib.get("tests") == "20"
            and junit.attrib.get("failures") == "0"
            and junit.attrib.get("errors") == "0"
            and junit.attrib.get("skipped") == "0"
        ),
        "forbidden_runtime_paths_untracked": not any(
            path.startswith(FORBIDDEN_TRACKED_PREFIXES) for path in tracked
        ),
    }
    result = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "repository_root": str(ROOT),
        "head": head,
        "tag": TAG,
        "tag_commit": tag_commit.stdout.strip() if tag_commit.returncode == 0 else None,
        "tracked_files": len(tracked),
        "checks": checks,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
