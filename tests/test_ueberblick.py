"""Überblick page (14.11.2026): shows what is new and what no register knows yet, without hand-kept lists."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from src.dashboard.app import DashboardState
from src.dashboard.cockpit import BUILT, ueberblick


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    studies = tmp_path / "docs/research_lab/studien"
    studies.mkdir(parents=True)
    (tmp_path / "docs/research_lab/LOGBUCH.json").write_text(json.dumps({"entries": [
        {"id": "S1", "title": "Alt", "status": "failed", "started": "2026-10-01"}]}), encoding="utf-8")
    (studies / "S1_ALT.md").write_text("x", encoding="utf-8")
    (studies / "S99_NEU_ENTWURF.md").write_text("x", encoding="utf-8")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "Start")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "Merge pull request #7 from org/branch", "-m", "Schatten-Score im Journal")
    return tmp_path


def test_new_merges_and_unlogged_studies_show_up(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    model = ueberblick.build_ueberblick(DashboardState(), datetime.now(timezone.utc), root=root)
    sections = {s["id"]: s for s in model["sections"]}
    assert set(sections) == {"waiting", "new", "studies", "mac"}
    rows = sections["new"]["table"]["rows"]
    assert rows[0][1]["text"] == "#7" and rows[0][2]["text"] == "Schatten-Score im Journal"
    studies = {t["id"]: t for t in sections["studies"]["tiles"]}
    assert studies["unlogged"]["value"] == "1" and studies["unlogged"]["state"] == "warn"
    assert sections["studies"]["table"]["rows"][0][0]["text"] == "S99" and sections["studies"]["table"]["rows"][0][2]["text"] == "Entwurf"


def test_a_broken_source_greys_one_section_not_the_page(tmp_path: Path) -> None:
    model = ueberblick.build_ueberblick(DashboardState(), datetime.now(timezone.utc), root=tmp_path / "gibt-es-nicht")
    new = next(s for s in model["sections"] if s["id"] == "new")
    assert new["tiles"][0]["state"] == "unknown" and "nicht lesbar" in new["tiles"][0]["reason"]
    assert "ueberblick" in BUILT
