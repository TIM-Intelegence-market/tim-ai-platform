"""Gedächtnis-Liste: Schema, Code-Verweise, Gruppen. Die Liste ändert keine Regel."""
from __future__ import annotations

from src.research_lab import gedaechtnis as g


def test_the_committed_list_is_valid_and_its_code_references_exist():
    aussagen = g.laden()
    assert len(aussagen) >= 50
    assert g.pruefen(aussagen) == []


def test_groups_follow_status_and_use():
    base = {"status": "ungeprueft", "nutzung": "entscheidet"}
    assert g.gruppe({**base, "status": "widerlegt"}) == 1
    assert g.gruppe(base) == 2
    assert g.gruppe({**base, "status": "belegt"}) == 5
    assert g.gruppe({**base, "nutzung": "schatten", "status": "belegt"}) == 3
    assert g.gruppe({**base, "nutzung": "keine", "status": "widerlegt"}) == 4
    assert g.gruppe({**base, "nutzung": "ruhend"}) == 6
    assert g.gruppe({**base, "nutzung": "unklar"}) == 2


def test_check_finds_broken_entries(tmp_path):
    ok = g.laden()[0]
    kaputt = [
        {**ok, "id": "X1", "status": "gut"},
        {**ok, "id": "X2", "code": "src/gibt/es/nicht.py"},
        {**ok, "id": "X3", "nutzung": "entscheidet", "code": "-"},
        {k: v for k, v in ok.items() if k != "beleg"},
        {**ok, "id": "X1"},
    ]
    meldungen = "\n".join(g.pruefen(kaputt))
    for erwartet in ("X1: Status", "X2: Pfad fehlt", "X3: genutzt, aber ohne Code-Stelle", "Felder fehlen", "doppelte Nummer"):
        assert erwartet in meldungen


def test_cli_lists_groups_and_checks(capsys):
    assert g.main([]) == 0
    assert "gesamt:" in capsys.readouterr().out
    assert g.main(["--pruefen"]) == 0
    assert g.main(["--gruppe", "1"]) == 0
    assert "C22" in capsys.readouterr().out
