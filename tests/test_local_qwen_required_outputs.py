from __future__ import annotations

from pathlib import Path

import pytest

from scripts import run_local_qwen_developer as developer


IMPLEMENTATION = "src/local_first/github_feeder.py"
TEST = "tests/test_local_first_github_feeder.py"


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "src/local_first").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    return tmp_path


def test_missing_allowlisted_files_become_required_outputs(tmp_path):
    repo = _repo(tmp_path)
    contract = developer._build_contract(
        repo,
        {"allowed_paths": [IMPLEMENTATION, TEST]},
    )

    assert contract["required_outputs"] == [IMPLEMENTATION, TEST]
    assert contract["tests"] == [TEST]


def test_test_only_proposal_cannot_reach_executor_when_implementation_is_missing(tmp_path):
    repo = _repo(tmp_path)
    contract = developer._build_contract(
        repo,
        {"allowed_paths": [IMPLEMENTATION, TEST]},
    )
    proposal = {
        "patches": [
            {"path": TEST, "content": "def test_placeholder():\n    assert True\n"},
        ]
    }

    with pytest.raises(developer.ProposalError, match="include required output patches: src/local_first/github_feeder.py"):
        developer._bind_proposal(proposal, contract, "tim-test")


def test_complete_atomic_proposal_binds_both_missing_outputs(tmp_path):
    repo = _repo(tmp_path)
    contract = developer._build_contract(
        repo,
        {"allowed_paths": [IMPLEMENTATION, TEST]},
    )
    proposal = {
        "patches": [
            {"path": IMPLEMENTATION, "content": "VALUE = 1\n"},
            {"path": TEST, "content": "def test_placeholder():\n    assert True\n"},
        ]
    }

    bound = developer._bind_proposal(proposal, contract, "tim-test")

    assert [patch["path"] for patch in bound["patches"]] == [IMPLEMENTATION, TEST]
    assert all(patch["expected_sha256"] == "MISSING" for patch in bound["patches"])
    assert bound["tests"] == [TEST]


def test_explicit_required_output_must_be_allowlisted(tmp_path):
    repo = _repo(tmp_path)

    with pytest.raises(developer.ContractError, match="required output is not allowlisted"):
        developer._build_contract(
            repo,
            {
                "allowed_paths": [IMPLEMENTATION, TEST],
                "required_outputs": ["src/local_first/not_allowed.py"],
            },
        )


def test_invalid_python_is_repairable_before_executor(tmp_path):
    repo = _repo(tmp_path)
    contract = developer._build_contract(
        repo,
        {"allowed_paths": [IMPLEMENTATION, TEST]},
    )
    proposal = {
        "patches": [
            {"path": IMPLEMENTATION, "content": "VALUE = {\n"},
            {"path": TEST, "content": "def test_placeholder():\n    assert True\n"},
        ]
    }

    with pytest.raises(
        developer.ProposalError,
        match=r"python syntax error: src/local_first/github_feeder\.py:1:",
    ):
        developer._bind_proposal(proposal, contract, "tim-test")
