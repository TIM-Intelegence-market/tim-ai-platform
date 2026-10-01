"""Tasks whose authoritative issue predates the fingerprint marker.

Issues created before the marker existed cannot be found by searching for it, so a caller
that forgets the hint would create a new duplicate. Known cases are therefore data here and
are applied automatically; an explicit `authoritative_hint` still overrides them.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class LegacyEntry:
    repository: str          # issue numbers are only meaningful inside this repository
    authoritative: int
    duplicates: tuple[int, ...]


# #68 evidence: M09-P0 audit is authoritative #11, retained duplicates #22..#65 (accidental series).
LEGACY_AUTHORITIES: dict[str, LegacyEntry] = {
    'M09|P0|BASELINE_ARCHITECTURE_AUDIT|TIM|v1': LegacyEntry('uezeyiraydin-cell/tim-ai-platform', 11, tuple(range(22, 66))),
}
