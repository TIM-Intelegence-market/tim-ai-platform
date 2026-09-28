import json

import pytest

from src.bugfixer.reproduction import CASE_ID, _run_source, reproduce_known_case


def test_known_source_defect_reproduces_without_real_process(monkeypatch):
    import subprocess
    import socket
    def deny(*args, **kwargs):
        raise AssertionError('external access forbidden')
    monkeypatch.setattr(subprocess, 'run', deny)
    monkeypatch.setattr(subprocess, 'Popen', deny)
    monkeypatch.setattr(socket, 'socket', deny)
    result = reproduce_known_case(CASE_ID)
    assert result['status'] == 'NOT_REPRODUCED'
    assert result['observed']['secret_in_argv'] is False
    assert result['observed']['secret_on_stdin'] is True
    assert result['real_process_calls'] == result['database_connections'] == 0
    assert 'TIM_SYNTHETIC_REPRODUCTION_VALUE' not in json.dumps(result)
    assert len(result['source_sha256']) == 64


def test_fixture_distinguishes_corrected_invariant_in_memory():
    corrected = '''def store_keychain(password: str, service: str, account: str):
    result = subprocess.run(['stub-credential-adapter'], input=password)
    if result.returncode != 0:
        raise RuntimeError('fixture failed')
'''
    assert _run_source(corrected) == {'secret_in_argv': False, 'secret_on_stdin': True}


@pytest.mark.parametrize('source', [
    "def store_keychain(password, service, account):\n    open('/tmp/forbidden','w')",
    "def store_keychain(password, service, account):\n    subprocess.Popen(['forbidden'])",
    "def store_keychain(password, service, account):\n    import os",
    "def store_keychain(password, service, account):\n    password.__class__.__mro__",
])
def test_unreviewed_source_shapes_fail_closed(source):
    with pytest.raises(ValueError):
        _run_source(source)


def test_unknown_case_never_runs():
    with pytest.raises(ValueError):
        reproduce_known_case('RUN_USER_CODE')


def test_source_reproduction_is_deterministic():
    assert reproduce_known_case(CASE_ID) == reproduce_known_case(CASE_ID)


def test_historical_argv_defect_remains_detectable():
    historical = """def store_keychain(password: str, service: str, account: str):
    result = subprocess.run(['security', 'add-generic-password', '-w', password])
"""
    assert _run_source(historical) == {'secret_in_argv': True, 'secret_on_stdin': False}
