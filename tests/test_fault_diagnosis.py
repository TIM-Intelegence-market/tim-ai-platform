"""Störungs-Diagnose (src/dashboard/fault_diagnosis.py): Dienststatus, bereinigte Logzeilen, Fragen nur bei neuer Störung."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from src.dashboard import fault_diagnosis as fd
from src.dashboard.cockpit.hermes import build_hermes, render_hermes
from tests.test_dashboard_cockpit import _live_state

NOW = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)
LISTING = ("PID\tStatus\tLabel\n63298\t0\tcom.tim.runtime\n-\t0\tcom.tim.nightly\n-\t-9\tcom.tim.s12-liquidations\n"
           "-\t255\tcom.tim.server-ollama-tunnel\n-\t1\tcom.apple.other\n-\t2\tcom.tim.kraken-trader\n")


def _run(logs: dict[str, Path]):
    def run(args, timeout=10):
        if args[:2] == ["launchctl", "list"]:
            return SimpleNamespace(returncode=0, stdout=LISTING)
        label = args[2].rsplit("/", 1)[-1]
        if label in logs:
            return SimpleNamespace(returncode=0, stdout=f"x = y\n\tstderr path = {logs[label]}\n")
        return SimpleNamespace(returncode=113, stdout="")
    return run


def test_only_failing_tim_services_are_listed_and_trading_logs_stay_home(tmp_path: Path) -> None:
    log = tmp_path / "s12.err"
    log.write_text("INFO fine\nTraceback (most recent call last)\nConnectionError: refused api_key=abcd1234 token AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA mail me@x.de\n")
    secret = tmp_path / "kraken.err"
    secret.write_text("Error: balance 123 USD\n")
    lines = fd.service_facts(_run({"com.tim.s12-liquidations": log, "com.tim.kraken-trader": secret}))
    text = "\n".join(lines)
    assert "com.tim.s12-liquidations läuft nicht, beendet durch Signal 9 (kill)" in text
    assert "com.tim.server-ollama-tunnel läuft nicht, Rückgabecode 255" in text and "keine Fehlerzeilen" in text
    assert "com.tim.runtime" not in text and "com.apple" not in text and "nightly" not in text
    assert "ConnectionError" in text and "abcd1234" not in text and "AAAAAAAA" not in text and "me@x.de" not in text
    assert "kraken-trader läuft nicht" in text and "balance" not in text and "bewusst nicht ausgewertet" in text


def test_no_launchctl_means_no_facts() -> None:
    def run(args, timeout=10):
        raise FileNotFoundError
    assert fd.service_facts(run) == []


def test_asks_once_for_a_new_fault_then_notes_it_resolved(tmp_path: Path) -> None:
    path = tmp_path / "f.json"
    asked: list[str] = []

    def ask(text: str) -> dict:
        asked.append(text)
        return {"ok": True, "answer": "Dienst abgestürzt, vermutlich Speicher."}

    lines = ["Dienst com.tim.a läuft nicht, Rückgabecode 1.", "com.tim.a Log: Error x"]
    first = fd.update(path, lines, NOW, ask)
    assert first and first["text"].startswith("Dienst abgestürzt") and len(asked) == 1 and "Fakten:" in asked[0]
    assert fd.update(path, lines, NOW + timedelta(minutes=1), ask) is None and len(asked) == 1
    fixed = fd.update(path, [], NOW + timedelta(minutes=2), ask)
    assert fixed and fixed["resolved"] and len(asked) == 1
    assert [e["resolved"] for e in fd.latest(path)] == [True, False]


def test_cooldown_and_a_failing_hermes(tmp_path: Path) -> None:
    path = tmp_path / "f.json"

    def broken(text: str) -> dict:
        raise RuntimeError("down")

    one = ["Dienst com.tim.a läuft nicht, Rückgabecode 1."]
    entry = fd.update(path, one, NOW, broken)
    assert entry and entry["text"] is None and entry["error"] == "RuntimeError"
    two = [*one, "Dienst com.tim.b läuft nicht, Rückgabecode 2."]
    assert fd.update(path, two, NOW + timedelta(minutes=5), lambda t: {"ok": True, "answer": "x"}) is None  # cooldown
    later = fd.update(path, two, NOW + timedelta(minutes=31), lambda t: {"ok": True, "answer": "x"})
    assert later and later["signature"] == sorted(two)
    # fewer faults than before: remembered, nothing asked
    assert fd.update(path, one, NOW + timedelta(minutes=70), lambda t: {"ok": True, "answer": "x"}) is None


def test_hermes_page_shows_the_faults(tmp_path: Path) -> None:
    state = _live_state(tmp_path, NOW)
    state.fault_diagnosis_path = tmp_path / "f.json"
    fd.update(state.fault_diagnosis_path, ["Dienst com.tim.a läuft nicht, Rückgabecode 1."], NOW, lambda t: {"ok": True, "answer": "Dienst a ist weg."})
    html = render_hermes(build_hermes(state, NOW))
    assert "Störungen" in html and "Dienst a ist weg." in html
