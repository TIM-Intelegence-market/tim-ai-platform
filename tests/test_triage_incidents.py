"""P4: code incidents of the reporter app reach triage, nothing else of the app does."""
from src.local_first import issue_triage

BOT = "tim-reporter-test[bot]"


def _issue(number, labels, author=BOT):
    return {"number": number, "state": "open", "title": "Vorfall", "body": "x",
            "author": {"login": author}, "labels": [{"name": n} for n in labels]}


def _ledger(tmp_path):
    return issue_triage.IssueLedger(tmp_path / "ledger.json")


def test_code_incident_is_candidate(tmp_path):
    issues = [_issue(5, ["incident", "source:tim-checkup", "incident:code"])]
    assert [i["number"] for i in issue_triage.triage_candidates(issues, _ledger(tmp_path), reporters={BOT})] == [5]


def test_other_incidents_never_candidates(tmp_path):
    issues = [
        _issue(1, ["incident"]),                                   # no verified diagnosis
        _issue(2, ["incident", "incident:code", "incident:safety"]),
        _issue(3, ["incident", "incident:code", "incident:ops"]),
        _issue(4, ["incident", "incident:code", "selftest"]),
        _issue(6, ["incident", "incident:code", "checkup:pause-qwen"]),
        _issue(7, ["incident:code"]),                              # not an incident issue
        _issue(8, ["incident", "incident:code"], author="someone-else[bot]"),
    ]
    assert issue_triage.triage_candidates(issues, _ledger(tmp_path), reporters={BOT}) == []


def test_off_without_configured_reporter(tmp_path, monkeypatch):
    monkeypatch.delenv("TIM_TRIAGE_INCIDENT_AUTHORS", raising=False)
    issues = [_issue(5, ["incident", "incident:code"])]
    assert issue_triage.triage_candidates(issues, _ledger(tmp_path)) == []


def test_reporter_env_only_bot_logins(monkeypatch):
    monkeypatch.setenv("TIM_TRIAGE_INCIDENT_AUTHORS", f"{BOT.upper()}, uezeyiraydin-cell ,")
    assert issue_triage.incident_authors() == {BOT}


def test_gh_app_author_shape(tmp_path):
    issue = _issue(9, ["incident", "incident:code"])
    issue["author"] = {"login": "app/tim-reporter-test", "is_bot": True}
    assert [i["number"] for i in issue_triage.triage_candidates([issue], _ledger(tmp_path), reporters={BOT})] == [9]
    issue["author"] = {"login": "app/tim-reporter-test", "is_bot": False}
    assert issue_triage.triage_candidates([issue], _ledger(tmp_path), reporters={BOT}) == []
