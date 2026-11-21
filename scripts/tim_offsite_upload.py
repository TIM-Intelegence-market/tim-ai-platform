#!/usr/bin/env python3
"""Offsite copy of TIM backups to another machine over SSH (Issue #285). OBSERVE only.

files   newest tim_files_*.tar.gz (own market data, small) -> remote folder
dump    newest tim_*.dump -> remote folder; only encrypted (openssl AES-256, key file), because a
        dump may hold credentials. ``--plain-dump`` is an explicit opt-out for trusted targets.

Each upload: sha256 of the local file, copy to a temporary name, remote sha256 must match,
then rename and prune to --keep files. Nothing is written when the check fails. Keys, host and
login come from the command line / ssh config, never from this file; no secret reaches a log.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.tim_db_backup import (  # noqa: E402
    DUMP_PATTERN, FILES_PATTERN, atomic_json, default_backup_directory, sha256_file,
)

REPORT_PATH = ROOT / "data/operational/backup_offsite.json"
SAFE_REMOTE = re.compile(r"^[A-Za-z0-9_./-]+$")
Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


class OffsiteError(RuntimeError):
    pass


def run(cmd: Sequence[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(list(cmd), capture_output=True, text=True, timeout=6 * 3600, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OffsiteError(f"{Path(cmd[0]).name} could not run") from exc


def ssh_opts(port: int | None, key: Path | None) -> list[str]:
    opts = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=20"]
    return opts + (["-i", str(key), "-o", "IdentitiesOnly=yes"] if key else [])


def newest(directory: Path, pattern: re.Pattern[str], suffix: str = "") -> Path:
    found = sorted(p for p in directory.iterdir() if pattern.match(p.name)) if directory.is_dir() else []
    if not found:
        raise OffsiteError(f"no matching backup in {directory}")
    return found[-1]


def verify_sidecar(path: Path) -> str:
    sidecar = path.with_name(path.name + ".sha256")
    if not sidecar.is_file():
        raise OffsiteError(f"checksum file missing for {path.name}")
    actual = sha256_file(path)
    if sidecar.read_text(encoding="utf-8").split()[0] != actual:
        raise OffsiteError(f"checksum mismatch for {path.name}")
    return actual


def encrypt(source: Path, key_file: Path, out_dir: Path) -> Path:
    if not key_file.is_file():
        raise OffsiteError("encryption key file missing")
    out = out_dir / (source.name + ".enc")
    result = run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-salt", "-in", str(source),
                  "-out", str(out), "-pass", f"file:{key_file}"])
    if result.returncode != 0:
        raise OffsiteError("openssl encryption failed")
    return out


def upload(local: Path, target: str, remote_dir: str, keep: int, pattern: str, *,
           port: int | None, key: Path | None, runner: Runner = run) -> dict[str, Any]:
    if not SAFE_REMOTE.match(remote_dir):
        raise OffsiteError("remote folder contains unsafe characters")
    checksum = sha256_file(local)
    opts = ssh_opts(port, key)
    ssh = ["ssh", *opts, *(["-p", str(port)] if port else []), target]
    scp = ["scp", "-q", *opts, *(["-P", str(port)] if port else [])]
    # remote_dir is relative to the login home or absolute; no "~" (quoting would stop its expansion)
    tmp_plain = f"{remote_dir}/.upload.{local.name}"
    rd, tmp = shlex.quote(remote_dir), shlex.quote(tmp_plain)
    final = shlex.quote(f"{remote_dir}/{local.name}")
    if runner([*ssh, f"mkdir -p {rd}"]).returncode != 0:
        raise OffsiteError("remote folder could not be created (login or network)")
    if runner([*scp, str(local), f"{target}:{tmp_plain}"]).returncode != 0:
        raise OffsiteError("scp failed")
    remote = runner([*ssh, f"sha256sum {tmp}"])
    got = remote.stdout.split()[0] if remote.returncode == 0 and remote.stdout.split() else ""
    if got != checksum:
        runner([*ssh, f"rm -f {tmp}"])
        raise OffsiteError("remote checksum does not match, copy removed")
    runner([*ssh, f"mv {tmp} {final}"])
    # keep the newest `keep` files of this kind (names sort by timestamp)
    prune = f"cd {rd} && ls -1 | grep -E {shlex.quote(pattern)} | sort | head -n -{keep} | xargs -r rm -f"
    runner([*ssh, prune])
    return {"remote": f"{target}:{remote_dir}/{local.name}", "bytes": local.stat().st_size, "sha256": checksum}


def main(argv: list[str] | None = None, runner: Runner = run) -> int:
    p = argparse.ArgumentParser(description="TIM offsite upload (OBSERVE only)")
    p.add_argument("command", choices=("files", "dump"))
    p.add_argument("--dir", type=Path, default=default_backup_directory())
    p.add_argument("--target", required=True, help="user@host (from ssh config; no password)")
    p.add_argument("--remote-dir", required=True)
    p.add_argument("--port", type=int)
    p.add_argument("--key", type=Path, help="ssh private key file (path only)")
    p.add_argument("--keep", type=int, default=7)
    p.add_argument("--encrypt-key-file", type=Path, help="dump: file with the passphrase")
    p.add_argument("--plain-dump", action="store_true", help="dump: upload unencrypted (explicit opt-out)")
    a = p.parse_args(argv)
    started = datetime.now(timezone.utc)
    try:
        if a.keep < 1:
            raise OffsiteError("--keep must be at least 1")
        src = newest(a.dir, FILES_PATTERN if a.command == "files" else DUMP_PATTERN)
        verify_sidecar(src)
        pattern = r"^tim_files_.*\.tar\.gz$" if a.command == "files" else r"^tim_.*\.dump(\.enc)?$"
        with tempfile.TemporaryDirectory(prefix=".tim_offsite.", dir=a.dir) as tmp:
            local = src
            if a.command == "dump":
                if a.encrypt_key_file:
                    local = encrypt(src, a.encrypt_key_file, Path(tmp))
                elif not a.plain_dump:
                    raise OffsiteError("dump needs --encrypt-key-file (or explicit --plain-dump)")
            info = upload(local, a.target, a.remote_dir, a.keep, pattern, port=a.port, key=a.key, runner=runner)
        payload = {"status": "PASS", "command": a.command, "source": src.name,
                   "encrypted": local is not src, **info}
    except Exception as exc:  # fail closed, leave evidence, never a secret
        payload = {"status": "FAIL", "command": a.command, "reason": f"{type(exc).__name__}: {exc}"[:300]}
    payload |= {"started_at": started.isoformat(), "completed_at": datetime.now(timezone.utc).isoformat(),
                "trading_actions": 0}
    atomic_json(REPORT_PATH, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
