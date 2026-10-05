"""A same-size repair in the same second as the pre-repair run must be tested against the NEW code.

Python reuses a cached .pyc when the source's size and whole-second mtime match. BROKEN and FIXED below have
the same length, so without a bytecode-free environment the post-repair run would still see the old code.
"""
import hashlib
import os
import sys
from types import SimpleNamespace

from src.task_engine.evidence_collector import EvidenceCollector
from src.task_engine.self_heal import detect

BROKEN = 'def add(a, b):\n    return a - b\n'
FIXED = 'def add(a, b):\n    return a + b\n'
TEST = 'from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n'
PROBE = 'import json\nfrom calc import add\nprint(json.dumps({"ok": add(2, 3) == 5}))\n'


def workspace(tmp_path):
    ws = tmp_path / 'ws'
    (ws / 'tests').mkdir(parents=True)
    (ws / 'calc.py').write_text(BROKEN)
    (ws / 'tests' / 'test_calc.py').write_text(TEST)
    (ws / 'probe.py').write_text(PROBE)
    return ws


def repair_in_the_same_second(ws):
    mtime = (ws / 'calc.py').stat().st_mtime_ns
    (ws / 'calc.py').write_text(FIXED)
    os.utime(ws / 'calc.py', ns=(mtime, mtime))  # same mtime as the pre-repair source: the case that defeats the pyc check


def test_post_repair_tests_see_the_repaired_code_and_no_bytecode_is_written(tmp_path):
    ws = workspace(tmp_path)
    collector = EvidenceCollector(None, 'bug', None, ws, tmp_path / 'out', python=sys.executable)
    assert len(BROKEN) == len(FIXED)
    assert collector.pytest(('tests/test_calc.py',), 'pre')['exit_status'] == 1
    repair_in_the_same_second(ws)
    assert collector.pytest(('tests/test_calc.py',), 'post')['exit_status'] == 0
    assert not list(ws.rglob('*.pyc'))


def test_probe_and_detection_runs_leave_no_bytecode_behind(tmp_path):
    ws = workspace(tmp_path)
    recipe = SimpleNamespace(probe={'path': 'probe.py', 'sha256': hashlib.sha256(PROBE.encode()).hexdigest()})
    collector = EvidenceCollector(None, 'bug', recipe, ws, tmp_path / 'out', python=sys.executable)
    assert collector.probe('pre')['ok'] is False
    assert detect(ws, python=sys.executable, tests=('tests/test_calc.py',), out_dir=tmp_path / 'det')['failing']
    repair_in_the_same_second(ws)
    assert collector.probe('post')['ok'] is True
    assert not list(ws.rglob('*.pyc'))
