"""Auslöser und Handoff-Kommentar nach docs/TIM_AGENT_HANDOFF.md §4 und CODEX_DAUERPRUEFUNG §4.5."""

from __future__ import annotations

import re
from typing import Any, Collection, Mapping, Sequence

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
LABEL = "abnahme:anfordern"
MAX_FILES = 50


def _labels(pr: Mapping[str, Any]) -> set[str]:
    out = set()
    for lb in pr.get("labels") or []:
        name = lb.get("name") if isinstance(lb, Mapping) else lb
        if isinstance(name, str):
            out.add(name)
    return out


def should_trigger(
    event_name: str, action: str, pr: Mapping[str, Any], already_handled_shas: Collection[str]
) -> tuple[bool, str]:
    """Entscheidet, ob eine Abnahme gestartet wird. Gibt (bool, Grund) zurück."""
    if not isinstance(pr, Mapping):
        return False, "PR-Daten ungültig"
    sha = (pr.get("head") or {}).get("sha") if isinstance(pr.get("head"), Mapping) else None
    if not isinstance(sha, str) or not SHA_RE.match(sha):
        return False, "HEAD_SHA ungültig"
    if sha in already_handled_shas:
        return False, "HEAD_SHA bereits behandelt (ein Lauf je SHA)"
    draft = bool(pr.get("draft"))
    labeled = LABEL in _labels(pr)
    is_label_event = event_name == "pull_request" and action == "labeled"
    if is_label_event:
        wanted = labeled
    elif event_name == "pull_request" and action in ("ready_for_review", "synchronize"):
        wanted = (not draft) or labeled
    else:
        return False, f"Ereignis {event_name}/{action} ist kein Auslöser"
    if not wanted:
        return False, "Entwurf ohne Label" if draft else "Label fehlt"
    head_repo = (pr.get("head") or {}).get("repo")
    base_repo = (pr.get("base") or {}).get("repo")
    h = head_repo.get("full_name") if isinstance(head_repo, Mapping) else None
    b = base_repo.get("full_name") if isinstance(base_repo, Mapping) else None
    if not h or not b or h != b:
        return False, "Fork-PR (oder unbekannt): nur lesend, Urteil INCONCLUSIVE bis Freigabe"
    return True, "Auslöser gültig"


def build_handoff_comment(
    pr_number: int, head_sha: str, base_sha: str, files: Sequence[str], pruefbefehl: str
) -> str:
    """Handoff-Kommentar im Kopfformat. ValueError bei ungültigen SHAs."""
    for name, val in (("HEAD_SHA", head_sha), ("BASE_SHA", base_sha)):
        if not isinstance(val, str) or not SHA_RE.match(val):
            raise ValueError(f"{name} muss 40 Hex-Zeichen (klein) sein")
    if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number <= 0:
        raise ValueError("pr_number ungültig")
    shown = list(files)[:MAX_FILES]
    rest = len(files) - len(shown)
    lines = [
        "[AGENT: CLAUDE]",
        "[TYPE: HANDOFF]",
        "[STATE: READY_FOR_REVIEW]",
        f"TASK: PR #{pr_number}",
        f"BASE_SHA: {base_sha}",
        f"HEAD_SHA: {head_sha}",
        f"GEÄNDERTE DATEIEN ({len(files)}):",
        *[f"- {f}" for f in shown],
    ]
    if rest > 0:
        lines.append(f"- ... und {rest} weitere")
    lines += [
        f"PRÜFBEFEHL: {pruefbefehl}",
        "HINWEIS: Ein Urteil gilt nur für HEAD_SHA.",
        "TRADING_AUTHORIZED=NO",
    ]
    return "\n".join(lines)
