"""Bounded file observation. No source mutation or automatic gap acceptance."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import fcntl
import os
from pathlib import Path
import stat
import tempfile
import math

from src.bugfixer.legacy import LegacyTraceAssembler
from src.bugfixer.store import IncidentStore
from src.bugfixer.rotation import RotationSeal, sealed_digest


class ObservationBlocked(RuntimeError):
    """Requires source reconciliation; committed progress is preserved."""


def _anchor(handle, offset: int) -> str:
    handle.seek(max(0, offset - 256))
    return hashlib.sha256(handle.read(min(offset, 256))).hexdigest()


class ErrorLogWorker:
    def __init__(self, store: IncidentStore, source: Path, *, max_records=200, max_line_bytes=65536):
        if not 1 <= max_records <= 10000 or not 128 <= max_line_bytes <= 1048576:
            raise ValueError('invalid observation bounds')
        self.store, self.source = store, Path(source)
        if self.source.is_symlink() or self.source.resolve() == store.path:
            raise ValueError('unsafe log source')
        self.max_records, self.max_line_bytes = max_records, max_line_bytes
        # Avoid persisting credentials that could occur in an arbitrary file path.
        self.source_id = hashlib.sha256(os.fsencode(self.source.absolute())).hexdigest()

    @contextmanager
    def _lease(self):
        """One observer per store AND source, including across different stores.

        Locks are advisory liveness, never stale-PID deletion or source mutation.
        A per-user shared directory also prevents worktree copies racing.
        """
        directory = Path(tempfile.gettempdir()).resolve() / ('tim-bugfixer-locks-' + str(os.getuid()))
        directory.mkdir(mode=0o700, exist_ok=True)
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ObservationBlocked('unsafe worker lock directory')
        source_info = self.source.stat()
        identities = (os.fsencode(self.source.resolve()),
                      f'{source_info.st_dev}:{source_info.st_ino}'.encode())
        paths = [self.store.worker_lock_path] + [
            directory / (hashlib.sha256(identity).hexdigest() + '.lock') for identity in identities]
        handles = []
        try:
            for path in paths:
                fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
                handles.append(fd)
                lock_info = os.fstat(fd)
                if not stat.S_ISREG(lock_info.st_mode) or lock_info.st_uid != os.getuid() or lock_info.st_nlink != 1:
                    raise ObservationBlocked('unsafe observer lock')
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise ObservationBlocked('observer for this store or source is already running') from None
            yield
        finally:
            for fd in reversed(handles):
                os.close(fd)

    @contextmanager
    def _open(self, path):
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(descriptor, 'rb') as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or os.path.samestat(info, self.store.path.stat()):
                raise ObservationBlocked('source must be a regular log, not the incident store')
            yield handle

    def _consume(self, handle, previous, now):
        info = os.fstat(handle.fileno())
        identity = [info.st_dev, info.st_ino]
        offset, in_private_key = 0, False
        generation = 0
        if previous:
            offset = previous['offset']
            if previous['identity'] != identity:
                raise ObservationBlocked('rotation requires reconciliation with previous file identity')
            if info.st_size < offset or _anchor(handle, offset) != previous['anchor_sha256']:
                raise ObservationBlocked('truncation or rewritten source requires reconciliation')
            in_private_key = previous['in_private_key']
            generation = previous.get('generation', 0)
        assembler = LegacyTraceAssembler(previous.get('pending_trace') if previous else None)
        handle.seek(offset)
        count = ignored = read = 0
        last_event_time = previous.get('last_event_time') if previous else None
        last_lag = previous.get('ingestion_lag_seconds') if previous else None
        for _ in range(self.max_records):
            line = handle.readline(self.max_line_bytes + 1)
            if not line:
                break
            if len(line) > self.max_line_bytes:
                raise ObservationBlocked('line exceeds bounded parser capacity; no bytes acknowledged')
            if not line.endswith(b'\n'):
                handle.seek(offset)
                break
            read += 1
            decoded = line.decode('utf-8', errors='replace')
            if '-----BEGIN ' in decoded and 'PRIVATE KEY-----' in decoded:
                in_private_key = True
            if in_private_key:
                ignored += 1
                if '-----END ' in decoded and 'PRIVATE KEY-----' in decoded:
                    in_private_key = False
            else:
                try:
                    events = assembler.feed(decoded, now)
                except ValueError:
                    raise ObservationBlocked('invalid structured event; source progress preserved') from None
                if not events and assembler.pending is None:
                    ignored += 1
                for event in events:
                    self.store.record(event)
                    last_event_time = event.timestamp
                    last_lag = (datetime.fromisoformat(now) - datetime.fromisoformat(event.timestamp)).total_seconds()
                    count += 1
            offset = handle.tell()
        checkpoint = {'identity': identity, 'generation': generation, 'offset': offset,
                      'anchor_sha256': _anchor(handle, offset), 'timestamp': now,
                      'in_private_key': in_private_key, 'pending_trace': assembler.pending,
                      'records_read_total': (previous or {}).get('records_read_total', 0) + read,
                      'records_ignored_total': (previous or {}).get('records_ignored_total', 0) + ignored,
                      'last_event_time': last_event_time, 'ingestion_lag_seconds': last_lag}
        return count, ignored, checkpoint

    def poll(self) -> dict:
        with self._lease():
            return self._poll()

    def _poll(self) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with self.store.transaction(), self._open(self.source) as handle:
            previous = self.store.checkpoint(self.source_id)
            if previous and previous.get('pending_seal_sha256'):
                raise ObservationBlocked('pending sealed rotation requires reconciliation')
            count, ignored, checkpoint = self._consume(handle, previous, now)
            self.store.save_checkpoint(self.source_id, checkpoint)
        return {'events_ingested': count, 'records_ignored': ignored, 'offset': checkpoint['offset'],
                'worker_running': False, 'mode': 'OBSERVE', 'origin': 'tim_bugfixer'}

    def reconcile_rotation(self, rotated_source: Path, seal: RotationSeal, *, max_sealed_bytes=64 * 1024 * 1024):
        with self._lease():
            return self._reconcile_rotation(rotated_source, seal, max_sealed_bytes=max_sealed_bytes)

    def _reconcile_rotation(self, rotated_source: Path, seal: RotationSeal, *, max_sealed_bytes=64 * 1024 * 1024):
        """Drain an explicitly sealed predecessor before acknowledging its successor.

        Reinvoke with the same seal when complete=False. No directory discovery,
        decompression, cursor reset, or implicit acceptance of missing generations.
        The producer must guarantee seal.writer_closed and contiguous_successor.
        """
        if not isinstance(seal, RotationSeal) or type(max_sealed_bytes) is not int or not 1 <= max_sealed_bytes <= 64 * 1024 * 1024:
            raise ValueError('invalid rotation reconciliation bounds')
        now = datetime.now(timezone.utc).isoformat()
        with self.store.transaction(), self._open(rotated_source) as old, self._open(self.source) as successor:
            previous = self.store.checkpoint(self.source_id)
            old_info, next_info = os.fstat(old.fileno()), os.fstat(successor.fileno())
            old_id = (old_info.st_dev, old_info.st_ino)
            next_id = (next_info.st_dev, next_info.st_ino)
            if (not previous or previous.get('generation', 0) != seal.generation
                    or tuple(previous['identity']) != seal.old_identity
                    or old_id != seal.old_identity or next_id != seal.successor_identity):
                raise ObservationBlocked('rotation seal does not match checkpoint and successor')
            try:
                if old_info.st_size != seal.size or sealed_digest(old, seal.size, max_sealed_bytes) != seal.sha256:
                    raise ValueError('seal mismatch')
                # A closed segment cannot acquire a missing newline later.
                if seal.size:
                    old.seek(seal.size - 1)
                    if old.read(1) != b'\n':
                        raise ValueError('sealed segment has an incomplete record')
                count, ignored, checkpoint = self._consume(old, previous, now)
                if sealed_digest(old, seal.size, max_sealed_bytes) != seal.sha256:
                    raise ValueError('sealed file changed during read')
                current = self.source.lstat()
                if not stat.S_ISREG(current.st_mode) or (current.st_dev, current.st_ino) != next_id:
                    raise ValueError('successor rotated during reconciliation')
            except ValueError:
                raise ObservationBlocked('sealed rotation validation failed; no progress acknowledged') from None
            complete = checkpoint['offset'] == seal.size
            if complete:
                checkpoint.update(identity=list(next_id), generation=seal.generation + 1,
                                  offset=0, anchor_sha256=hashlib.sha256(b'').hexdigest(),
                                  predecessor_sha256=seal.sha256)
            else:
                checkpoint['pending_seal_sha256'] = seal.digest()
            pending = previous.get('pending_seal_sha256')
            if pending and pending != seal.digest():
                raise ObservationBlocked('pending rotation seal cannot change')
            self.store.save_checkpoint(self.source_id, checkpoint)
        return {'events_ingested': count, 'records_ignored': ignored, 'complete': complete,
                'generation': checkpoint['generation'], 'offset': checkpoint['offset'],
                'mode': 'OBSERVE', 'origin': 'tim_bugfixer'}

    def run(self, stop, *, interval: float = 1.0):
        if type(interval) not in {int, float} or not math.isfinite(interval) or not .1 <= interval <= 60:
            raise ValueError('poll interval must be at least 0.1 seconds')
        if stop.is_set():
            return  # stopped before start: no lease, no source stat, no reads
        with self._lease():
            while not stop.is_set():
                self._poll()
                stop.wait(interval)
