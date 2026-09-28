import ctypes
import io
import json
from types import SimpleNamespace

import pytest

from scripts.admin import keychain_stdin


class Function:
    def __init__(self, implementation):
        self.implementation = implementation
    def __call__(self, *args):
        return self.implementation(*args)


@pytest.fixture
def native(monkeypatch):
    calls = []
    states = {'find': -25300, 'write': 0}
    def find(*args):
        calls.append(('find', args))
        if states['find'] == 0:
            ctypes.cast(args[-1], ctypes.POINTER(ctypes.c_void_p))[0] = 42
        return states['find']
    def add(*args):
        calls.append(('add', args))
        ctypes.cast(args[-1], ctypes.POINTER(ctypes.c_void_p))[0] = 43
        return states['write']
    def modify(*args):
        calls.append(('modify', args))
        return states['write']
    security = SimpleNamespace(
        SecKeychainSetUserInteractionAllowed=Function(lambda value: calls.append(('interaction', value)) or 0),
        SecKeychainFindGenericPassword=Function(find),
        SecKeychainAddGenericPassword=Function(add),
        SecKeychainItemModifyAttributesAndData=Function(modify))
    core = SimpleNamespace(CFRelease=Function(lambda value: calls.append(('release', value.value))))
    monkeypatch.setattr(keychain_stdin.sys, 'platform', 'darwin')
    monkeypatch.setattr(keychain_stdin.ctypes, 'CDLL', lambda path: security if '/Security.' in path else core)
    return keychain_stdin.NativeKeychain(), states, calls


def test_native_add_uses_byte_length_wipes_buffer_and_releases(native):
    backend, states, calls = native
    backend.store('päss fixture', 'service', 'account')
    added = [args for name, args in calls if name == 'add'][0]
    assert added[5] == len('päss fixture'.encode())
    assert added[6].raw == b'\0' * ctypes.sizeof(added[6])
    assert ('release', 43) in calls
    assert ('interaction', False) in calls
    found = [args for name, args in calls if name == 'find'][0]
    assert found[5] is None and found[6] is None  # no old secret requested


def test_existing_item_updates_without_add(native):
    backend, states, calls = native
    states['find'] = 0
    backend.store('fixture', 'service', 'account')
    assert any(name == 'modify' for name, _ in calls)
    assert not any(name == 'add' for name, _ in calls)
    assert ('release', 42) in calls


def test_native_failure_does_not_fall_back_or_leak(native):
    backend, states, calls = native
    states['find'] = -25293
    with pytest.raises(RuntimeError, match='write failed'):
        backend.store('fixture', 'service', 'account')
    assert not any(name in {'add', 'modify'} for name, _ in calls)


def test_write_failure_still_wipes_buffer_and_releases(native):
    backend, states, calls = native
    states['write'] = -1
    with pytest.raises(RuntimeError):
        backend.store('fixture', 'service', 'account')
    args = [args for name, args in calls if name == 'add'][0]
    assert args[6].raw == b'\0' * ctypes.sizeof(args[6])
    assert ('release', 43) in calls


@pytest.mark.parametrize('raw', [b'bad json', b'{}', b'x' * 65537,
    json.dumps({'password':'fixture','service':'bad\nidentity','account':'a'}).encode()])
def test_invalid_payload_never_loads_native_library(raw):
    def forbidden():
        raise AssertionError('native access forbidden')
    output = io.StringIO()
    assert keychain_stdin.main(io.BytesIO(raw), output, forbidden) == 2
    assert output.getvalue() == '{"status":"ERROR"}\n'


def test_stdin_adapter_success_and_error_never_echo_secret():
    payload = {'password':'fixture','service':'s','account':'a'}
    received = []
    output = io.StringIO()
    backend = SimpleNamespace(store=lambda **value: received.append(value))
    assert keychain_stdin.main(io.BytesIO(json.dumps(payload).encode()), output, lambda: backend) == 0
    assert received == [payload] and 'fixture' not in output.getvalue()
    def failure(**value):
        raise RuntimeError('fixture secret from library')
    output = io.StringIO()
    assert keychain_stdin.main(io.BytesIO(json.dumps(payload).encode()), output,
                              lambda: SimpleNamespace(store=failure)) == 2
    assert 'fixture' not in output.getvalue()
