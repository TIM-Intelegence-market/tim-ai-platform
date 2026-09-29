#!/usr/bin/env python3
"""Store the OpenMarket API key for TIM's ``file`` secret provider, safely.

The key is read with a hidden prompt (no echo, no clipboard file, no shell
history), checked against the same shape rule the resolver enforces, and
written atomically with mode 0600. Nothing is printed except the length and
``****last4`` so the operator can compare it with the OpenMarket dashboard.

usage: python scripts/openmarket_store_key.py [--file PATH]
Then: TIM_OPENMARKET_SECRET_PROVIDER=file python scripts/openmarket_api_proof.py
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

from src.market_data.providers.openmarket.auth import (  # noqa: E402
    _KEY_SHAPE,
    DEFAULT_SECRET_FILE,
    OpenMarketSecretResolver,
)

# Plausibility guard, not an OpenMarket rule: a key name such as "TIM-SERVER"
# also matches the shape, a real API key is much longer.
MIN_PLAUSIBLE_LENGTH = 20


def problems(value: str, *, allow_short: bool) -> list[str]:
    found = []
    if any(c.isspace() for c in value):
        found.append("contains spaces or line breaks (more than the key was pasted)")
    if any(not 33 <= ord(c) <= 126 for c in value if not c.isspace()):
        found.append("contains non-ASCII characters")
    if not _KEY_SHAPE.fullmatch(value) and not found:
        found.append("does not match the key shape (8-512 printable ASCII characters)")
    if len(value) < MIN_PLAUSIBLE_LENGTH and not allow_short:
        found.append(f"only {len(value)} characters; is this the key name instead of the key?")
    return found


def write_private(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".openmarket-key-")
    try:
        os.fchmod(handle, 0o600)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(value)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None, prompt: Callable[[str], str] = getpass.getpass) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--file", default=DEFAULT_SECRET_FILE)
    parser.add_argument("--allow-short", action="store_true", help="accept keys shorter than 20 characters")
    args = parser.parse_args(argv)
    path = Path(args.file).expanduser()

    value = prompt("OpenMarket API key (input hidden, paste only the key): ").strip()
    issues = problems(value, allow_short=args.allow_short)
    if issues:
        print("NOT STORED: the input " + "; ".join(issues) + ".")
        print("The existing file was left unchanged.")
        return 2
    write_private(path, value)
    resolver = OpenMarketSecretResolver({"TIM_OPENMARKET_SECRET_PROVIDER": "file", "TIM_OPENMARKET_SECRET_FILE": str(path)})
    resolver.api_key()  # proves the resolver accepts exactly what was written
    print(f"STORED {path} mode=0600 length={len(value)} key=****{value[-4:]}")
    print("SECRET_CONFIGURED=YES (compare the last 4 characters with the OpenMarket dashboard)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
