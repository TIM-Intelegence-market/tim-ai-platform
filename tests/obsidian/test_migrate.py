import json
from datetime import date
from pathlib import Path

import pytest

from src.obsidian_vault.lint import lint_vault
from src.obsidian_vault.migrate import Migration, main

OLD = {
    "00 HOME/TIM Current Status.md": ("gate", "active", "[[TIM/30 Missions/Missions MOC]]"),
    "00 HOME/TIM Navigation.md": ("navigation", "active", "[[Missions MOC|Missionen]]"),
    "10 Architecture/System Architecture.md": ("architecture", "active", ""),
    "40 Architecture/TIM Graph MCP.md": ("architecture", "active", "[[System Architecture]]"),
    "20 Incidents/Active Incidents.md": ("index", "active", ""),
    "20 Incidents/Hash Blocker.md": ("incident", "resolved", ""),
    "30 Missions/Missions MOC.md": ("moc", "active", "[[LONG History Extension Execution]]"),
    "30 Missions/LONG History Extension Execution.md": ("mission", "active", ""),
    "30 Missions/MID Readiness Audit.md": ("report", "completed", ""),
    "30 Missions/Qwen Self Repair Gate.md": ("gate", "pass", ""),
    "30 Missions/MID Design.md": ("mission", "blocked", ""),
    "40 Systems/Candle Engine.md": ("system", "active", ""),
    "50 Data & QA/Determinism.md": ("architecture", "active", ""),
    "50 Data & QA/LONG Readiness.md": ("gate", "blocked", ""),
    "60 Agents & Tools/Qwen.md": ("tool", "active", "```\n[[Code Link]]\n```"),
    "70 Decisions/Decision Log.md": ("decision-log", "active",
                                     "[[LONG History\nExtension Execution]]"),
    "80 Runbooks/Safe Restart.md": ("runbook", "active", ""),
    "90 Reports/Mission Reports/2026-09-18 Build.md": ("report", "completed",
                                                       "[[Neuer Link]] und `[[Code]]`"),
    "Templates/Template Daily Status.md": ("report", "completed", "[[{{date}}]]"),
    "Templates/Template Gate.md": ("gate", "unknown", ""),
}


@pytest.fixture
def old_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "TIM OBSIDIAN"
    for rel, (type_, status, body) in OLD.items():
        path = vault / "TIM" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\ntype: {type_}\nproject: TIM\nstatus: {status}\n"
                        f"created: 2026-09-18\nupdated: 2026-09-24\n---\n# T\n{body}\n",
                        encoding="utf-8")
    settings = vault / ".obsidian"
    settings.mkdir()
    (settings / "core-plugins.json").write_text(json.dumps({"sync": True, "bases": True}))
    (settings / "templates.json").write_text(json.dumps({"folder": "TIM/Templates"}))
    (settings / "daily-notes.json").write_text(json.dumps({"folder": "TIM/90 Reports/Daily"}))
    (settings / "workspace.json").write_text("{}")
    return vault


def test_plan_maps_every_note(old_vault):
    plans, _ = Migration(old_vault).plan()
    by_source = {p.source: p for p in plans}
    assert len(plans) == len(OLD)
    assert by_source["00 HOME/TIM Current Status.md"].new_type == "home"
    assert by_source["40 Architecture/TIM Graph MCP.md"].target == "TIM/10 Architektur/TIM Graph MCP.md"
    assert by_source["30 Missions/MID Readiness Audit.md"].target.startswith("TIM/90 Berichte/")
    assert by_source["30 Missions/Qwen Self Repair Gate.md"].new_status == "done"
    assert by_source["50 Data & QA/Determinism.md"].new_type == "data-qa"
    assert by_source["70 Decisions/Decision Log.md"].new_type == "moc"
    assert by_source["Templates/Template Daily Status.md"].new_type == "daily"
    assert by_source["Templates/Template Gate.md"].new_status == "planned"


def test_plan_never_writes(old_vault):
    before = {p: p.read_bytes() for p in old_vault.rglob("*") if p.is_file()}
    Migration(old_vault).plan()
    assert main(["plan", "--source", str(old_vault), "--markdown"]) == 0
    assert before == {p: p.read_bytes() for p in old_vault.rglob("*") if p.is_file()}


def test_apply_produces_a_lint_clean_vault(old_vault, tmp_path):
    target = tmp_path / "neu"
    before = {p: p.read_bytes() for p in old_vault.rglob("*") if p.is_file()}
    Migration(old_vault).apply(target)
    assert before == {p: p.read_bytes() for p in old_vault.rglob("*") if p.is_file()}
    assert lint_vault(target, today=date(2026, 10, 1)) == []
    root = target / "TIM"
    assert len(list(root.rglob("*.md"))) == len(OLD)
    assert (root / "00 Inbox").is_dir() and (root / "90 Berichte" / "Daily").is_dir()
    log = (root / "70 Entscheidungen" / "Decision Log.md").read_text()
    assert "[[LONG History Extension Execution]]" in log and "type: moc" in log
    status = (root / "01 Home" / "TIM Current Status.md").read_text()
    assert "[[Missions MOC]]" in status
    report = (root / "90 Berichte" / "Mission Reports" / "2026-09-18 Build.md").read_text()
    assert "[[Neuer Link]]" not in report and "Neuer Link" in report and "`[[Code]]`" in report
    assert "[[Code Link]]" in (root / "60 Agenten & Tools" / "Qwen.md").read_text()
    assert "[[{{date}}]]" in (root / "99 Vorlagen" / "Template Daily Status.md").read_text()
    settings = target / ".obsidian"
    assert json.loads((settings / "core-plugins.json").read_text())["sync"] is False
    assert json.loads((settings / "templates.json").read_text())["folder"] == "TIM/99 Vorlagen"
    assert json.loads((settings / "daily-notes.json").read_text())["folder"] == "TIM/90 Berichte/Daily"
    assert not (settings / "workspace.json").exists()


def test_apply_refuses_non_empty_target_and_source(old_vault, tmp_path):
    target = tmp_path / "voll"
    target.mkdir()
    (target / "x").write_text("x")
    with pytest.raises(FileExistsError):
        Migration(old_vault).apply(target)
    with pytest.raises(FileExistsError):
        Migration(old_vault).apply(old_vault)


def test_unknown_folder_or_status_stops_the_plan(old_vault):
    extra = old_vault / "TIM" / "Sonstiges" / "X.md"
    extra.parent.mkdir()
    extra.write_text("---\ntype: moc\nstatus: active\nupdated: 2026-09-24\n---\n")
    with pytest.raises(ValueError, match="keine Zuordnung"):
        Migration(old_vault).plan()
    extra.unlink()
    extra.parent.rmdir()
    (old_vault / "TIM" / "40 Systems" / "Y.md").write_text(
        "---\ntype: system\nstatus: irgendwas\nupdated: 2026-09-24\n---\n")
    with pytest.raises(ValueError, match="keine Zuordnung"):
        Migration(old_vault).plan()
