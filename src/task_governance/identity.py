"""Canonical task identity, independent of volatile wording such as titles."""
from dataclasses import dataclass
import hashlib
import re

_PART = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.\-]*$')


@dataclass(frozen=True)
class TaskRequest:
    mission_id: str
    phase_id: str
    task_type: str
    target: str
    schema_version: str
    title: str = ''   # display only, never part of the identity
    body: str = ''

    @property
    def key(self) -> str:
        return canonical_task_key(self.mission_id, self.phase_id, self.task_type, self.target, self.schema_version)

    @property
    def fingerprint(self) -> str:
        return task_fingerprint(self.key)


def canonical_task_key(mission_id, phase_id, task_type, target, schema_version) -> str:
    """`M09|P0|BASELINE_ARCHITECTURE_AUDIT|TIM|v1`; identifier parts are upper-cased, the schema version lower-cased.

    Empty parts and parts containing the separator are rejected instead of
    being normalised, so two different tasks can never collapse into one key.
    """
    parts = []
    for name, value in (('mission_id', mission_id), ('phase_id', phase_id), ('task_type', task_type),
                        ('target', target), ('schema_version', schema_version)):
        text = str(value).strip() if value is not None else ''
        if not _PART.match(text):
            raise ValueError(f'invalid {name}: {value!r}')
        parts.append(text.lower() if name == 'schema_version' else text.upper())
    return '|'.join(parts)


def task_fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode('utf-8')).hexdigest()


def fingerprint_marker(fingerprint: str) -> str:
    """Marker a gateway embeds in every authoritative issue body so GitHub can be searched by identity."""
    return f'<!-- TIM_TASK_FINGERPRINT:{fingerprint} -->'
