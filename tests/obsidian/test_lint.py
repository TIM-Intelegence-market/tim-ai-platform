from datetime import date
from pathlib import Path

from src.obsidian_vault.lint import lint_vault, main
from tests.obsidian.conftest import note

TODAY = date(2026, 10, 1)


def codes(findings, level="error"):
    return sorted((f.code, f.path.split("/")[-1]) for f in findings if f.level == level)


def write(vault: Path, rel: str, text: str) -> None:
    path = vault / "TIM" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_clean_vault_has_no_findings(clean_vault):
    assert lint_vault(clean_vault, today=TODAY) == []
    assert main(["--vault", str(clean_vault), "--today", "2026-10-01"]) == 0


def test_schema_violations_are_errors(clean_vault):
    write(clean_vault, "30 Missionen/Kein Frontmatter.md", "# nur Text\n")
    write(clean_vault, "30 Missionen/Falscher Status.md", note("mission", "completed"))
    write(clean_vault, "30 Missionen/Falscher Typ.md", note("navigation"))
    write(clean_vault, "30 Missionen/Falscher Ordner.md", note("tool"))
    write(clean_vault, "30 Missionen/Ohne Datum.md", "---\ntype: gate\nstatus: done\n---\n")
    write(clean_vault, "30 Missionen/Kaputtes Datum.md", note("gate", updated="gestern"))
    write(clean_vault, "95 Archiv/Nicht archiviert.md", note("system", "active"))
    write(clean_vault, "00 Inbox/Ohne Review.md", note("decision", "planned"))
    write(clean_vault, "40 Architecture/Alt.md", note("architecture"))
    write(clean_vault, "Lose Notiz.md", note("home"))
    found = codes(lint_vault(clean_vault, today=TODAY))
    assert found == sorted([
        ("no-frontmatter", "Kein Frontmatter.md"),
        ("unknown-status", "Falscher Status.md"),
        ("unknown-type", "Falscher Typ.md"),
        ("type-folder-mismatch", "Falscher Ordner.md"),
        ("missing-field", "Ohne Datum.md"),
        ("bad-date", "Kaputtes Datum.md"),
        ("status-folder-mismatch", "Nicht archiviert.md"),
        ("inbox-not-pending", "Ohne Review.md"),
        ("unknown-folder", "40 Architecture"),
        ("note-outside-folder", "Lose Notiz.md"),
    ])
    assert main(["--vault", str(clean_vault), "--today", "2026-10-01"]) == 1


def test_broken_and_wrapped_links(clean_vault):
    write(clean_vault, "70 Entscheidungen/Log.md",
          note("moc", body="[[LONG History\nExtension Execution]] und [[Neuer Link]] "
                            "und [[Demo Gate]] und [[TIM/30 Missionen/Demo Mission]] "
                            "und ![[bild.png]]"))
    (clean_vault / "TIM" / "70 Entscheidungen" / "bild.png").write_bytes(b"x")
    found = lint_vault(clean_vault, today=TODAY)
    assert codes(found) == [("broken-link", "Log.md"), ("wrapped-link", "Log.md")]
    assert "Neuer Link" in next(f.message for f in found if f.code == "broken-link")


def test_links_in_code_are_ignored_and_templates_skip_placeholders(clean_vault):
    # conftest already has [[nur im Code]] in a fence and [[{{title}}]] in a template
    assert codes(lint_vault(clean_vault, today=TODAY)) == []


def test_stale_active_note_is_only_a_warning(clean_vault):
    write(clean_vault, "40 Systeme/Alt.md", note("system", updated="2026-07-01"))
    findings = lint_vault(clean_vault, today=TODAY)
    assert codes(findings) == []
    assert codes(findings, "warning") == [("stale", "Alt.md")]


def test_missing_content_root(tmp_path):
    findings = lint_vault(tmp_path, today=TODAY)
    assert [f.code for f in findings] == ["no-content-root"]


def test_crlf_frontmatter_is_read(clean_vault):
    write(clean_vault, "40 Systeme/Windows.md", note("system").replace("\n", "\r\n"))
    assert codes(lint_vault(clean_vault, today=TODAY)) == []


def test_json_output(clean_vault, capsys):
    import json
    write(clean_vault, "30 Missionen/X.md", note("mission", "completed"))
    assert main(["--vault", str(clean_vault), "--json", "--today", "2026-10-01"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["errors"] == 1 and payload["findings"][0]["code"] == "unknown-status"
