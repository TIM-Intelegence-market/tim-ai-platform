"""Fail-closed release gate over fresh, content-bound local verifier evidence.

This reads small reports only. It never scans a market database, repairs data,
starts a worker or activates collection/trading. A hash proves report identity,
not report truth: producers must be trusted local verifiers, never LLM output.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat


SOURCE_FILES = (
    'main.py', 'src/data_ingestion/durable.py', 'src/data_ingestion/ingress.py',
    'src/database/safety.py', 'src/bugfixer/processing.py', 'src/bugfixer/worker.py',
    'src/bugfixer/store.py', 'src/bugfixer/safety.py', 'src/bugfixer/remediation.py',
    'src/bugfixer/readiness.py', 'src/bugfixer/executor.py', 'src/bugfixer/diagnosis.py',
    'src/collection_reporting/verified.py', 'scripts/verified_live_collection.py',
)

# Each gate requires specific measurements, not a single caller-supplied PASS.
REQUIRED = {
    'safety': {'mode': 'OBSERVE', 'live_trading': False, 'execution': False,
               'strict_ordering': True, 'determinism': True, 'lookahead_safety': True,
               'production_deletions': 0, 'queue_clears': 0, 'outbox_clears': 0,
               'attempt_resets': 0, 'events_skipped': 0},
    'runtime': {'tim_workers': 1, 'repair_workers': 1, 'healthy': True,
                'loaded_source_verified': True, 'resources_within_budget': True},
    'observer': {'continuous_source_coverage': True, 'checkpoint_verified': True,
                 'pending_bytes': 0, 'pending_tracebacks': 0, 'healthy': True},
    'incidents': {'unresolved': 0, 'unknown': 0, 'safe_stop': 0},
    'queue': {'pending': 0, 'quarantined': 0, 'terminal_blocked': 0,
              'catchup_complete': True, 'ordering_verified': True},
    'data_quality': {'coverage_verified': True, 'lineage_verified': True,
                     'gaps': 0, 'future_events': 0, 'stale_source_events': 0},
    'integrity': {'cursor_hash_verified': True, 'raw_data_preserved': True,
                  'no_duplicate_side_effects': True, 'outbox_accounted': True},
    'regression': {'targeted_tests_passed': True, 'regression_tests_passed': True,
                   'safety_negative_tests_passed': True, 'test_database_isolated': True},
    'replay': {'deterministic': True, 'lookahead_safe': True, 'reproduced': True},
    'self_heal': {'actual_repair_verified': True, 'rollback_verified': True,
                  'recurrence_protected': True, 'allowlist_enforced': True},
}
ISOLATED_GATES = frozenset({'regression', 'replay', 'self_heal'})


def _read(path, *, bound=262144):
    path = Path(path).absolute()
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError('evidence symlink forbidden')
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > bound:
            raise ValueError('invalid evidence type or size')
        data = handle.read(bound + 1)
    if len(data) > bound:
        raise ValueError('evidence exceeds bound')
    return data


def source_digest(root):
    """Bounded explicit critical-source set; source edits invalidate old proof."""
    hashes = {name: hashlib.sha256(_read(Path(root) / name, bound=1048576)).hexdigest()
              for name in SOURCE_FILES}
    return hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()


def _date(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timestamp needs timezone')
    return parsed


def evaluate_readiness(manifest_path, *, repo_root, now=None, runtime_id=None):
    """Recompute release permission. Missing, old, foreign or partial proof stops.

    A production release caller must additionally supply its freshly observed
    runtime_id (PID:start-generation), so a prior process cannot authorize it.
    CLI audit may omit it, but that audit cannot authorize a live collection.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('readiness time needs timezone')
    result = {'schema_version': 1, 'LIVE_DATA_READINESS': 'SAFE_STOP',
              'live_data_release_allowed': False, 'live_trading': False,
              'execution': False, 'checked_at': now.isoformat(), 'checks': {},
              'blockers': [], 'scope': 'LIVE_DATA_RELEASE_ONLY'}
    try:
        current_code = source_digest(repo_root)
        path = Path(manifest_path).absolute()
        manifest = json.loads(_read(path))
        if (not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int
                or manifest['schema_version'] != 1 or manifest.get('code_sha256') != current_code
                or not isinstance(manifest.get('runtime_id'), str) or not manifest['runtime_id']
                or len(manifest['runtime_id']) > 128
                or not isinstance(manifest.get('artifacts'), dict)
                or set(manifest['artifacts']) != set(REQUIRED)):
            raise ValueError('invalid manifest')
        result['code_sha256'] = current_code
        result['manifest_sha256'] = hashlib.sha256(_read(path)).hexdigest()
        if runtime_id is None or manifest['runtime_id'] != runtime_id:
            result['blockers'].append('runtime_identity_unverified')
        for gate, required in REQUIRED.items():
            try:
                reference = manifest['artifacts'][gate]
                if not isinstance(reference, dict) or set(reference) != {'path', 'sha256'}:
                    raise ValueError('invalid reference')
                relative = Path(reference['path'])
                if relative.is_absolute() or '..' in relative.parts:
                    raise ValueError('evidence outside manifest directory')
                raw = _read(path.parent / relative)
                if hashlib.sha256(raw).hexdigest() != reference['sha256']:
                    raise ValueError('evidence hash mismatch')
                report = json.loads(raw)
                expected_scope = 'ISOLATED_VERIFICATION' if gate in ISOLATED_GATES else 'LIVE_RUNTIME'
                age = (now - _date(report['observed_at'])).total_seconds()
                if (type(report.get('schema_version')) is not int or report['schema_version'] != 1
                        or report.get('gate') != gate or report.get('status') != 'PASS'
                        or report.get('scope') != expected_scope
                        or report.get('code_sha256') != current_code
                        or report.get('runtime_id') != manifest['runtime_id']
                        or not 0 <= age <= (86400 if gate in ISOLATED_GATES else 60)):
                    raise ValueError('unusable evidence')
                checks = report['checks']
                if not isinstance(checks, dict) or any(
                        type(checks.get(key)) is not type(expected) or checks[key] != expected
                        for key, expected in required.items()):
                    raise ValueError('required check not satisfied')
                result['checks'][gate] = True
            except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError):
                result['checks'][gate] = False
                result['blockers'].append(gate + '_evidence_missing_invalid_or_failed')
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError):
        result['blockers'].append('manifest_missing_invalid_or_source_changed')
    if not result['blockers'] and all(result['checks'].get(gate) is True for gate in REQUIRED):
        result['LIVE_DATA_READINESS'] = 'PASS'
        result['live_data_release_allowed'] = True
    return result
