"""Machine-readable repair evidence collector (Issue #12, P1.12).

Runs the recipe's checks in the disposable workspace before and after the
engine's repair and writes content-addressed artifacts plus task-bound
reports in the format the Fix-First gate verifies. Nothing here decides
FIXED; results are data for the gate. Probe scripts are executed only when
their SHA-256 matches the approved recipe.
"""
from __future__ import annotations

from datetime import datetime, timezone
import difflib
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

from src.task_engine.repair_executor import sha256_file, workspace_violations

COLLECTOR_ID = 'src.task_engine.evidence_collector'


class ReproductionFailed(RuntimeError):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def junit_summary(path):
    tree = ET.parse(path)
    cases = list(tree.iter('testcase'))
    failing = sorted(f"{case.get('classname')}::{case.get('name')}" for case in cases
                     if case.find('failure') is not None or case.find('error') is not None)
    counts = {tag: len(list(tree.iter(tag))) for tag in ('testcase', 'failure', 'error', 'skipped')}
    return {'counts': counts, 'failing': failing}


class EvidenceCollector:
    def __init__(self, engine, task_id, recipe, workspace, out_dir, *, python):
        self.engine, self.task_id, self.recipe = engine, task_id, recipe
        self.workspace, self.out, self.python = Path(workspace), Path(out_dir), python
        self.out.mkdir(parents=True, exist_ok=True)
        self.pre = None

    # -- artifacts ---------------------------------------------------------
    def artifact(self, name, content):
        path = self.out / name
        path.write_text(content)
        return {'path': str(path.resolve()), 'sha256': sha256_file(path)}

    def report(self, name, **fields):
        task = self.engine.get_task(self.task_id)
        body = {**fields, 'task_id': task.task_id, 'attempt_count': task.attempt_count, 'git_sha': task.git_sha,
                'collector': COLLECTOR_ID, 'collected_at': _now()}
        return self.artifact(f'{name}.json', json.dumps(body, indent=2, sort_keys=True) + '\n')

    # -- checks ------------------------------------------------------------
    def pytest(self, tests, name):
        junit = self.out / f'{name}.junit.xml'
        result = subprocess.run([self.python, '-m', 'pytest', *tests, '-q', '-p', 'no:cacheprovider',
                                 f'--junitxml={junit}'], cwd=self.workspace, capture_output=True, text=True,
                                timeout=900)
        summary = junit_summary(junit)
        return {'exit_status': result.returncode, 'tests': list(tests),
                'junit': {'path': str(junit.resolve()), 'sha256': sha256_file(junit)}, **summary}

    def probe(self, name):
        if not self.recipe.probe:
            return None
        script = self.workspace / self.recipe.probe['path']
        if sha256_file(script) != self.recipe.probe['sha256']:
            raise ReproductionFailed('probe script does not match the approved recipe')
        result = subprocess.run([self.python, str(script)], cwd=self.workspace, capture_output=True, text=True,
                                timeout=120)
        if result.returncode != 0:
            raise ReproductionFailed(f'probe exited {result.returncode}: {result.stderr[-500:]}')
        data = json.loads(result.stdout)
        data['artifact'] = self.artifact(f'{name}.probe.json', result.stdout)
        return data

    # -- phases ------------------------------------------------------------
    def collect_pre_repair(self):
        """Reproduce the defect before repair; BLOCKED if it does not reproduce."""
        tests = self.pytest(self.recipe.targeted_tests, 'pre_repair_targeted')
        probe = self.probe('pre_repair')
        reproduced = tests['counts']['failure'] > 0 and (probe is None or probe['defect_present'])
        self.pre = {'at': _now(), 'defect_commit': self._head(), 'targeted': tests, 'probe': probe,
                    'status': 'FAIL_AS_EXPECTED' if reproduced else 'NOT_REPRODUCED'}
        if not reproduced:
            self.engine.block(self.task_id, 'evidence collector: defect did not reproduce before repair')
            raise ReproductionFailed('defect did not reproduce before repair')
        self.engine.checkpoint(self.task_id, 'pre_repair_repro', next_action='execute approved repair',
                               metadata={'verification': 'PRE_REPAIR_REPRO_FAIL_AS_EXPECTED',
                                         'failing_tests': tests['failing']})
        return self.pre

    def _head(self):
        return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=self.workspace, capture_output=True, text=True,
                              check=True).stdout.strip()

    def _show(self, commit, path):
        return subprocess.run(['git', 'show', f'{commit}:{path}'], cwd=self.workspace, capture_output=True,
                              text=True, check=True).stdout

    def collect_post_repair(self, execution, *, root_cause):
        """Verify the repaired workspace and attach every evidence reference to the task."""
        if self.pre is None:
            raise ReproductionFailed('pre-repair reproduction was not collected')
        if execution.get('outcome') != 'APPLIED' or len(execution['changed_paths']) != 1:
            raise ReproductionFailed('exactly one applied single-file repair is supported')
        path = execution['changed_paths'][0]
        before = self._show(execution['defect_commit'], path)
        after = self._show(execution['repair_commit'], path)
        patch = ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                             fromfile='before', tofile='after'))
        repair = {'kind': 'CODE_PATCH', 'before': self.artifact('before.src', before),
                  'after': self.artifact('after.src', after), 'patch': self.artifact('change.diff', patch)}

        targeted = self.pytest(self.recipe.targeted_tests, 'post_repair_targeted')
        regression = self.pytest(self.recipe.regression_tests, 'post_repair_regression')
        probe = self.probe('post_repair')
        head = self._head()
        tracked = subprocess.run(['git', 'ls-files', '--', *self.recipe.targeted_tests], cwd=self.workspace,
                                 capture_output=True, text=True, check=True).stdout.split()

        def passed(result):
            return result['exit_status'] == 0 and result['counts']['testcase'] > 0 and not any(
                result['counts'][k] for k in ('failure', 'error', 'skipped'))

        post_status = 'PASS' if passed(targeted) and (probe is None or not probe['defect_present']) else 'FAIL'
        refs = {'root_cause': root_cause, 'repair': repair}
        refs['repair_execution'] = self.report('repair_execution', **execution)
        refs['pre_repair_repro'] = self.report(
            'pre_repair_repro', status=self.pre['status'], defect_commit=self.pre['defect_commit'],
            junit=self.pre['targeted']['junit'], failing=self.pre['targeted']['failing'],
            probe=None if self.pre['probe'] is None else self.pre['probe']['artifact'], at=self.pre['at'])
        refs['post_repair_repro'] = self.report(
            'post_repair_repro', status=post_status, junit=targeted['junit'],
            probe=None if probe is None else probe['artifact'])
        refs['reproduction'] = self.report(
            'reproduction', outcome='REPRODUCED',
            details=f"targeted tests failed before repair: {', '.join(self.pre['targeted']['failing'])}",
            pre_repair_repro=refs['pre_repair_repro'])
        for gate, result in (('targeted_tests', targeted), ('regression_tests', regression)):
            refs[gate] = self.report(gate, status='PASS' if passed(result) else 'FAIL',
                                     code_sha256=repair['after']['sha256'], junit=result['junit'],
                                     counts=result['counts'], tests=result['tests'])
        runtime_checks = {'defect_reproduced_before': self.pre['probe'] is None or self.pre['probe']['defect_present'],
                          'defect_absent_after': probe is None or not probe['defect_present'],
                          'targeted_tests_pass_after': passed(targeted)}
        if probe is not None:
            runtime_checks.update({f'probe_{k}': v for k, v in probe['checks'].items()})
        refs['runtime'] = self.report('runtime', status='PASS' if all(runtime_checks.values()) else 'FAIL',
                                      checks=runtime_checks)
        safety_checks = {'workspace_disposable': not workspace_violations(self.workspace),
                         'changed_paths_allowlisted': set(execution['changed_paths']) <= set(self.recipe.allowed_paths),
                         'executor_exit_status_zero': execution['exit_status'] == 0}
        refs['safety'] = self.report('safety', status='PASS' if all(safety_checks.values()) else 'FAIL',
                                     checks=safety_checks)
        integrity_checks = {
            'before_matches_pre_hash': hashlib.sha256(before.encode()).hexdigest() == execution['pre_sha256'][path],
            'after_matches_post_hash': hashlib.sha256(after.encode()).hexdigest() == execution['post_sha256'][path],
            'after_matches_recipe': execution['post_sha256'][path] == self.recipe.after_sha256.get(path),
            'workspace_head_is_repair_commit': head == execution['repair_commit'],
            'workspace_clean': not subprocess.run(['git', 'status', '--porcelain', '--untracked-files=no'],
                                                  cwd=self.workspace, capture_output=True, text=True).stdout.strip(),
            'engine_diff_artifact_intact': sha256_file(execution['git_diff']['path']) == execution['git_diff']['sha256'],
        }
        refs['integrity'] = self.report('integrity', status='PASS' if all(integrity_checks.values()) else 'FAIL',
                                        checks=integrity_checks)
        recurrence_checks = {
            'targeted_tests_failed_before': self.pre['targeted']['counts']['failure'] > 0,
            'targeted_tests_pass_after': passed(targeted),
            'previously_failing_tests_now_pass': set(self.pre['targeted']['failing']).isdisjoint(targeted['failing'])
                                                 and bool(self.pre['targeted']['failing']),
            'targeted_tests_tracked_in_repository': sorted(tracked) == sorted(self.recipe.targeted_tests),
        }
        protection = self.artifact('recurrence_protection.txt', ''.join(
            self._show(execution['repair_commit'], test) for test in self.recipe.targeted_tests))
        refs['recurrence'] = self.report('recurrence', status='PASS' if all(recurrence_checks.values()) else 'FAIL',
                                         checks=recurrence_checks, protection=protection)
        for name, reference in refs.items():
            self.engine.attach_evidence_ref(self.task_id, name, reference)
        task = self.engine.get_task(self.task_id)
        bundle = {'collector': COLLECTOR_ID, 'task_id': task.task_id, 'git_sha': task.git_sha,
                  'attempt_count': task.attempt_count, 'collected_at': _now(), 'case_id': self.recipe.case_id,
                  'defect_commit': execution['defect_commit'], 'repair_commit': execution['repair_commit'],
                  'pre_repair_repro': self.pre['status'], 'post_repair_repro': post_status,
                  'targeted_tests': targeted['counts'], 'regression_tests': regression['counts'],
                  'runtime_checks': runtime_checks, 'safety_checks': safety_checks,
                  'integrity_checks': integrity_checks, 'recurrence_checks': recurrence_checks,
                  'pre_sha256': execution['pre_sha256'], 'post_sha256': execution['post_sha256'],
                  'evidence': refs}
        self.artifact('bundle.json', json.dumps(bundle, indent=2, sort_keys=True) + '\n')
        self.engine.checkpoint(self.task_id, 'post_repair_evidence', next_action='move to VERIFYING and request FIXED',
                               metadata={'verification': 'POST_REPAIR_' + post_status})
        return bundle
