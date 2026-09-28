#!/usr/bin/env python3
"""Provision a private TIM daemon secret from the logged-in macOS Keychain.

The password is never printed or passed on a command line.  This must run while
the desktop user's Keychain is unlocked, before enabling the logout-safe daemon.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile


DEFAULT_PATH = Path("~/Library/Application Support/TIM/database-password").expanduser()


def private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    metadata = path.lstat()
    if path.is_symlink() or not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
        raise RuntimeError("daemon secret directory is unsafe")
    os.chmod(path, 0o700)


def write_private(path: Path, secret: str) -> None:
    private_directory(path.parent)
    if path.exists():
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise RuntimeError("daemon secret path is unsafe")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(secret)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", default="com.tim.database")
    parser.add_argument("--account", default="tim")
    parser.add_argument("--output", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args()
    result = subprocess.run(
        ["/usr/bin/security", "find-generic-password", "-s", args.service, "-a", args.account, "-w"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    secret = result.stdout.rstrip("\n")
    if result.returncode != 0 or not secret or "\n" in secret or "\r" in secret:
        raise RuntimeError("Keychain database secret is unavailable")
    output = args.output.expanduser()
    write_private(output, secret)
    secret = ""
    print(json.dumps({"status": "PROVISIONED", "path": str(output), "secret_printed": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
