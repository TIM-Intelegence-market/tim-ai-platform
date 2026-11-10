"""PS5 als Rechenhost (docs/MULTI_AGENTEN_SYSTEM.md, Paket P7): ssh-Ausführung, ohne echte Verbindung."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.research_lab.workshop import runner

COMMIT = "a" * 40


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake_run(argv, **kwargs):
        seen.append(argv)
        if argv[0] == "git":
            return SimpleNamespace(returncode=0, stdout=COMMIT + "\n", stderr="")
        if argv[0] == "ssh":
            return SimpleNamespace(returncode=0, stdout=COMMIT + "\nfertig\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    return seen


def test_ps5_through_warpgate_uses_port_key_python_and_scp(calls, tmp_path):
    run = runner.ssh_executor("uzi:ps5-research@tim-core-01", "~/tim-research/code", port=2222,
                              identity="~/.ssh/tim_uzi", python="~/tim-research/.venv/bin/python", host="ps5", copy="scp")
    result = run(["-m", "src.research_lab.studies.s19", "count"], tmp_path, tmp_path / "J-0001")
    ssh, scp = calls[1], calls[2]
    assert ssh[:10] == ["ssh", "-o", "BatchMode=yes", "-o", "User=uzi:ps5-research", "-p", "2222", "-i",
                        "~/.ssh/tim_uzi", "tim-core-01"]
    script = ssh[-1]
    assert script.startswith("cd ~/tim-research/code && git rev-parse HEAD && ")
    assert f'[ "$(git rev-parse HEAD)" = {COMMIT} ] || {{ echo "commit-mismatch" >&2; exit 97; }}' in script
    assert "TIM_RESEARCH_NO_HOLDOUT=1" in script and "~/tim-research/.venv/bin/python -m src.research_lab.studies.s19 count" in script
    # The colon in the Warpgate user must not reach scp's host:path parsing.
    assert scp[:2] == ["scp", "-r"] and ["-P", "2222"] == scp[6:8] and "-o" in scp and "User=uzi:ps5-research" in scp
    assert scp[-2:] == ["tim-core-01:tim-research/code/out/J-0001/.", f"{tmp_path / 'J-0001'}/"]
    assert result.host == "ps5" and result.extra["remote_commit"] == COMMIT


def test_rsync_gets_the_same_ssh_options(calls, tmp_path):
    run = runner.ssh_executor("tim-research@tim-core-01", "/srv/lab", port=2222, identity="/k")
    run(["-m", "src.research_lab.x"], tmp_path, tmp_path / "J-0002")
    rsync = calls[2]
    assert rsync[:4] == ["rsync", "-a", "-e", "ssh -o BatchMode=yes -o User=tim-research -p 2222 -i /k"]
    assert rsync[4] == "tim-core-01:/srv/lab/out/J-0002/"
    assert calls[1][-1].startswith("cd /srv/lab && ")


def test_failed_copy_keeps_the_host_and_commit(monkeypatch, tmp_path):
    def fake_run(argv, **kwargs):
        if argv[0] == "git":
            return SimpleNamespace(returncode=0, stdout=COMMIT, stderr="")
        if argv[0] == "ssh":
            return SimpleNamespace(returncode=0, stdout=COMMIT + "\n", stderr="")
        return SimpleNamespace(returncode=23, stdout="", stderr="kein rsync")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    result = runner.ssh_executor("h", "/d", host="ps5")(["-m", "src.research_lab.x"], tmp_path, tmp_path / "J")
    assert (result.exit_code, result.host, result.extra["remote_commit"]) == (23, "ps5", COMMIT)
    assert "kein rsync" in result.stderr


def test_bad_options_are_refused():
    with pytest.raises(runner.JobError):
        runner.ssh_executor("h", "/d", copy="ftp")
    with pytest.raises(runner.JobError):
        runner.ssh_executor("h", "/d", host="mac")


def test_ps5_is_a_known_job_host(tmp_path):
    queue = runner.JobQueue(tmp_path / "jobs.jsonl")
    queue.approve("S19", by="uzi", reference="Thread 10.11.")
    job = queue.submit("S19", ["-m", "src.research_lab.studies.s19", "count"], host="ps5")
    assert queue.pending("ps5")[0]["job"] == job
