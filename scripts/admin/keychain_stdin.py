"""Administrative Keychain writer with a bounded JSON stdin contract.

No secret is accepted on argv, emitted in diagnostics or passed to another
process. Framework calls happen only after validated input, never on import.
"""
from __future__ import annotations
import ctypes
import json
import re
import sys

MAX_INPUT = 65536


def validate_payload(payload):
    if not isinstance(payload, dict) or set(payload) != {'password', 'service', 'account'}:
        raise ValueError('invalid credential payload')
    for key in ('service', 'account'):
        if not isinstance(payload[key], str) or not re.fullmatch(r'[A-Za-z0-9_.@+-]{1,128}', payload[key]):
            raise ValueError('invalid credential identity')
    if not isinstance(payload['password'], str) or not 1 <= len(payload['password']) <= 4096 or '\x00' in payload['password']:
        raise ValueError('invalid credential data')
    return payload


class NativeKeychain:
    """Existing generic-password Keychain API, scoped to this helper process."""
    def __init__(self):
        if sys.platform != 'darwin':
            raise RuntimeError('Keychain requires macOS')
        self.security = ctypes.CDLL('/System/Library/Frameworks/Security.framework/Security')
        self.core = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        pointer, number, text = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p
        signatures = {
            'SecKeychainFindGenericPassword': [pointer, number, text, number, text, pointer, pointer, ctypes.POINTER(pointer)],
            'SecKeychainAddGenericPassword': [pointer, number, text, number, text, number, pointer, ctypes.POINTER(pointer)],
            'SecKeychainItemModifyAttributesAndData': [pointer, pointer, number, pointer],
            'SecKeychainSetUserInteractionAllowed': [ctypes.c_ubyte],
        }
        for name, args in signatures.items():
            function = getattr(self.security, name)
            function.argtypes, function.restype = args, ctypes.c_int32
        self.core.CFRelease.argtypes, self.core.CFRelease.restype = [pointer], None

    def store(self, password, service, account):
        if self.security.SecKeychainSetUserInteractionAllowed(False) != 0:
            raise RuntimeError('Keychain interaction policy failed')
        service, account = service.encode('utf-8'), account.encode('utf-8')
        raw = password.encode('utf-8')
        buffer = ctypes.create_string_buffer(raw)
        item = ctypes.c_void_p()
        try:
            status = self.security.SecKeychainFindGenericPassword(
                None, len(service), service, len(account), account, None, None, ctypes.byref(item))
            if status == 0:
                status = self.security.SecKeychainItemModifyAttributesAndData(item, None, len(raw), buffer)
            elif status == -25300:  # errSecItemNotFound
                status = self.security.SecKeychainAddGenericPassword(
                    None, len(service), service, len(account), account, len(raw), buffer, ctypes.byref(item))
            if status != 0:
                raise RuntimeError('Keychain write failed')
        finally:
            ctypes.memset(buffer, 0, ctypes.sizeof(buffer))
            if item.value:
                self.core.CFRelease(item)


def main(stdin=None, stdout=None, backend_factory=NativeKeychain):
    stdin = sys.stdin.buffer if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    try:
        if len(sys.argv) != 1 and stdin is sys.stdin.buffer:
            raise ValueError('arguments are not accepted')
        raw = stdin.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError('input too large')
        payload = validate_payload(json.loads(raw))
        backend_factory().store(**payload)
    except Exception:
        # Never echo exception text: OS/library errors may carry secret input.
        stdout.write('{"status":"ERROR"}\n')
        return 2
    stdout.write('{"status":"STORED"}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
