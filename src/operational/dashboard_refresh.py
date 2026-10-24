"""Keep the dashboards on the Mac mini on the current platform-main (OBSERVE only).

One run (launchd every 10 minutes, see scripts/dashboard_refresh.py):

1. ``git fetch`` platform-main in the live checkout (~/TIM-live).
2. Decide with :func:`decide` whether a new commit may go live: CI job ``test`` green on that
   commit or on a commit with the identical tree (the PR head of a merge under the strict
   ruleset), fast-forward only, no running DB backup, no active qualification campaign, a CI
   test job delays the restart for at most ``max_defer_minutes``, at most one runtime restart
   per interval (shorter when only the display changed), and while a registered study runs only
   display-safe changes (policy ``ops/dashboard_refresh/policy.json``). When the newest commit
   touches protected paths, the newest *unblocked* ancestor on the first-parent chain goes live
   instead, so one mixed commit no longer holds every display fix behind it.
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
    "busy_deferred": "CI-Testjob läuft, Neustart wird kurz verschoben.",
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
        return {"action": self.action, "reason": self.reason, "text": self.text(), "details": self.details}

    def text(self) -> str:
        """Reason text with the facts a reader needs (which files hold, until when a restart waits)."""
        base = REASON_TEXT.get(self.reason, self.reason)
        held = self.details.get("held_back") or {}
        if self.reason == "study_protected_paths":
            return f"{base} Hält zurück: {_file_list(self.details.get('blocked_files'))}."
        latest = parse_time(self.details.get("deploy_at_latest_utc"))
        if self.reason == "busy_deferred" and latest:
            return f"{base} Spätestens {latest.astimezone().strftime('%H:%M')} Uhr."
        if held:
            return (f"{base} {held.get('commits', 0)} neuere Commits warten wegen "
                    f"{_file_list(held.get('blocked_files'))}.")
        return base


def _file_list(blocked: Any, limit: int = 3) -> str:
    files: list[str] = []
    if isinstance(blocked, dict):
        for paths in blocked.values():
            files.extend(str(path) for path in paths)
    elif isinstance(blocked, (list, tuple)):
        files.extend(str(path) for path in blocked)
    files = sorted(set(files))
    if not files:
        return "unbekannt"
    shown = ", ".join(files[:limit])
    return shown if len(files) <= limit else f"{shown} (+{len(files) - limit})"


def load_policy(path: Path) -> dict[str, Any]:
    policy = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(policy, dict) or policy.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported dashboard refresh policy: {path}")
    return policy


DISPLAY_SAFE_KEYS = ("display_safe_prefixes", "display_safe_files", "display_safe_suffixes")


def is_display_safe(path: str, rules: dict[str, Any]) -> bool:
    if path in rules.get("display_safe_files", []):
        return True
    if any(path.startswith(prefix) for prefix in rules.get("display_safe_prefixes", [])):
        return True
    return any(path.endswith(suffix) for suffix in rules.get("display_safe_suffixes", []))


def display_rules(policy: dict[str, Any], study: dict[str, Any] | None = None) -> dict[str, Any]:
    """The display-safe path rules: a study's own lists, or the policy default (``display_safe``)."""
    if study and any(key in study for key in DISPLAY_SAFE_KEYS):
        return {key: list(study.get(key, [])) for key in DISPLAY_SAFE_KEYS}
    default = policy.get("display_safe") or {}
    return {key: list(default.get(key, [])) for key in DISPLAY_SAFE_KEYS}


def display_only(policy: dict[str, Any], changed_files: Iterable[str]) -> bool:
    rules = display_rules(policy)
    return all(is_display_safe(path, rules) for path in changed_files)


def active_studies(policy: dict[str, Any], now: datetime, exists: Callable[[str], bool]) -> list[dict[str, Any]]:
    """Studies that started and have no end marker in the live checkout or the target commit.

    Each returned study carries its resolved display-safe lists, so :func:`study_blockers` needs no policy.
    """
    active = []
    for study in policy.get("studies", []):
        start = parse_time(study.get("active_from_utc"))
        if start is None or now < start:
            continue
        marker = study.get("ended_marker")
        if marker and exists(marker):
            continue
        active.append({**study, **display_rules(policy, study)})
    return active


def furthest_unblocked(chain: list[str], changed_up_to: Callable[[str], list[str]],
                       studies: list[dict[str, Any]]) -> tuple[str | None, dict[str, list[str]]]:
    """Newest commit on ``chain`` (oldest first) whose cumulative diff is display-safe for every study.

    Returns ``(commit, blockers_of_the_newest_commit)``; ``commit`` is None when even the oldest is blocked.
    """
    newest_blockers: dict[str, list[str]] = {}
    for index, commit in enumerate(reversed(chain)):
        blockers = study_blockers(studies, changed_up_to(commit))
        if index == 0:
            newest_blockers = blockers
        if not blockers:
            return commit, newest_blockers
    return None, newest_blockers


def same_tree(tree: str, candidates: dict[str, str | None]) -> list[str]:
    """Commits whose tree hash equals ``tree`` (their code is byte-identical, so their CI result counts)."""
    return [sha for sha, candidate_tree in candidates.items() if candidate_tree and candidate_tree == tree]


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
    deferred: list[str] | None = None,
    deferred_since: datetime | None = None,
    max_defer_minutes: float = 0,
    held_back: dict[str, Any] | None = None,
) -> Decision:
    """Pure decision; the order puts the hard stops (pause, campaign) first.

    ``busy`` always waits. ``deferred`` (e.g. a running CI test job) waits only until
    ``max_defer_minutes`` after ``deferred_since``, the moment the commit first became deployable.
    """
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
    if blockers:
        return Decision("HOLD", "study_protected_paths", {"target": target, "blocked_files": blockers})
    conclusion = (ci or {}).get("conclusion")
    if ci is None or ci.get("status") != "completed":
        return Decision("WAIT", "ci_pending", {"target": target})
    if conclusion != "success":
        return Decision("HOLD", "ci_failed", {"target": target, "conclusion": conclusion, "url": ci.get("url")})
    if dirty:
        return Decision("HOLD", "local_changes", {"files": dirty})
    if busy:
        return Decision("WAIT", "busy", {"busy": busy})
    if last_restart_at is not None and now - last_restart_at < timedelta(minutes=min_minutes_between_restarts):
        return Decision("WAIT", "restart_interval", {
            "next_possible_at_utc": iso(last_restart_at + timedelta(minutes=min_minutes_between_restarts))})
    if deferred:
        since = deferred_since or now
        latest = since + timedelta(minutes=max_defer_minutes)
        if now < latest:
            return Decision("WAIT", "busy_deferred", {"busy": deferred, "deferred_since_utc": iso(since),
                                                      "deploy_at_latest_utc": iso(latest), "target": target})
    details: dict[str, Any] = {"from": deployed, "to": target}
    if held_back:
        details["held_back"] = held_back
    return Decision("DEPLOY", "deploy", details)


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

    def gh_json(self, endpoint: str, timeout: float = 60) -> Any:
        result = self.run([self.policy.get("gh", "gh"), "api", endpoint], timeout=timeout)
        if result.returncode != 0:
            return None
        try:
            return json.loads(result.stdout)
        except ValueError:
            return None

    def check_run(self, commit: str) -> dict[str, Any] | None:
        repository = self.policy.get("repository")
        if not repository:
            return None
        payload = self.gh_json(f"repos/{repository}/commits/{commit}/check-runs?per_page=100")
        return pick_check_run(payload, self.policy.get("required_check", "test")) if isinstance(payload, dict) else None

    def tree_of(self, commit: str) -> str | None:
        local = self.git("rev-parse", f"{commit}^{{tree}}", timeout=15)
        if local.returncode == 0 and local.stdout.strip():
            return local.stdout.strip()
        repository = self.policy.get("repository")
        payload = self.gh_json(f"repos/{repository}/git/commits/{commit}") if repository else None
        return (payload.get("tree") or {}).get("sha") if isinstance(payload, dict) else None

    def tested_equivalents(self, commit: str) -> list[str]:
        """Commits with the same tree as ``commit``: its second parent (merge) and the heads of its PRs.

        Under the strict ruleset a PR must be current before it merges, so the merge commit's tree equals
        the tested PR head's tree; a squash merge of a current branch yields the same tree as well.
        """
        tree = self.tree_of(commit)
        if not tree:
            return []
        candidates: dict[str, str | None] = {}
        second_parent = self.git("rev-parse", "--verify", "--quiet", f"{commit}^2", timeout=15)
        if second_parent.returncode == 0 and second_parent.stdout.strip():
            candidates[second_parent.stdout.strip()] = None
        repository = self.policy.get("repository")
        pulls = self.gh_json(f"repos/{repository}/commits/{commit}/pulls?per_page=10") if repository else None
        for pull in pulls if isinstance(pulls, list) else []:
            head = ((pull or {}).get("head") or {}).get("sha") if isinstance(pull, dict) else None
            if head and head != commit:
                candidates.setdefault(head, None)
        for sha in list(candidates):
            candidates[sha] = self.tree_of(sha)
        return same_tree(tree, candidates)

    def ci_result(self, commit: str) -> dict[str, Any] | None:
        """Green ``test`` on the commit itself, else on a commit with the identical tree (PR head)."""
        direct = self.check_run(commit)
        if direct and direct.get("status") == "completed" and direct.get("conclusion") == "success":
            return direct
        for equivalent in self.tested_equivalents(commit):
            run = self.check_run(equivalent)
            if run and run.get("status") == "completed" and run.get("conclusion") == "success":
                return {**run, "tested_commit": equivalent, "same_tree_as": commit}
        return direct

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
        chosen = target
        blockers: dict[str, list[str]] = {}
        held_back: dict[str, Any] | None = None
        studies = active_studies(self.policy, now, self.exists_in(target))
        if target and target != deployed:
            fast_forward = self.git("merge-base", "--is-ancestor", deployed, target).returncode == 0
            def changed_up_to(commit: str) -> list[str]:
                return [line for line in self.git("diff", "--name-only", deployed, commit).stdout.splitlines() if line]

            changed = changed_up_to(target)
            if fast_forward and studies:
                chain = [line for line in self.git("rev-list", "--first-parent", "--reverse",
                                                   f"{deployed}..{target}").stdout.splitlines() if line] or [target]
                chosen, blockers = furthest_unblocked(chain, changed_up_to, studies)
                if chosen is None:
                    chosen = target
                elif chosen != target:
                    held_back = {"target": target, "commits": chain.index(target) - chain.index(chosen),
                                 "blocked_files": blockers}
                    blockers = {}
                    changed = changed_up_to(chosen)
            if fast_forward and not blockers:
                ci = self.ci_result(chosen)
        ps_output = self.run(["ps", "-axo", "command="], timeout=15).stdout
        busy = busy_processes(ps_output, self.policy.get("busy_process_patterns", {}))
        deferred = busy_processes(ps_output, self.policy.get("deferrable_process_patterns", {}))
        dirty = parse_porcelain(self.git("status", "--porcelain", "--untracked-files=no").stdout,
                                self.policy.get("generated_tracked_files", []))
        interval_key = ("min_minutes_between_runtime_restarts_display_only"
                        if changed and display_only(self.policy, changed) else "min_minutes_between_runtime_restarts")
        min_minutes = float(self.policy.get(interval_key, self.policy.get("min_minutes_between_runtime_restarts", 60)))
        deferral = state.get("deferral") if isinstance(state.get("deferral"), dict) else {}
        deferred_since = parse_time(deferral.get("since_utc")) if deferral.get("target") == chosen else None
        decision = decide(
            deployed=deployed, target=chosen, is_fast_forward=fast_forward, ci=ci, busy=busy, dirty=dirty,
            campaign_active=self.campaign_active(), last_restart_at=parse_time(state.get("last_restart_at_utc")),
            now=now, min_minutes_between_restarts=min_minutes, blockers=blockers,
            failed_targets=state.get("failed_targets", []), paused=paused, deferred=deferred,
            deferred_since=deferred_since, max_defer_minutes=float(self.policy.get("max_defer_minutes", 0)),
            held_back=held_back,
        )
        if decision.reason == "busy_deferred":
            state["deferral"] = {"target": chosen, "since_utc": decision.details["deferred_since_utc"]}
        else:
            state.pop("deferral", None)

        deploy_result = None
        if decision.action == "DEPLOY" and not dry_run and chosen and ci:
            deploy_result = self.deploy(deployed, chosen, ci, changed, state)
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
            "deploy_target": chosen,
            "held_back": held_back,
            "restart_interval_minutes": min_minutes,
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
