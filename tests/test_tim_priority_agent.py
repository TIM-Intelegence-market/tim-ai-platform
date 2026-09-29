from pathlib import Path

from scripts.tim_priority_agent import (
    PriorityAgent,
    PriorityAgentError,
    RestGitHubClient,
    classify_issue,
    render_pull_request_blockers,
)


BOT = "github-actions[bot]"


def issue(number, title, *, state="open", labels=(), body="", updated_at="2026-09-27T10:00:00Z", author="someone"):
    return {"number": number, "title": title, "state": state, "labels": [{"name": label} for label in labels], "body": body, "updated_at": updated_at, "user": {"login": author}}


class FakeGitHub:
    def __init__(self, issues, comments=None, pull_requests=None):
        self.issues = issues
        self.comments = comments or {}
        self.pull_requests = pull_requests or []
        self.created = []
        self.updated = []

    def list_issues(self, state="open"):
        return self.issues

    def list_comments(self, number):
        return self.comments.get(number, [])

    def list_open_pull_requests(self):
        return self.pull_requests

    def create_issue(self, title, body):
        self.created.append((title, body))
        return {"number": 999}

    def update_issue(self, number, body):
        self.updated.append((number, body))
        return {"number": number}


def agent(client):
    return PriorityAgent(client, "TIM Priority Board", "TIM_PRIORITY_BOARD_V1", "Europe/Berlin", 5)


def test_classification_prioritizes_active_p0_without_open_dependencies():
    candidate = issue(12, "Task Engine", labels=("status:active", "priority:p0"), body="Depends on: #11")
    result = classify_issue(candidate, candidate["body"], {12})
    assert result.status == "NEXT"


def test_classification_waits_for_open_dependency():
    candidate = issue(13, "Incident Foundation", body="Blocked by: #12")
    result = classify_issue(candidate, candidate["body"], {12, 13})
    assert result.status == "WAITING"
    assert result.dependency_numbers == (12,)


def test_archived_or_duplicate_issue_is_never_prioritized():
    candidate = issue(22, "Historical duplicate", labels=("archive", "duplicate"))
    result = classify_issue(candidate, candidate["body"], {22})
    assert result.status == "ARCHIVE"


def test_explicit_blocker_precedes_active_label():
    candidate = issue(79, "CI", labels=("status:active", "ci-blocked"), body="NEXT_ACTION=repair CI")
    result = classify_issue(candidate, candidate["body"], {79})
    assert result.status == "BLOCKED"


def test_first_run_creates_exactly_one_board_and_excludes_archived_work():
    client = FakeGitHub([issue(12, "Task Engine", labels=("status:active",)), issue(22, "Duplicate", labels=("archive", "duplicate"))])
    board_number, board = agent(client).run()
    assert board_number == 999
    assert len(client.created) == 1
    assert "#12 — Task Engine" in board
    assert "#22 — Duplicate" not in board
    assert "TIM_PRIORITY_BOARD_V1" in board


def test_second_run_updates_existing_board_instead_of_creating_another():
    board = issue(500, "TIM Priority Board", body="<!-- TIM_PRIORITY_BOARD_V1 -->", author=BOT)
    client = FakeGitHub([board, issue(12, "Task Engine", labels=("status:active",))])
    board_number, _ = agent(client).run()
    assert board_number == 500
    assert client.created == []
    assert len(client.updated) == 1


def test_ambiguous_marker_fails_closed_without_mutation():
    client = FakeGitHub([
        issue(500, "TIM Priority Board", body="<!-- TIM_PRIORITY_BOARD_V1 -->", author=BOT),
        issue(501, "TIM Priority Board", body="<!-- TIM_PRIORITY_BOARD_V1 -->", author=BOT),
    ])
    try:
        agent(client).run()
    except PriorityAgentError as error:
        assert "Mehrdeutige" in str(error)
    else:
        raise AssertionError("Expected fail-closed ambiguity error")
    assert client.created == []
    assert client.updated == []


def test_api_failure_before_rendering_never_writes_board():
    class FailingGitHub(FakeGitHub):
        def list_open_pull_requests(self):
            raise PriorityAgentError("API unavailable")

    client = FailingGitHub([issue(500, "TIM Priority Board", body="<!-- TIM_PRIORITY_BOARD_V1 -->", author=BOT), issue(12, "Task Engine")])
    try:
        agent(client).run()
    except PriorityAgentError:
        pass
    else:
        raise AssertionError("Expected API error")
    assert client.updated == []


def test_pr_check_failure_is_rendered_as_a_blocker():
    client = FakeGitHub(
        [issue(12, "Task Engine")],
        pull_requests=[{
            "number": 80,
            "title": "Server bootstrap",
            "mergeable_state": "unstable",
            "statusCheckRollup": [{"name": "codeql", "conclusion": "FAILURE"}],
        }],
    )
    _, board = agent(client).run()
    assert "PR #80 — Server bootstrap: codeql" in board


class RecordingRestClient(RestGitHubClient):
    """REST client with canned responses shaped like the real GitHub REST API."""

    def __init__(self, responses):
        super().__init__("owner/repo", "token")
        self.responses = responses
        self.paths = []

    def _request(self, path, method="GET", payload=None):
        self.paths.append(path)
        return self.responses[path]


def test_rest_check_conclusions_are_lowercase_and_still_detected():
    blockers = render_pull_request_blockers([
        {"number": 81, "title": "Lint", "statusCheckRollup": [{"name": "ruff", "conclusion": "failure"}]},
        {"number": 82, "title": "Green", "statusCheckRollup": [{"name": "tests", "conclusion": "success"}]},
    ])
    assert blockers == ["- PR #81 — Lint: ruff"]


def test_pagination_reads_every_page_beyond_the_first_hundred():
    base = "/repos/owner/repo/issues?state=all&per_page=100"
    client = RecordingRestClient({
        f"{base}&page=1": [{"number": n} for n in range(250, 150, -1)],
        f"{base}&page=2": [{"number": n} for n in range(150, 50, -1)],
        f"{base}&page=3": [{"number": n} for n in range(50, 0, -1)],
    })
    numbers = [item["number"] for item in client.list_issues("all")]
    assert len(numbers) == 250
    assert numbers[-1] == 1


def test_pagination_fails_closed_instead_of_truncating(monkeypatch):
    import scripts.tim_priority_agent as module

    monkeypatch.setattr(module, "MAX_PAGES", 2)

    class EndlessClient(RecordingRestClient):
        def _request(self, path, method="GET", payload=None):
            return [{"number": 1}] * module.PAGE_SIZE

    try:
        EndlessClient({}).list_issues("all")
    except PriorityAgentError as error:
        assert "Abbruch statt Teilergebnis" in str(error)
    else:
        raise AssertionError("Expected fail-closed pagination error")


def test_mergeable_state_is_fetched_from_single_pull_request_endpoint():
    client = RecordingRestClient({
        "/repos/owner/repo/pulls?state=open&per_page=100&page=1": [
            {"number": 80, "title": "Server bootstrap", "head": {"sha": "abc"}},
        ],
        "/repos/owner/repo/pulls/80": {"number": 80, "mergeable_state": "dirty"},
        "/repos/owner/repo/commits/abc/check-runs?per_page=100": {"check_runs": []},
    })
    pull_requests = client.list_open_pull_requests()
    assert pull_requests[0]["mergeable_state"] == "dirty"
    assert render_pull_request_blockers(pull_requests) == ["- PR #80 — Server bootstrap: Merge-Zustand: dirty"]


def test_workflow_grants_checks_read_for_check_run_api():
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/tim-priority-board.yml").read_text()
    permissions = workflow.split("permissions:", 1)[1].split("jobs:", 1)[0]
    assert "checks: read" in permissions
    assert "issues: write" in permissions
    assert "contents: write" not in permissions
    assert "pull-requests: write" not in permissions
