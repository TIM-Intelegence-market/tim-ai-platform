"""Recurrence / self-heal loop (Issue #12, P1.14).

detect -> match known repair case -> create or resume BUGFIX -> reproduce ->
execute stored approved repair -> collect evidence -> Fix-First gate.

The only memory is the Task Engine itself: a known case is a FIXED BUGFIX
with the same defect fingerprint (task source) and a stored repair recipe.
Without a known case or an explicitly approved recipe the task is BLOCKED;
nothing is improvised. Nothing here creates or syncs GitHub issues (#68).
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

from src.task_engine.evidence_collector import EvidenceCollector, ReproductionFailed, junit_summary
from src.task_engine.fix_first import ENGINE_REPAIR_EVIDENCE, FixFirstRejected
from src.task_engine.model import TaskState
from src.task_engine.repair_executor import RepairFailed, RepairRecipe, execute_repair

S = TaskState
BUGFIX_EVIDENCE = ('root_cause', 'reproduction', 'repair', 'targeted_tests', 'regression_tests', 'safety',
                   'runtime', 'integrity', 'recurrence', *ENGINE_REPAIR_EVIDENCE, 'repair_recipe')
HELD = {S.BLOCKED, S.SAFE_STOP}


def detect(workspace, *, python, tests, out_dir):
    """Run detection tests; the fingerprint is derived from the failing test ids only."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    junit = out_dir / 'detection.junit.xml'
    subprocess.run([python, '-m', 'pytest', *tests, '-q', '-p', 'no:cacheprovider', f'--junitxml={junit}'],
                   cwd=workspace, capture_output=True, text=True, timeout=900)
    summary = junit_summary(junit)
    failing = summary['failing']
    fingerprint = hashlib.sha256('\n'.join(failing).encode()).hexdigest()[:16] if failing else None
    return {'failing': failing, 'counts': summary['counts'], 'fingerprint': fingerprint,
            'source': f'defect:{fingerprint}' if fingerprint else None, 'junit': str(junit)}


def find_known_case(engine, source):
    """Most recently fixed BUGFIX for this fingerprint that stores a repair recipe."""
    fixed = [t for t in engine.tasks(source=source, state=S.FIXED, type='BUGFIX')
             if 'repair_recipe' in engine.evidence(t.task_id)]
    if not fixed:
        return None
    task = max(fixed, key=lambda t: (t.timestamps.get('fixed_at', ''), t.task_id))
    return task, RepairRecipe.from_dict(engine.evidence(task.task_id)['repair_recipe'])


def self_heal(engine, workspace, *, python, detection_tests, out_dir, parent_task_id=None,
              approved_recipe=None, root_cause=None, forbidden_roots=()):
    out_dir = Path(out_dir)
    detection = detect(workspace, python=python, tests=detection_tests, out_dir=out_dir)
    result = {'detection': detection}
    if detection['source'] is None:
        return {**result, 'outcome': 'NO_DEFECT'}
    source = detection['source']

    existing = [t for t in engine.tasks(source=source, type='BUGFIX') if t.state not in {S.FIXED, S.FAILED}]
    held = [t for t in existing if t.state in HELD]
    if held:
        return {**result, 'outcome': 'HELD', 'task_id': held[0].task_id}  # needs an explicit decision

    known = find_known_case(engine, source)
    recipe = known[1] if known else approved_recipe
    if known:
        root_cause = engine.evidence(known[0].task_id).get('root_cause', root_cause)
    result['known_case_task_id'] = known[0].task_id if known else None

    if existing:
        task_id = existing[0].task_id
        result['resumed'] = True
    else:
        number = len(engine.tasks(source=source, type='BUGFIX')) + 1
        case = recipe.case_id if recipe else detection['fingerprint']
        task_id = f'bugfix-{case}-{number}'
        engine.create_task(task_id, type='BUGFIX', source=source, parent_task_id=parent_task_id,
                           title=f'Recurring defect {detection["fingerprint"]}',
                           objective='Repair the detected defect with the approved recipe and verify it',
                           dependencies=[known[0].task_id] if known else [],
                           required_evidence=list(BUGFIX_EVIDENCE), git_sha='0' * 40,
                           next_action='reproduce detected defect')
        result['resumed'] = False
    result['task_id'] = task_id

    if recipe is None or not root_cause:
        engine.block(task_id, 'UNKNOWN_DEFECT_NO_APPROVED_RECIPE: fingerprint ' + detection['fingerprint'])
        return {**result, 'outcome': 'BLOCKED', 'state': engine.get_task(task_id).state.value}

    for target in _path_from(engine.get_task(task_id).state):
        engine.transition_task(task_id, target)
    if 'engine_repair' in [c['step_id'] for c in engine.checkpoints(task_id)]:
        engine.block(task_id, 'RESUME_AFTER_REPAIR_REQUIRES_ORIGINAL_WORKSPACE')
        return {**result, 'outcome': 'BLOCKED', 'state': 'BLOCKED'}
    engine.attach_evidence_ref(task_id, 'repair_recipe', recipe.to_dict())
    engine.checkpoint(task_id, 'detect', next_action='reproduce defect before repair',
                      metadata={'fingerprint': detection['fingerprint'], 'failing': detection['failing'],
                                'known_case_task_id': result['known_case_task_id']})
    collector = EvidenceCollector(engine, task_id, recipe, workspace, out_dir, python=python)
    try:
        collector.collect_pre_repair()
        execution = execute_repair(engine, task_id, recipe, workspace, out_dir, forbidden_roots=forbidden_roots)
        result['bundle'] = collector.collect_post_repair(execution, root_cause=root_cause)
    except (ReproductionFailed, RepairFailed) as error:
        return {**result, 'outcome': 'BLOCKED', 'reason': str(error), 'state': engine.get_task(task_id).state.value}
    engine.transition_task(task_id, S.VERIFYING)
    try:
        engine.transition_task(task_id, S.FIXED)
    except FixFirstRejected as error:
        engine.block(task_id, f'Fix-First gate rejected: {error}'[:500])
        return {**result, 'outcome': 'BLOCKED', 'reason': str(error), 'state': 'BLOCKED'}
    return {**result, 'outcome': 'FIXED', 'state': 'FIXED'}


def _path_from(state):
    order = [S.NEW, S.PLANNED, S.READY, S.IN_PROGRESS]
    return order[order.index(state) + 1:] if state in order else []
