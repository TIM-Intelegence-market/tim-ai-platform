"""One isolated repair-candidate run: reproduce -> patch check -> gates -> candidate -> review artifact.

This ties the separately delivered pieces of #17 (reproduction in isolated workspaces), #18 (one gate engine,
SAFE_STOP on critical failures) and #20 (candidate status and review artifact) into the order #20 requires.
Nothing here applies a patch, touches git, merges, deploys or marks a task FIXED: the result is a record for
human review. Invalid input never raises; it ends the run as BLOCKED.
"""
import hashlib

from src.repair_gates.aggregate import decide
from src.repair_gates.integrity import db_integrity, determinism, lookahead_safety, queue_integrity
from src.repair_gates.result import GateResult, GateStatus
from src.repair_repro.result import ReproStatus
from src.repair_repro.workspace import replay_twice
from src.repair_workflow.candidate import candidate_status
from src.repair_workflow.diff_limits import check_diff
from src.repair_workflow.review_artifact import build_review_artifact

REQUIRED_GATES = ('determinism', 'lookahead_safety', 'db_integrity', 'queue_integrity', 'targeted_tests')


def _tests_gate(test_reports) -> GateResult:
    if not isinstance(test_reports, dict) or not test_reports:
        return GateResult('targeted_tests', GateStatus.FAIL, 'no test reports')
    failed = sorted(str(name) for name, status in test_reports.items() if status != 'PASS')
    if failed:
        return GateResult('targeted_tests', GateStatus.FAIL, 'failed: ' + ', '.join(failed))
    return GateResult('targeted_tests', GateStatus.PASS)


def gate_results(evidence) -> list:
    """Every gate is computed from evidence; a missing value makes that gate FAIL, never PASS."""
    ev = evidence if isinstance(evidence, dict) else {}
    return [determinism(ev.get('first_digest'), ev.get('second_digest')),
            lookahead_safety(ev.get('events'), ev.get('cutoff')),
            db_integrity(ev.get('test_db_url'), ev.get('runtime_db_url')),
            queue_integrity(ev.get('queue_before'), ev.get('queue_after')),
            _tests_gate(ev.get('test_reports'))]


def _stopped(stage, reasons, **parts):
    return {'stage': stage, 'candidate': {'status': 'BLOCKED', 'reasons': sorted(reasons), 'auto_merge': False,
                                          'fixed': False},
            'fixed': False, 'auto_merge': False, **parts}


def run_patch_pipeline(*, incident_id, task_id, case_id, reproduce, payload, patch_diff, allowed_paths,
                       evidence, reproduction_waiver=None) -> dict:
    """Run one candidate through the full isolated workflow and stop before any merge."""
    try:
        for name, value in (('incident_id', incident_id), ('task_id', task_id), ('case_id', case_id)):
            if not isinstance(value, str) or not value.strip():
                return _stopped('INPUT', [f'invalid {name}'])
        repro = replay_twice(case_id, reproduce, payload)
        record = {'incident_id': incident_id, 'task_id': task_id, 'reproduction': repro.to_dict()}
        if reproduction_waiver is not None:
            record['reproduction_waiver'] = reproduction_waiver
        waived = repro.status is ReproStatus.INSUFFICIENT_EVIDENCE and isinstance(reproduction_waiver, str) \
            and reproduction_waiver.strip()
        if repro.status is not ReproStatus.REPRODUCED and not waived:
            # No patch is looked at before the defect is reproduced (#20 hard rule).
            return _stopped('REPRODUCTION', [f'reproduction is {repro.status.value}'], reproduction=repro.to_dict())
        diff = check_diff(patch_diff, allowed_paths)
        decision = decide(REQUIRED_GATES, gate_results(evidence))
        record.update(diff_check=diff, gate_decision=decision)
        candidate = candidate_status(record)
        patch_sha256 = hashlib.sha256(patch_diff.encode() if isinstance(patch_diff, str) else b'').hexdigest()
        reports = (evidence or {}).get('test_reports') if isinstance(evidence, dict) else None
        artifact = build_review_artifact(
            incident_id=incident_id, task_id=task_id, reproduction_ref=repro.to_dict(), patch_sha256=patch_sha256,
            diff_check=diff, test_reports=reports if isinstance(reports, dict) and reports else {'targeted_tests': 'MISSING'},
            gate_decision=decision)
        return {'stage': 'REVIEW', 'reproduction': repro.to_dict(), 'diff_check': diff, 'gate_decision': decision,
                'candidate': candidate, 'review_artifact': artifact,
                'linkage': {'incident_id': incident_id, 'task_id': task_id, 'case_id': case_id,
                            'reproduction_refs': list(repro.evidence_refs), 'patch_sha256': patch_sha256,
                            'artifact_sha256': artifact['artifact_sha256']},
                'fixed': False, 'auto_merge': False}
    except Exception as exc:          # never let a malformed candidate look like progress
        return _stopped('INPUT', [f'pipeline rejected input: {type(exc).__name__}'])
