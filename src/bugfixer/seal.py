"""Producer-side seal for a rename rotation (#14).

The observer never decides on its own that a rotated segment is complete. The producer (the process or operator
that owns the log writer) renames the log, opens the successor, closes its old writer and then calls
`create_seal` with an explicit attestation. This module only measures the files; the attestation stays a
human/producer statement and is never derived from mtimes or directory listings.
"""
from dataclasses import asdict
import json
import os
from pathlib import Path
import stat

from src.bugfixer.rotation import RotationSeal, sealed_digest

MAX_SEALED_BYTES = 64 * 1024 * 1024


def _identity(path: Path) -> tuple[tuple[int, int], int]:
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('rotation files must be regular files, not links')
    return (info.st_dev, info.st_ino), info.st_size


def create_seal(rotated: Path, successor: Path, generation: int, *, writer_closed: bool,
                contiguous_successor: bool, max_bytes: int = MAX_SEALED_BYTES) -> RotationSeal:
    """Measure a closed, rotated segment and its successor and return the seal the observer accepts.

    Both attestations must be passed as True by the caller; nothing here can prove them.
    """
    if writer_closed is not True or contiguous_successor is not True:
        raise ValueError('the producer must attest a closed writer and a contiguous successor')
    if type(generation) is not int or generation < 0:
        raise ValueError('invalid generation')
    rotated, successor = Path(rotated), Path(successor)
    old_id, size = _identity(rotated)
    next_id, _ = _identity(successor)
    if old_id == next_id:
        raise ValueError('copytruncate is not a sealed rename rotation')
    descriptor = os.open(rotated, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as handle:
        if (os.fstat(handle.fileno()).st_dev, os.fstat(handle.fileno()).st_ino) != old_id:
            raise ValueError('rotated file changed while sealing')
        digest = sealed_digest(handle, size, max_bytes)
        if size:
            handle.seek(size - 1)
            if handle.read(1) != b'\n':
                raise ValueError('rotated segment ends inside a record; close the writer first')
    if _identity(rotated) != (old_id, size):
        raise ValueError('rotated file changed while sealing')
    return RotationSeal(generation, old_id, next_id, size, digest, True, True)


def seal_to_dict(seal: RotationSeal) -> dict:
    row = asdict(seal)
    row.update(schema_version=1, old_identity=list(seal.old_identity), successor_identity=list(seal.successor_identity))
    return row


def write_seal(seal: RotationSeal, target: Path) -> Path:
    """Write the seal once (0600, never overwrite) so the observer reads exactly what the producer measured."""
    target = Path(target)
    payload = json.dumps(seal_to_dict(seal), sort_keys=True).encode()
    if RotationSeal.from_dict(json.loads(payload)) != seal:
        raise ValueError('seal does not round-trip')
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return target
