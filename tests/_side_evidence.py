"""Test helper: a hand-built Lage window with the ``side_evidence`` block the producer writes (27.11., Codex #376).

Older tests describe a window by its display numbers ``volume`` and ``unknown_volume``. Since round 2 the known-side
policy reads only ``side_evidence`` (exact decimal strings), so :func:`win` translates the old description into that
block and keeps each test's intent: a finite non-negative number is an exact value (known = volume - unknown), a
missing or null number is a missing amount, anything else (NaN, infinity, negative, bool, a string, known < 0) is an
invalid amount. The display numbers stay in the window unchanged, the policy never reads them.
"""
from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

ABSENT = object()
SCHEMA = "side-evidence/1"
_BAD = "-1"   # not a plain decimal string, so the consumer reads it as INVALID


def _state(value: Any) -> tuple[str, Decimal | None]:
    if value is ABSENT or value is None:
        return "MISSING", None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return "INVALID", None
    return "VALUE", Decimal(repr(value))


def _text(value: Decimal) -> str:
    text = format(value, "f")
    return (text.rstrip("0").rstrip(".") if "." in text else text) or "0"


def evidence(volume: Any = ABSENT, unknown_volume: Any = ABSENT) -> dict[str, Any]:
    (vs, v), (us, u) = _state(volume), _state(unknown_volume)
    block: dict[str, Any] = {"schema": SCHEMA}
    if us == "VALUE":
        block["unknown"] = _text(u)
    elif us == "INVALID":
        block["unknown"] = _BAD
    if vs == "INVALID" or (vs == "VALUE" and us == "VALUE" and v - u < 0):
        block["known"] = _BAD
    elif vs == "VALUE":
        block["known"] = _text(v - u) if us == "VALUE" else _text(v)
    return block


def win(volume: Any = ABSENT, unknown_volume: Any = ABSENT, **extra: Any) -> dict[str, Any]:
    window = {key: value for key, value in (("volume", volume), ("unknown_volume", unknown_volume)) if value is not ABSENT}
    return {**window, **extra, "side_evidence": evidence(volume, unknown_volume)}
