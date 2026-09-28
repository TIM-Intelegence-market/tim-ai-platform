from __future__ import annotations

import plistlib
from pathlib import Path

from scripts.validate_launchd_runtime import validate


def test_validator_accepts_complete_launchd_configuration(tmp_path: Path) -> None:
    program = tmp_path / "python"
    program.write_text("#!/bin/sh\n")
    program.chmod(0o700)
    main = tmp_path / "main.py"
    main.write_text("")
    config = tmp_path / "config"
    config.mkdir()
    (config / "settings.py").write_text("")
    stdout = tmp_path / "stdout.log"
    stderr = tmp_path / "stderr.log"
    stdout.touch()
    stderr.touch()
    plist = tmp_path / "runtime.plist"
    with plist.open("wb") as handle:
        plistlib.dump(
            {
                "Label": "com.tim.runtime",
                "ProgramArguments": [str(program), str(main)],
                "WorkingDirectory": str(tmp_path),
                "StandardOutPath": str(stdout),
                "StandardErrorPath": str(stderr),
                "EnvironmentVariables": {
                    "TIM_ENABLE_OLLAMA": "false",
                    "TIM_OLLAMA_URL": "http://127.0.0.1:11434",
                    "TIM_OLLAMA_MODEL": "test",
                },
            },
            handle,
        )

    assert validate(plist)["status"] == "PASS"


def test_validator_rejects_missing_log_target_and_config(tmp_path: Path) -> None:
    program = tmp_path / "python"
    program.write_text("#!/bin/sh\n")
    program.chmod(0o700)
    main = tmp_path / "main.py"
    main.write_text("")
    plist = tmp_path / "runtime.plist"
    with plist.open("wb") as handle:
        plistlib.dump(
            {
                "ProgramArguments": [str(program), str(main)],
                "WorkingDirectory": str(tmp_path),
                "StandardOutPath": str(tmp_path / "missing.log"),
                "StandardErrorPath": str(tmp_path / "missing.err.log"),
                "EnvironmentVariables": {},
            },
            handle,
        )

    report = validate(plist)

    assert report["status"] == "FAIL"
    assert {"central_config", "stdout", "stderr", "environment"}.issubset(report["failed"])
