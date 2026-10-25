"""#67: fail-closed publisher and reader-side health, against a real throw-away git repository."""
from datetime import datetime, timedelta, timezone
import fcntl
import json
import subprocess

import pytest

from src.collaboration.publish_plan import SNAPSHOT_PATH
from src.collaboration.publisher import derive_health, main, publish_once
from src.collaboration.snapshot import build_live_status

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
OBSERVED = {'collectors': {'running': 3, 'stale': 0, 'total': 3},
            'queue': {'pending': 10, 'blocked': 0, 'oldest_age_seconds': 4},
            'coverage': {'symbols': 1, 'complete_minutes_24h': 1440, 'missing_minutes_24h': 0},
            'quality': {'unknown_rate': 0.0, 'critical_incidents': 0, 'last_check_ok': True}}


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / 'repo'
    path.mkdir()
    git(path, 'init', '-q')
    git(path, 'config', 'user.email', 'publisher@example.invalid')
    git(path, 'config', 'user.name', 'publisher')
    (path / 'README').write_text('x\n')
    git(path, 'add', 'README')
    git(path, 'commit', '-q', '-m', 'init')
    return path


def commits(repo):
    return int(git(repo, 'rev-list', '--count', 'HEAD'))


def test_dry_run_is_the_default_and_writes_nothing(repo):
    result = publish_once(repo, OBSERVED, now=NOW)
    assert result['action'] == 'dry_run'
    assert not (repo / SNAPSHOT_PATH).exists() and commits(repo) == 1


def test_commit_stages_exactly_the_snapshot_and_skips_when_unchanged(repo):
    first = publish_once(repo, OBSERVED, now=NOW, commit=True)
    assert first['action'] == 'committed' and commits(repo) == 2
    assert git(repo, 'show', '--name-only', '--format=', 'HEAD').split() == [SNAPSHOT_PATH]
    later = publish_once(repo, OBSERVED, now=NOW + timedelta(minutes=5), commit=True)
    assert later['action'] == 'skip' and commits(repo) == 2           # only timestamps differ


def test_other_staged_files_stop_the_run(repo):
    (repo / 'other.txt').write_text('secret-ish\n')
    git(repo, 'add', 'other.txt')
    result = publish_once(repo, OBSERVED, now=NOW, commit=True)
    assert result['action'] == 'safe_stop' and commits(repo) == 1


def test_local_edits_on_the_snapshot_path_stop_the_run(repo):
    publish_once(repo, OBSERVED, now=NOW, commit=True)
    (repo / SNAPSHOT_PATH).write_text('{"edited": true}\n')
    result = publish_once(repo, {**OBSERVED, 'queue': {'pending': 11}}, now=NOW, commit=True)
    assert result['action'] == 'safe_stop' and 'uncommitted' in result['reasons'][0]
    assert commits(repo) == 2


def test_non_object_observed_values_stop_the_run(repo):
    result = publish_once(repo, 'not a dict', now=NOW, commit=True)
    assert result['action'] == 'safe_stop' and commits(repo) == 1


def test_free_text_in_observed_values_is_dropped_not_published(repo):
    unsafe = {**OBSERVED, 'collectors': {**OBSERVED['collectors'], 'running': 'postgresql://u:p@db/tim'}}
    assert publish_once(repo, unsafe, now=NOW, commit=True)['action'] == 'committed'
    text = (repo / SNAPSHOT_PATH).read_text()
    assert 'postgresql' not in text and json.loads(text)['collectors']['running'] is None


def test_a_held_lock_skips_the_run(repo):
    lock_path = repo / '.git' / 'tim-collab-publisher.lock'
    with open(lock_path, 'a+') as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX)
        result = publish_once(repo, OBSERVED, now=NOW, commit=True)
    assert result['action'] == 'skip' and commits(repo) == 1


def test_push_failure_keeps_the_local_commit(repo):
    result = publish_once(repo, OBSERVED, now=NOW, commit=True, push_branch='collab-status')
    assert result['action'] == 'push_failed'                 # no remote configured
    assert commits(repo) == 2 and (repo / SNAPSHOT_PATH).is_file()


def test_a_git_that_stages_more_than_allowed_is_caught(repo):
    real = subprocess.run

    def sneaky(args):
        if args[:1] == ['add']:
            (repo / 'extra.txt').write_text('x\n')
            real(['git', '-C', str(repo), 'add', 'extra.txt'], check=True)
        return real(['git', '-C', str(repo), *args], capture_output=True, text=True, check=False)
    result = publish_once(repo, OBSERVED, now=NOW, commit=True, git=sneaky)
    assert result['action'] == 'safe_stop' and 'allowlist' in result['reasons'][0]
    assert commits(repo) == 1


def doc(**quality):
    return build_live_status(
        {**OBSERVED, 'quality': {**OBSERVED['quality'], **quality}},
        captured_at_utc='2026-10-25T12:00:00Z', published_at_utc='2026-10-25T12:00:00Z')


def test_health_states():
    assert derive_health(doc(), now=NOW)['state'] == 'HEALTHY'
    assert derive_health(doc(critical_incidents=1), now=NOW)['state'] == 'DEGRADED'
    assert derive_health(doc(), now=NOW + timedelta(minutes=16))['state'] == 'STALE'
    broken = doc()
    broken['safety']['trading_actions_emitted'] = 1
    assert derive_health(broken, now=NOW)['state'] == 'SAFE_STOP'
    assert derive_health(doc(), now=NOW)['rules_version'] == 'collab-health/1'


def test_cli_dry_run(repo, tmp_path, capsys):
    observed = tmp_path / 'observed.json'
    observed.write_text(json.dumps(OBSERVED))
    assert main(['--repo', str(repo), '--observed', str(observed)]) == 0
    assert json.loads(capsys.readouterr().out)['action'] == 'dry_run'
    with pytest.raises(SystemExit):
        main(['--repo', str(repo), '--observed', str(observed), '--push-branch', 'x'])
