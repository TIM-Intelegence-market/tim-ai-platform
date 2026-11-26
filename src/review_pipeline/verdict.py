"""Urteilslogik nach docs/CODEX_DAUERPRUEFUNG.md §4.4. Reine Funktionen, fail-closed."""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional, Sequence

TRUSTED_BOT_LOGIN = "chatgpt-codex-connector[bot]"
CHECK_NAME = "codex-abnahme"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SCHWEREN_BLOCKIEREND = {"hoch", "kritisch", "high", "critical"}
_HEADER_RE = re.compile(r"\[(AGENT|STATE):\s*([A-Za-z_]+)\s*\]")


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and SHA_RE.match(value) is not None


def parse_agent_header(text: Any) -> dict[str, Any]:
    """Liest [AGENT: X] [STATE: Y]. Das Ergebnis ist nie vertrauenswürdig (reiner Text)."""
    out: dict[str, Any] = {"agent": None, "state": None, "trusted": False}
    if not isinstance(text, str):
        return out
    for key, val in _HEADER_RE.findall(text):
        out[key.lower()] = val.upper()
    return out


def is_trusted_review(review: Any, head_sha: str) -> bool:
    """Nur Bot-Review des Codex-Connectors (type Bot) auf exakt head_sha."""
    if not isinstance(review, Mapping) or not _is_sha(head_sha):
        return False
    user = review.get("user")
    if not isinstance(user, Mapping):
        return False
    return (
        user.get("type") == "Bot"
        and user.get("login") == TRUSTED_BOT_LOGIN
        and review.get("commit_id") == head_sha
    )


def is_trusted_check(check: Any, head_sha: str, expected_app_id: Optional[int]) -> bool:
    """Check-Run `codex-abnahme` von erwarteter App auf head_sha; ohne App-ID nie gültig."""
    if expected_app_id is None or not _is_sha(head_sha) or not isinstance(check, Mapping):
        return False
    app = check.get("app")
    app_id = app.get("id") if isinstance(app, Mapping) else None
    return (
        check.get("name") == CHECK_NAME
        and check.get("head_sha") == head_sha
        and isinstance(app_id, int)
        and not isinstance(app_id, bool)
        and app_id == expected_app_id
    )


def _open_blocking(findings: Any) -> Optional[list[Any]]:
    """Offene hoch/kritisch-Befunde; None bei kaputter Struktur."""
    if not isinstance(findings, Sequence) or isinstance(findings, (str, bytes)):
        return None
    out = []
    for f in findings:
        if not isinstance(f, Mapping):
            return None
        sev = f.get("schwere")
        if not isinstance(sev, str):
            return None
        if sev.lower() in SCHWEREN_BLOCKIEREND and f.get("offen", True) is not False:
            out.append(f)
    return out


def _tests_ok(tests: Any, head_sha: str) -> tuple[Optional[bool], str]:
    """(True/False/None, Grund). None = nicht belegt."""
    if not isinstance(tests, Mapping):
        return None, "Testlauf fehlt (NOT_RUN)"
    if tests.get("status") == "NOT_RUN":
        return None, "Testlauf NOT_RUN"
    if tests.get("head_sha") != head_sha:
        return None, "Testlauf nicht auf aktuellem HEAD_SHA"
    nums = []
    for k in ("passed", "failed", "errors"):
        v = tests.get(k)
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            return None, f"Testfeld {k} fehlt oder ungültig"
        nums.append(v)
    passed, failed, errors = nums
    if failed > 0 or errors > 0:
        return False, f"Tests rot (failed={failed}, errors={errors})"
    if passed == 0:
        return None, "Testlauf ohne bestandene Tests"
    return True, "Tests grün auf HEAD_SHA"


def evaluate(
    head_sha: str,
    reviews: Any,
    check_runs: Any,
    test_results: Any,
    expected_app_id: Optional[int] = None,
) -> dict[str, Any]:
    """Urteil PASS|FAIL|INCONCLUSIVE für genau head_sha."""
    gruende: list[str] = []
    quellen: list[str] = []

    def done(urteil: str) -> dict[str, Any]:
        return {"urteil": urteil, "gruende": gruende, "quellen": quellen, "head_sha": head_sha}

    if not _is_sha(head_sha):
        gruende.append("HEAD_SHA ungültig")
        return done("INCONCLUSIVE")

    fail = False
    t_ok, t_reason = _tests_ok(test_results, head_sha)
    gruende.append(t_reason)
    if t_ok is False:
        fail = True
    if t_ok is True:
        quellen.append("testlauf")

    review_list = reviews if isinstance(reviews, Sequence) and not isinstance(reviews, (str, bytes)) else []
    if not review_list and reviews is not None and not isinstance(reviews, Sequence):
        gruende.append("Review-Liste ungültig")
    trusted = [r for r in review_list if is_trusted_review(r, head_sha)]
    ignored = len(review_list) - len(trusted)
    if ignored:
        gruende.append(f"{ignored} Review(s) nicht vertrauenswürdig oder auf anderem SHA ignoriert (INFO_ONLY)")

    review_ok = False
    review_unclear = False
    if not trusted:
        gruende.append("Kein gültiges Bot-Review auf HEAD_SHA")
    else:
        for r in trusted:
            if "findings" not in r:
                gruende.append("Review ohne Befundliste (fail-closed)")
                review_unclear = True
                continue
            blocking = _open_blocking(r["findings"])
            if blocking is None:
                gruende.append("Befundliste kaputt (fail-closed)")
                review_unclear = True
            elif blocking:
                gruende.append(f"{len(blocking)} offener Befund hoch/kritisch")
                fail = True
                quellen.append(f"bot-review:{r.get('id')}")
            else:
                review_ok = True
                quellen.append(f"bot-review:{r.get('id')}")

    check_list = check_runs if isinstance(check_runs, Sequence) and not isinstance(check_runs, (str, bytes)) else []
    valid_checks = [c for c in check_list if is_trusted_check(c, head_sha, expected_app_id)]
    for c in valid_checks:
        concl = c.get("conclusion")
        quellen.append("check:codex-abnahme")
        if concl == "failure":
            gruende.append("Check codex-abnahme meldet failure")
            fail = True
        elif concl != "success":
            gruende.append(f"Check codex-abnahme nicht success ({concl})")
            review_ok = False  # widersprüchlich/unklar: nie PASS
    if check_list and not valid_checks:
        gruende.append("Check-Run(s) ohne erwartete App-ID ignoriert")

    if fail:
        return done("FAIL")
    if t_ok is True and review_ok and not review_unclear:
        return done("PASS")
    return done("INCONCLUSIVE")
