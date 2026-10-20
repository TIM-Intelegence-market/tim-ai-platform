"""Secret-detection repair gate."""

from __future__ import annotations

from typing import Any, Iterable

from src.bugfixer.processing import redact_text
from src.repair_gates.result import GateResult, GateStatus


def scan(text: str, *, literals: Iterable[str] = ()) -> GateResult:
    """Check text for values that the bugfixer's redactor would remove."""
    gate = "secret_scan"
    if not isinstance(text, str):
        return GateResult(gate, GateStatus.FAIL, "input must be a string")

    lines = text.splitlines() or [text]
    matched_lines: set[int] = set()

    for number, line in enumerate(lines, 1):
        if redact_text(line) != line:
            matched_lines.add(number)

    for literal in literals:
        if isinstance(literal, str) and literal:
            for number, line in enumerate(lines, 1):
                if literal in line:
                    matched_lines.add(number)

    if not matched_lines:
        return GateResult(gate, GateStatus.PASS, "")

    numbers = sorted(matched_lines)[:20]
    return GateResult(
        gate,
        GateStatus.FAIL,
        "possible secret on lines " + ", ".join(str(number) for number in numbers),
    )
