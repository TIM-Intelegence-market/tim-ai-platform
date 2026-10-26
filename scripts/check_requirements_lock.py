#!/usr/bin/env python3
"""Vergleicht eine venv (``pip freeze``) oder requirements.txt mit requirements.lock (Grün-Plan C3).

    python -m pip freeze | python scripts/check_requirements_lock.py            # venv gegen Sperrdatei
    python scripts/check_requirements_lock.py --freeze freeze.txt               # dasselbe aus einer Datei
    python scripts/check_requirements_lock.py --requirements requirements.txt  # Sperrdatei erfüllt requirements.txt?

Exit 0 = gleich bzw. erfüllt, 1 = Abweichung, 2 = Eingabefehler. Nur lesend, kein Netz, keine Installation.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(.*?)\s*(?:#.*)?$")


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_pins(text: str) -> dict[str, str]:
    """``name==version`` je Zeile; Kommentare, Leerzeilen und Editable-Zeilen werden übersprungen."""
    pins: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        if "==" not in line:
            raise ValueError(f"keine feste Version: {raw.strip()!r}")
        name, version = line.split("==", 1)
        pins[canonical(name.split("[", 1)[0])] = version.split(";", 1)[0].strip()
    return pins


def parse_requirements(text: str) -> dict[str, str]:
    """Name → Spezifikator aus requirements.txt (ohne Marker, ohne Extras)."""
    result: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        match = _NAME.match(line.split(";", 1)[0])
        if not match:
            raise ValueError(f"unlesbare Zeile: {raw.strip()!r}")
        name, spec = match.groups()
        result[canonical(name.split("[", 1)[0])] = spec.strip()
    return result


def compare_freeze(freeze: dict[str, str], lock: dict[str, str]) -> list[str]:
    problems = []
    for name in sorted(set(freeze) | set(lock)):
        if name not in lock:
            problems.append(f"zusätzlich in der venv: {name}=={freeze[name]}")
        elif name not in freeze:
            problems.append(f"fehlt in der venv: {name}=={lock[name]}")
        elif freeze[name] != lock[name]:
            problems.append(f"andere Version: {name} venv {freeze[name]} / Sperrdatei {lock[name]}")
    return problems


def check_requirements(requirements: dict[str, str], lock: dict[str, str]) -> list[str]:
    try:
        from packaging.specifiers import SpecifierSet
        from packaging.version import Version
    except ImportError:  # pragma: no cover - packaging fehlt nur in sehr schlanken Umgebungen
        SpecifierSet = Version = None  # type: ignore[assignment]
    problems = []
    for name, spec in sorted(requirements.items()):
        if name not in lock:
            problems.append(f"nicht gesperrt: {name}{spec}")
            continue
        if spec and SpecifierSet is not None and not SpecifierSet(spec).contains(Version(lock[name]), prereleases=True):
            problems.append(f"Sperrdatei erfüllt requirements.txt nicht: {name}=={lock[name]} gegen {spec}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lock", type=Path, default=ROOT / "requirements.lock")
    parser.add_argument("--freeze", type=Path, help="Datei mit `pip freeze`-Ausgabe (Standard: stdin)")
    parser.add_argument("--requirements", type=Path, help="requirements.txt gegen die Sperrdatei prüfen")
    args = parser.parse_args(argv)
    try:
        lock = parse_pins(args.lock.read_text(encoding="utf-8"))
        if args.requirements is not None:
            problems = check_requirements(parse_requirements(args.requirements.read_text(encoding="utf-8")), lock)
            label = f"{args.requirements.name} gegen {args.lock.name}"
        else:
            text = args.freeze.read_text(encoding="utf-8") if args.freeze else sys.stdin.read()
            problems = compare_freeze(parse_pins(text), lock)
            label = f"venv gegen {args.lock.name} ({len(lock)} Pakete)"
    except (OSError, ValueError) as exc:
        print(f"Eingabefehler: {exc}")
        return 2
    if problems:
        print(f"ABWEICHUNG {label}:")
        print("\n".join(f"  - {p}" for p in problems))
        return 1
    print(f"OK {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
