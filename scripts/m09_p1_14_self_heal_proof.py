"""Issue #12 P1.11-P1.14: autonomous repair and recurrence self-heal proof.

Run 1: fresh disposable clone of --source with the Binance clean-close defect
       re-created by this harness; the engine repairs it with the recipe
       approved in P1.10 (commits --approved-base..--approved-repair).
Run 2: another fresh clone with the same defect; the engine gets no recipe
       and no root cause - it must recognise the defect, find its own FIXED
       case, apply the stored repair, verify and only then reach FIXED.
Run 3: a different, unknown defect; the engine must block, not improvise.

Defects are injected before the engine is called; nobody edits code during a
run. Disposable clones live in the temp dir and have no remote; the task store
is a temporary file; the only network use is 127.0.0.1. No GitHub access.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.task_engine import TaskState as S  # noqa: E402
from src.task_engine.repair_executor import RepairRecipe, create_disposable_workspace, sha256_file  # noqa: E402
from src.task_engine.repository import SqliteTaskRepository  # noqa: E402
from src.task_engine.self_heal import self_heal  # noqa: E402
from src.task_engine.service import TaskEngine  # noqa: E402

TARGET = 'src/data_ingestion/binance_ws.py'
TARGETED = ('tests/test_binance_ws_clean_close.py',)
SUITE = ('tests/test_binance_ws_clean_close.py', 'tests/test_binance_ws.py', 'tests/test_binance_recovery_v2.py')
PROBE = 'scripts/m09_probes/binance_ws_clean_close.py'
PARENT = 'm09-p1-14-self-heal-proof'
PROTECTED = [ROOT, Path('/home/tim/code/tim-ai-platform')]


def git(*args, cwd=ROOT):
    return subprocess.run(['git', '-c', 'user.name=tim-proof-harness', '-c', 'user.email=harness@localhost',
                           '-c', 'commit.gpgsign=false', *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout


def approved_recipe(base, repair, source):
    before, after = git('show', f'{base}:{TARGET}'), git('show', f'{repair}:{TARGET}')
    return RepairRecipe(
        case_id='binance-ws-clean-close', approved_commit=repair, patch=git('diff', base, repair, '--', TARGET),
        allowed_paths=(TARGET,), before_sha256={TARGET: hashlib.sha256(before.encode()).hexdigest()},
        after_sha256={TARGET: hashlib.sha256(after.encode()).hexdigest()}, targeted_tests=TARGETED,
        regression_tests=SUITE, detection_tests=SUITE,
        probe={'path': PROBE, 'sha256': hashlib.sha256(git('show', f'{source}:{PROBE}').encode()).hexdigest()})


def inject_known_defect(workspace, recipe):
    patch = workspace / '.git' / 'harness-injection.patch'
    patch.write_text(recipe.patch)
    git('apply', '-R', str(patch), cwd=workspace)
    if sha256_file(workspace / TARGET) != recipe.before_sha256[TARGET]:
        raise SystemExit('injected defect does not match the historical defective file')
    git('commit', '-qam', 'harness: controlled re-injection of the clean-close defect', cwd=workspace)
    return git('rev-parse', 'HEAD', cwd=workspace).strip()


def inject_unknown_defect(workspace):
    path = workspace / TARGET
    text = path.read_text()
    broken = text.replace('if payload.get("e") != "aggTrade":', 'if payload.get("e") == "aggTrade":')
    if broken == text:
        raise SystemExit('unknown-defect injection point not found')
    path.write_text(broken)
    git('commit', '-qam', 'harness: unrelated defect without an approved recipe', cwd=workspace)
    return git('rev-parse', 'HEAD', cwd=workspace).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--approved-base', required=True)
    parser.add_argument('--approved-repair', required=True)
    parser.add_argument('--root-cause-from', required=True, help='P1.10 final_state.json')
    parser.add_argument('--source', default='HEAD')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    out = (ROOT / args.out).resolve()
    if out.exists():
        raise SystemExit(f'{out} exists; evidence runs never overwrite earlier evidence')
    source = git('rev-parse', args.source).strip()
    if git('status', '--porcelain', '--untracked-files=no').strip():
        raise SystemExit('commit all changes first: the proof runs committed code only')
    recipe = approved_recipe(git('rev-parse', args.approved_base).strip(),
                             git('rev-parse', args.approved_repair).strip(), source)
    p110 = json.loads(Path(args.root_cause_from).read_text())
    root_cause = p110['bugfix-binance-ws-clean-close']['evidence']['root_cause']
    out.mkdir(parents=True)
    scratch = Path(tempfile.mkdtemp(prefix='m09-p1-14-'))
    summary = {'source_commit': source, 'recipe': {k: v for k, v in recipe.to_dict().items() if k != 'patch'},
               'task_store': 'temporary file outside repository', 'github_access': 'NONE'}
    try:
        repo = SqliteTaskRepository(scratch / 'task-engine.sqlite3')
        engine = TaskEngine(repo)
        engine.create_task(PARENT, type='MAINTENANCE', source='issue:12', title='P1.11-P1.14 self-heal proof',
                           required_evidence=['run1_fixed', 'run2_fixed'], git_sha=source)
        for target in (S.PLANNED, S.READY):
            engine.transition_task(PARENT, target)
        runs = {}
        for name, inject, kwargs in (
                ('run1_first_autonomous_repair', lambda ws: inject_known_defect(ws, recipe),
                 {'approved_recipe': recipe, 'root_cause': root_cause, 'parent_task_id': PARENT}),
                ('run2_recurrence_self_heal', lambda ws: inject_known_defect(ws, recipe),
                 {'parent_task_id': PARENT}),
                ('run3_unknown_defect', inject_unknown_defect, {})):
            workspace = create_disposable_workspace(ROOT, source, sandbox_root=scratch)
            injected = inject(workspace)
            result = self_heal(engine, workspace, python=sys.executable, detection_tests=SUITE,
                               out_dir=out / name, forbidden_roots=PROTECTED, **kwargs)
            bundle = result.pop('bundle', None)
            runs[name] = {**result, 'injection_commit': injected,
                          'defect_commit_seen_by_executor': bundle['defect_commit'] if bundle else None,
                          'repair_commit': bundle['repair_commit'] if bundle else None,
                          'bundle': bundle and {k: bundle[k] for k in (
                              'pre_repair_repro', 'post_repair_repro', 'targeted_tests', 'regression_tests',
                              'runtime_checks', 'safety_checks', 'integrity_checks', 'recurrence_checks',
                              'pre_sha256', 'post_sha256')}}
            shutil.rmtree(workspace.parent, ignore_errors=True)
            print(name, result['outcome'], result.get('task_id'), flush=True)

        r1, r2 = runs['run1_first_autonomous_repair'], runs['run2_recurrence_self_heal']
        if r1['outcome'] == r2['outcome'] == 'FIXED':
            engine.attach_evidence_ref(PARENT, 'run1_fixed', r1['task_id'])
            engine.attach_evidence_ref(PARENT, 'run2_fixed', r2['task_id'])
            for target in (S.IN_PROGRESS, S.VERIFYING, S.FIXED):
                engine.transition_task(PARENT, target)
        repo.close()

        with SqliteTaskRepository(scratch / 'task-engine.sqlite3') as reopened:
            engine = TaskEngine(reopened)
            state = {t.task_id: {'task': t.to_dict(), 'revision': engine.revision(t.task_id),
                                 'history': engine.history(t.task_id), 'checkpoints': engine.checkpoints(t.task_id),
                                 'evidence': engine.evidence(t.task_id)} for t in engine.tasks()}
        (out / 'final_state.json').write_text(json.dumps(state, indent=2, sort_keys=True) + '\n')

        def gate(run):
            b = run['bundle'] or {}
            return {
                'ROOT_CAUSE_IDENTIFIED': bool(state.get(run['task_id'], {}).get('evidence', {}).get('root_cause')),
                'REPAIR_EXECUTED_BY_ENGINE': run['repair_commit'] is not None,
                'IMPLEMENTATION_DIFF_PRESENT': b.get('pre_sha256') != b.get('post_sha256') and bool(b),
                'PRE_REPAIR_REPRO': b.get('pre_repair_repro'),
                'POST_REPAIR_REPRO': b.get('post_repair_repro'),
                'TARGETED_TESTS': 'PASS' if b and b['targeted_tests']['failure'] == 0 else 'FAIL',
                'REGRESSION_TEST': 'PASS' if b and b['regression_tests']['failure'] == 0 else 'FAIL',
                'RUNTIME_OR_REPRO_VERIFICATION': 'PASS' if b and all(b['runtime_checks'].values()) else 'FAIL',
                'RECURRENCE_PROTECTION': 'PASS' if b and all(b['recurrence_checks'].values()) else 'FAIL',
                'FINAL_TASK_STATE': state[run['task_id']]['task']['state'],
            }
        summary.update(runs=runs, gate_run1=gate(r1), gate_run2=gate(r2),
                       run3_state=state[runs['run3_unknown_defect']['task_id']]['task']['state'],
                       run3_blocker=state[runs['run3_unknown_defect']['task_id']]['task']['blocker_reason'],
                       parent_state=state[PARENT]['task']['state'],
                       run2_used_known_case=r2.get('known_case_task_id') == r1['task_id'],
                       run2_inputs='no recipe, no root cause',
                       human_edits_during_runs=0, production_mutations=0)
        (out / 'summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n')
        ok = (summary['gate_run1']['FINAL_TASK_STATE'] == summary['gate_run2']['FINAL_TASK_STATE'] == 'FIXED'
              and summary['run2_used_known_case'] and summary['run3_state'] == 'BLOCKED'
              and summary['parent_state'] == 'FIXED')
        print(json.dumps({'P1_14_SELF_HEAL': 'PASS' if ok else 'FAIL', 'run3': summary['run3_state']}))
        return 0 if ok else 1
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == '__main__':
    raise SystemExit(main())
