"""scripts/tim_log_maintenance.py: launchd stdout/stderr logs rotate in place, without a safe stop."""
from __future__ import annotations

import gzip
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _run(root: Path, *arguments: str) -> tuple[int, dict]:
    result = subprocess.run(
        [sys.executable, str(root / "scripts/tim_log_maintenance.py"), *arguments],
        capture_output=True, text=True, timeout=60, cwd=root,
        env={**os.environ, "HOME": str(root)},  # never touch the real ~/Library/Logs/TIM
    )
    return result.returncode, json.loads(result.stdout)


def _copy_repo_parts(tmp_path: Path) -> Path:
    root = tmp_path / "tim"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(REPO / "scripts/tim_log_maintenance.py", root / "scripts")
    shutil.copytree(REPO / "src", root / "src", ignore=shutil.ignore_patterns("__pycache__"))
    (root / "data/operational").mkdir(parents=True)
    return root


def test_server_health_log_rotates_in_place_without_safe_stop(tmp_path: Path) -> None:
    root = _copy_repo_parts(tmp_path)
    log = root / "data/operational/server_health_launchd.log"
    content = b'{"status": "AMBER"}\n' * 200
    log.write_bytes(content)
    inode = log.stat().st_ino

    code, report = _run(root, "--max-bytes", "1024")

    assert code == 0 and report["status"] == "PASS"
    assert log.exists() and log.stat().st_size == 0
    assert log.stat().st_ino == inode  # launchd keeps writing to the same file
    with gzip.open(log.with_name(log.name + ".1.gz"), "rb") as archive:
        assert archive.read() == content


def test_runtime_stderr_log_rotates_in_place_while_runtime_runs(tmp_path: Path) -> None:
    """launchd holds the runtime's stderr with O_APPEND; copy-and-truncate keeps that handle valid."""
    root = _copy_repo_parts(tmp_path)
    log = root / "data/operational/runtime_launchd.err.log"
    content = b"2026-11-09 20:57:04,285 INFO tim Research trigger\n" * 50
    log.write_bytes(content)
    inode = log.stat().st_ino
    with log.open("ab") as writer:  # the running runtime's handle, opened before rotation
        code, report = _run(root, "--max-bytes", "1024")
        writer.write(b"after rotation\n")
        writer.flush()

    assert code == 0 and report["status"] == "PASS"
    assert log.stat().st_ino == inode
    assert log.read_bytes() == b"after rotation\n"  # O_APPEND writes land at the new end, no sparse file
    with gzip.open(log.with_name(log.name + ".1.gz"), "rb") as archive:
        assert archive.read() == content
    entry = next(item for item in report["logs"] if item["path"].endswith("runtime_launchd.err.log"))
    assert entry["rotated"] and entry["size_before"] == len(content)


def test_service_stopped_flag_is_still_accepted(tmp_path: Path) -> None:
    root = _copy_repo_parts(tmp_path)
    (root / "data/operational/runtime_launchd.err.log").write_bytes(b"x" * 2048)

    code, report = _run(root, "--max-bytes", "1024", "--service-stopped")

    assert code == 0 and report["status"] == "PASS"


def test_log_maintenance_own_output_is_rotated(tmp_path: Path) -> None:
    root = _copy_repo_parts(tmp_path)
    own = root / "data/operational/log_maintenance_launchd.log"
    own.write_bytes(b"{}\n" * 1000)

    code, _report = _run(root, "--max-bytes", "1024")

    assert code == 0 and own.stat().st_size == 0
    assert own.with_name(own.name + ".1.gz").exists()


def test_user_log_dir_logs_rotate_in_place(tmp_path: Path) -> None:
    """~/Library/Logs/TIM (Qwen worker, Ollama, ...) rotates like the other launchd logs."""
    root = _copy_repo_parts(tmp_path)
    logs = tmp_path / "Logs/TIM"
    logs.mkdir(parents=True)
    big = logs / "local-first.out.log"
    content = b'{"TIM_GITHUB_INTAKE": "DONE"}\n' * 100
    big.write_bytes(content)
    inode = big.stat().st_ino
    small = logs / "ki-filter.log"
    small.write_bytes(b"ok\n")
    old_archive = logs / "local-first.out.log.2026-11-10.gz"
    old_archive.write_bytes(b"x" * 4096)

    code, report = _run(root, "--max-bytes", "1024", "--user-log-dir", str(logs))

    assert code == 0 and report["status"] == "PASS"
    assert big.stat().st_ino == inode and big.stat().st_size == 0
    with gzip.open(big.with_name(big.name + ".1.gz"), "rb") as archive:
        assert archive.read() == content
    assert small.read_bytes() == b"ok\n"
    assert old_archive.stat().st_size == 4096  # archives are not log files
    assert not (logs / "local-first.out.log.2026-11-10.gz.1.gz").exists()


def test_missing_user_log_dir_is_skipped(tmp_path: Path) -> None:
    root = _copy_repo_parts(tmp_path)

    code, report = _run(root, "--max-bytes", "1024", "--user-log-dir", str(tmp_path / "missing"))

    assert code == 0 and report["status"] == "PASS"
    assert not (tmp_path / "missing").exists()
