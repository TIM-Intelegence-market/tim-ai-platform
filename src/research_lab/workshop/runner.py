"""Job runner and result bundles (F4).

A job runs one approved study entry point and leaves a bundle: the code
commit, the hashes of every input and output file, the exact command and its
exit code. The same job on the same inputs gives the same ``content_hash``,
whichever host ran it; times and host stay in the manifest but outside that
hash. A bundle is only used after ``verify_bundle`` re-hashed every file.

Guards, checked before anything starts:
- stage 1: the study needs a recorded approval by Uzi;
- only lab entry points (``scripts/research_lab_*.py``, ``-m src.research_lab.*``);
- no argument naming the holdout and no date on or after 2025-01-01;
- ``--commit-register`` only if the approval allows registration.
The runner never merges, never pushes and never touches the runtime.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from src.research_lab.workshop import charter
from src.research_lab.workshop.check import HOLDOUT_START

JOBS_PATH = Path("data/research/jobs/jobs.jsonl")
BUNDLES_DIR = Path("data/research/bundles")
GENESIS = "0" * 64
SCRIPT_PATTERN = re.compile(r"^scripts/research_lab_[a-z0-9_]+\.py$")
MODULE_PATTERN = re.compile(r"^src\.research_lab\.[a-z0-9_.]+$")
DATE_PATTERN = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
HOSTS = {"mac", "server"}
NICE = 15


class JobError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _digest(previous: str, body: Mapping[str, Any]) -> str:
    return hashlib.sha256((previous + json.dumps(body, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_hashes(root: Path) -> dict[str, str]:
    if root.is_file():
        return {root.name: file_hash(root)}
    return {p.relative_to(root).as_posix(): file_hash(p) for p in sorted(root.rglob("*")) if p.is_file()}


# --- guards ---------------------------------------------------------------------------------------
def check_command(command: Sequence[str], *, allow_register: bool) -> None:
    if not command:
        raise JobError("leerer Befehl")
    if command[0] == "-m":
        if len(command) < 2 or not MODULE_PATTERN.match(command[1]):
            raise JobError(f"nur Module unter src.research_lab erlaubt, nicht {command[1:2]}")
        args = command[2:]
    else:
        if not SCRIPT_PATTERN.match(command[0]):
            raise JobError(f"nur scripts/research_lab_*.py erlaubt, nicht {command[0]!r}")
        args = command[1:]
    for arg in args:
        if "holdout" in arg.lower():
            raise JobError(f"Argument {arg!r} nennt den Holdout; öffnen nur mit Uzis ausdrücklichem Wort, nie per Auftrag")
        for year, month, day in DATE_PATTERN.findall(arg):
            try:
                when = date(int(year), int(month), int(day))
            except ValueError:
                continue
            if when >= HOLDOUT_START:
                raise JobError(f"Datum {when} in {arg!r} liegt im Holdout ab {HOLDOUT_START}")
        if arg == "--commit-register" and not allow_register:
            raise JobError("--commit-register braucht eine Freigabe mit Registrierung")


# --- job queue ------------------------------------------------------------------------------------
class JobQueue:
    """Append-only, hash-chained list of approvals and jobs (local, under data/)."""

    def __init__(self, path: Path | str = JOBS_PATH) -> None:
        self.path = Path(path)

    def events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
        previous = GENESIS
        for number, event in enumerate(events, 1):
            body = {k: v for k, v in event.items() if k != "hash"}
            if body.get("previous") != previous or event.get("hash") != _digest(previous, body):
                raise JobError(f"Hash-Kette in {self.path} bricht in Zeile {number}")
            previous = event["hash"]
        return events

    def _append(self, body: dict[str, Any]) -> dict[str, Any]:
        events = self.events()
        previous = events[-1]["hash"] if events else GENESIS
        body = {**body, "charter": charter.CHARTER_VERSION, "previous": previous}
        event = {**body, "hash": _digest(previous, body)}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n")
        return event

    def approve(self, study_id: str, *, by: str, reference: str, register: bool = False, at: str | None = None) -> None:
        if by != "uzi":
            raise JobError("Studien gibt in Stufe 1 nur Uzi frei")
        if not reference.strip():
            raise JobError("Freigabe braucht einen Beleg (z. B. Datum und Nachricht im Thread)")
        self._append({"kind": "approval", "study": study_id, "by": by, "reference": reference.strip(),
                      "register": register, "at": at or _now()})

    def approval(self, study_id: str) -> dict[str, Any] | None:
        found = [e for e in self.events() if e["kind"] == "approval" and e["study"] == study_id]
        return found[-1] if found else None

    def submit(self, study_id: str, command: Sequence[str], *, host: str = "mac", inputs: Iterable[str] = (),
               at: str | None = None) -> str:
        if host not in HOSTS:
            raise JobError(f"unbekannter Rechner {host!r}")
        approval = self.approval(study_id)
        if charter.STAGE <= 1 and approval is None:
            raise JobError(f"{study_id} ist nicht freigegeben (Stufe {charter.STAGE}: Uzis Freigabe je Studie)")
        check_command(command, allow_register=bool(approval and approval.get("register")))
        jobs = [e for e in self.events() if e["kind"] == "job"]
        job_id = f"J-{len(jobs) + 1:04d}"
        self._append({"kind": "job", "job": job_id, "study": study_id, "command": list(command), "host": host,
                      "inputs": sorted(inputs), "at": at or _now()})
        return job_id

    def finish(self, job_id: str, bundle: Mapping[str, Any], at: str | None = None) -> None:
        self._append({"kind": "result", "job": job_id, "content_hash": bundle["content_hash"],
                      "exit_code": bundle["exit_code"], "bundle": bundle["bundle_dir"], "at": at or _now()})

    def jobs(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for event in self.events():
            if event["kind"] == "job":
                result[event["job"]] = {**event, "status": "queued"}
            elif event["kind"] == "result":
                result[event["job"]].update(status="done" if event["exit_code"] == 0 else "failed",
                                            content_hash=event["content_hash"], bundle=event["bundle"])
        return result

    def pending(self, host: str | None = None) -> list[dict[str, Any]]:
        return [j for j in self.jobs().values() if j["status"] == "queued" and (host is None or j["host"] == host)]


# --- execution ------------------------------------------------------------------------------------
@dataclass
class RunResult:
    exit_code: int
    stdout: str
    stderr: str
    host: str
    extra: dict[str, Any] = field(default_factory=dict)


Executor = Callable[[Sequence[str], Path, Path], RunResult]


def local_executor(command: Sequence[str], workdir: Path, outdir: Path) -> RunResult:
    """Runs on this machine, niced, with TIM_RESEARCH_OUT pointing at the bundle's output folder."""
    env = {**os.environ, "TIM_RESEARCH_OUT": str(outdir), "TIM_RESEARCH_NO_HOLDOUT": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    argv = ["nice", "-n", str(NICE), sys.executable, *command]
    done = subprocess.run(argv, cwd=workdir, env=env, capture_output=True, text=True)
    return RunResult(done.returncode, done.stdout, done.stderr, host="mac")


def ssh_executor(target: str, remote_dir: str) -> Executor:
    """Runs on the compute host over ssh. The Mac opens the connection; the host never reaches the Mac.

    The remote checkout must be at the same commit; the runner checks it before starting.
    """
    def run(command: Sequence[str], workdir: Path, outdir: Path) -> RunResult:
        remote_out = f"{remote_dir}/out/{outdir.name}"
        script = (f"cd {shlex.quote(remote_dir)} && git rev-parse HEAD && mkdir -p {shlex.quote(remote_out)} && "
                  f"TIM_RESEARCH_OUT={shlex.quote(remote_out)} TIM_RESEARCH_NO_HOLDOUT=1 nice -n {NICE} "
                  f"python3 {' '.join(shlex.quote(c) for c in command)}")
        done = subprocess.run(["ssh", "-o", "BatchMode=yes", target, script], capture_output=True, text=True)
        remote_commit = done.stdout.splitlines()[0].strip() if done.stdout else ""
        if done.returncode == 0:
            pull = subprocess.run(["rsync", "-a", f"{target}:{remote_out}/", f"{outdir}/"], capture_output=True, text=True)
            if pull.returncode != 0:
                return RunResult(pull.returncode, done.stdout, done.stderr + pull.stderr, host="server")
        return RunResult(done.returncode, done.stdout, done.stderr, host="server", extra={"remote_commit": remote_commit})
    return run


def git_commit(workdir: Path) -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=workdir, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _content(manifest: Mapping[str, Any]) -> dict[str, Any]:
    # Without job id, host and times: the same job on the same inputs has the same content hash anywhere.
    keys = ("study", "command", "commit", "inputs", "outputs", "exit_code", "stdout_hash")
    return {k: manifest[k] for k in keys}


def run_job(queue: JobQueue, job_id: str, *, workdir: Path = Path("."), bundles_dir: Path = BUNDLES_DIR,
            executor: Executor | None = None) -> dict[str, Any]:
    jobs = queue.jobs()
    if job_id not in jobs or jobs[job_id]["status"] != "queued":
        raise JobError(f"{job_id} ist nicht offen")
    job = jobs[job_id]
    approval = queue.approval(job["study"])
    check_command(job["command"], allow_register=bool(approval and approval.get("register")))
    commit = git_commit(workdir)
    bundle_dir = bundles_dir / job_id
    outdir = bundle_dir / "out"
    if bundle_dir.exists():
        raise JobError(f"{bundle_dir} gibt es schon")
    outdir.mkdir(parents=True)
    inputs: dict[str, str] = {}
    for item in job["inputs"]:
        path = workdir / item
        if not path.exists():
            raise JobError(f"Eingabe {item} fehlt")
        inputs.update({f"{item}/{k}" if path.is_dir() else item: v for k, v in tree_hashes(path).items()})
    started = _now()
    result = (executor or local_executor)(job["command"], workdir, outdir)
    if result.extra.get("remote_commit") and result.extra["remote_commit"] != commit:
        raise JobError(f"Rechner hat Commit {result.extra['remote_commit']}, erwartet {commit}")
    (bundle_dir / "stdout.txt").write_text(result.stdout, encoding="utf-8")
    (bundle_dir / "stderr.txt").write_text(result.stderr, encoding="utf-8")
    manifest = {
        "schema": "tim_research_bundle/1", "job": job_id, "study": job["study"], "command": job["command"],
        "commit": commit, "inputs": inputs, "outputs": tree_hashes(outdir), "exit_code": result.exit_code,
        "stdout_hash": hashlib.sha256(result.stdout.encode()).hexdigest(),
        "host": result.host, "started_at": started, "finished_at": _now(), "charter": charter.CHARTER_VERSION,
    }
    manifest["content_hash"] = hashlib.sha256(json.dumps(_content(manifest), sort_keys=True).encode()).hexdigest()
    manifest["bundle_dir"] = bundle_dir.as_posix()
    (bundle_dir / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
                                              encoding="utf-8")
    queue.finish(job_id, manifest)
    return manifest


def verify_bundle(bundle_dir: Path) -> dict[str, Any]:
    """Re-hashes every output and the stdout; raises on any mismatch. Returns the manifest."""
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    outputs = tree_hashes(bundle_dir / "out")
    if outputs != manifest["outputs"]:
        changed = sorted(set(outputs.items()) ^ set(manifest["outputs"].items()))
        raise JobError(f"Bündel {bundle_dir.name}: Ausgaben stimmen nicht mit dem Manifest überein ({changed[:3]})")
    stdout = (bundle_dir / "stdout.txt").read_text(encoding="utf-8")
    if hashlib.sha256(stdout.encode()).hexdigest() != manifest["stdout_hash"]:
        raise JobError(f"Bündel {bundle_dir.name}: Ausgabeprotokoll wurde verändert")
    expected = hashlib.sha256(json.dumps(_content(manifest), sort_keys=True).encode()).hexdigest()
    if expected != manifest["content_hash"]:
        raise JobError(f"Bündel {bundle_dir.name}: Manifest wurde verändert")
    return manifest
