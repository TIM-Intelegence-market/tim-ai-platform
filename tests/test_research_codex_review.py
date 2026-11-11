from src.research_lab.workshop import codex_review as review

DRAFT = "docs/research_lab/studien/S21_TRADE_REFLEXION_PRAEREGISTRIERUNG_ENTWURF.md"
GREEN = {"test": "SUCCESS", "PR gate": "SUCCESS", "DCO sign-off": "SUCCESS"}


def test_only_exact_ok_first_line_approves():
    assert review.parse_verdict("OK\nkeine Befunde") == ("OK", "keine Befunde")
    assert review.parse_verdict("**OK**") == ("OK", "")
    assert review.parse_verdict("PROBLEM\nStoppregel fehlt")[0] == "PROBLEM"
    assert review.parse_verdict("Sieht OK aus")[0] == "PROBLEM"
    assert review.parse_verdict("")[0] == "PROBLEM"


def test_ask_fails_closed_and_passes_prompt(monkeypatch):
    monkeypatch.setenv("TIM_CODEX_MODEL", "gpt-5.6-luna")
    seen = {}

    def runner(argv, prompt, env, cwd, timeout):
        seen["prompt"], seen["argv"] = prompt, argv
        return 0, "OK\n"
    assert review.ask("draft", "Entwurf-Text", runner=runner) == ("OK", "")
    assert "Entwurf-Text" in seen["prompt"] and "read-only" in seen["argv"]
    assert review.ask("draft", "x", runner=lambda *a: (1, "OK"))[0] == "PROBLEM"
    monkeypatch.setenv("TIM_CODEX_MODEL", "bad model;rm")
    assert review.ask("result", "x", runner=runner)[0] == "PROBLEM"


def test_draft_mergeable_needs_single_draft_green_checks_and_ok():
    assert review.draft_mergeable([DRAFT], GREEN, "OK")
    assert not review.draft_mergeable([DRAFT], GREEN, "PROBLEM")
    assert not review.draft_mergeable([DRAFT, "src/x.py"], GREEN, "OK")
    assert not review.draft_mergeable(["src/research_lab/x.py"], GREEN, "OK")
    assert not review.draft_mergeable([DRAFT], {**GREEN, "test": "FAILURE"}, "OK")
    assert not review.draft_mergeable([DRAFT], {"PR gate": "SUCCESS"}, "OK")


def test_draft_prompt_treats_journal_trades_as_prospective():
    assert "Papier-Plan-Journalen sind" in review.DRAFT_PROMPT and "kein Holdout" in review.DRAFT_PROMPT
    assert "Bewertungsregel vor dem Einfrieren" in review.DRAFT_PROMPT
