"""Fail-closed publisher for the collaboration live status (#67, phases 2, 4 and 6).

Order of one run: lock -> build snapshot from read-only observed values -> validate -> plan (only the one
allowed path, only on change) -> write -> stage exactly that path -> verify the index holds exactly that path ->
commit -> optional push. Any safety, schema or staging problem is SAFE_STOP and nothing is committed. The
publisher never touches queue, outbox, database or trading state; it only reads the observed values it is given.

Default is a dry run (rollout stage A): it builds, validates and plans, and writes nothing.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import subprocess
from typing import Callable

from src.collaboration.live_status import validate_live_status
from src.collaboration.publish_plan import SNAPSHOT_PATH, plan_publish
from src.collaboration.snapshot import build_live_status

HEALTH_RULES_VERSION = 'collab-health/1'
STALE_AFTER_SECONDS = 15 * 60          # three missed 5-minute runs
GIT_TIMEOUT_SECONDS = 60

Git = Callable[[list[str]], subprocess.CompletedProcess]


def _git_runner(repo: Path) -> Git:
    def run(args: list[str]) -> subprocess.CompletedProcess:
        # explicit argv, no shell, no inherited credentials in the message; output is captured, never echoed
        return subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True,
                              timeout=GIT_TIMEOUT_SECONDS, check=False)
    return run


def _utc(now: datetime) -> str:
    return now.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def _result(action, reasons, **extra):
    return {'action': action, 'reasons': sorted(reasons), **extra}


def publish_once(repo: Path, observed, *, now: datetime | None = None, captured_at: datetime | None = None,
                 commit: bool = False, push_branch: str | None = None, git: Git | None = None) -> dict:
    """One publisher run. Returns what happened; never raises for data or git problems."""
    repo = Path(repo)
    git = git or _git_runner(repo)
    now = now or datetime.now(timezone.utc)
    lock_path = repo / '.git' / 'tim-collab-publisher.lock'
    try:
        lock = open(lock_path, 'a+')
    except OSError:
        return _result('safe_stop', ['cannot open publisher lock'])
    with lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return _result('skip', ['another publisher run holds the lock'])
        try:
            doc = build_live_status(observed, captured_at_utc=_utc(captured_at or now), published_at_utc=_utc(now))
        except Exception as exc:     # invalid observed values: never publish
            return _result('safe_stop', [f'snapshot rejected: {type(exc).__name__}'])
        target = repo / SNAPSHOT_PATH
        previous = target.read_text() if target.is_file() else None

        status = git(['status', '--porcelain', '--', SNAPSHOT_PATH])
        if status.returncode != 0:
            return _result('safe_stop', ['git status failed'])
        if status.stdout.strip():
            return _result('safe_stop', ['snapshot path has uncommitted local edits'])
        staged = git(['diff', '--cached', '--name-only'])
        if staged.returncode != 0 or staged.stdout.strip():
            return _result('safe_stop', ['index already holds staged changes'])
        plan = plan_publish(doc, previous, [SNAPSHOT_PATH])
        if plan['action'] != 'publish':
            return _result(plan['action'], plan['reasons'], document=doc)
        if not commit:
            return _result('dry_run', ['snapshot valid and changed; dry run writes nothing'], document=doc, plan=plan)

        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix('.json.tmp')
        temp.write_text(json.dumps(doc, sort_keys=True, indent=2) + '\n')
        os.replace(temp, target)
        if not validate_live_status(json.loads(target.read_text()))['ok']:
            return _result('safe_stop', ['written snapshot failed validation'])
        if git(['add', '--', SNAPSHOT_PATH]).returncode != 0:
            return _result('safe_stop', ['git add failed'])
        staged = git(['diff', '--cached', '--name-only'])
        if staged.returncode != 0 or staged.stdout.split() != [SNAPSHOT_PATH]:
            git(['reset', '--quiet', '--', SNAPSHOT_PATH])
            return _result('safe_stop', ['staged files differ from the allowlist'])
        if git(['commit', '--quiet', '-m', plan['commit_message']]).returncode != 0:
            return _result('safe_stop', ['git commit failed'])
        if push_branch is None:
            return _result('committed', ['snapshot committed locally'], document=doc)
        pushed = git(['push', '--quiet', 'origin', f'HEAD:refs/heads/{push_branch}'])
        if pushed.returncode != 0:
            # The snapshot stays committed locally; the next run retries. TIM itself is not affected.
            return _result('push_failed', ['push failed; snapshot kept locally'], document=doc)
        return _result('published', ['snapshot committed and pushed'], document=doc)


def derive_health(doc, *, now: datetime, stale_after_seconds: int = STALE_AFTER_SECONDS) -> dict:
    """Reader-side health of a published snapshot: HEALTHY, DEGRADED, STALE or SAFE_STOP (rules versioned)."""
    rules = {'rules_version': HEALTH_RULES_VERSION, 'stale_after_seconds': stale_after_seconds}
    check = validate_live_status(doc)
    if not check['ok']:
        return {'state': 'SAFE_STOP', 'reasons': check['errors'], **rules}
    published = datetime.fromisoformat(doc['published_at_utc'].replace('Z', '+00:00'))
    age = (now - published).total_seconds()
    if age > stale_after_seconds:
        return {'state': 'STALE', 'reasons': [f'published {int(age)} s ago'], **rules}
    reasons = []
    collectors, queue, quality = doc['collectors'], doc['queue'], doc['quality']
    if (collectors.get('stale') or 0) > 0:
        reasons.append('stale collectors')
    if (queue.get('blocked') or 0) > 0:
        reasons.append('blocked queue items')
    if (quality.get('critical_incidents') or 0) > 0:
        reasons.append('critical incidents')
    if quality.get('last_check_ok') is False:
        reasons.append('last quality check failed')
    return {'state': 'DEGRADED' if reasons else 'HEALTHY', 'reasons': reasons, **rules}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Publish the sanitized collaboration live status (fail closed).')
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--observed', type=Path, required=True, help='JSON with the read-only observed values')
    parser.add_argument('--commit', action='store_true', help='write and commit (default: dry run)')
    parser.add_argument('--push-branch', help='push the commit to this branch (requires --commit)')
    args = parser.parse_args(argv)
    if args.push_branch and not args.commit:
        parser.error('--push-branch requires --commit')
    try:
        observed = json.loads(args.observed.read_text())
    except (OSError, ValueError):
        print(json.dumps({'action': 'safe_stop', 'reasons': ['observed values unreadable']}))
        return 2
    result = publish_once(args.repo, observed, commit=args.commit, push_branch=args.push_branch)
    result.pop('document', None)
    print(json.dumps(result, sort_keys=True))
    return 0 if result['action'] in {'skip', 'dry_run', 'committed', 'published'} else 2


if __name__ == '__main__':
    raise SystemExit(main())
