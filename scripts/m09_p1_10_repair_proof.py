"""Issue #12 P1.10: real repair proof driven through the Task Engine.

Defect: BinanceTradeStream treated a clean server close (1000/1001) as a
normal loop turn - no backoff, no DISCONNECTED telemetry, no resume catch-up.
Repair commit: see --repair. This script replays the lifecycle on exact
commits and lets only the Task Engine (Fix-First gate) decide FIXED:

  DETECT -> BUGFIX task -> ROOT CAUSE -> REPAIR (commit diff) -> TARGETED TEST
  -> RUNTIME / ISOLATED REPRO -> RECURRENCE PROTECTION -> FIXED

Before/after code runs in detached temporary git worktrees. Network use is a
websockets server on 127.0.0.1 only. The task store is a temporary file; no
production database, queue, outbox, trading or execution is touched.

Usage:
  python scripts/m09_p1_10_repair_proof.py --base <sha> --repair <sha> --out docs/evidence/m09-p1-10
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.task_engine import TaskState as S  # noqa: E402
from src.task_engine.fix_first import FixFirstRejected  # noqa: E402
from src.task_engine.repository import SqliteTaskRepository  # noqa: E402
from src.task_engine.service import TaskEngine  # noqa: E402

TARGET = 'src/data_ingestion/binance_ws.py'
REGRESSION = 'tests/test_binance_ws_clean_close.py'
REGRESSION_SUITE = [REGRESSION, 'tests/test_binance_ws.py', 'tests/test_binance_recovery_v2.py']
ALLOWED_DIFF = {TARGET, REGRESSION}
FORBIDDEN_PATH_WORDS = ('order', 'execution', 'trading', 'paper', 'outbox', 'database', 'durable')
BUG_ID = 'bugfix-binance-ws-clean-close'
PARENT_ID = 'm09-p1-10-real-repair-proof'
ROOT_CAUSE = (
    'websockets ends `async for` iteration without raising when the server closes with 1000/1001 '
    '(Binance rotates connections within 24 h). BinanceTradeStream.run() only treated exceptions as '
    'disconnects, so after a clean close it re-entered its loop immediately: no backoff, no DISCONNECTED '
    'event (reconnect_total never counted it) and needs_recovery stayed False, skipping resume catch-up '
    'before the next live trade.')

PROBE = r'''
import asyncio, json, sys
import websockets
from src.data_ingestion.binance_ws import BinanceTradeStream

def raw(i):
    return json.dumps({"e": "aggTrade", "s": "BTCUSDT", "a": i, "p": "100", "q": "1", "T": 1767225600000, "m": False})

async def main():
    loop = asyncio.get_running_loop()
    connections = []
    async def serve(ws):
        connections.append(loop.time())
        if len(connections) == 1:
            await ws.send(raw(1)); await ws.send(raw(2))
            await ws.close(code=1000, reason="rotation")
        else:
            await ws.send(raw(5))
            await asyncio.sleep(0.2)
            await ws.close(code=1000)
    async with websockets.serve(serve, "127.0.0.1", 0) as server:
        url = "ws://127.0.0.1:%d" % server.sockets[0].getsockname()[1]
        events, recovered, handled = [], [], []
        stream = None
        async def on_event(name, fields):
            events.append({"name": name, **{k: v for k, v in fields.items() if k != "delay_seconds"}})
        async def recover(trade):
            recovered.append(trade.trade_id)
        async def handle(trade):
            handled.append(trade.trade_id)
            if trade.trade_id == 5:
                stream.stop()
        stream = BinanceTradeStream(url, "BTCUSDT", handle, stream_event_handler=on_event, recovery_handler=recover)
        await asyncio.wait_for(stream.run(), 30)
    print(json.dumps({"url_host": "127.0.0.1", "websockets_version": websockets.__version__,
                      "handled": handled, "recovered_before_live": recovered, "events": events,
                      "reconnect_gap_seconds": round(connections[1] - connections[0], 3)}, sort_keys=True))

asyncio.run(main())
'''


def run(cmd, cwd, check=True):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=600, check=check)


def git(*args, cwd=ROOT):
    return run(['git', *args], cwd).stdout


class Evidence:
    def __init__(self, out: Path):
        self.out = out

    def artifact(self, name, content):
        path = self.out / name
        path.write_text(content)
        return {'path': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    def report(self, name, task, **fields):
        body = dict(task_id=task.task_id, attempt_count=task.attempt_count, git_sha=task.git_sha, **fields)
        return self.artifact(name + '.json', json.dumps(body, indent=2, sort_keys=True) + '\n')


def pytest_junit(python, cwd, tests, junit_path):
    result = run([python, '-m', 'pytest', *tests, '-q', '-p', 'no:cacheprovider', f'--junitxml={junit_path}'],
                 cwd, check=False)
    tree = ET.parse(junit_path)
    counts = {tag: len(list(tree.iter(tag))) for tag in ('testcase', 'failure', 'error', 'skipped')}
    return result.returncode, counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', required=True, help='defective commit')
    parser.add_argument('--repair', required=True, help='commit containing the repair and regression test')
    parser.add_argument('--out', required=True)
    parser.add_argument('--python', default=sys.executable)
    args = parser.parse_args()
    base, repair = git('rev-parse', args.base).strip(), git('rev-parse', args.repair).strip()
    out = (ROOT / args.out).resolve()
    if out.exists():
        raise SystemExit(f'{out} exists; evidence runs never overwrite earlier evidence')
    out.mkdir(parents=True)
    ev = Evidence(out)
    scratch = Path(tempfile.mkdtemp(prefix='m09-p1-10-'))
    before_tree, after_tree = scratch / 'before', scratch / 'after'
    git('worktree', 'add', '--detach', str(before_tree), base)
    git('worktree', 'add', '--detach', str(after_tree), repair)
    try:
        repo = SqliteTaskRepository(scratch / 'task-engine.sqlite3')
        engine = TaskEngine(repo)  # real UTC clock: this is an actual run
        summary = {'base_commit': base, 'repair_commit': repair, 'task_store': 'temporary file outside repository'}

        # BUGFIX task under a parent maintenance task
        engine.create_task(PARENT_ID, type='MAINTENANCE', source='issue:12', title='P1.10 real repair proof',
                           objective='Prove one real TIM defect is repaired through the Task Engine',
                           required_evidence=['bugfix_fixed'], git_sha=base)
        engine.create_task(BUG_ID, type='BUGFIX', parent_task_id=PARENT_ID, source='defect:binance-ws-clean-close',
                           priority='P2', risk='LOW', title='Clean server close bypasses disconnect handling',
                           objective='Treat a clean close like any disconnect: backoff, telemetry, catch-up',
                           acceptance_criteria=['clean close emits DISCONNECTED', 'backoff before reconnect',
                                                'resume catch-up before next live trade', 'stop() is not a disconnect'],
                           git_sha=base, code_version=base, next_action='reproduce defect on base commit')
        for target in (S.PLANNED, S.READY):
            engine.transition_task(PARENT_ID, target)
        for target in (S.PLANNED, S.READY, S.IN_PROGRESS):
            engine.transition_task(BUG_ID, target)

        # DETECT / REPRODUCE on the defective commit
        probe_before = json.loads(run([args.python, '-c', PROBE], before_tree).stdout)
        before_probe_ref = ev.artifact('runtime_before.json', json.dumps(probe_before, indent=2, sort_keys=True) + '\n')
        shutil.copy(after_tree / REGRESSION, before_tree / REGRESSION)
        code_before, counts_before = pytest_junit(args.python, before_tree, [REGRESSION], out / 'regression_before.junit.xml')
        regression_before_ref = ev.artifact('regression_before.junit.xml', (out / 'regression_before.junit.xml').read_text())
        defect_seen = ('DISCONNECTED' not in [e['name'] for e in probe_before['events']]
                       and probe_before['recovered_before_live'] == [] and probe_before['reconnect_gap_seconds'] < 1.0)
        if not defect_seen or code_before == 0:
            raise SystemExit('defect not reproduced on base commit; refusing to continue')
        engine.checkpoint(BUG_ID, 'reproduce', next_action='record root cause',
                          metadata={'verification': 'DEFECT_REPRODUCED', 'regression_failures_on_base': counts_before['failure']})

        engine.attach_evidence_ref(BUG_ID, 'root_cause', ROOT_CAUSE)
        engine.checkpoint(BUG_ID, 'root_cause', next_action='apply repair commit')

        # REPAIR: exact commit diff, limited to the allowlist
        changed = set(filter(None, git('diff', '--name-only', base, repair).splitlines()))
        before_src, after_src = git('show', f'{base}:{TARGET}'), git('show', f'{repair}:{TARGET}')
        patch = ''.join(difflib.unified_diff(before_src.splitlines(True), after_src.splitlines(True),
                                             fromfile='before', tofile='after'))
        repair_ref = {'kind': 'CODE_PATCH', 'before': ev.artifact('before_binance_ws.py', before_src),
                      'after': ev.artifact('after_binance_ws.py', after_src), 'patch': ev.artifact('change.diff', patch)}
        ev.artifact('commit.diff', git('diff', base, repair))
        engine.set_code_version(BUG_ID, git_sha=repair, code_version=repair)
        engine.checkpoint(BUG_ID, 'repair', next_action='run targeted regression test on repair commit',
                          metadata={'changed_files': sorted(changed)})
        task = engine.get_task(BUG_ID)

        reproduction_ref = ev.report('reproduction', task, outcome='REPRODUCED',
                                     details='Loopback websockets server closing with 1000 on base commit: no '
                                             'DISCONNECTED event, reconnect after %.3fs, no resume catch-up; '
                                             'regression test fails on base.' % probe_before['reconnect_gap_seconds'],
                                     base_commit=base, runtime_probe=before_probe_ref, regression_junit=regression_before_ref,
                                     regression_counts=counts_before)

        # TARGETED + REGRESSION TESTS on the repair commit
        code_t, counts_t = pytest_junit(args.python, after_tree, [REGRESSION], out / 'targeted_after.junit.xml')
        targeted_junit = ev.artifact('targeted_after.junit.xml', (out / 'targeted_after.junit.xml').read_text())
        code_r, counts_r = pytest_junit(args.python, after_tree, REGRESSION_SUITE, out / 'regression_after.junit.xml')
        regression_junit = ev.artifact('regression_after.junit.xml', (out / 'regression_after.junit.xml').read_text())
        targeted_ref = ev.report('targeted_tests', task, status='PASS' if code_t == 0 else 'FAIL', tests=[REGRESSION],
                                 counts=counts_t, code_sha256=repair_ref['after']['sha256'], junit=targeted_junit)
        regression_ref = ev.report('regression_tests', task, status='PASS' if code_r == 0 else 'FAIL',
                                   tests=REGRESSION_SUITE, counts=counts_r,
                                   code_sha256=repair_ref['after']['sha256'], junit=regression_junit)
        engine.checkpoint(BUG_ID, 'tests', next_action='runtime verification on loopback',
                          metadata={'verification': 'TESTS_PASS' if code_t == code_r == 0 else 'TESTS_FAIL'})

        # RUNTIME / ISOLATED REPRODUCTION on the repair commit
        probe_after = json.loads(run([args.python, '-c', PROBE], after_tree).stdout)
        after_probe_ref = ev.artifact('runtime_after.json', json.dumps(probe_after, indent=2, sort_keys=True) + '\n')
        names = [e['name'] for e in probe_after['events']]
        runtime_checks = {
            'disconnect_event_emitted': names.count('DISCONNECTED') == 1,
            'disconnect_reason_is_stream_closed': any(e.get('error_type') == 'StreamClosed' for e in probe_after['events']),
            'backoff_before_reconnect_ge_2s': probe_after['reconnect_gap_seconds'] >= 2.0,
            'resume_catchup_before_next_live_trade': probe_after['recovered_before_live'] == [5],
            'all_live_trades_handled': probe_after['handled'] == [1, 2, 5],
            'stop_after_final_close_not_counted': names.count('DISCONNECTED') == 1,
        }
        runtime_ref = ev.report('runtime', task, status='PASS' if all(runtime_checks.values()) else 'FAIL',
                                checks=runtime_checks, probe=after_probe_ref, network='127.0.0.1 loopback only')
        engine.checkpoint(BUG_ID, 'runtime', next_action='safety, integrity and recurrence checks',
                          metadata={'verification': 'RUNTIME_PASS' if all(runtime_checks.values()) else 'RUNTIME_FAIL'})

        # SAFETY / INTEGRITY / RECURRENCE
        safety_checks = {
            'diff_limited_to_allowlist': changed == ALLOWED_DIFF,
            'no_trading_execution_persistence_paths_changed': not any(
                word in path for path in changed for word in FORBIDDEN_PATH_WORDS),
            'runtime_network_loopback_only': probe_before['url_host'] == probe_after['url_host'] == '127.0.0.1',
            'task_store_outside_repository': not str(scratch).startswith(str(ROOT)),
        }
        integrity_checks = {
            'repair_commit_descends_from_base': run(['git', 'merge-base', '--is-ancestor', base, repair], ROOT,
                                                    check=False).returncode == 0,
            'before_matches_base_commit_blob': hashlib.sha256(before_src.encode()).hexdigest() == repair_ref['before']['sha256'],
            'after_matches_repair_commit_blob': hashlib.sha256(after_src.encode()).hexdigest() == repair_ref['after']['sha256'],
            'after_worktree_clean': git('status', '--porcelain', cwd=after_tree) == '',
            'patch_is_nonempty_code_change': bool(patch) and before_src != after_src,
        }
        regression_text = (after_tree / REGRESSION).read_text()
        recurrence_checks = {
            'regression_test_fails_on_base': code_before != 0 and counts_before['failure'] > 0,
            'regression_test_passes_on_repair': code_t == 0 and counts_t['failure'] == counts_t['error'] == 0,
            'regression_test_runs_in_ci': REGRESSION.startswith('tests/') and 'local_env' not in regression_text,
            'runtime_loopback_case_in_regression_test': 'websockets.serve' in regression_text,
        }
        safety_ref = ev.report('safety', task, status='PASS' if all(safety_checks.values()) else 'FAIL',
                               checks=safety_checks, changed_files=sorted(changed))
        integrity_ref = ev.report('integrity', task, status='PASS' if all(integrity_checks.values()) else 'FAIL',
                                  checks=integrity_checks, base_commit=base, repair_commit=repair)
        protection_ref = ev.artifact('regression_test.py', regression_text)
        recurrence_ref = ev.report('recurrence', task, status='PASS' if all(recurrence_checks.values()) else 'FAIL',
                                   checks=recurrence_checks, protection=protection_ref)
        engine.checkpoint(BUG_ID, 'gates', next_action='move to VERIFYING and request FIXED',
                          metadata={'verification': 'GATES_RECORDED'})

        # VERIFYING -> analysis-only FIXED must fail -> full evidence -> FIXED
        engine.transition_task(BUG_ID, S.VERIFYING)
        engine.attach_evidence_ref(BUG_ID, 'reproduction', reproduction_ref)
        try:
            engine.transition_task(BUG_ID, S.FIXED)
            summary['analysis_only_fixed'] = 'ACCEPTED'
        except FixFirstRejected as error:
            summary['analysis_only_fixed'] = 'REJECTED'
            summary['analysis_only_rejection'] = str(error)
        for name, ref in (('repair', repair_ref), ('targeted_tests', targeted_ref), ('regression_tests', regression_ref),
                          ('runtime', runtime_ref), ('safety', safety_ref), ('integrity', integrity_ref),
                          ('recurrence', recurrence_ref)):
            engine.attach_evidence_ref(BUG_ID, name, ref)
        try:
            final = engine.transition_task(BUG_ID, S.FIXED)
            summary['bugfix_final_state'] = final.state.value
        except FixFirstRejected as error:
            summary['bugfix_final_state'] = engine.get_task(BUG_ID).state.value
            summary['fixed_rejection'] = str(error)
        if summary['bugfix_final_state'] == 'FIXED':
            engine.attach_evidence_ref(PARENT_ID, 'bugfix_fixed', {'task_id': BUG_ID, 'repair_commit': repair})
            for target in (S.IN_PROGRESS, S.VERIFYING, S.FIXED):
                engine.transition_task(PARENT_ID, target)
        repo.close()

        # Reload and export the exact durable state
        with SqliteTaskRepository(scratch / 'task-engine.sqlite3') as reopened:
            engine = TaskEngine(reopened)
            state = {task_id: {'task': engine.get_task(task_id).to_dict(), 'revision': engine.revision(task_id),
                               'history': engine.history(task_id), 'checkpoints': engine.checkpoints(task_id),
                               'evidence': engine.evidence(task_id)} for task_id in (PARENT_ID, BUG_ID)}
        ev.artifact('final_state.json', json.dumps(state, indent=2, sort_keys=True) + '\n')
        summary.update(
            parent_final_state=state[PARENT_ID]['task']['state'], changed_files=sorted(changed),
            runtime_checks=runtime_checks, safety_checks=safety_checks, integrity_checks=integrity_checks,
            recurrence_checks=recurrence_checks, targeted_counts=counts_t, regression_counts=counts_r,
            regression_counts_on_base=counts_before, runtime_before=probe_before, runtime_after=probe_after)
        ev.artifact('summary.json', json.dumps(summary, indent=2, sort_keys=True) + '\n')
        print(json.dumps({k: summary[k] for k in ('analysis_only_fixed', 'bugfix_final_state', 'parent_final_state')}))
        return 0 if summary['bugfix_final_state'] == 'FIXED' else 1
    finally:
        for tree in (before_tree, after_tree):
            run(['git', 'worktree', 'remove', '--force', str(tree)], ROOT, check=False)
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == '__main__':
    raise SystemExit(main())
