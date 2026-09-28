from __future__ import annotations

import argparse
import json
import os
import plistlib
from pathlib import Path
from typing import Any


REQUIRED_ENVIRONMENT_NAMES = {
    "TIM_ENABLE_OLLAMA",
    "TIM_OLLAMA_URL",
    "TIM_OLLAMA_MODEL",
}


def _path_check(path: Path, *, executable: bool = False, directory: bool = False) -> dict[str, Any]:
    exists = path.exists()
    correct_type = path.is_dir() if directory else path.is_file()
    return {
        "path": str(path),
        "exists": exists,
        "correct_type": correct_type,
        "readable": exists and os.access(path, os.R_OK),
        "executable": exists and os.access(path, os.X_OK) if executable else None,
    }


def validate(plist_path: Path) -> dict[str, Any]:
    with plist_path.open("rb") as handle:
        payload = plistlib.load(handle)
    arguments = payload.get("ProgramArguments") or []
    program_value = payload.get("Program") or (arguments[0] if arguments else "")
    working_value = payload.get("WorkingDirectory") or ""
    stdout_value = payload.get("StandardOutPath") or ""
    stderr_value = payload.get("StandardErrorPath") or ""
    environment = payload.get("EnvironmentVariables") or {}

    checks: dict[str, Any] = {
        "plist": _path_check(plist_path),
        "program": _path_check(Path(program_value), executable=True) if program_value else {"path": "", "exists": False},
        "working_directory": _path_check(Path(working_value), directory=True) if working_value else {"path": "", "exists": False},
        "main": _path_check(Path(arguments[1])) if len(arguments) > 1 else {"path": "", "exists": False},
        "central_config": _path_check(Path(working_value) / "config" / "settings.py") if working_value else {"path": "", "exists": False},
    }
    for name, value in (("stdout", stdout_value), ("stderr", stderr_value)):
        path = Path(value) if value else Path("")
        checks[name] = {
            **(_path_check(path) if value else {"path": "", "exists": False}),
            "parent_writable": bool(value) and path.parent.is_dir() and os.access(path.parent, os.W_OK),
            "writable": bool(value) and path.exists() and os.access(path, os.W_OK),
        }

    missing_environment = sorted(REQUIRED_ENVIRONMENT_NAMES.difference(environment))
    failed = []
    for name, check in checks.items():
        if not check.get("exists") or check.get("correct_type") is False or check.get("readable") is False:
            failed.append(name)
        if name == "program" and not check.get("executable"):
            failed.append(name)
        if name in {"stdout", "stderr"} and (not check.get("parent_writable") or not check.get("writable")):
            failed.append(name)
    if missing_environment:
        failed.append("environment")

    return {
        "status": "PASS" if not failed else "FAIL",
        "label": payload.get("Label"),
        "checks": checks,
        "environment": {
            "configured_names": sorted(environment),
            "missing_required_names": missing_environment,
        },
        "failed": sorted(set(failed)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate TIM launchd paths and non-secret configuration")
    parser.add_argument("plist", type=Path)
    arguments = parser.parse_args()
    report = validate(arguments.plist.expanduser())
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
