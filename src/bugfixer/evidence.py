"""Content-addressed sanitized evidence. Hashes prove integrity, not truth."""
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

from src.bugfixer.processing import Event, fingerprint

MAX_BUNDLE_BYTES = 1024 * 1024


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def make_bundle(store, identity):
    row = store.inspect(identity)
    event = Event(**json.loads(row['evidence']))
    if fingerprint(event) != identity:
        raise ValueError('incident evidence does not match fingerprint')
    body = {'schema_version': 1, 'incident_id': identity, 'event': event.safe_dict(),
            'scope': 'sanitized_event_processing_only'}
    return {'body': body, 'sha256': hashlib.sha256(_encoded(body)).hexdigest()}


def validate_bundle(bundle):
    if not isinstance(bundle, dict) or set(bundle) != {'body', 'sha256'}:
        raise ValueError('invalid evidence envelope')
    body = bundle['body']
    if not isinstance(body, dict) or set(body) != {'schema_version', 'incident_id', 'event', 'scope'}:
        raise ValueError('invalid evidence body')
    if type(body['schema_version']) is not int or body['schema_version'] != 1 or body['scope'] != 'sanitized_event_processing_only':
        raise ValueError('unsupported evidence schema or scope')
    if hashlib.sha256(_encoded(body)).hexdigest() != bundle['sha256']:
        raise ValueError('evidence digest mismatch')
    if not isinstance(body['event'], dict) or set(body['event']) != {'timestamp', 'component', 'exception', 'message', 'code', 'stack'}:
        raise ValueError('invalid event evidence')
    event = Event(**body['event'])
    if event.safe_dict() != body['event']:
        raise ValueError('unsanitized evidence rejected')
    if fingerprint(event) != body['incident_id']:
        raise ValueError('evidence fingerprint mismatch')
    return event


def load_bundle(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError('evidence must be a regular file')
        raw = handle.read(MAX_BUNDLE_BYTES + 1)
    if len(raw) > MAX_BUNDLE_BYTES:
        raise ValueError('evidence exceeds size limit')
    try:
        bundle = json.loads(raw)
        return validate_bundle(bundle)
    except (RecursionError, TypeError, UnicodeError):
        raise ValueError('invalid evidence input') from None


def export_bundle(store, identity, directory):
    bundle = make_bundle(store, identity)
    validate_bundle(bundle)
    encoded = _encoded(bundle) + b'\n'
    if len(encoded) > MAX_BUNDLE_BYTES:
        raise ValueError('evidence exceeds size limit')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (bundle['sha256'] + '.json')
    descriptor, temporary = tempfile.mkstemp(prefix='.evidence-', dir=directory)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            # Publish without replacing an existing file, including a symlink.
            os.link(temporary, target)
        except FileExistsError:
            existing = load_bundle(target)
            if _encoded(existing.safe_dict()) != _encoded(bundle['body']['event']):
                raise ValueError('conflicting evidence artifact')
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        os.unlink(temporary)
    with store.transaction():
        store.db.execute('INSERT OR IGNORE INTO evidence_bundles VALUES (?,?,?)',
                         (bundle['sha256'], identity, encoded.decode()))
    return target
