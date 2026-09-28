"""Isolated fault injection for the derived-artifact repair contract only."""
import hashlib
import json
from pathlib import Path
import tempfile

from .executor import DiagnosticRepairExecutor, NAMESPACE, missing_summary_event
from .processing import Event, fingerprint


def _bundle(event):
    body = {'schema_version': 1, 'incident_id': fingerprint(event),
            'event': event.safe_dict(), 'scope': 'sanitized_event_processing_only'}
    raw = json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    return {'body': body, 'sha256': hashlib.sha256(raw).hexdigest()}


def self_heal_proof(base_directory):
    """Retain fixture evidence without inspecting any runtime log or database.

    A successful report does not meet the production recurrence/runtime gates.
    Callers must not promote this proof to live-data readiness or incident FIXED.
    """
    base = Path(base_directory)
    if not base.is_dir():
        raise ValueError('existing isolated proof parent directory required')
    workspace = Path(tempfile.mkdtemp(prefix='isolated-self-heal-', dir=base))
    source = Event('2026-01-01T00:00:00+00:00', 'synthetic.proof',
                   'TimeoutError', 'network timeout in isolated diagnostic fixture')
    bundle = _bundle(source)
    sentinel = workspace / 'untouched-fixture.json'
    sentinel_bytes = b'{"scope":"synthetic fixture only","attempts":7,"outbox":[1,2,3]}\n'
    sentinel.write_bytes(sentinel_bytes)
    observer = DiagnosticRepairExecutor(workspace)
    observe = observer.execute(missing_summary_event(), bundle)
    executor = DiagnosticRepairExecutor(workspace, enabled=True)
    detected = executor.detect(bundle)
    repaired = executor.execute(detected, bundle)
    repeated = executor.execute(missing_summary_event(), bundle)
    unknown = executor.execute(Event(source.timestamp, 'synthetic.proof', '',
                                     'unrecognized repair request'), bundle)

    class VerificationFailure(DiagnosticRepairExecutor):
        @staticmethod
        def _verify(directory, name, expected):
            return False

    rollback_base = workspace / 'rollback-fixture'
    rollback_base.mkdir(mode=0o700)
    failed = VerificationFailure(rollback_base, enabled=True).execute(missing_summary_event(), bundle)
    rollback_target = rollback_base / NAMESPACE / ('summary-' + bundle['sha256'] + '.json')
    checks = {
        'default_observe_does_not_repair': observe['body']['decision'] == 'OBSERVE_ONLY',
        'missing_artifact_detected': detected is not None,
        'reproduced_then_repaired': repaired['body']['decision'] == 'REPAIRED',
        'repeat_is_idempotent': repeated['body']['decision'] == 'NO_CHANGE',
        'recurrence_absent_at_immediate_check': executor.detect(bundle) is None,
        'unknown_request_stops_and_escalates': unknown['body']['safe_stop']
            and unknown['body']['escalation_task']['state'] == 'SAFE_STOP',
        'verification_failure_rolls_back_only_new_artifact': failed['body'].get('rollback') == 'RESTORED_ABSENCE'
            and not rollback_target.exists(),
        'unrelated_fixture_unchanged': sentinel.read_bytes() == sentinel_bytes,
    }
    result = {'schema_version': 1, 'scope': 'ISOLATED_DERIVED_ARTIFACT_ONLY',
              'status': 'PASS' if all(checks.values()) else 'FAIL', 'checks': checks,
              'runtime_repair_proven': False, 'live_data_ready': False,
              'production_data_accessed': False, 'production_recurrence_window': 'NOT_OBSERVED',
              'workspace': str(workspace.absolute()),
              'evidence': {'repair': repaired, 'idempotency': repeated,
                           'unknown_escalation': unknown, 'rollback': failed}}
    report = workspace / 'self-heal-proof.json'
    report.write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    return {**result, 'report_path': str(report.absolute())}
