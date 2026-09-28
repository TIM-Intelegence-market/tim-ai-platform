"""Allowlisted source-function reproduction with no real process/DB adapters.

This runs a validated AST of one known function with a stub process adapter. It
is not a general Python sandbox and accepts no user-selected code or executable.
"""
import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
CASE_ID = 'KEYCHAIN_ARGV_EXPOSURE_V1'
SOURCE = ROOT / 'scripts/admin/prepare_tim_credential.py'

_ALLOWED_NODES = (
    ast.FunctionDef, ast.arguments, ast.arg, ast.Assign, ast.Expr, ast.Call,
    ast.Name, ast.Load, ast.Store, ast.Constant, ast.List, ast.Tuple, ast.keyword,
    ast.Try, ast.ExceptHandler, ast.Raise, ast.If, ast.Compare, ast.NotEq,
    ast.Attribute, ast.Dict,
)


def _function(source):
    module = ast.parse(source)
    matches = [node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == 'store_keychain']
    if len(matches) != 1:
        raise ValueError('known reproduction function is absent or ambiguous')
    function = matches[0]
    if function.decorator_list or function.args.defaults or function.args.kw_defaults:
        raise ValueError('unsupported reproduction function contract')
    for node in ast.walk(function):
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError('source shape outside reproduction allowlist')
        if isinstance(node, ast.Attribute):
            if not isinstance(node.value, ast.Name) or (node.value.id, node.attr) not in {
                ('subprocess', 'run'), ('subprocess', 'TimeoutExpired'), ('result', 'returncode'),
                ('sys', 'executable'), ('json', 'dumps')}:
                raise ValueError('adapter access outside reproduction allowlist')
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id not in {'RuntimeError', 'str'}:
                    raise ValueError('call outside reproduction allowlist')
            elif not (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                      and (node.func.value.id, node.func.attr) in {('subprocess', 'run'), ('json', 'dumps')}):
                raise ValueError('call outside reproduction allowlist')
        if isinstance(node, ast.Name) and node.id.startswith('__'):
            raise ValueError('dunder access forbidden')
    return ast.Module(body=[function], type_ignores=[])


def _run_source(source):
    fixture_password = 'TIM_SYNTHETIC_REPRODUCTION_VALUE'
    calls = []

    def fake_run(command, **kwargs):
        # Keep values in memory only, expose booleans rather than command text.
        provided = kwargs.get('input')
        try:
            on_stdin = json.loads(provided).get('password') == fixture_password
        except (ValueError, TypeError, AttributeError):
            on_stdin = provided == fixture_password
        calls.append({'secret_in_argv': fixture_password in str(command),
                      'secret_on_stdin': on_stdin})
        return SimpleNamespace(returncode=0)

    adapter = SimpleNamespace(run=fake_run, TimeoutExpired=TimeoutError)
    namespace = {'__builtins__': {'str': str, 'RuntimeError': RuntimeError, 'OSError': OSError},
                 'subprocess': adapter, 'sys': SimpleNamespace(executable='fixture-python'),
                 'json': SimpleNamespace(dumps=json.dumps),
                 'KEYCHAIN_STDIN_HELPER': '/fixture/keychain_stdin.py'}
    exec(compile(_function(source), '<validated-keychain-fixture>', 'exec'), namespace)
    namespace['store_keychain'](fixture_password, 'fixture-service', 'fixture-account')
    if len(calls) != 1:
        raise ValueError('unexpected adapter call count')
    return calls[0]


def reproduce_known_case(case_id):
    if case_id != CASE_ID:
        raise ValueError('unknown reproduction case; automatic code execution forbidden')
    if SOURCE.is_symlink() or SOURCE.stat().st_size > 65536:
        raise ValueError('invalid reproduction source')
    source = SOURCE.read_text()
    observed = _run_source(source)
    return {'schema_version': 1, 'case_id': CASE_ID,
            'source': 'scripts/admin/prepare_tim_credential.py',
            'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
            'status': 'REPRODUCED' if observed['secret_in_argv'] else 'NOT_REPRODUCED',
            'invariant': 'credential_must_not_appear_in_process_arguments',
            'observed': observed, 'real_process_calls': 0, 'database_connections': 0,
            'production_touched': False, 'auto_remediation': 'NOT_SAFE',
            'scope': 'known_source_function_with_stub_adapter'}
