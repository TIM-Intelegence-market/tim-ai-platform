from __future__ import annotations

from pathlib import Path

import pytest


def note(type_: str, status: str = "active", updated: str = "2026-09-30",
         body: str = "", extra: str = "") -> str:
    return (f"---\ntype: {type_}\nstatus: {status}\nupdated: {updated}\n{extra}---\n"
            f"# Titel\n{body}\n")


@pytest.fixture
def clean_vault(tmp_path: Path) -> Path:
    """A vault that satisfies the schema completely."""
    vault = tmp_path / "vault"
    root = vault / "TIM"
    files = {
        "01 Home/TIM Home.md": note("home", body="Siehe [[Missionen MOC]] und [[Demo Mission#Ziel|Ziel]]."),
        "30 Missionen/Missionen MOC.md": note("moc", body="[[Demo Mission]], [[Demo Gate]]"),
        "30 Missionen/Demo Mission.md": note("mission", body="Gate: [[Demo Gate]]\n```\n[[nur im Code]]\n```\n`[[auch Code]]`"),
        "30 Missionen/Demo Gate.md": note("gate", "done"),
        "70 Entscheidungen/Drawdown 20 Prozent.md": note("decision", "done", extra="source: https://github.com/x/y/pull/118\n"),
        "00 Inbox/Entwurf.md": note("decision", "planned", extra="review: pending\n"),
        "95 Archiv/Alt.md": note("system", "archived"),
        "99 Vorlagen/Vorlage Mission.md": "---\ntype: mission\nstatus: planned\nupdated:\n---\n[[{{title}}]]\n",
    }
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian" / "app.json").write_text("{}")
    return vault
