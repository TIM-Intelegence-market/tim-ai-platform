from datetime import date

import pytest

from src.obsidian_vault.draft_writer import Draft, main, safe_title, write_draft
from src.obsidian_vault.lint import lint_vault

DAY = date(2026, 10, 1)
PR = "https://github.com/uezeyiraydin-cell/tim-ai-platform/pull/118"


def test_draft_lands_in_inbox_and_passes_lint(clean_vault):
    path, text = write_draft(clean_vault, Draft("decision", "Drawdown-Grenze 20 %",
                                                 "Begründung.", PR, DAY))
    assert path.parent.name == "00 Inbox"
    assert "review: pending" in text and f"source: {PR}" in text
    assert lint_vault(clean_vault, today=DAY) == []


def test_never_overwrites(clean_vault):
    write_draft(clean_vault, Draft("daily", "2026-10-01 Tagesstatus", "x", today=DAY))
    with pytest.raises(FileExistsError):
        write_draft(clean_vault, Draft("daily", "2026-10-01 Tagesstatus", "y", today=DAY))


@pytest.mark.parametrize("title", ["../../01 Home/TIM Home", "/etc/passwd", "..", "a/../../b"])
def test_title_cannot_escape_inbox(clean_vault, title):
    try:
        path, _ = write_draft(clean_vault, Draft("daily", title, "x", today=DAY))
    except ValueError:
        return
    assert path.parent == (clean_vault / "TIM" / "00 Inbox").resolve()
    assert (clean_vault / "TIM" / "01 Home" / "TIM Home.md").read_text().startswith("---\ntype: home")


def test_rules_on_source_body_and_kind(clean_vault):
    with pytest.raises(ValueError, match="Quelle"):
        write_draft(clean_vault, Draft("decision", "Ohne Quelle", "x", today=DAY))
    with pytest.raises(ValueError, match="http"):
        write_draft(clean_vault, Draft("research", "R5", "x", "nur text", DAY))
    with pytest.raises(ValueError, match="Frontmatter"):
        write_draft(clean_vault, Draft("daily", "T", "---\ntype: home\n---", today=DAY))
    with pytest.raises(ValueError, match="unbekannte"):
        write_draft(clean_vault, Draft("mission", "M", "x", PR, DAY))


def test_safe_title():
    assert safe_title(" R4: Ergebnis [kein Edge] ") == "R4 Ergebnis kein Edge"
    with pytest.raises(ValueError):
        safe_title("///")


def test_dry_run_writes_nothing(clean_vault, capsys):
    before = sorted(p for p in clean_vault.rglob("*"))
    assert main(["daily", "--vault", str(clean_vault), "--date", "2026-10-01", "--dry-run"]) == 0
    assert "# 2026-10-01 Tagesstatus" in capsys.readouterr().out
    assert sorted(p for p in clean_vault.rglob("*")) == before


def test_missing_vault_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        write_draft(tmp_path / "fehlt", Draft("daily", "T", "x", today=DAY))
