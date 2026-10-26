"""Grün-Plan C3: requirements.lock bleibt eine echte Sperrdatei und passt zu requirements.txt."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("check_requirements_lock", ROOT / "scripts/check_requirements_lock.py")
crl = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(crl)


def test_lock_file_pins_every_package_exactly_once():
    text = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    pins = crl.parse_pins(text)
    lines = [l.split("#", 1)[0].strip() for l in text.splitlines()]
    assert len([l for l in lines if l]) == len(pins) >= 40
    assert all(v and not v.startswith(("<", ">", "~")) for v in pins.values())


def test_lock_satisfies_requirements_txt():
    pytest.importorskip("packaging")
    requirements = crl.parse_requirements((ROOT / "requirements.txt").read_text(encoding="utf-8"))
    lock = crl.parse_pins((ROOT / "requirements.lock").read_text(encoding="utf-8"))
    assert crl.check_requirements(requirements, lock) == []


def test_compare_freeze_reports_each_kind_of_drift():
    lock = {"asyncpg": "0.32.0", "websockets": "16.1.1", "ollama": "0.6.3"}
    freeze = {"asyncpg": "0.32.0", "websockets": "15.0", "requests": "2.34.2"}
    problems = crl.compare_freeze(freeze, lock)
    assert problems == [
        "fehlt in der venv: ollama==0.6.3",
        "zusätzlich in der venv: requests==2.34.2",
        "andere Version: websockets venv 15.0 / Sperrdatei 16.1.1",
    ]


def test_cli_exit_codes(tmp_path: Path):
    lock = tmp_path / "requirements.lock"
    lock.write_text("Foo_Bar==1.0\nbaz==2.0 ; python_version >= '3.9'\n", encoding="utf-8")
    same = tmp_path / "same.txt"
    same.write_text("foo-bar==1.0\nbaz==2.0\n", encoding="utf-8")
    drift = tmp_path / "drift.txt"
    drift.write_text("foo-bar==1.1\nbaz==2.0\n", encoding="utf-8")
    broken = tmp_path / "broken.txt"
    broken.write_text("foo-bar>=1\n", encoding="utf-8")
    assert crl.main(["--lock", str(lock), "--freeze", str(same)]) == 0
    assert crl.main(["--lock", str(lock), "--freeze", str(drift)]) == 1
    assert crl.main(["--lock", str(lock), "--freeze", str(broken)]) == 2


def test_requirements_check_flags_unlocked_and_unsatisfied(tmp_path: Path):
    pytest.importorskip("packaging")
    requirements = crl.parse_requirements("alpha>=1,<2\nbeta>=3\ngamma\n")
    problems = crl.check_requirements(requirements, {"alpha": "2.5", "gamma": "0.1"})
    assert problems == [
        "Sperrdatei erfüllt requirements.txt nicht: alpha==2.5 gegen >=1,<2",
        "nicht gesperrt: beta>=3",
    ]
