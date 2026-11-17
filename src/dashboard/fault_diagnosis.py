"""Störungs-Diagnose: Hermes (DeepSeek) erklärt in wenigen Sätzen, was bei TIM kaputt ist und warum.

Uzi, 17.11.2026 ("Punkt 1 danach Punkt 2 go"). TIM sammelt die Fakten selbst: welche Dienste (``com.tim.*``) laufen
nicht oder endeten mit einem Fehlercode, die letzten Fehlerzeilen aus deren Log und was das Control Center als
"braucht einen Blick" meldet. Hermes bekommt nur diese Zeilen und schreibt: was ist kaputt, wahrscheinlichste
Ursache, nächster lesender Prüfschritt, ist der Handel betroffen.

Gefragt wird nur, wenn eine neue Störung auftaucht (andere Störungsmenge als zuletzt), höchstens einmal je
30 Minuten und sechsmal am Tag. Verschwindet die Störung, wird "behoben" vermerkt, ohne Frage. Nur lesend: nichts
hier startet etwas neu, ändert einen Dienst oder eine Datei außer der eigenen. Hinaus gehen Dienstnamen, Codes und
kurze, bereinigte Fehlerzeilen. Von Diensten mit Konto- oder Handelsbezug (``kraken``, ``trader``, ``live-order``)
gehen nur Name und Code hinaus, nie eine Logzeile. Schlüssel-ähnliche Zeichenfolgen werden vorher geschwärzt.
"""
from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.dashboard.orderflow_shadow import _iso, _save, _time, load

SCHEMA = "tim_fault_diagnosis/1"
DEFAULT_PATH = Path("data/hermes/fault_diagnosis.json")
LABEL_PREFIX = "com.tim."
COOLDOWN_MINUTES = 30
MAX_ASKS_PER_DAY = 6
KEEP = 30
MAX_PROMPT = 4000
MAX_LOG_LINES = 5
MAX_LINE = 160
LOG_TAIL_BYTES = 16384
NO_LOG_WORDS = ("kraken", "trader", "live-order", "order")  # status only, never a log line
ERROR_WORDS = re.compile(r"traceback|error|exception|failed|refused|denied|timeout|timed out|killed|no such|cannot|unable", re.IGNORECASE)
SECRET_LIKE = re.compile(r"[A-Za-z0-9_\-+/=]{24,}")
KEY_VALUE = re.compile(r"(?i)\b(api[_-]?key|secret|token|password|passwd|authorization|bearer)\b\s*[:=]?\s*\S+")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

Ask = Callable[[str], Mapping[str, Any]]
Run = Callable[..., Any]


def _run(args: Sequence[str], timeout: int = 10) -> Any:
    return subprocess.run(list(args), capture_output=True, text=True, timeout=timeout, check=False)


def redact(line: str) -> str:
    """Mask key-like strings, key/value secrets and e-mail addresses; shorten the line."""
    text = KEY_VALUE.sub(lambda m: f"{m.group(1)}=***", line)
    text = SECRET_LIKE.sub("***", text)
    text = EMAIL.sub("***", text)
    return text.strip()[:MAX_LINE]


def parse_launchctl(output: str) -> list[dict[str, Any]]:
    """``launchctl list`` rows (PID, status, label) of TIM's own services."""
    services = []
    for row in output.splitlines():
        parts = row.split(None, 2)
        if len(parts) != 3 or not parts[2].startswith(LABEL_PREFIX):
            continue
        pid, status, label = parts
        services.append({"label": label.strip(), "pid": int(pid) if pid.isdigit() else None,
                         "exit": int(status) if re.fullmatch(r"-?\d+", status) else None})
    return services


def faulty(services: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Services with no process whose last exit was not clean."""
    return sorted((dict(s) for s in services if s.get("pid") is None and s.get("exit") not in (0, None)), key=lambda s: s["label"])


def _meaning(code: int) -> str:
    if code < 0:
        return f"beendet durch Signal {-code}" + (" (kill)" if code == -9 else "")
    return f"Rückgabecode {code}"


def log_path(label: str, run: Run = _run, uid: int | None = None) -> Path | None:
    """The stderr file of a service, from ``launchctl print``; None when it has none or cannot be read."""
    uid = os.getuid() if uid is None else uid
    result = run(["launchctl", "print", f"gui/{uid}/{label}"])
    if getattr(result, "returncode", 1) != 0:
        return None
    for row in str(result.stdout).splitlines():
        match = re.match(r"\s*stderr path = (.+)", row)
        if match and match.group(1).strip() not in ("", "/dev/null"):
            return Path(match.group(1).strip())
    return None


def error_lines(path: Path, limit: int = MAX_LOG_LINES) -> list[str]:
    """The last error-looking lines of a log file (last 16 KB only), masked. Empty when unreadable."""
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - LOG_TAIL_BYTES))
            tail = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    rows = [redact(r) for r in tail.splitlines() if r.strip() and ERROR_WORDS.search(r)]
    return [r for r in rows if r][-limit:]


def service_facts(run: Run = _run, listing: str | None = None) -> list[str]:
    """One line per failing service, plus its recent error lines. A missing ``launchctl`` (not a Mac) gives no lines."""
    if listing is None:
        try:
            result = run(["launchctl", "list"])
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return []
        if getattr(result, "returncode", 1) != 0:
            return []
        listing = str(result.stdout)
    lines = []
    for service in faulty(parse_launchctl(listing)):
        label = service["label"]
        lines.append(f"Dienst {label} läuft nicht, {_meaning(service['exit'])}.")
        if any(word in label.lower() for word in NO_LOG_WORDS):
            lines.append(f"{label}: Logzeilen bewusst nicht ausgewertet (Konto- oder Handelsbezug).")
            continue
        path = log_path(label, run)
        rows = error_lines(path) if path else []
        lines.extend(f"{label} Log: {row}" for row in rows) if rows else lines.append(f"{label}: keine Fehlerzeilen im Log gefunden.")
    return lines


def attention_facts(attention: Sequence[Mapping[str, Any]]) -> list[str]:
    """What the Control Center itself flags as needing a look."""
    return [f"Control Center meldet: {item.get('label')}: {item.get('value')}" + (f" ({item.get('reason')})" if item.get("reason") else "") + "."
            for item in list(attention)[:6]]


def signature(lines: Sequence[str]) -> list[str]:
    """The identity of a fault set: one key per fault, without log lines and without changing numbers.

    A Control Center item is keyed by its label only: "Bybit-Orderflow: 10 Neuverbindungen" and "... 11 ..." are the same fault.
    """
    keys = set()
    for line in lines:
        if line.startswith("Dienst "):
            keys.add(line)
        elif line.startswith("Control Center meldet: "):
            keys.add("Control Center meldet: " + line.removeprefix("Control Center meldet: ").split(": ", 1)[0])
    return sorted(keys)


def prompt(lines: Sequence[str]) -> str:
    text = ("Du bist die Störungs-Diagnose von TIM (BTC-Papierhandel, Chart und Forschung auf einem Mac). Nutze keine Werkzeuge und "
            "nur diese Fakten, erfinde nichts dazu. Schreibe auf Deutsch höchstens fünf Sätze: 1. Was ist kaputt (je Störung ein Satz). "
            "2. Wahrscheinlichste Ursache, mit 'vermutlich' markiert, wenn die Fakten sie nicht belegen. 3. Der nächste Schritt, der nur "
            "etwas liest (kein Neustart, keine Änderung). 4. Ist Handel, Journal oder Chart betroffen: ja, nein oder unklar.\nFakten:\n"
            + "\n".join(lines))
    return text[:MAX_PROMPT]


def _hermes(text: str) -> Mapping[str, Any]:
    from src.dashboard import hermes_bridge

    return hermes_bridge.ask(text, limit=MAX_PROMPT, record=False)


def latest(path: Path | None, count: int = 5) -> list[dict[str, Any]]:
    entries = (load(Path(path or DEFAULT_PATH)) or {}).get("entries") or []
    return list(reversed(entries[-count:]))


def update(path: Path, lines: Sequence[str], now: datetime | None = None, ask: Ask | None = None) -> dict[str, Any] | None:
    """Compare the fault set with the last one; ask Hermes about a new fault. Returns the entry written, or None."""
    now = now or datetime.now(timezone.utc)
    path = Path(path)
    state = load(path) or {"schema": SCHEMA, "known": [], "entries": []}
    entries = state.setdefault("entries", [])
    known = list(state.get("known") or [])
    current = signature(lines)
    if current == known:
        return None
    if not current:  # all clear: note it, no question
        entry = {"at": _iso(now), "signature": [], "facts": [], "text": None, "error": None, "resolved": True}
    else:
        new = [s for s in current if s not in known]
        if not new:  # only fewer faults than before: remember the smaller set, nothing to ask
            state["known"] = current
            _save(state, path)
            return None
        last_ask = _time(state["last_ask_at"]) if state.get("last_ask_at") else None
        today = [e for e in entries if e.get("asked") and _time(e["at"]).astimezone(timezone.utc).date() == now.date()]
        if (last_ask and now - last_ask < timedelta(minutes=COOLDOWN_MINUTES)) or len(today) >= MAX_ASKS_PER_DAY:
            return None  # signature stays unrecorded, so the next minute after the cooldown asks
        try:
            reply = (ask or _hermes)(prompt(lines))
        except Exception as error:  # noqa: BLE001 - the facts stay as the record then
            reply = {"ok": False, "error": type(error).__name__}
        state["last_ask_at"] = _iso(now)
        entry = {"at": _iso(now), "signature": current, "facts": list(lines)[:30], "asked": True, "resolved": False,
                 "text": str(reply.get("answer") or "")[:2000] if reply.get("ok") else None,
                 "error": None if reply.get("ok") else str(reply.get("error") or "keine Antwort")[:200]}
    entries.append(entry)
    state["entries"] = entries[-KEEP:]
    state["known"] = current
    _save(state, path)
    return entry


def state_lines(attention: Callable[[], Sequence[Mapping[str, Any]]] | None = None, run: Run = _run) -> list[str]:
    """All fact lines of the running TIM; a failing source is named, never left out quietly."""
    lines: list[str] = []
    for name, source in (("Dienste", lambda: service_facts(run)), ("Control Center", lambda: attention_facts(attention()) if attention else [])):
        try:
            lines.extend(source())
        except Exception as error:  # noqa: BLE001 - one broken source must not stop the diagnosis
            lines.append(f"{name}: nicht lesbar ({type(error).__name__}).")
    return lines
