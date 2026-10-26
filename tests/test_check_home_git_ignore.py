"""Paket S1 (Grün-Plan Sicht 10): the home-git check only reads and reports what `git add .` would capture."""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "ops" / "macos" / "check_home_git_ignore.py"


def load():
    spec = importlib.util.spec_from_file_location("check_home_git_ignore", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(home: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(home), "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True, capture_output=True)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    for rel in ("Library/Application Support/TIM", "TIM-live", ".ssh", "Documents/TIM"):
        (tmp_path / rel).mkdir(parents=True)
    git(tmp_path, "init", "-q")
    (tmp_path / ".gitignore").write_text("TIM-live/\nLibrary/\n")
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / ".env").write_text("SECRET=1")
    git(tmp_path, "add", ".gitignore", "notes.txt", ".env")
    git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def test_reports_unignored_tim_paths_and_tracked_secrets(home: Path) -> None:
    module = load()
    result = module.check(home)
    assert result["git_repo"] and not result["ok"]
    assert set(result["not_ignored"]) == {"Documents/TIM", ".ssh"}
    assert result["tracked_suspicious"] == [".env"]
    assert "TIM-worker" in result["missing"]
    text = module.render(result)
    assert "FAIL" in text and "Documents/TIM" in text and ".env" in text
    assert module.main(["--home", str(home)]) == 1
    # the check changed nothing
    status = subprocess.run(["git", "-C", str(home), "status", "--porcelain"], capture_output=True, text=True, check=True)
    assert status.stdout == ""


def test_passes_once_everything_is_ignored(home: Path) -> None:
    module = load()
    (home / ".gitignore").write_text("TIM-live/\nLibrary/\nDocuments/TIM/\n.ssh/\n")
    git(home, "rm", "-q", "--cached", ".env")
    git(home, "commit", "-q", "-am", "ignore")
    result = module.check(home)
    assert result["ok"] and result["not_ignored"] == [] and result["tracked_suspicious"] == []
    assert module.main(["--home", str(home), "--json"]) == 0


def test_home_without_git_passes(tmp_path: Path) -> None:
    module = load()
    result = module.check(tmp_path)
    assert result["ok"] and not result["git_repo"]
