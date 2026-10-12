from __future__ import annotations

import json
from unittest.mock import Mock, patch

import pytest

from src.analysis.repo_language_reporter import (
    build_language_report,
    fetch_repo_languages,
    render_markdown,
)


def test_private_repo_uses_existing_gh_login_without_exposing_token() -> None:
    response = Mock()
    response.read.return_value = json.dumps({"Python": 75, "Shell": 25}).encode()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    auth = Mock(returncode=0, stdout="private-token\n")

    with patch.dict("os.environ", {}, clear=True), patch(
        "subprocess.run", return_value=auth
    ) as run, patch("urllib.request.urlopen", return_value=response) as open_url:
        languages = fetch_repo_languages("owner", "repo")

    run.assert_called_once_with(
        ["gh", "auth", "token"], capture_output=True, text=True, check=False
    )
    assert open_url.call_args.args[0].get_header("Authorization") == "Bearer private-token"
    assert languages == {"Python": 75, "Shell": 25}


def test_report_sorts_and_renders_percentages() -> None:
    report = build_language_report("owner", "repo", {"Shell": 25, "Python": 75})
    assert report["total_bytes"] == 100
    assert [entry["language"] for entry in report["languages"]] == ["Python", "Shell"]
    assert "| Python | 75 | 75.00% |" in render_markdown(report)


@pytest.mark.parametrize("owner,repo", [("bad/name", "repo"), ("owner", "../repo")])
def test_rejects_invalid_repo_components(owner: str, repo: str) -> None:
    with pytest.raises(ValueError, match="repository name components"):
        fetch_repo_languages(owner, repo)
