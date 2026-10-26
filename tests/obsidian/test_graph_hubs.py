from __future__ import annotations

import json
from pathlib import Path

from src.obsidian_vault import graph_hubs as gh
from src.obsidian_vault.lint import lint_vault


def write(vault: Path, rel: str, text: str) -> Path:
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def fm(type_: str, extra: str = "") -> str:
    return f"---\ntype: {type_}\nstatus: active\nupdated: 2026-10-26\n{extra}---\n"


def make(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    write(vault, "TIM/01 Home/TIM Home.md", fm("home") + "# TIM\n\nEigener Text.\n")
    write(vault, "TIM/01 Home/TIM Current Status.md", fm("home") + "# S\n")
    write(vault, "TIM/40 Systeme/Systems MOC.md", fm("moc") + "# Systems MOC\n\nHandtext.\n")
    write(vault, "TIM/40 Systeme/Candle Engine.md", fm("system") + "# C\n")
    write(vault, "TIM/40 Systeme/Neu/Tiefer.md", fm("system") + "# T\n")
    write(vault, "TIM/70 Entscheidungen/Decision Log.md", fm("decision") + "# D\n")
    write(vault, "TIM/90 Berichte/Automatisch/PRs 2026-W44.md",
          fm("report", "tags:\n  - automatisch\n") + "# W\n")
    write(vault, "TIM/90 Berichte/Automatisch/TIM Stand automatisch.md",
          fm("report", "tags:\n  - automatisch\n") + "# A\n")
    write(vault, "TIM/99 Vorlagen/Template System.md", fm("system") + "# V\n")
    write(vault, "TIM/95 Archiv/Alt.md", "---\ntype: system\nstatus: archived\nupdated: 2026-10-26\n---\n")
    write(vault, "Claude Anleitung.md", "# Anleitung\n")
    return vault


def test_sync_links_every_note_and_keeps_hand_text(tmp_path: Path):
    vault = make(tmp_path)
    assert gh.orphans(vault)  # before: nothing is linked
    changed = gh.sync(vault)
    rels = sorted(p.relative_to(vault).as_posix() for p in changed)
    assert "TIM/70 Entscheidungen/Decisions MOC.md" in rels  # missing hub created
    assert "TIM/90 Berichte/Reports MOC.md" in rels
    systems = (vault / "TIM/40 Systeme/Systems MOC.md").read_text()
    assert "Handtext." in systems and "[[Candle Engine]]" in systems and "[[Tiefer]]" in systems
    assert "[[TIM Home]]" in systems
    home = (vault / "TIM/01 Home/TIM Home.md").read_text()
    assert "Eigener Text." in home
    for hub in ("Systems MOC", "Decisions MOC", "Reports MOC", "TIM Current Status",
                "Claude Anleitung"):
        assert f"[[{hub}]]" in home
    reports = (vault / "TIM/90 Berichte/Reports MOC.md").read_text()
    assert "[[TIM Stand automatisch]]" in reports and "PRs 2026-W44" not in reports
    assert "Template System" not in home + systems and "[[Alt]]" not in home
    assert gh.orphans(vault) == []
    assert gh.sync(vault) == []  # idempotent
    assert not [f for f in lint_vault(vault) if f.level == "error"]


def test_block_replaced_in_place(tmp_path: Path):
    vault = make(tmp_path)
    gh.sync(vault)
    (vault / "TIM/40 Systeme/Candle Engine.md").unlink()
    write(vault, "TIM/40 Systeme/Durable Outbox.md", fm("system") + "# O\n")
    gh.sync(vault)
    text = (vault / "TIM/40 Systeme/Systems MOC.md").read_text()
    assert text.count(gh.START) == 1 and "[[Durable Outbox]]" in text
    assert "[[Candle Engine]]" not in text and text.index("Handtext.") < text.index(gh.START)


def test_dry_run_and_check(tmp_path: Path, capsys):
    vault = make(tmp_path)
    assert gh.sync(vault, dry_run=True)
    assert not (vault / "TIM/70 Entscheidungen/Decisions MOC.md").exists()
    assert gh.main(["check", "--vault", str(vault)]) == 1
    gh.main(["sync", "--vault", str(vault)])
    assert gh.main(["check", "--vault", str(vault)]) == 0
    assert "0 unverbundene" in capsys.readouterr().out


def test_settings_keep_zoom(tmp_path: Path):
    vault = make(tmp_path)
    write(vault, ".obsidian/graph.json", json.dumps({"scale": 0.3, "colorGroups": []}))
    assert gh.apply_settings(vault)
    data = json.loads((vault / ".obsidian/graph.json").read_text())
    template = json.loads(gh.GRAPH_TEMPLATE.read_text())
    assert data["scale"] == 0.3 and data["colorGroups"] == template["colorGroups"]
    assert data["hideUnresolved"] is True
    assert not gh.apply_settings(vault)


def test_every_hub_has_a_colour():
    template = json.loads(gh.GRAPH_TEMPLATE.read_text())
    queries = " ".join(group["query"] for group in template["colorGroups"])
    for folder in [gh.HOME_FOLDER, *gh.HUBS]:
        assert f'path:"{folder}"' in queries
