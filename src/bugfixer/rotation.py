"""Explicit producer/operator attestation for a sealed rename-rotation segment.

A digest alone cannot prove that a writer will never append again. The producer
must close the old segment and attest that the successor is contiguous. The
observer never fabricates that assertion from a directory listing or mtime.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
import re


@dataclass(frozen=True)
class RotationSeal:
    generation: int
    old_identity: tuple[int, int]
    successor_identity: tuple[int, int]
    size: int
    sha256: str
    writer_closed: bool
    contiguous_successor: bool

    def __post_init__(self):
        for identity in (self.old_identity, self.successor_identity):
            if len(identity) != 2 or any(type(v) is not int or v < 0 for v in identity):
                raise ValueError('invalid file identity')
        if self.old_identity == self.successor_identity:
            raise ValueError('copytruncate is not a sealed rename rotation')
        if type(self.generation) is not int or self.generation < 0 or type(self.size) is not int or self.size < 0:
            raise ValueError('invalid rotation size or generation')
        if not isinstance(self.sha256, str) or not re.fullmatch('[0-9a-f]{64}', self.sha256):
            raise ValueError('invalid seal digest')
        if self.writer_closed is not True or self.contiguous_successor is not True:
            raise ValueError('closed writer and contiguous successor must be attested')

    def digest(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    @classmethod
    def from_dict(cls, row):
        fields = {'schema_version', 'generation', 'old_identity', 'successor_identity',
                  'size', 'sha256', 'writer_closed', 'contiguous_successor'}
        if not isinstance(row, dict) or set(row) != fields or type(row['schema_version']) is not int or row['schema_version'] != 1:
            raise ValueError('unsupported rotation seal')
        if not all(isinstance(row[key], list) for key in ('old_identity', 'successor_identity')):
            raise ValueError('invalid seal identities')
        return cls(row['generation'], tuple(row['old_identity']), tuple(row['successor_identity']),
                   row['size'], row['sha256'], row['writer_closed'], row['contiguous_successor'])


def sealed_digest(handle, size, limit):
    if size > limit:
        raise ValueError('sealed file exceeds reconciliation byte budget')
    handle.seek(0)
    digest = hashlib.sha256()
    remaining = size
    while remaining:
        chunk = handle.read(min(65536, remaining))
        if not chunk:
            raise ValueError('sealed file is incomplete')
        digest.update(chunk)
        remaining -= len(chunk)
    if handle.read(1):
        raise ValueError('sealed file grew')
    return digest.hexdigest()
