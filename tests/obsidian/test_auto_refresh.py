from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.obsidian_vault import auto_refresh as ar
from src.obsidian_vault.lint import lint_vault


def sh(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout


def make_upstream(tmp_path: Path) -> tuple[Path, Path]:
    """Bare origin with platform-main holding two PR merges, plus a clone."""
    work = tmp_path / "work"
    work.mkdir()
    sh(work, "init", "-q", "-b", ar.BRANCH)
    sh(work, "config", "user.email", "t@example.com")
    sh(work, "config", "user.name", "t")
    (work / "README.md").write_text("x\n")
    sh(work, "add", ".")
    sh(work, "commit", "-qm", "start", "--date=2026-10-02T10:00:00")

    def pr(number: int, path: str, subject: str, body: str, day: str) -> None:
        sh(work, "checkout", "-qb", f"pr{number}")
        target = work / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"{number}\n")
        sh(work, "add", ".")
        sh(work, "commit", "-qm", f"change {number}")
        sh(work, "checkout", "-q", ar.BRANCH)
        env_date = f"{day}T12:00:00"
        subprocess.run(["git", "-C", str(work), "merge", "-q", "--no-ff", f"pr{number}",
                        "-m", subject, "-m", body], check=True, capture_output=True,
                       env={"GIT_COMMITTER_DATE": env_date, "GIT_AUTHOR_DATE": env_date,
                            "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(tmp_path)})

    pr(431, "src/graph_mcp/x.py", "Merge pull request #431 from org/branch",
       "Graph schneller", "2026-10-20")
    pr(432, "src/research_lab/y.py", "Merge pull request #432: S2 beendet [[x]]", "", "2026-10-26")
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(origin)], check=True)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", "-b", ar.BRANCH, str(origin), str(clone)], check=True)
    return work, clone


def make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    home = vault / "TIM" / "01 Home"
    home.mkdir(parents=True)
    (home / "TIM Current Status.md").write_text(
        "---\ntype: home\nstatus: active\nupdated: 2026-10-13\n---\n# S\n")
    return vault


def test_parse_merge_log_both_subject_shapes():
    log = ("a\x1f2026-10-20\x1fMerge pull request #431 from o/b\x1fGraph schneller\n\x1e"
           "b\x1f2026-10-26\x1fMerge pull request #432: S2 beendet\x1f\x1e"
           "c\x1f2026-10-26\x1fMerge branch 'x'\x1f\x1e"
           "d\x1f2026-10-24\x1fdocs(license): Apache (#401)\x1f\x1e"
           "e\x1f2026-10-24\x1fdirekter Commit\x1f\x1e")
    assert ar.parse_merge_log(log) == [("a", 431, "2026-10-20", "Graph schneller"),
                                       ("b", 432, "2026-10-26", "S2 beendet"),
                                       ("d", 401, "2026-10-24", "docs(license): Apache")]


def test_links_for_maps_paths_to_existing_notes():
    assert ar.links_for(["src/graph_mcp/a.py", "docs/obsidian/b.md", "README.md"]) == (
        "Obsidian", "TIM Graph MCP")
    assert ar.links_for(["README.md"]) == ()


def test_run_writes_week_notes_overview_and_is_idempotent(tmp_path: Path):
    _, clone = make_upstream(tmp_path)
    vault = make_vault(tmp_path)
    report = ar.run(clone, vault, skip_graph=True, skip_graphify=True)
    assert report.pull == "up_to_date" and report.prs == 2
    folder = vault / "TIM" / ar.AUTO_DIR
    names = sorted(p.name for p in folder.iterdir())
    assert names == ["PRs 2026-W43.md", "PRs 2026-W44.md", "TIM Stand automatisch.md"]
    w44 = (folder / "PRs 2026-W44.md").read_text()
    assert "[#432](" in w44 and "[[Research Engine]]" in w44 and "[[x]]" not in w44
    overview = (folder / "TIM Stand automatisch.md").read_text()
    assert "[[PRs 2026-W44]]" in overview and "[[TIM Graph MCP]]: 1 PRs" in overview
    assert not [f for f in lint_vault(vault) if f.level == "error" and f.code != "broken-link"]

    again = ar.run(clone, vault, skip_graph=True, skip_graphify=True)
    assert again.notes_written == [] and again.notes_unchanged == 3


def test_run_fast_forwards_and_keeps_local_changes(tmp_path: Path):
    work, clone = make_upstream(tmp_path)
    vault = make_vault(tmp_path)
    (work / "NEW.md").write_text("n\n")
    sh(work, "add", ".")
    sh(work, "commit", "-qm", "neu")
    sh(work, "push", "-q", str(tmp_path / "origin.git"), ar.BRANCH)
    assert ar.run(clone, vault, skip_graph=True, skip_graphify=True).pull == "updated"
    assert (clone / "NEW.md").exists()

    (work / "NEW2.md").write_text("n\n")
    sh(work, "add", ".")
    sh(work, "commit", "-qm", "neu2")
    sh(work, "push", "-q", str(tmp_path / "origin.git"), ar.BRANCH)
    (clone / "README.md").write_text("lokal\n")
    report = ar.run(clone, vault, skip_graph=True, skip_graphify=True)
    assert report.pull == "local_changes"
    assert (clone / "README.md").read_text() == "lokal\n" and not (clone / "NEW2.md").exists()


def test_foreign_note_in_auto_folder_is_never_overwritten(tmp_path: Path):
    _, clone = make_upstream(tmp_path)
    vault = make_vault(tmp_path)
    folder = vault / "TIM" / ar.AUTO_DIR
    folder.mkdir(parents=True)
    mine = folder / "TIM Stand automatisch.md"
    mine.write_text("---\ntype: report\nstatus: active\nupdated: 2026-10-01\n---\n# Uzi\n")
    report = ar.run(clone, vault, skip_graph=True, skip_graphify=True)
    assert report.notes_refused == [str(mine)]
    assert "# Uzi" in mine.read_text()


def test_vault_commit_only_touches_auto_folder(tmp_path: Path):
    _, clone = make_upstream(tmp_path)
    vault = make_vault(tmp_path)
    sh(vault, "init", "-q")
    sh(vault, "config", "user.email", "t@example.com")
    sh(vault, "config", "user.name", "t")
    sh(vault, "add", ".")
    sh(vault, "commit", "-qm", "start")
    status = vault / "TIM" / "01 Home" / "TIM Current Status.md"
    status.write_text(status.read_text() + "Uzis Änderung\n")
    report = ar.run(clone, vault, skip_graph=True, skip_graphify=True)
    assert report.vault_commit == "committed"
    changed = sh(vault, "show", "--name-only", "--format=", "HEAD").split("\n")
    assert all(line.startswith("TIM/90 Berichte/Automatisch/") or line in report.hubs_written
               for line in changed if line)
    assert report.hubs_written == ["TIM/90 Berichte/Reports MOC.md"]
    assert "TIM/01 Home/TIM Current Status.md" in sh(vault, "status", "--porcelain")


def test_dry_run_writes_nothing(tmp_path: Path):
    _, clone = make_upstream(tmp_path)
    vault = make_vault(tmp_path)
    report = ar.run(clone, vault, dry_run=True)
    assert len(report.notes_written) == 3
    assert not (vault / "TIM" / ar.AUTO_DIR).exists()


@pytest.mark.parametrize("day,week", [("2026-10-26", "2026-W44"), ("2026-01-01", "2026-W01")])
def test_week_of(day: str, week: str):
    assert ar.week_of(day) == week


def test_heavy_steps_only_when_head_moved(tmp_path: Path, monkeypatch):
    _, clone = make_upstream(tmp_path)
    vault = make_vault(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(ar, "refresh_graph",
                        lambda repo, v, report, mode="refresh-all": (
                            calls.append(mode), setattr(report, "graph", f"ok {mode}")))
    monkeypatch.setattr(ar, "refresh_graphify",
                        lambda repo, view, report: (calls.append("graphify"),
                                                    setattr(report, "graphify", "ok")))
    first = ar.run(clone, vault)
    assert calls == ["refresh-all", "graphify"]
    calls.clear()
    second = ar.run(clone, vault, previous=dict(first.__dict__))
    assert calls == ["refresh-docs"] and second.graphify == "unchanged"
    calls.clear()
    ar.run(clone, vault, previous={"head": "alt", "graph": "ok refresh-all", "graphify": "ok"})
    assert calls == ["refresh-all", "graphify"]
