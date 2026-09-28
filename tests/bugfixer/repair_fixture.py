"""Synthetic protocol evidence for unit tests, never operational attestation."""
import difflib
import hashlib
import json


def evidence(tmp_path, task):
    def artifact(name, content):
        p=tmp_path/name;p.write_text(content)
        return {'path':str(p.resolve()),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    before='value = 1\n';after='value = 2\n'
    patch=''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='before',tofile='after'))
    repair={'kind':'CODE_PATCH','before':artifact('before.py',before),'after':artifact('after.py',after),'patch':artifact('change.diff',patch)}
    def report(name, **fields):
        return artifact(name+'.json',json.dumps(dict(task_id=task.id,attempt_count=task.attempt_count,git_sha=task.git_sha,**fields)))
    result={'root_cause':'Synthetic unit-test defect','repair':repair,'reproduction':report('reproduction',outcome='REPRODUCED',details='Synthetic fixture only')}
    junit=artifact('junit.xml','<testsuite><testcase name="synthetic"/></testsuite>')
    for gate in ['targeted_tests','regression_tests']:
        result[gate]=report(gate,status='PASS',code_sha256=repair['after']['sha256'],junit=junit)
    for gate in ['safety','runtime','integrity','recurrence']:
        result[gate]=report(gate,status='PASS',checks={'synthetic_protocol_check':True},protection=repair['after'])
    return result
