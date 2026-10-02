import json
from datetime import date

from src.obsidian_vault.lint import lint_vault
from src.obsidian_vault.pr_drafts import main, parse_prs, run

DAY = date(2026, 10, 2)
BASE = "https://github.com/uezeyiraydin-cell/tim-ai-platform/pull/"


def payload(*items):
    return json.dumps([{"number": n, "title": t, "url": BASE + str(n), "mergedAt": m}
                       for n, t, m in items])


def test_parse_keeps_only_merged_github_prs():
    raw = json.loads(payload((140, "Research Case Explorer", "2026-10-02T08:00:00Z"),
                             (141, "Offen", None)))
    raw.append({"number": 9, "title": "fremd", "url": "https://evil.example/pull/9",
                "mergedAt": "2026-10-02T00:00:00Z"})
    prs = parse_prs(json.dumps(raw))
    assert [(p.number, p.merged_on) for p in prs] == [(140, "2026-10-02")]


def test_writes_inbox_drafts_that_pass_lint(clean_vault):
    prs = parse_prs(payload((140, "Research Case Explorer: Case Builder (#3)", "2026-10-02T08:00:00Z")))
    report = run(clean_vault, prs, today=DAY)
    assert len(report["written"]) == 1
    note = (clean_vault / "TIM" / "00 Inbox" / "PR 140 Research Case Explorer Case Builder.md")
    text = note.read_text(encoding="utf-8")
    assert "type: report" in text and "review: pending" in text and f"source: {BASE}140" in text
    assert lint_vault(clean_vault, today=DAY) == []


def test_idempotent_and_skips_urls_already_in_vault(clean_vault):
    # https://github.com/x/y/pull/118 is already the source of a fixture note
    known = "https://github.com/x/y/pull/118"
    raw = json.loads(payload((140, "Case Explorer", "2026-10-02T00:00:00Z")))
    raw.append({"number": 118, "title": "Drawdown", "url": known,
                "mergedAt": "2026-10-01T00:00:00Z"})
    prs = parse_prs(json.dumps(raw))
    first = run(clean_vault, prs, today=DAY)
    second = run(clean_vault, prs, today=DAY)
    assert len(first["written"]) == 1 and first["skipped_known"] == [known]
    assert second["written"] == [] and len(second["skipped_known"]) == 2


def test_since_and_dry_run(clean_vault, capsys, tmp_path):
    source = tmp_path / "prs.json"
    source.write_text(payload((130, "Alt", "2026-09-30T00:00:00Z"),
                              (140, "Neu", "2026-10-02T00:00:00Z")))
    assert main(["--prs-json", str(source), "--since", "2026-10-01", "--dry-run",
                 "--vault", str(clean_vault), "--date", "2026-10-02"]) == 0
    out = capsys.readouterr().out
    assert '"written": 1' in out and '"skipped_old": 1' in out
    assert not (clean_vault / "TIM" / "00 Inbox" / "PR 140 Neu.md").exists()


def test_existing_inbox_title_is_skipped_not_overwritten(clean_vault):
    inbox = clean_vault / "TIM" / "00 Inbox"
    (inbox / "PR 150 Gleich.md").write_text("eigene Notiz", encoding="utf-8")
    report = run(clean_vault, parse_prs(payload((150, "Gleich", "2026-10-02T00:00:00Z"))),
                 today=DAY)
    assert report["skipped_exists"] == [BASE + "150"] and report["written"] == []
    assert (inbox / "PR 150 Gleich.md").read_text(encoding="utf-8") == "eigene Notiz"
