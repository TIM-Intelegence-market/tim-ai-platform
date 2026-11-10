"""Reviewer-Pflicht für kritische Pfade (Paket P3 of ``docs/MULTI_AGENTEN_SYSTEM.md``, Uzi 10.11.2026).

A pull request that touches a critical path is only "merge-fertig" when an independent reviewer has looked at it
and the PR text carries the reviewer's handover slip (``TIM_HANDOVER_V1`` with ``from_role`` REVIEWER, see
``src/agents/handover.py``). The reviewer is an agent that did not write the change; Uzi decided on 26.10.2026
that no second person is forced (docs/audits/GRUEN_PLAN_11_SICHTEN.md, R2), so this gate does not ask for a
GitHub approval and is not a required check. Uzi's "merge" stays the only release.

What the gate cannot prove: who wrote the slip. Anyone who can edit the PR text can paste one. It makes a
missing review visible and names the review's evidence; it is no authentication.

Run in CI: ``python -m src.agents.review_gate --event "$GITHUB_EVENT_PATH" --files changed.txt``.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from src.agents.handover import HandoverError, Role, parse

# Journal logic, cost model, holdout lock, register, watchdog/lifecycle, incident reporter, CI and services.
CRITICAL_PREFIXES = (
    ".github/",
    "ops/",
    "scripts/timctl",
    "scripts/tim_watchdog.py",
    "src/database/",
    "src/tim_incident/",
    "src/task_governance/",
    "src/dashboard/plan_journal.py",
    "src/research_lab/exit_variants.py",
    "src/research_lab/protocol.py",
    "src/research_lab/learning/",
    "docs/research_lab/REGISTER.jsonl",
    "docs/research_lab/PROTOKOLL.md",
    "src/agents/handover.py",
    "src/agents/review_gate.py",
)


@dataclass(frozen=True, slots=True)
class GateResult:
    critical: tuple[str, ...]
    ok: bool
    reason: str


def critical_files(files: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({name for name in files if name.startswith(CRITICAL_PREFIXES)}))


def check(files: Sequence[str], body: str | None, pr_number: int | None = None) -> GateResult:
    """PASS without critical paths; with them only when the PR text carries a valid REVIEWER slip."""
    critical = critical_files(files)
    if not critical:
        return GateResult(critical, True, "keine kritischen Pfade, kein Pflicht-Review")
    try:
        slip = parse(body, issue_number=pr_number)
    except HandoverError as error:
        return GateResult(critical, False, f"kritische Pfade ohne gültigen Reviewer-Zettel: {error}")
    if slip.from_role is not Role.REVIEWER:
        return GateResult(critical, False, f"Zettel kommt von {slip.from_role.value}, nicht vom REVIEWER")
    return GateResult(critical, True, f"Reviewer-Zettel gültig, Nachweis: {slip.evidence[0].ref}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--event", required=True, help="GitHub event JSON (pull_request)")
    parser.add_argument("--files", required=True, help="file with one changed path per line")
    args = parser.parse_args(argv)
    try:
        event = json.loads(Path(args.event).read_text(encoding="utf-8"))
        files = [line.strip() for line in Path(args.files).read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError) as error:
        print(f"FAIL: Eingabe nicht lesbar ({type(error).__name__})")
        return 1
    pull = event.get("pull_request") if isinstance(event, dict) else None
    body = pull.get("body") if isinstance(pull, dict) else None
    number = pull.get("number") if isinstance(pull, dict) else None
    result = check(files, body, number if isinstance(number, int) else None)
    for name in result.critical:
        print(f"kritisch: {name}")
    print(("PASS: " if result.ok else "FAIL: ") + result.reason)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
