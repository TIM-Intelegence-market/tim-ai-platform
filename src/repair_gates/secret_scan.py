"""Secret-detection repair gate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from src.bugfixer.processing import redact_text


@dataclass(frozen=True)
class GateResult:
    gate: str
    status: str
    reason: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"gate": self.gate, "status": self.status, "reason": self.reason}


def scan(text: str, *, literals: Iterable[str] = ()) -> GateResult:
    """Check text for values that the bugfixer's redactor would remove."""
    gate = "secret_scan"
    if not isinstance(text, str):
        return GateResult(gate, "FAIL", "input must be a string")

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
        return GateResult(gate, "PASS", "")

    numbers = sorted(matched_lines)[:20]
    return GateResult(
        gate,
        "FAIL",
        "possible secret on lines " + ", ".join(str(number) for number in numbers),
    )
