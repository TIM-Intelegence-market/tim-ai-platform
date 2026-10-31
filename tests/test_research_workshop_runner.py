"""Research workshop F4: job guards, approvals, bundles with hashes, verification."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.research_lab.workshop.runner import (JobError, JobQueue, RunResult, check_command, run_job, verify_bundle)

AT = "2026-10-31T15:00:00Z"


def fake_executor(command, workdir: Path, outdir: Path) -> RunResult:
    (outdir / "result.json").write_text(json.dumps({"command": list(command), "n": 42}, sort_keys=True))
    return RunResult(0, "fertig\n", "", host="mac")


@pytest.fixture()
def queue(tmp_path: Path) -> JobQueue:
    q = JobQueue(tmp_path / "jobs.jsonl")
    q.approve("S12", by="uzi", reference="Uzi 31.10. im Thread", at=AT)
    return q


@pytest.mark.parametrize("command, match", [
    (["scripts/other.py"], "research_lab_"),
    (["-m", "src.dashboard.app"], "src.research_lab"),
    (["scripts/research_lab_s4.py", "--use-holdout"], "Holdout"),
    (["scripts/research_lab_s4.py", "--to", "2025-01-01"], "Holdout"),
    (["scripts/research_lab_s4.py", "--commit-register"], "Registrierung"),
    ([], "leer"),
])
def test_guards_refuse(command, match) -> None:
    with pytest.raises(JobError, match=match):
        check_command(command, allow_register=False)


def test_allowed_commands_pass() -> None:
    check_command(["scripts/research_lab_s4.py", "--from", "2020-01-01", "--to", "2024-12-31"], allow_register=False)
    check_command(["-m", "src.research_lab.orderflow_ml", "export"], allow_register=False)
    check_command(["scripts/research_lab_run.py", "--commit-register"], allow_register=True)


def test_stage_one_needs_uzis_approval(tmp_path: Path) -> None:
    q = JobQueue(tmp_path / "jobs.jsonl")
    with pytest.raises(JobError, match="nicht freigegeben"):
        q.submit("S13", ["scripts/research_lab_s4.py"], at=AT)
    with pytest.raises(JobError, match="nur Uzi"):
        q.approve("S13", by="tim", reference="x")
    with pytest.raises(JobError, match="Beleg"):
        q.approve("S13", by="uzi", reference=" ")


def test_same_job_gives_same_content_hash_and_bundle_verifies(queue: JobQueue, tmp_path: Path) -> None:
    data = tmp_path / "work" / "data.csv"
    data.parent.mkdir()
    data.write_text("a,b\n1,2\n")
    first = queue.submit("S12", ["scripts/research_lab_s4.py", "--count"], inputs=["data.csv"], at=AT)
    second = queue.submit("S12", ["scripts/research_lab_s4.py", "--count"], inputs=["data.csv"], at=AT)
    a = run_job(queue, first, workdir=data.parent, bundles_dir=tmp_path / "b", executor=fake_executor)
    b = run_job(queue, second, workdir=data.parent, bundles_dir=tmp_path / "b", executor=fake_executor)
    assert a["inputs"] == {"data.csv": b["inputs"]["data.csv"]}
    assert a["content_hash"] == b["content_hash"] and a["job"] != b["job"]
    assert verify_bundle(Path(a["bundle_dir"]))["content_hash"] == a["content_hash"]
    assert queue.jobs()[first]["status"] == "done"
    with pytest.raises(JobError, match="nicht offen"):
        run_job(queue, first, workdir=data.parent, bundles_dir=tmp_path / "b", executor=fake_executor)


def test_tampered_bundle_is_refused(queue: JobQueue, tmp_path: Path) -> None:
    job = queue.submit("S12", ["scripts/research_lab_s4.py"], at=AT)
    manifest = run_job(queue, job, workdir=tmp_path, bundles_dir=tmp_path / "b", executor=fake_executor)
    bundle = Path(manifest["bundle_dir"])
    (bundle / "out" / "result.json").write_text('{"n": 43}')
    with pytest.raises(JobError, match="Ausgaben"):
        verify_bundle(bundle)


def test_tampered_manifest_and_stdout_are_refused(queue: JobQueue, tmp_path: Path) -> None:
    job = queue.submit("S12", ["scripts/research_lab_s4.py"], at=AT)
    bundle = Path(run_job(queue, job, workdir=tmp_path, bundles_dir=tmp_path / "b", executor=fake_executor)["bundle_dir"])
    (bundle / "stdout.txt").write_text("anders\n")
    with pytest.raises(JobError, match="Ausgabeprotokoll"):
        verify_bundle(bundle)
    (bundle / "stdout.txt").write_text("fertig\n")
    manifest = json.loads((bundle / "manifest.json").read_text())
    manifest["exit_code"] = 1
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(JobError, match="Manifest"):
        verify_bundle(bundle)


def test_remote_commit_mismatch_is_refused(queue: JobQueue, tmp_path: Path) -> None:
    job = queue.submit("S12", ["scripts/research_lab_s4.py"], host="server", at=AT)

    def remote(command, workdir, outdir):
        return RunResult(0, "", "", host="server", extra={"remote_commit": "deadbeef"})
    with pytest.raises(JobError, match="Commit"):
        run_job(queue, job, workdir=tmp_path, bundles_dir=tmp_path / "b", executor=remote)


def test_failed_job_is_recorded_as_failed(queue: JobQueue, tmp_path: Path) -> None:
    job = queue.submit("S12", ["scripts/research_lab_s4.py"], at=AT)
    run_job(queue, job, workdir=tmp_path, bundles_dir=tmp_path / "b",
            executor=lambda c, w, o: RunResult(2, "", "Fehler", host="mac"))
    assert queue.jobs()[job]["status"] == "failed"


def test_edited_job_list_breaks_chain(queue: JobQueue) -> None:
    queue.submit("S12", ["scripts/research_lab_s4.py"], at=AT)
    lines = queue.path.read_text().splitlines()
    lines[0] = lines[0].replace("Thread", "Chat")
    queue.path.write_text("\n".join(lines) + "\n")
    with pytest.raises(JobError, match="Zeile 1"):
        queue.events()


def test_local_executor_runs_a_real_lab_module(queue: JobQueue, tmp_path: Path) -> None:
    job = queue.submit("S12", ["-m", "src.research_lab.workshop", "charter"], at=AT)
    manifest = run_job(queue, job, workdir=Path.cwd(), bundles_dir=tmp_path / "b")
    assert manifest["exit_code"] == 0 and "forschungsbereich/1.0" in (Path(manifest["bundle_dir"]) / "stdout.txt").read_text()
