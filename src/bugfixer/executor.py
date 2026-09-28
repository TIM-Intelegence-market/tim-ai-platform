"""Code-owned repair of one missing, derived diagnostic artifact.

This is local observer maintenance, never a runtime/production repair dispatcher.
Model output, editable recipe files and caller attestations have no authority here.
Existing artifacts are never overwritten. A corrupt/foreign artifact stops repair.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
from types import MappingProxyType

from .evidence import MAX_BUNDLE_BYTES, validate_bundle
from .model import State
from .processing import Event, classify, fingerprint
from .safety import Policy
from .tasks import TaskState

SCOPE = 'LOCAL_DERIVED_DIAGNOSTIC_ARTIFACT_ONLY'
NAMESPACE = 'diagnostic-repairs-v1'
_OWNER = b'TIM bugfixer derived diagnostic artifacts v1\n'
_MAX = MAX_BUNDLE_BYTES + 4096


def missing_summary_event(timestamp='1970-01-01T00:00:00+00:00'):
    return Event(timestamp, 'bugfixer.diagnostic_summary', 'FileNotFoundError',
                 'configuration: derived incident summary missing',
                 'DIAGNOSTIC_SUMMARY_MISSING_V1')


@dataclass(frozen=True)
class Recipe:
    remediation_id: str
    version: str
    fingerprint: str
    category: str
    risk: str
    action: str


_RECIPE = Recipe('REBUILD_MISSING_DIAGNOSTIC_SUMMARY', '1.0.0',
                 fingerprint(missing_summary_event()), 'CONFIGURATION', 'LOW',
                 'create_missing_content_addressed_summary')
REGISTRY = MappingProxyType({_RECIPE.remediation_id: _RECIPE})


class RepairBlocked(ValueError):
    """No broader filesystem or runtime authority may be inferred from failure."""


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode() + b'\n'


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _summary(bundle):
    # Validate and round-trip so caller mutation cannot change execution inputs.
    raw = _encode(bundle)
    if len(raw) > MAX_BUNDLE_BYTES:
        raise RepairBlocked('source_evidence_too_large')
    bundle = json.loads(raw)
    event = validate_bundle(bundle)
    result = classify(event)
    summary = {'schema_version': 1, 'scope': SCOPE,
               'source_evidence_sha256': bundle['sha256'],
               'incident_id': fingerprint(event), 'category': result.category,
               'matched_rule': result.matched_rule, 'event': event.safe_dict()}
    return 'summary-' + bundle['sha256'] + '.json', _encode(summary), bundle


def _read(directory_fd, name):
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, 'rb') as handle:
        info = os.fstat(handle.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != os.getuid() or info.st_size > _MAX):
            raise RepairBlocked('unsafe_artifact_type_owner_links_or_size')
        raw = handle.read(_MAX + 1)
        if len(raw) > _MAX:
            raise RepairBlocked('artifact_too_large')
        return raw


def _write_all(fd, raw):
    view = memoryview(raw)
    while view:
        count = os.write(fd, view)
        if count <= 0:
            raise OSError('short artifact write')
        view = view[count:]
    os.fsync(fd)


def _new_file(directory_fd, name, raw):
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=directory_fd)
    try:
        _write_all(fd, raw)
    finally:
        os.close(fd)
    os.fsync(directory_fd)


@contextmanager
def _base(path):
    """Walk absolute ancestors with openat/O_NOFOLLOW, then pin the directory."""
    path = Path(path).absolute()
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            if part in {'.', '..'}:
                raise RepairBlocked('ambiguous_base_path')
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


class DiagnosticRepairExecutor:
    def __init__(self, base_directory, *, policy=Policy(), enabled=False):
        if type(enabled) is not bool:
            raise ValueError('local maintenance enabled must be boolean')
        policy.verify()
        self.base_directory = Path(base_directory).absolute()
        self.policy, self.enabled = policy, enabled

    @contextmanager
    def _workspace(self):
        with _base(self.base_directory) as parent:
            created = False
            try:
                os.mkdir(NAMESPACE, 0o700, dir_fd=parent)
                created = True
            except FileExistsError:
                pass
            directory = os.open(NAMESPACE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            try:
                info = os.fstat(directory)
                if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                    raise RepairBlocked('workspace_owner_or_permissions')
                if created:
                    _new_file(directory, 'OWNER', _OWNER)
                if _read(directory, 'OWNER') != _OWNER:
                    raise RepairBlocked('unowned_workspace')
                lock = os.open('executor.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                               0o600, dir_fd=directory)
                try:
                    info = os.fstat(lock)
                    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                            or info.st_uid != os.getuid()):
                        raise RepairBlocked('unsafe_executor_lock')
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        raise RepairBlocked('executor_already_running') from None
                    yield directory
                finally:
                    os.close(lock)
            finally:
                os.close(directory)

    def _report(self, event, decision, *, reason, **fields):
        report = {'schema_version': 1, 'scope': SCOPE, 'decision': decision,
                  'reason': reason, 'executed': False, 'safe_stop': decision == 'SAFE_STOP',
                  'incident_id': fingerprint(event), 'event': event.safe_dict(),
                  'policy_mode': self.policy.mode, 'local_artifact_maintenance': self.enabled,
                  'production_mutation': False, 'runtime_repair_proven': False,
                  'live_data_ready': False, **fields}
        if decision == 'SAFE_STOP':
            report['escalation_task'] = {
                'id': 'diagnostic-' + fingerprint(event), 'state': 'SAFE_STOP',
                'type': 'INVESTIGATION', 'reason': reason,
                'next_action': 'Review preserved evidence and create or update GitHub task; no runtime repair authorized'}
        return {'body': report, 'sha256': _sha(_encode(report))}

    def _persist(self, directory, result):
        raw = _encode(result)
        name = 'evidence-' + _sha(raw) + '.json'
        existing = _read(directory, name)
        if existing is None:
            _new_file(directory, name, raw)
        elif existing != raw:
            raise RepairBlocked('conflicting_repair_evidence')
        return {**result, 'evidence_path': str(self.base_directory / NAMESPACE / name)}

    def detect(self, bundle):
        """Bounded inspection only; absence gives the single exact supported event."""
        name, expected, _ = _summary(bundle)
        with _base(self.base_directory) as parent:
            try:
                directory = os.open(NAMESPACE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            except FileNotFoundError:
                return missing_summary_event()
            try:
                if _read(directory, 'OWNER') != _OWNER:
                    raise RepairBlocked('unowned_workspace')
                actual = _read(directory, name)
            finally:
                os.close(directory)
        if actual is None:
            return missing_summary_event()
        if actual != expected:
            raise RepairBlocked('existing_artifact_conflicts_with_source')
        return None

    @staticmethod
    def _verify(directory, name, expected):
        return _read(directory, name) == expected

    @staticmethod
    def _rollback(directory, name, identity, expected):
        """Remove only the new file created by this attempt, with unchanged content."""
        try:
            info = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if (not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != identity
                    or info.st_nlink != 1 or _read(directory, name) != expected):
                return 'REFUSED_CHANGED_ARTIFACT'
            os.unlink(name, dir_fd=directory)
            os.fsync(directory)
            return 'RESTORED_ABSENCE'
        except FileNotFoundError:
            return 'ALREADY_ABSENT'
        except (OSError, ValueError):
            return 'ROLLBACK_FAILED_SAFE_STOP'

    def _execute(self, directory, event, name, expected, bundle):
        before = _read(directory, name)
        common = {'recipe': {'id': _RECIPE.remediation_id, 'version': _RECIPE.version,
                             'risk': _RECIPE.risk, 'action': _RECIPE.action},
                  'source_evidence_sha256': bundle['sha256'], 'artifact_name': name,
                  'before': {'exists': before is not None, 'sha256': _sha(before) if before is not None else None}}
        if before == expected:
            return self._persist(directory, self._report(event, 'NO_CHANGE', reason='artifact_already_verified',
                **common, after={'exists': True, 'sha256': _sha(expected)}, idempotent=True))
        if before is not None:
            return self._persist(directory, self._report(event, 'SAFE_STOP',
                reason='existing_artifact_conflicts_with_source', **common))
        # Two independent bounded observations reproduce the absence before mutation.
        if _read(directory, name) is not None:
            raise RepairBlocked('artifact_changed_during_reproduction')
        reproduction = {'outcome': 'REPRODUCED', 'observations': 2, 'failure': 'MISSING_ARTIFACT'}
        prepared = self._persist(directory, self._report(event, 'PREPARED',
            reason='absence_reproduced_before_local_artifact_creation', **common,
            reproduction=reproduction, expected_after_sha256=_sha(expected)))
        common['before_evidence_sha256'] = prepared['sha256']
        identity = None
        try:
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
            try:
                info = os.fstat(fd)
                identity = info.st_dev, info.st_ino
                _write_all(fd, expected)
            finally:
                os.close(fd)
            os.fsync(directory)
            if not self._verify(directory, name, expected):
                raise RepairBlocked('artifact_verification_failed')
            # Regeneration protects against nondeterminism; repeated observation is a
            # local recurrence check, never a production monitoring-window claim.
            repeated_name, repeated_bytes, _ = _summary(bundle)
            if (repeated_name != name or repeated_bytes != expected
                    or not self._verify(directory, name, expected)):
                raise RepairBlocked('artifact_regression_or_recurrence_failed')
            result = self._report(event, 'REPAIRED', reason='missing_derived_summary_recreated',
                **common, executed=True, after={'exists': True, 'sha256': _sha(expected)},
                reproduction=reproduction,
                verification={'status': 'PASS', 'content_matches_source': True,
                              'deterministic_regeneration': True, 'repeated_read_matches': True},
                recurrence_scope='immediate_local_artifact_only', rollback='NOT_NEEDED')
            # Failure to durably preserve evidence rolls back the new artifact too.
            try:
                return self._persist(directory, result)
            except (OSError, ValueError):
                return {**result, 'evidence_persistence': 'UNAVAILABLE_SAFE_STOP'}
        except (OSError, ValueError):
            rollback = self._rollback(directory, name, identity, expected) if identity else 'NO_ARTIFACT_CREATED'
            result = self._report(event, 'SAFE_STOP', reason='repair_or_evidence_verification_failed',
                                  **common, executed=identity is not None, rollback=rollback,
                                  attempted_after_sha256=_sha(expected))
            return self._persist(directory, result)

    def execute(self, event, bundle, *, store=None):
        """Only enabled local maintenance may create a missing owned artifact.

        An optional observer store receives SAFE_STOP evidence/task linkage only.
        Local artifact success never resolves or completes a runtime repair task.
        """
        checks = self.policy.verify()
        if not isinstance(event, Event):
            raise ValueError('validated event required')
        if (fingerprint(event) != _RECIPE.fingerprint or classify(event).category != _RECIPE.category
                or _RECIPE.risk != 'LOW'):
            result = self._report(event, 'SAFE_STOP', reason='no_exact_code_owned_low_risk_recipe')
        elif not self.enabled:
            return self._report(event, 'OBSERVE_ONLY', reason='local_artifact_maintenance_not_enabled', safety=checks)
        else:
            try:
                name, expected, bundle = _summary(bundle)
                with self._workspace() as directory:
                    result = self._execute(directory, event, name, expected, bundle)
            except (OSError, ValueError, TypeError, RecursionError):
                result = self._report(event, 'SAFE_STOP', reason='unsafe_or_unavailable_evidence_or_workspace')
        if result['body']['safe_stop'] and self.enabled and 'evidence_path' not in result:
            try:
                with self._workspace() as directory:
                    result = self._persist(directory, result)
            except (OSError, ValueError):
                # The returned digest-bound envelope remains available to the caller.
                result = {**result, 'evidence_persistence': 'UNAVAILABLE_SAFE_STOP'}
        if store is not None and result['body']['safe_stop']:
            with store.transaction():
                identity = fingerprint(event)
                try:
                    incident = store.inspect(identity)
                except KeyError:
                    store.record(event)
                    incident = store.inspect(identity)
                task = store.task_for_incident(identity)
                reason = 'Local repair SAFE_STOP evidence sha256=' + result['sha256']
                if incident['state'] != State.SAFE_STOP:
                    store.transition(identity, State.SAFE_STOP, reason)
                if task.state != TaskState.SAFE_STOP:
                    store.transition_task(task.id, TaskState.SAFE_STOP, reason=reason,
                        next_action='Review local repair evidence and update GitHub task; preserve runtime state')
            result = {**result, 'observer_task_id': task.id}
        return result
