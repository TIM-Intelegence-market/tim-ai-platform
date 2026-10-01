#!/usr/bin/env python3
"""Store the FRED/ALFRED API key for TIM's ``file`` secret provider, safely.

The key is read with a hidden prompt (no echo, no shell history), checked
against FRED's documented shape (32 lowercase letters and digits) and written
atomically with mode 0600. Nothing is printed except ``****last4`` so the
operator can compare it with the FRED account page.

usage: python scripts/fred_store_key.py [--file PATH]
Then:  TIM_FRED_SECRET_PROVIDER=file python scripts/research_lab_alfred_ingest.py ...
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
import tempfile
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.research_lab.external.fred_secret import (  # noqa: E402
    DEFAULT_SECRET_FILE,
    FILE_ENV,
    KEY_SHAPE,
    PROVIDER_ENV,
    FredSecretResolver,
    describe_shape,
)


def write_private(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".fred-key-")
    try:
        os.fchmod(handle, 0o600)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(value)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def inside_repository(path: Path) -> bool:
    """True when the file would land inside a Git working tree (a key there could be committed).

    The parent directory is resolved, the file name is not: os.replace replaces a symlink itself,
    so the key lands where the link is, not where it points."""
    directory = path.absolute().parent.resolve()
    return any((candidate / ".git").exists() for candidate in (directory, *directory.parents))


def main(argv: list[str] | None = None, prompt: Callable[[str], str] = getpass.getpass) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--file", default=DEFAULT_SECRET_FILE)
    args = parser.parse_args(argv)
    path = Path(args.file).expanduser()
    if path.is_symlink():
        print(f"NOT STORED: {path} is a symbolic link; name the target file itself.")
        return 2
    if inside_repository(path):
        print(f"NOT STORED: {path} lies inside a Git working tree; choose a path outside any repository.")
        return 2
    value = prompt("FRED API key (input hidden, paste only the key): ").strip()
    if not KEY_SHAPE.fullmatch(value):
        print(f"NOT STORED: expected 32 lowercase letters/digits ({describe_shape(value)}). The existing file was left unchanged.")
        return 2
    write_private(path, value)
    FredSecretResolver({PROVIDER_ENV: "file", FILE_ENV: str(path)}).api_key()  # proves the resolver accepts it
    print(f"STORED {path} mode=0600 key=****{value[-4:]}")
    print(f"Use it with: export {PROVIDER_ENV}=file" + (f" {FILE_ENV}='{path}'" if args.file != DEFAULT_SECRET_FILE else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
