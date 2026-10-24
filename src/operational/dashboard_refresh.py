"""Keep the dashboards on the Mac mini on the current platform-main (OBSERVE only).

One run (launchd every 10 minutes, see scripts/dashboard_refresh.py):

1. ``git fetch`` platform-main in the live checkout (~/TIM-live).
2. Decide with :func:`decide` whether the new commit may go live: CI job ``test`` green on
   exactly that commit, fast-forward only, no running CI test job or DB backup, no active
   qualification campaign, at most one runtime restart per interval, and while a registered
   study runs only display-safe changes (policy ``ops/dashboard_refresh/policy.json``).
3. Deploy: detached checkout, ``scripts/record_deployment.py`` with the CI result,
   ``scripts/timctl restart`` and a check that a new runtime process answers. Any failure rolls
   back to the previous commit and blocks that commit for further attempts.
4. Rebuild the Mac worker dashboard (Rust) only when its source tree changed; the LaunchAgent
   plist is never rewritten, only the binary is swapped and the agent restarted.
5. Probe every dashboard and write ``data/operational/dashboard_refresh.json`` for the
   Control Center.

Nothing here trades, touches credentials or writes launchd plists. A pause file
(``~/Library/Application Support/TIM/dashboard-refresh/PAUSE``) stops all changes.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

SCHEMA_VERSION = "1.0.0"
HISTORY_LIMIT = 500

REASON_TEXT = {
    "paused": "Pausiert (PAUSE-Datei vorhanden).",
    "fetch_failed": "platform-main konnte nicht geholt werden.",
    "campaign_active": "Qualifizierungskampagne läuft: jede Code-Änderung würde sie beenden.",
    "up_to_date": "Läuft auf dem aktuellen platform-main.",
    "not_fast_forward": "Neuer Stand ist kein Nachfolger des laufenden Commits.",
    "previous_attempt_failed": "Dieser Stand ist beim letzten Versuch gescheitert und wurde zurückgerollt.",
    "ci_pending": "CI-Test auf dem neuen Stand läuft noch oder fehlt.",
    "ci_failed": "CI-Test auf dem neuen Stand ist nicht grün.",
    "study_protected_paths": "Studie läuft: neuer Stand ändert mehr als die Anzeige.",
    "local_changes": "Lokale Änderungen in ~/TIM-live.",
    "busy": "CI-Testjob oder Backup läuft gerade.",
    "restart_interval": "Letzter Neustart ist zu kurz her.",
    "deploy": "Neuer Stand wird eingespielt.",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


@dataclass(frozen=True, slots=True)
class Decision:
    action: str  # UP_TO_DATE | HOLD | WAIT | DEPLOY
    reason: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "reason": self.reason, "text": REASON_TEXT.get(self.reason, self.reason),
                "details": self.details}


def load_policy(path: Path) -> dict[str, Any]:
    policy = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(policy, dict) or policy.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported dashboard refresh policy: {path}")
    return policy


def is_display_safe(path: str, study: dict[str, Any]) -> bool:
    if path in study.get("display_safe_files", []):
        return True
    if any(path.startswith(prefix) for prefix in study.get("display_safe_prefixes", [])):
        return True
    return any(path.endswith(suffix) for suffix in study.get("display_safe_suffixes", []))


def active_studies(policy: dict[str, Any], now: datetime, exists: Callable[[str], bool]) -> list[dict[str, Any]]:
    """Studies that started and have no end marker in the live checkout or the target commit."""
    active = []
    for study in policy.get("studies", []):
        start = parse_time(study.get("active_from_utc"))
        if start is None or now < start:
            continue
        marker = study.get("ended_marker")
        if marker and exists(marker):
            continue
        active.append(study)
    return active


def study_blockers(studies: Iterable[dict[str, Any]], changed_files: Iterable[str]) -> dict[str, list[str]]:
    """Per active study, the changed files that are not display-safe (empty dict = nothing blocks)."""
    changed = sorted(set(changed_files))
    blockers = {}
    for study in studies:
        blocked = [path for path in changed if not is_display_safe(path, study)]
        if blocked:
            blockers[study["id"]] = blocked
    return blockers


def decide(
    *,
    deployed: str,
    target: str | None,
    is_fast_forward: bool,
    ci: dict[str, Any] | None,
    busy: list[str],
    dirty: list[str],
    campaign_active: bool,
    last_restart_at: datetime | None,
    now: datetime,
    min_minutes_between_restarts: float,
    blockers: dict[str, list[str]],
    failed_targets: Iterable[str],
    paused: bool,
) -> Decision:
    """Pure decision; the order puts the hard stops (pause, campaign) first."""
    if paused:
        return Decision("HOLD", "paused")
    if target is None:
        return Decision("HOLD", "fetch_failed")
    if campaign_active:
        return Decision("HOLD", "campaign_active", {"target": target})
    if target == deployed:
        return Decision("UP_TO_DATE", "up_to_date", {"commit": deployed})
    if not is_fast_forward:
        return Decision("HOLD", "not_fast_forward", {"deployed": deployed, "target": target})
    if target in set(failed_targets):
        return Decision("HOLD", "previous_attempt_failed", {"target": target})
    conclusion = (ci or {}).get("conclusion")
    if ci is None or ci.get("status") != "completed":
        return Decision("WAIT", "ci_pending", {"target": target})
    if conclusion != "success":
        return Decision("HOLD", "ci_failed", {"target": target, "conclusion": conclusion, "url": ci.get("url")})
    if blockers:
        return Decision("HOLD", "study_protected_paths", {"target": target, "blocked_files": blockers})
    if dirty:
        return Decision("HOLD", "local_changes", {"files": dirty})
    if busy:
        return Decision("WAIT", "busy", {"busy": busy})
    if last_restart_at is not None and now - last_restart_at < timedelta(minutes=min_minutes_between_restarts):
        return Decision("WAIT", "restart_interval", {
            "next_possible_at_utc": iso(last_restart_at + timedelta(minutes=min_minutes_between_restarts))})
    return Decision("DEPLOY", "deploy", {"from": deployed, "to": target})


def pytest_counts(log: str) -> dict[str, int]:
    """Counts from the last pytest summary line of a CI log ("6114 passed, 49 skipped in 1900s")."""
    summary = None
    for line in log.splitlines():
        if re.search(r"\b\d+ (passed|failed)\b.* in [\d.]+s", line):
            summary = line
    if summary is None:
        return {}
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    for number, word in re.findall(r"(\d+) (passed|failed|skipped|errors?)\b", summary):
        key = "failed" if word.startswith("error") else word
        counts[key] += int(number)
    return counts


def pick_check_run(payload: dict[str, Any], name: str) -> dict[str, Any] | None:
    runs = [run for run in payload.get("check_runs", []) if run.get("name") == name]
    if not runs:
        return None
    run = max(runs, key=lambda item: item.get("started_at") or "")
    return {
        "id": run.get("id"),
        "status": run.get("status"),
        "conclusion": run.get("conclusion"),
        "completed_at_utc": run.get("completed_at"),
        "url": run.get("html_url") or "",
    }


def parse_porcelain(output: str, generated: Iterable[str]) -> list[str]:
    allowed = set(generated)
    dirty = []
    for line in output.splitlines():
        path = line[3:].strip()
        if path and path not in allowed:
            dirty.append(path)
    return dirty


def busy_processes(ps_output: str, patterns: dict[str, str]) -> list[str]:
    found = []
    for name, pattern in patterns.items():
        expression = re.compile(pattern)
        if any(expression.search(line) for line in ps_output.splitlines() if "dashboard_refresh" not in line):
            found.append(name)
    return found


def launchd_pid(print_output: str) -> int | None:
    match = re.search(r"^\s*pid = (\d+)", print_output, re.MULTILINE)
    return int(match.group(1)) if match else None


def http_probe(url: str, timeout: float) -> dict[str, Any]:
    started = time.monotonic()
    try:
        with urlopen(url, timeout=timeout) as response:
            response.read(4 * 1024 * 1024)
            code = response.status
    except HTTPError as exc:
        code = exc.code
    except (URLError, OSError, ValueError) as exc:
        return {"url": url, "ok": False, "error": type(exc).__name__,
                "seconds": round(time.monotonic() - started, 2)}
    return {"url": url, "ok": code == 200, "http_status": code, "seconds": round(time.monotonic() - started, 2)}


Runner = Callable[..., subprocess.CompletedProcess]


def default_runner(command: list[str], *, cwd: Path | None = None, timeout: float = 120,
                   env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(command, cwd=cwd, timeout=timeout, env=env, check=False,
                              capture_output=True, text=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(command, 124, "", f"{type(exc).__name__}: {exc}")


class DashboardRefresh:
    """IO side: reads git, gh, ps and launchctl, deploys and writes the status file."""

    def __init__(self, root: Path, home: Path, policy: dict[str, Any], *, runner: Runner = default_runner,
                 probe: Callable[[str, float], dict[str, Any]] = http_probe,
                 clock: Callable[[], datetime] = utc_now, sleep: Callable[[float], None] = time.sleep,
                 uid: int | None = None) -> None:
        self.root = root
        self.home = home
        self.policy = policy
        self.run = runner
        self.probe = probe
        self.clock = clock
        self.sleep = sleep
        self.uid = os.getuid() if uid is None else uid
        self.state_dir = home / "Library/Application Support/TIM/dashboard-refresh"
        self.state_path = self.state_dir / "state.json"
        self.status_path = root / "data/operational/dashboard_refresh.json"
        self.python = root / ".venv/bin/python"
        self.branch = policy.get("branch", "platform-main")

    # ---------- small helpers ----------
    def git(self, *args: str, timeout: float = 60) -> subprocess.CompletedProcess:
        return self.run(["git", "-C", str(self.root), *args], timeout=timeout)

    def read_state(self) -> dict[str, Any]:
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            return state if isinstance(state, dict) else {}
        except (OSError, ValueError):
            return {}

    def write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)

    def append_history(self, entry: dict[str, Any]) -> None:
        path = self.state_dir / "history.jsonl"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[-(HISTORY_LIMIT - 1):]
        except OSError:
            lines = []
        lines.append(json.dumps(entry, sort_keys=True))
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(".history.jsonl.tmp")
        temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(temporary, path)

    def runtime_pid(self) -> int | None:
        result = self.run(["launchctl", "print", f"gui/{self.uid}/com.tim.runtime"], timeout=15)
        return launchd_pid(result.stdout) if result.returncode == 0 else None

    def exists_in(self, commit: str | None) -> Callable[[str], bool]:
        def check(path: str) -> bool:
            if (self.root / path).exists():
                return True
            if commit is None:
                return False
            return self.git("cat-file", "-e", f"{commit}:{path}", timeout=15).returncode == 0
        return check

    def campaign_active(self) -> bool:
        campaign = self.root / "data/qualification/qualification_campaign.json"
        if not campaign.exists() or (self.root / "data/qualification/campaign_aborted.json").exists():
            return False
        try:
            status = str(json.loads(campaign.read_text(encoding="utf-8")).get("status", "")).upper()
        except (OSError, ValueError, AttributeError):
            return True  # unreadable campaign file: stay safe
        return status not in {"COMPLETED", "ABORTED", "ENDED", "FINISHED"}

    def ci_result(self, commit: str) -> dict[str, Any] | None:
        repository = self.policy.get("repository")
        if not repository:
            return None
        result = self.run([self.policy.get("gh", "gh"), "api", f"repos/{repository}/commits/{commit}/check-runs?per_page=100"],
                          timeout=60)
        if result.returncode != 0:
            return None
        try:
            return pick_check_run(json.loads(result.stdout), self.policy.get("required_check", "test"))
        except ValueError:
            return None

    def ci_counts(self, check_run_id: Any) -> dict[str, int]:
        repository = self.policy.get("repository")
        if not repository or not check_run_id:
            return {}
        result = self.run([self.policy.get("gh", "gh"), "api", f"repos/{repository}/actions/jobs/{check_run_id}/logs"],
                          timeout=120)
        return pytest_counts(result.stdout) if result.returncode == 0 else {}

    # ---------- one run ----------
    def run_once(self, *, dry_run: bool = False) -> dict[str, Any]:
        now = self.clock()
        state = self.read_state()
        paused = (self.state_dir / "PAUSE").exists()
        fetched = self.git("fetch", "--quiet", "origin", self.branch, timeout=180).returncode == 0
        deployed = self.git("rev-parse", "HEAD").stdout.strip()
        target_result = self.git("rev-parse", f"origin/{self.branch}")
        target = target_result.stdout.strip() if fetched and target_result.returncode == 0 else None

        changed: list[str] = []
        fast_forward = False
        ci = None
        if target and target != deployed:
            changed = [line for line in self.git("diff", "--name-only", deployed, target).stdout.splitlines() if line]
            fast_forward = self.git("merge-base", "--is-ancestor", deployed, target).returncode == 0
            ci = self.ci_result(target)
        ps_output = self.run(["ps", "-axo", "command="], timeout=15).stdout
        busy = busy_processes(ps_output, self.policy.get("busy_process_patterns", {}))
        dirty = parse_porcelain(self.git("status", "--porcelain", "--untracked-files=no").stdout,
                                self.policy.get("generated_tracked_files", []))
        studies = active_studies(self.policy, now, self.exists_in(target))
        decision = decide(
            deployed=deployed, target=target, is_fast_forward=fast_forward, ci=ci, busy=busy, dirty=dirty,
            campaign_active=self.campaign_active(), last_restart_at=parse_time(state.get("last_restart_at_utc")),
            now=now, min_minutes_between_restarts=float(self.policy.get("min_minutes_between_runtime_restarts", 60)),
            blockers=study_blockers(studies, changed), failed_targets=state.get("failed_targets", []), paused=paused,
        )

        deploy_result = None
        if decision.action == "DEPLOY" and not dry_run and target and ci:
            deploy_result = self.deploy(deployed, target, ci, changed, state)
        worker = self.refresh_worker_dashboard(state, busy=busy, paused=paused, dry_run=dry_run)
        health = [{"name": check["name"], "optional": bool(check.get("optional")),
                   **self.probe(check["url"], float(check.get("timeout_seconds", 10)))}
                  for check in self.policy.get("health_checks", [])]
        if not dry_run:
            self.write_json(self.state_path, state)

        status = {
            "schema_version": SCHEMA_VERSION,
            "checked_at_utc": iso(now),
            "finished_at_utc": iso(self.clock()),
            "dry_run": dry_run,
            "deployed_commit": self.git("rev-parse", "HEAD").stdout.strip(),
            "target_commit": target,
            "decision": decision.to_dict(),
            "ci": ci,
            "active_studies": [study["id"] for study in studies],
            "deploy": deploy_result,
            "worker_dashboard": worker,
            "health": health,
            "health_ok": all(item["ok"] for item in health if not item["optional"]),
            "last_restart_at_utc": state.get("last_restart_at_utc"),
            "mode": "OBSERVE",
        }
        if not dry_run:
            self.write_json(self.status_path, status)
            self.append_history({key: status[key] for key in ("checked_at_utc", "deployed_commit", "target_commit", "health_ok")}
                                | {"action": decision.action, "reason": decision.reason,
                                   "deploy": (deploy_result or {}).get("result"), "worker": worker.get("result")})
        return status

    # ---------- Control Center ----------
    def timctl(self, command: str, timeout: float = 240) -> subprocess.CompletedProcess:
        return self.run([str(self.python), str(self.root / "scripts/timctl"), command], timeout=timeout,
                        env=dict(os.environ))

    def restart_runtime(self) -> dict[str, Any]:
        before = self.runtime_pid()
        restart = self.timctl("restart")
        attempts = [{"command": "restart", "returncode": restart.returncode}]
        if restart.returncode != 0:
            # Known: verify_running can probe the dashboard too early; one more start is the documented fix.
            self.sleep(10)
            start = self.timctl("start")
            attempts.append({"command": "start", "returncode": start.returncode})
        verified = self.timctl("verify-running", timeout=120).returncode == 0
        after = self.runtime_pid()
        health = self.probe("http://127.0.0.1:8765/api/health", 10)
        ok = verified and after is not None and after != before and health["ok"]
        return {"ok": ok, "pid_before": before, "pid_after": after, "verify_running": verified,
                "health": health, "attempts": attempts}

    def save_generated(self, stamp: str) -> list[str]:
        saved = []
        for relative in self.policy.get("generated_tracked_files", []):
            source = self.root / relative
            if self.git("diff", "--quiet", "--", relative).returncode == 0 or not source.exists():
                continue
            backup = self.state_dir / "generated-backup" / stamp / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, backup)
            self.git("checkout", "--", relative)
            saved.append(relative)
        return saved

    def install_requirements(self) -> bool:
        result = self.run([str(self.python), "-m", "pip", "install", "-q", "-r", str(self.root / "requirements.txt")],
                          timeout=900)
        return result.returncode == 0

    def deploy(self, previous: str, target: str, ci: dict[str, Any], changed: list[str], state: dict[str, Any]) -> dict[str, Any]:
        stamp = iso(self.clock()).replace(":", "")
        record = {"from": previous, "to": target, "started_at_utc": iso(self.clock())}
        record["generated_files_saved"] = self.save_generated(stamp)
        deployment_file = self.root / "data/operational/deployment.json"
        old_deployment = deployment_file.read_bytes() if deployment_file.exists() else None
        requirements_changed = "requirements.txt" in changed
        state["last_restart_at_utc"] = iso(self.clock())  # also on failure: no restart loops

        failure = None
        if self.git("checkout", "--detach", "--quiet", target).returncode != 0:
            failure = "checkout_failed"
        elif requirements_changed and not self.install_requirements():
            failure = "pip_install_failed"
        else:
            counts = self.ci_counts(ci.get("id"))
            command = [str(self.python), str(self.root / "scripts/record_deployment.py"), "--commit", target,
                       "--ci-conclusion", "success", "--ci-completed-at", ci["completed_at_utc"], "--ci-url", ci.get("url", "")]
            for key in ("passed", "failed", "skipped"):
                if key in counts:
                    command += [f"--{key}", str(counts[key])]
            if self.run(command, timeout=60).returncode != 0:
                failure = "record_deployment_failed"
            else:
                restart = self.restart_runtime()
                record["restart"] = restart
                if not restart["ok"]:
                    failure = "restart_or_health_failed"
        if failure is None:
            record["result"] = "DEPLOYED"
            drift = self.run([str(self.python), str(self.root / "scripts/mac_live_install.py"), "--check"], timeout=60)
            record["launchd_drift"] = _json_or_text(drift.stdout)
        else:
            record["result"] = "ROLLED_BACK"
            record["failure"] = failure
            record["rollback"] = self.rollback(previous, old_deployment, requirements_changed)
            state["failed_targets"] = (list(state.get("failed_targets", [])) + [target])[-20:]
        record["finished_at_utc"] = iso(self.clock())
        return record

    def rollback(self, previous: str, old_deployment: bytes | None, requirements_changed: bool) -> dict[str, Any]:
        checkout = self.git("checkout", "--detach", "--quiet", previous).returncode == 0
        if requirements_changed:
            self.install_requirements()
        deployment_file = self.root / "data/operational/deployment.json"
        if old_deployment is not None:
            deployment_file.write_bytes(old_deployment)
        else:
            deployment_file.unlink(missing_ok=True)
        restart = self.restart_runtime()
        return {"checkout": checkout, "restart": restart}

    # ---------- worker dashboard ----------
    def refresh_worker_dashboard(self, state: dict[str, Any], *, busy: list[str], paused: bool, dry_run: bool) -> dict[str, Any]:
        config = self.policy.get("worker_dashboard") or {}
        if not config:
            return {"result": "NOT_CONFIGURED"}
        tree = self.git("rev-parse", f"HEAD:{config['source_dir']}").stdout.strip()
        installed = state.get("worker_dashboard_tree")
        if not tree:
            return {"result": "SOURCE_MISSING"}
        if installed is None:
            # First run: the running binary is taken as built from the current source.
            state["worker_dashboard_tree"] = tree
            return {"result": "BASELINE_RECORDED", "tree": tree}
        if installed == tree:
            return {"result": "UP_TO_DATE", "tree": tree}
        if tree in state.get("failed_worker_trees", []):
            return {"result": "HOLD_PREVIOUS_ATTEMPT_FAILED", "tree": tree}
        if paused or busy or dry_run:
            return {"result": "WAIT", "tree": tree, "installed": installed, "busy": busy, "paused": paused}
        return self.rebuild_worker_dashboard(config, tree, state)

    def rebuild_worker_dashboard(self, config: dict[str, Any], tree: str, state: dict[str, Any]) -> dict[str, Any]:
        cargo = self.home / ".cargo/bin/cargo"
        target_dir = self.state_dir / "cargo-target"
        env = dict(os.environ) | {"CARGO_TARGET_DIR": str(target_dir)}
        build = self.run([str(cargo), "build", "--release", "--locked", "--manifest-path",
                          str(self.root / config["source_dir"] / "Cargo.toml")], timeout=1800, env=env)
        if build.returncode != 0:
            state["failed_worker_trees"] = (list(state.get("failed_worker_trees", [])) + [tree])[-20:]
            return {"result": "BUILD_FAILED", "tree": tree, "stderr_tail": build.stderr[-2000:]}
        binary = self.home / config["installed_binary"]
        built = target_dir / "release" / binary.name
        previous = binary.with_name(binary.name + ".prev")
        fresh = binary.with_name(binary.name + ".new")
        shutil.copy2(binary, previous)
        shutil.copy2(built, fresh)
        os.chmod(fresh, 0o755)
        os.replace(fresh, binary)
        if self.restart_worker_dashboard(config):
            state["worker_dashboard_tree"] = tree
            return {"result": "REBUILT", "tree": tree}
        os.replace(previous, binary)
        self.restart_worker_dashboard(config)
        state["failed_worker_trees"] = (list(state.get("failed_worker_trees", [])) + [tree])[-20:]
        return {"result": "ROLLED_BACK", "tree": tree}

    def restart_worker_dashboard(self, config: dict[str, Any]) -> bool:
        self.run(["launchctl", "kickstart", "-k", f"gui/{self.uid}/{config['label']}"], timeout=30)
        for _ in range(12):
            self.sleep(5)
            if self.probe(config["status_url"], 30)["ok"]:
                return True
        return False


def _json_or_text(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return text.strip()[-2000:]
