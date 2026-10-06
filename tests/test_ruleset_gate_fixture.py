"""Exercise the actual fixture shell body without contacting GitHub."""
from pathlib import Path
import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize('scenario, expected', [
    ('absent', 'success'), ('marker', 'failure'), ('commit-error', 'failure'),
    ('tree-403', 'failure'), ('tree-404', 'failure'), ('malformed', 'failure'),
])
def test_fixture_rejects_api_errors_and_only_accepts_a_verified_absent_marker(tmp_path, scenario, expected):
    workflow = (Path(__file__).resolve().parents[1] / 'docs/rulesets/test-repo/github-workflows/pr-gate.yml').read_text()
    body = workflow.split('        run: |\n', 1)[1].split('        env:\n', 1)[0]
    script = '\n'.join(line[10:] for line in body.splitlines())
    fake = tmp_path / 'gh'
    fake.write_text('#!' + sys.executable + '\n' + '''
import os,sys
from pathlib import Path
args = sys.argv[1:]
if '-X' in args:
    state = next(a.split('=', 1)[1] for a in args if a.startswith('state='))
    Path(os.environ['RESULT']).write_text(state)
elif '/commits/' in args[1]:
    if os.environ['SCENARIO'] == 'commit-error': sys.exit(1)
    print('a' * 40)
else:
    mode = os.environ['SCENARIO']
    if mode in ('tree-403', 'tree-404'): sys.exit(1)
    print({'marker': 'true', 'absent': 'false', 'malformed': 'garbage'}.get(mode, 'false'))
''')
    fake.chmod(0o700)
    result = tmp_path / 'result'
    env = {'PATH': str(tmp_path) + ':' + os.environ['PATH'], 'SCENARIO': scenario,
           'RESULT': str(result), 'GITHUB_REPOSITORY': 'fixture/repo', 'HEAD_SHA': 'b' * 40,
           'RUN_URL': 'https://example.invalid/run'}
    subprocess.run(['bash', '-c', script], env=env, check=True, capture_output=True, text=True)
    assert result.read_text() == expected
